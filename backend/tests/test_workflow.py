from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app import main
from app.auth import resolve_principal, token_hash
from app.channels import ChannelGateway
from app.config import Settings
from app.database import Database
from app.demo_seed import seed_demo_data
from app.evaluation import evaluation_summary, regression_gate
from app.schemas import (
    ExtractedEntities,
    InboundMessageRequest,
    Intent,
    ModelTriage,
    Route,
    Sentiment,
    TriageRequest,
    Urgency,
)
from app.service import TriageService
from app.workflow import SupportWorkflow, WorkflowWorker


def inbound(
    event_id: str,
    provider_message_id: str,
    *,
    thread_id: str = "thread-1",
    sender: str = "customer@example.com",
) -> InboundMessageRequest:
    return InboundMessageRequest(
        event_id=event_id,
        provider_message_id=provider_message_id,
        channel="email",
        sender=sender,
        customer_name="Chika Okoro",
        subject="Cannot access account",
        message="I changed my phone and cannot log in to my account.",
        external_thread_id=thread_id,
    )


class ConfidentAccountModel:
    model_name = "fake-groq-model"

    async def classify(
        self, _request: TriageRequest, _memory: list[dict]
    ) -> ModelTriage:
        return ModelTriage(
            intent=Intent.account_access,
            urgency=Urgency.medium,
            sentiment=Sentiment.concerned,
            route=Route.account_support,
            confidence=0.97,
            entities=ExtractedEntities(
                amount=None,
                transaction_id=None,
                order_id=None,
                account_last4=None,
                card_last4=None,
            ),
            memory_used=False,
            evidence=["Customer cannot access the account after changing device"],
            draft_response=(
                "Hello Customer, Account Support will review the device-change access issue."
            ),
        )


def test_inbound_events_are_idempotent_threaded_and_tenant_isolated(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "kora.db")
    database.initialize()
    workflow = SupportWorkflow(database)

    first = workflow.ingest(inbound("event-1", "message-1"), provider="postmark", tenant_id="tenant-a")
    duplicate = workflow.ingest(inbound("event-1", "message-1"), provider="postmark", tenant_id="tenant-a")
    assert first["duplicate"] is False
    assert duplicate == {"duplicate": True, "event_id": "event-1"}
    assert len(database.conversation(first["case_id"], "tenant-a")) == 1

    database.set_lifecycle(first["case_id"], "resolved", tenant_id="tenant-a")
    reply = workflow.ingest(inbound("event-2", "message-2"), provider="postmark", tenant_id="tenant-a")
    assert reply["case_id"] == first["case_id"]
    assert reply["state"] == "reopened"
    assert database.lifecycle(first["case_id"], "tenant-a")["reopened_count"] == 1
    assert len(database.conversation(first["case_id"], "tenant-a")) == 2

    other_tenant = workflow.ingest(
        inbound("event-1", "message-tenant-b"),
        provider="postmark",
        tenant_id="tenant-b",
    )
    assert other_tenant["duplicate"] is False
    assert other_tenant["case_id"] != first["case_id"]
    assert database.support_ticket(first["case_id"], "tenant-b") is None


@pytest.mark.asyncio
async def test_worker_triages_auto_approves_and_sends_in_demo_mode(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "kora.db")
    database.initialize()
    workflow = SupportWorkflow(database)
    accepted = workflow.ingest(
        inbound("event-1", "message-1"), provider="postmark", tenant_id="tenant-a"
    )
    service = TriageService(database, ConfidentAccountModel())
    worker = WorkflowWorker(
        database,
        lambda: service,
        ChannelGateway(Settings(database_path=tmp_path / "unused.db", channel_mode="demo")),
        poll_seconds=0.01,
    )

    assert await worker.process_one() is True
    assert database.lifecycle(accepted["case_id"], "tenant-a")["state"] == "triaged"
    assert database.job_counts("tenant-a")["queued"] == 1

    assert await worker.process_one() is True
    assert database.lifecycle(accepted["case_id"], "tenant-a")["state"] == "sent"
    messages = database.conversation(accepted["case_id"], "tenant-a")
    assert [message["direction"] for message in messages] == ["inbound", "outbound"]
    assert messages[-1]["provider"] == "kora_demo"
    assert database.audit_event_exists(accepted["case_id"], "response_sent", "tenant-a")


@pytest.mark.asyncio
async def test_failed_job_moves_to_dead_letter_and_marks_case_failed(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "kora.db")
    database.initialize()
    case_id = "KOR-9999"
    database.set_lifecycle(case_id, "queued", tenant_id="tenant-a")
    first_id = database.enqueue_job(
        tenant_id="tenant-a",
        job_type="unsupported",
        idempotency_key="same-operation",
        payload={"case_id": case_id},
        max_attempts=1,
    )
    second_id = database.enqueue_job(
        tenant_id="tenant-a",
        job_type="unsupported",
        idempotency_key="same-operation",
        payload={"case_id": case_id},
        max_attempts=1,
    )
    assert first_id == second_id

    worker = WorkflowWorker(
        database,
        lambda: None,
        ChannelGateway(Settings(database_path=tmp_path / "unused.db")),
    )
    assert await worker.process_one() is True
    assert database.jobs("tenant-a")[0]["status"] == "dead"
    assert database.lifecycle(case_id, "tenant-a")["state"] == "failed"


def test_feedback_metrics_and_release_gate_use_only_the_current_tenant(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "kora.db")
    database.initialize()
    seed_demo_data(database)
    database.add_feedback(
        case_id="KOR-2401",
        customer_id="CUS-1042",
        actor="Ada Okafor",
        predicted={"route": "Transfers"},
        corrected={"route": "Billing"},
        response_accepted=True,
        response_edited=True,
        reason="Incorrect specialist route",
        tenant_id="tenant-demo",
    )

    summary = evaluation_summary(database, "tenant-demo")
    assert summary["processed"] == 18
    assert summary["feedback_count"] == 1
    assert summary["routing_correction_rate"] == 1
    assert summary["draft_edit_rate"] == 1
    assert regression_gate(database, "tenant-demo")["passed"] is False
    assert evaluation_summary(database, "tenant-other")["processed"] == 0


def test_required_auth_and_settings_are_tenant_scoped(tmp_path: Path) -> None:
    database = Database(tmp_path / "kora.db")
    database.initialize()
    database.add_principal(
        token_hash=token_hash("secret-a"),
        tenant_id="tenant-a",
        user_id="agent-a",
        display_name="Agent A",
        role="support_agent",
    )
    required = Settings(database_path=tmp_path / "kora.db", auth_mode="required")

    with pytest.raises(HTTPException) as missing:
        resolve_principal(None, database, required)
    assert missing.value.status_code == 401
    principal = resolve_principal("Bearer secret-a", database, required)
    assert principal.tenant_id == "tenant-a"
    assert principal.role == "support_agent"

    database.set_setting("automation", {"enabled": True}, "tenant-a")
    database.set_setting("automation", {"enabled": False}, "tenant-b")
    assert database.get_setting("automation", {}, "tenant-a")["enabled"] is True
    assert database.get_setting("automation", {}, "tenant-b")["enabled"] is False


def test_delivery_receipt_updates_message_lifecycle_and_audit(
    tmp_path: Path, monkeypatch
) -> None:
    database = Database(tmp_path / "kora.db")
    database.initialize()
    accepted = SupportWorkflow(database).ingest(
        inbound("event-1", "message-1"),
        provider="postmark",
        tenant_id="tenant-demo",
    )
    ticket = database.support_ticket(accepted["case_id"])
    database.add_message(
        message_id="outbound-1",
        case_id=accepted["case_id"],
        tenant_id="tenant-demo",
        customer_id=ticket["customerId"],
        channel="email",
        direction="outbound",
        provider="postmark",
        provider_message_id="provider-outbound-1",
        contact="customer@example.com",
        body="We are reviewing your case.",
        delivery_status="sent",
    )
    monkeypatch.setattr(main, "database", database)

    receipt = main._record_delivery_update(
        event_id="delivery-1",
        provider="postmark",
        provider_message_id="provider-outbound-1",
        status_value="delivered",
        payload={"MessageID": "provider-outbound-1"},
    )
    assert receipt["status"] == "delivered"
    assert database.lifecycle(accepted["case_id"])["state"] == "delivered"
    assert database.conversation(accepted["case_id"])[-1]["delivery_status"] == "delivered"
    assert database.audit_event_exists(accepted["case_id"], "delivery_updated")
