from pathlib import Path

import pytest
from fastapi import HTTPException

from app import main
from app.api import deps
from app.api.routers import operations
from app.auth import Principal
from app.channels import ChannelGateway
from app.config import Settings
from app.database import Database
from app.schemas import ActionRequest, InboundMessageRequest, ManualAssessmentRequest
from app.workflow import SupportWorkflow, WorkflowWorker


@pytest.fixture
def database(tmp_path: Path, monkeypatch):
    db = Database(tmp_path / "regressions.db")
    db.initialize()
    monkeypatch.setattr(deps, "database", db)
    monkeypatch.setattr(deps, "settings", Settings(channel_mode="demo"))
    return db


def ingest(
    database, event="first", tenant="tenant-demo", sender="customer@example.com",
    *, channel="email", provider="postmark", thread="shared-thread",
):
    return SupportWorkflow(database).ingest(
        InboundMessageRequest(
            event_id=event,
            provider_message_id=event,
            channel=channel,
            sender=sender,
            customer_name="Test Customer",
            message="Please help me access my account.",
            external_thread_id=thread,
        ),
        provider=provider,
        tenant_id=tenant,
    )


@pytest.mark.parametrize("prior_model_decision", [False, True])
def test_manual_assessment_can_be_approved_without_using_old_model_draft(
    database, prior_model_decision
):
    case = ingest(database)
    principal = Principal("tenant-demo", "agent", "Test Agent", "support_agent")
    if prior_model_decision:
        database.add_audit(
            case_id=case["case_id"], customer_id=case["customer_id"],
            event_type="triage", model="old-model", request={},
            decision={"response": "Outdated model response"},
            guardrails={"escalated": True}, actor="groq-model",
        )
    draft = "Account Support will review your access issue."
    main.manual_assessment(
        case["case_id"],
        ManualAssessmentRequest(
            customer_id=case["customer_id"], intent="Account access",
            urgency="medium", route="Account Support", response=draft,
        ),
        principal,
    )
    # Manual decisions must stay out of bulk automation even after human review.
    with pytest.raises(HTTPException) as error:
        main.approve(
            case["case_id"],
            ActionRequest(customer_id=case["customer_id"], require_automation_eligible=True),
            principal,
        )
    assert error.value.status_code == 409
    approved = main.approve(
        case["case_id"], ActionRequest(customer_id=case["customer_id"]), principal
    )
    assert approved["status"] == "approved"
    assert database.feedback()[0]["predicted"]["response"] == draft


@pytest.mark.asyncio
async def test_manager_run_once_only_processes_their_tenants_jobs(database, monkeypatch):
    for tenant in ("tenant-b", "tenant-a"):
        database.enqueue_job(
            tenant_id=tenant, job_type="triage", idempotency_key="one",
            payload={"case_id": "unused"},
        )
    worker = WorkflowWorker(database, lambda: None, ChannelGateway(Settings()))
    processed = []

    async def record_job(job):
        processed.append(job["tenant_id"])

    monkeypatch.setattr(worker, "_triage", record_job)
    monkeypatch.setattr(deps, "worker", worker)
    principal = Principal("tenant-a", "manager", "Manager", "support_manager")
    assert await operations.run_job_once(principal) == {"processed": True}
    assert processed == ["tenant-a"]
    assert await operations.run_job_once(principal) == {"processed": False}
    assert database.job_counts("tenant-b")["queued"] == 1
    # The background worker must still service every tenant.
    assert await worker.process_one() is True
    assert processed == ["tenant-a", "tenant-b"]


def outbound(database, case, provider="postmark", message_id="outbound"):
    database.add_message(
        message_id=f"row-{provider}-{message_id}", case_id=case["case_id"],
        tenant_id="tenant-demo", customer_id=case["customer_id"], channel="email",
        direction="outbound", provider=provider, provider_message_id=message_id,
        body="We are reviewing your case.", delivery_status="sent",
    )


def receipt(event="receipt", status="delivered", provider="postmark"):
    return main._record_delivery_update(
        event_id=event, provider=provider, provider_message_id="outbound",
        status_value=status, payload={},
    )


@pytest.mark.parametrize("state", ["resolved", "reopened", "review_required"])
def test_late_delivery_receipt_preserves_case_workflow(database, state):
    case = ingest(database)
    outbound(database, case)
    database.set_lifecycle(case["case_id"], state)
    database.update_support_ticket_fields(case["case_id"], {"status": state})
    before = database.lifecycle(case["case_id"])
    receipt()
    assert database.conversation(case["case_id"])[-1]["delivery_status"] == "delivered"
    assert database.lifecycle(case["case_id"]) == before
    assert database.support_ticket(case["case_id"])["status"] == state


def test_failed_receipt_can_be_retried_atomically(database, monkeypatch):
    case = ingest(database)
    outbound(database, case)
    original = database.add_audit

    def fail_audit(**kwargs):
        raise RuntimeError("Simulated persistence failure")

    monkeypatch.setattr(database, "add_audit", fail_audit)
    with pytest.raises(RuntimeError):
        receipt()
    assert database.conversation(case["case_id"])[-1]["delivery_status"] == "sent"
    monkeypatch.setattr(database, "add_audit", original)
    assert receipt()["duplicate"] is False
    assert database.conversation(case["case_id"])[-1]["delivery_status"] == "delivered"
    assert receipt()["duplicate"] is True


def test_delivery_receipts_are_scoped_to_provider(database):
    case = ingest(database)
    outbound(database, case)
    assert receipt(provider="whatsapp_cloud")["case_id"] is None
    assert database.conversation(case["case_id"])[-1]["delivery_status"] == "sent"


def test_late_sent_receipt_does_not_undo_delivered_status(database):
    case = ingest(database)
    outbound(database, case)
    receipt()
    receipt(event="late-sent", status="sent")
    assert database.conversation(case["case_id"])[-1]["delivery_status"] == "delivered"
    assert database.lifecycle(case["case_id"])["state"] == "delivered"


def test_thread_reference_does_not_merge_different_customers(database):
    first = ingest(database)
    other = ingest(database, event="other", sender="other@example.com")
    assert other["case_id"] != first["case_id"]
    reply = ingest(database, event="reply")
    assert reply["case_id"] == first["case_id"]
    assert len(database.conversation(first["case_id"])) == 2
    assert len(database.conversation(other["case_id"])) == 1


@pytest.mark.parametrize("reference", ["shared-thread", "first"])
@pytest.mark.parametrize("scope", [
    {"sender": "other@example.com"},
    {"channel": "whatsapp"},
    {"provider": "kora_webhook"},
])
def test_thread_and_message_reference_enforce_customer_channel_and_provider(
    database, reference, scope
):
    first = ingest(database)
    other = ingest(database, event="other", thread=reference, **scope)
    assert other["case_id"] != first["case_id"]
    # Case-insensitive contact normalization still allows legitimate replies.
    reply = ingest(database, event="reply", sender="CUSTOMER@example.com", thread=reference)
    assert reply["case_id"] == first["case_id"]


@pytest.mark.parametrize("newer_direction", ["inbound", "outbound"])
def test_receipt_for_old_message_does_not_change_newer_conversation_state(
    database, newer_direction
):
    case = ingest(database)
    outbound(database, case)
    database.add_message(
        message_id="newer-message", case_id=case["case_id"], tenant_id="tenant-demo",
        customer_id=case["customer_id"], channel="email", direction=newer_direction,
        provider="postmark", provider_message_id="newer-provider-id",
        body="A newer message", delivery_status="sent" if newer_direction == "outbound" else "received",
    )
    database.set_lifecycle(case["case_id"], "sent")
    before = database.lifecycle(case["case_id"])
    receipt()
    assert database.lifecycle(case["case_id"]) == before
    assert database.conversation(case["case_id"])[1]["delivery_status"] == "delivered"


def test_late_delivery_receipt_does_not_undo_read_status(database):
    case = ingest(database)
    outbound(database, case)
    receipt(event="read", status="read")
    receipt()
    assert database.conversation(case["case_id"])[-1]["delivery_status"] == "read"
