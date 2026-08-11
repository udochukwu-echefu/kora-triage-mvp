from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app import main
from app.database import Database
from app.demo_seed import seed_demo_data
from app.guardrails import apply_guardrails
from app.privacy import redact_for_model
from app.schemas import (
    CustomerContext,
    ExtractedEntities,
    Intent,
    ModelTriage,
    Route,
    Sentiment,
    TriageRequest,
    Urgency,
)
from app.service import TriageService, _redacted_request


def request(message: str = "I did not make this debit on account 0192846671") -> TriageRequest:
    return TriageRequest(
        case_id="KOR-TEST",
        channel="whatsapp",
        message=message,
        customer=CustomerContext(
            customer_id="CUS-TEST",
            name="Ifeanyi Obi",
            previous_context="Customer reported an unknown debit yesterday.",
            notes=[],
        ),
    )


def model_result(**updates) -> ModelTriage:
    values = {
        "intent": Intent.fraud_report,
        "urgency": Urgency.critical,
        "sentiment": Sentiment.hostile,
        "route": Route.risk_fraud,
        "confidence": 0.94,
        "entities": ExtractedEntities(
            amount="₦145,000",
            transaction_id=None,
            order_id=None,
            account_last4=None,
            card_last4=None,
        ),
        "memory_used": False,
        "evidence": ["Customer explicitly denies the debit"],
        "draft_response": "Hi Customer, this has been sent to the fraud team for review.",
    }
    values.update(updates)
    return ModelTriage(**values)


def test_model_schema_meets_groq_strict_mode_requirements() -> None:
    schema = ModelTriage.model_json_schema()

    def check(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                properties = node.get("properties", {})
                assert node.get("additionalProperties") is False
                assert set(node.get("required", [])) == set(properties)
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    check(schema)


def test_redacts_account_but_preserves_last_four() -> None:
    redacted, entities = redact_for_model("Account 0192846671, call 08031234567")
    assert "0192846671" not in redacted
    assert "08031234567" not in redacted
    assert "ENDING 6671" in redacted
    assert entities["account_last4"] == "6671"


def test_redacts_customer_notes_before_model_use() -> None:
    unsafe = request().model_copy(
        update={
            "customer": request().customer.model_copy(
                update={"notes": ["Call 08031234567 or agent@example.com"]}
            )
        }
    )
    safe, _ = _redacted_request(unsafe)
    assert safe.customer.notes == ["Call [PHONE REDACTED] or [EMAIL REDACTED]"]


def test_fraud_and_hostility_force_escalation() -> None:
    decision = apply_guardrails(request(), model_result())
    assert decision.escalated is True
    assert "fraud_report" in decision.flags
    assert "hostile_sentiment" in decision.flags


def test_sensitive_data_request_is_replaced() -> None:
    result = model_result(
        intent=Intent.account_access,
        urgency=Urgency.medium,
        sentiment=Sentiment.concerned,
        route=Route.account_support,
        draft_response="Please send your OTP and password so we can help.",
    )
    decision = apply_guardrails(request("I cannot login"), result)
    assert "sensitive_data_request_blocked" in decision.flags
    assert "do not share your PIN, OTP" in decision.response


@pytest.mark.parametrize(
    "draft",
    [
        "Hello Customer, I’ve generated a fresh password-reset link for you.",
        "Hello Customer, I have checked the tracking information for your order.",
        "Hello Customer, I’ll contact the courier and update you.",
    ],
)
def test_unverified_external_actions_are_replaced(draft: str) -> None:
    result = model_result(
        intent=Intent.account_access,
        urgency=Urgency.medium,
        sentiment=Sentiment.concerned,
        route=Route.account_support,
        draft_response=draft,
    )
    decision = apply_guardrails(request("I cannot login"), result)
    assert "unverified_action_claim_blocked" in decision.flags
    assert "No financial, delivery, or account action has been completed" in decision.response


class FakeModel:
    model_name = "fake-groq-model"

    async def classify(self, _request: TriageRequest, _memory: list[dict]) -> ModelTriage:
        return model_result()


@pytest.mark.asyncio
async def test_service_persists_memory_and_audit(tmp_path: Path) -> None:
    database = Database(tmp_path / "kora.db")
    database.initialize()
    service = TriageService(database, FakeModel())
    result = await service.triage(request())
    assert result.source == "groq"
    assert result.entities["account"] == "••••••6671"
    assert result.escalated is True
    assert len(database.audits()) == 1
    assert len(database.memories_for("CUS-TEST")) == 1
    latest = database.latest_triage_for_case("KOR-TEST")
    assert latest is not None
    assert latest["customer_id"] == "CUS-TEST"
    assert result.processing_ms >= 0
    assert result.estimated_minutes_saved <= 12


@pytest.mark.asyncio
async def test_service_deduplicates_memory_and_restores_greeting(tmp_path: Path) -> None:
    database = Database(tmp_path / "kora.db")
    database.initialize()

    class HelloModel(FakeModel):
        async def classify(self, _request: TriageRequest, _memory: list[dict]) -> ModelTriage:
            return model_result(
                sentiment=Sentiment.concerned,
                urgency=Urgency.high,
                draft_response="Hello Customer, your case is ready for review.",
            )

    service = TriageService(database, HelloModel())
    first = await service.triage(request())
    await service.triage(request())
    assert first.response.startswith("Hello Ifeanyi")
    assert len(database.memories_for("CUS-TEST")) == 1
    assert len(database.audits()) == 2


@pytest.mark.asyncio
async def test_confidence_alone_cannot_auto_approve_without_governance(tmp_path: Path) -> None:
    database = Database(tmp_path / "kora.db")
    database.initialize()
    database.set_setting(
        "automation",
        {"enabled": True, "auto_approve_threshold": 95, "mandatory_review_threshold": 70},
    )

    class ConfidentModel(FakeModel):
        async def classify(self, _request: TriageRequest, _memory: list[dict]) -> ModelTriage:
            return model_result(
                intent=Intent.account_access,
                urgency=Urgency.medium,
                sentiment=Sentiment.concerned,
                route=Route.account_support,
                confidence=0.97,
                draft_response="Hello Customer, Account Support will review your access request.",
            )

    result = await TriageService(database, ConfidentModel()).triage(request("I cannot login"))
    assert result.status == "AI draft ready"
    latest = database.latest_triage_for_case("KOR-TEST")
    assert latest["decision"]["automation"]["code"] == "no_policy"
    assert [item["event_type"] for item in database.audits()] == ["triage"]


@pytest.mark.asyncio
async def test_low_risk_case_needs_policy_delivery_and_confidence_to_auto_approve(tmp_path: Path) -> None:
    database = Database(tmp_path / "kora.db")
    database.initialize()
    database.set_setting(
        "automation",
        {"enabled": True, "auto_approve_threshold": 95, "mandatory_review_threshold": 70},
    )
    database.add_policy(
        tenant_id="tenant-demo",
        title="General help",
        content="General help and opening hours enquiries may use this approved response.",
        source_url=None,
        version="1.0",
    )

    class SafeModel(FakeModel):
        async def classify(self, _request: TriageRequest, _memory: list[dict]) -> ModelTriage:
            return model_result(
                intent=Intent.general_enquiry,
                urgency=Urgency.low,
                sentiment=Sentiment.calm,
                route=Route.general_support,
                confidence=0.97,
                draft_response="Hello Customer, our opening hours are available in the approved help policy.",
            )

    safe_request = request("What are your general help opening hours?")
    result = await TriageService(
        database,
        SafeModel(),
        delivery_available=True,
    ).triage(safe_request)
    assert result.status == "Auto-approved"
    assert database.latest_triage_for_case("KOR-TEST")["decision"]["automation"]["code"] == "eligible"
    assert database.audit_event_exists("KOR-TEST", "safety_policy_auto_approved")


def test_case_actions_reject_a_different_customer(tmp_path: Path, monkeypatch) -> None:
    database = Database(tmp_path / "kora.db")
    database.initialize()
    database.add_audit(
        case_id="KOR-BOUND",
        customer_id="CUS-RIGHT",
        event_type="triage",
        model="fake",
        request={},
        decision={},
        guardrails={"escalated": False},
    )
    monkeypatch.setattr(main, "database", database)
    with pytest.raises(HTTPException) as error:
        main.validated_case("KOR-BOUND", "CUS-WRONG")
    assert error.value.status_code == 409


def test_demo_seed_is_idempotent_and_spans_operational_range(tmp_path: Path) -> None:
    database = Database(tmp_path / "kora.db")
    database.initialize()
    seed_demo_data(database)
    seed_demo_data(database)

    tickets = database.support_tickets()
    audits = database.audits(100)
    assert len(tickets) == 18
    assert len([item for item in audits if item["event_type"] == "triage"]) == 18
    assert len([item for item in audits if item["event_type"] == "human_approved"]) == 5
    assert len([item for item in audits if item["event_type"] == "human_escalated"]) == 4
    assert len([item for item in audits if item["event_type"] == "human_routed"]) == 3
    assert {ticket["route"] for ticket in tickets} >= {"Transfers", "Fraud", "Logistics", "Billing"}
    assert min(ticket["confidence"] for ticket in tickets) == 0.70
    assert max(ticket["confidence"] for ticket in tickets) == 0.99
    assert next(ticket for ticket in tickets if ticket["id"] == "KOR-2401")["status"] == "Approved"
    assert next(ticket for ticket in tickets if ticket["id"] == "KOR-2403")["status"] == "Assigned"


def test_ticket_updates_and_automation_settings_persist(tmp_path: Path) -> None:
    database = Database(tmp_path / "kora.db")
    database.initialize()
    seed_demo_data(database)
    database.update_support_ticket_fields("KOR-2402", {"route": "Billing", "status": "Routed to Billing"})
    updated = next(ticket for ticket in database.support_tickets() if ticket["id"] == "KOR-2402")
    assert updated["route"] == "Billing"
    assert updated["status"] == "Routed to Billing"

    value = {"enabled": False, "auto_approve_threshold": 97, "mandatory_review_threshold": 68}
    database.set_setting("automation", value)
    assert database.get_setting("automation", {}) == value
