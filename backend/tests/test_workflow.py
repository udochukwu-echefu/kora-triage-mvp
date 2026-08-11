from __future__ import annotations

import base64
import hashlib
import hmac
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import main
from app.auth import resolve_principal, token_hash
from app.benchmark import score_predictions
from app.run_evaluation import SMOKE_CASE_IDS, _measurement_summary
from app.channels import ChannelGateway
from app.config import Settings
from app.database import Database
from app.demo_seed import seed_demo_data
from app.evaluation import evaluation_summary, regression_gate
from app.evaluation_dataset import GOLD_CASES, dataset_summary
from app.schemas import (
    CustomerContext,
    ExtractedEntities,
    InboundMessageRequest,
    Intent,
    ModelTriage,
    Route,
    Sentiment,
    TriageRequest,
    Urgency,
)
from app.triage_policy import apply_operational_policy
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


def test_email_reply_resolves_the_case_from_kora_outbound_message_id(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "kora.db")
    database.initialize()
    workflow = SupportWorkflow(database)
    accepted = workflow.ingest(
        inbound("event-1", "inbound-1", thread_id="original-thread"),
        provider="postmark",
        tenant_id="tenant-a",
    )
    database.add_message(
        message_id="outbound-row",
        case_id=accepted["case_id"],
        tenant_id="tenant-a",
        customer_id=accepted["customer_id"],
        channel="email",
        direction="outbound",
        provider="postmark",
        provider_message_id="kora-outbound-message",
        external_thread_id="original-thread",
        contact="customer@example.com",
        body="We are reviewing your request.",
        delivery_status="sent",
    )

    reply = workflow.ingest(
        inbound(
            "event-2",
            "inbound-2",
            thread_id="kora-outbound-message",
        ),
        provider="postmark",
        tenant_id="tenant-a",
    )

    assert reply["case_id"] == accepted["case_id"]
    assert len(database.conversation(accepted["case_id"], "tenant-a")) == 3


@pytest.mark.asyncio
async def test_worker_keeps_demo_delivery_human_reviewed(
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
    assert database.job_counts("tenant-a")["queued"] == 0
    assert await worker.process_one() is False
    assert database.lifecycle(accepted["case_id"], "tenant-a")["state"] == "triaged"
    messages = database.conversation(accepted["case_id"], "tenant-a")
    assert [message["direction"] for message in messages] == ["inbound"]
    assert not database.audit_event_exists(accepted["case_id"], "response_sent", "tenant-a")


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


def test_gold_dataset_has_100_cases_and_required_operational_coverage() -> None:
    summary = dataset_summary()
    assert len(GOLD_CASES) == 100
    assert summary["cases"] == 100
    assert set(summary["languages"]) == {"english", "mixed", "pidgin"}
    assert set(summary["channels"]) == {"email", "whatsapp"}
    assert set(summary["domains"]) == {
        "account_issue",
        "billing_dispute",
        "delivery_complaint",
        "duplicate_charge",
        "fraud_unauthorised",
        "transfer_dispute",
    }
    cases = [case for case in GOLD_CASES if case.case_id in SMOKE_CASE_IDS]
    assert len(cases) == 11
    assert len({case.intent for case in cases}) == 11
    assert {case.domain for case in cases} == {
        "account_issue",
        "billing_dispute",
        "delivery_complaint",
        "duplicate_charge",
        "fraud_unauthorised",
        "transfer_dispute",
    }
    assert {language: sum(case.language == language for case in cases) for language in {"english", "mixed", "pidgin"}} == {
        "english": 4,
        "mixed": 3,
        "pidgin": 4,
    }


def test_benchmark_scores_route_and_normalised_entities() -> None:
    case = GOLD_CASES[0]
    report = score_predictions(
        [case],
        {
            case.case_id: {
                "intent": case.intent,
                "urgency": case.urgency,
                "route": case.route,
                "entities": {
                    **case.entities,
                    "amount": "NGN 45,000",
                },
            }
        },
    )
    assert report["combined_accuracy"] == 1
    assert report["entity_required_accuracy"] == 1
    assert report["entity_exact_match"] == 1
    assert report["failures"] == []
    assert report["fraud_recall"] is None
    assert report["release_gate"]["passed"] is False
    measurements = _measurement_summary(
        {
            "one": {"latency_ms": 100, "prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            "two": {"latency_ms": 300, "prompt_tokens": 40, "completion_tokens": 20, "total_tokens": 60},
        }
    )
    assert measurements["latency_ms"] == {
        "measured_cases": 2,
        "min": 100,
        "median": 200.0,
        "p95": 300,
        "max": 300,
    }
    assert measurements["tokens"]["total"] == {
        "measured_cases": 2,
        "total": 90,
        "average": 45.0,
    }


@pytest.mark.parametrize("case", GOLD_CASES, ids=lambda case: case.case_id)
def test_operational_policy_matches_gold_routing_and_urgency(case) -> None:
    expected = case.entities
    request = TriageRequest(
        case_id=case.case_id,
        channel=case.channel,
        subject=case.subject,
        message=case.message,
        customer=CustomerContext(customer_id="policy-test", name="Test Customer"),
    )
    model_result = ModelTriage(
        intent=Intent(case.intent),
        urgency=Urgency.critical,
        sentiment=Sentiment.concerned,
        route=Route.general_support,
        confidence=0.9,
        entities=ExtractedEntities(
            amount=expected["amount"],
            transaction_id=expected["transactionId"],
            order_id=expected["orderId"],
            account_last4=(
                "".join(filter(str.isdigit, expected["account"]))[-4:]
                if expected["account"]
                else None
            ),
            card_last4=(
                "".join(filter(str.isdigit, expected["card"]))[-4:]
                if expected["card"]
                else None
            ),
        ),
        memory_used=False,
        evidence=["Customer message provides the complaint type."],
        draft_response="Hello Customer, we received your message.",
    )
    result = apply_operational_policy(request, model_result).triage
    assert result.route.value == case.route
    assert result.urgency.value == case.urgency


def test_live_generic_webhook_fails_closed_without_a_secret(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "settings",
        Settings(channel_mode="live", webhook_token=None),
    )
    with pytest.raises(HTTPException) as error:
        main.verify_webhook_token(None)
    assert error.value.status_code == 503


def test_postmark_supports_basic_auth_for_provider_webhooks(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "settings",
        Settings(
            channel_mode="live",
            postmark_webhook_username="kora",
            postmark_webhook_password="secret",
        ),
    )
    credentials = base64.b64encode(b"kora:secret").decode("ascii")
    main.verify_postmark_webhook(f"Basic {credentials}", None)
    with pytest.raises(HTTPException) as error:
        main.verify_postmark_webhook("Basic bad", None)
    assert error.value.status_code == 401


def test_whatsapp_signature_uses_the_exact_raw_request_body(monkeypatch) -> None:
    raw = b'{"entry":[{"id":"1"}],"object":"whatsapp_business_account"}'
    secret = "whatsapp-secret"
    signature = "sha256=" + hmac.new(
        secret.encode("utf-8"), raw, hashlib.sha256
    ).hexdigest()
    monkeypatch.setattr(
        main,
        "settings",
        Settings(channel_mode="live", whatsapp_app_secret=secret),
    )
    main.verify_whatsapp_signature(raw, signature)
    with pytest.raises(HTTPException) as error:
        main.verify_whatsapp_signature(raw + b" ", signature)
    assert error.value.status_code == 401
