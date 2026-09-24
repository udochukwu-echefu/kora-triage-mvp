"""Regression tests for the approval, privacy, guardrail and evaluation fixes."""

from __future__ import annotations

import ast
import re
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import main, triage_policy
from app.auth import Principal
from app.config import Settings
from app.database import Database
from app.demo_seed import seed_demo_data
from app.evaluation import evaluation_summary
from app.evaluation_dataset import GOLD_CASES
from app.guardrails import LEGAL_OR_PUBLIC_THREAT, claims_unverified_action, requests_sensitive_data
from app.launch_features import relevant_policies
from app.privacy import redact_for_model
from app.schemas import (
    ActionRequest,
    CustomerContext,
    ExtractedEntities,
    FeedbackRequest,
    InboundMessageRequest,
    Intent,
    ModelTriage,
    ResolveRequest,
    Route,
    Sentiment,
    TriageRequest,
    Urgency,
)
from app.service import TriageService, _redacted_request
from app.triage_policy import apply_operational_policy, parse_amount
from app.workflow import SupportWorkflow

AGENT = Principal("tenant-demo", "agent", "Test Agent", "support_agent")
OTHER_AGENT = Principal("tenant-demo", "agent-2", "Other Agent", "support_agent")
MANAGER = Principal("tenant-demo", "manager", "Test Manager", "support_manager")
LIVE = Settings(channel_mode="live", postmark_server_token="token", postmark_from_email="help@kora.test")


@pytest.fixture
def database(tmp_path: Path, monkeypatch) -> Database:
    db = Database(tmp_path / "safety.db")
    db.initialize()
    monkeypatch.setattr(main, "database", db)
    monkeypatch.setattr(main, "settings", Settings(channel_mode="demo"))
    return db


def triaged_case(
    database: Database,
    *,
    escalated: bool = False,
    response: str = "Hello Chika, Account Support will review your access request.",
    event: str = "event-1",
) -> dict:
    case = SupportWorkflow(database).ingest(
        InboundMessageRequest(
            event_id=event,
            provider_message_id=event,
            channel="email",
            sender="chika@example.com",
            customer_name="Chika Okoro",
            message="I cannot log in to my account.",
        ),
        provider="postmark",
        tenant_id="tenant-demo",
    )
    database.add_audit(
        case_id=case["case_id"],
        customer_id=case["customer_id"],
        event_type="triage",
        model="fake",
        request={},
        decision={"response": response, "automation": {"eligible": False, "reason": "Human review required.", "code": "disabled"}},
        guardrails={"escalated": escalated, "reason": "Fraud report" if escalated else None},
    )
    database.set_lifecycle(case["case_id"], "review_required" if escalated else "triaged")
    return case


# 1. Approval integrity ------------------------------------------------------

def test_client_note_cannot_label_a_manual_approval_as_automated(database):
    case = triaged_case(database)
    result = main.approve(
        case["case_id"],
        ActionRequest(customer_id=case["customer_id"], note="confidence_policy_auto_approve"),
        AGENT,
    )
    assert result["status"] == "approved"
    audit = next(item for item in database.audits() if item["event_type"] == "human_approved")
    assert audit["decision"]["status"] == "approved"
    assert database.support_ticket(case["case_id"])["status"] == "Approved"


@pytest.mark.parametrize(
    "reply",
    [
        "Please send us your OTP so we can reverse the debit.",
        "What is your PIN?",
        "Kindly confirm your BVN to continue.",
        "We have refunded the money to your account.",
        "We will reverse the transfer today.",
    ],
)
def test_edited_replies_get_the_same_guardrails_as_ai_drafts(database, reply):
    case = triaged_case(database)
    with pytest.raises(HTTPException) as error:
        main.approve(case["case_id"], ActionRequest(customer_id=case["customer_id"], response=reply), AGENT)
    assert error.value.status_code == 422
    assert not database.audit_event_exists(case["case_id"], "human_approved")


def test_a_case_cannot_be_approved_twice(database):
    case = triaged_case(database)
    main.approve(case["case_id"], ActionRequest(customer_id=case["customer_id"]), AGENT)
    with pytest.raises(HTTPException) as error:
        main.approve(case["case_id"], ActionRequest(customer_id=case["customer_id"]), AGENT)
    assert error.value.status_code == 409


def test_concurrent_live_approvals_queue_exactly_one_send(database, monkeypatch):
    monkeypatch.setattr(main, "settings", LIVE)
    case = triaged_case(database)

    def attempt(_):
        try:
            return main.approve(case["case_id"], ActionRequest(customer_id=case["customer_id"]), AGENT)
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert sum(isinstance(item, dict) and item["status"] == "queued" for item in results) == 1
    assert results.count(409) == 5
    assert database.job_counts()["queued"] == 2  # the inbound triage job + one send


# 6. Escalated cases have a path forward ----------------------------------------

def test_escalated_case_needs_assigned_specialist_or_manager_and_a_note(database):
    case = triaged_case(database, escalated=True)
    request = ActionRequest(customer_id=case["customer_id"], note="Verified with the fraud team; safe to acknowledge.")
    with pytest.raises(HTTPException) as unassigned:
        main.approve(case["case_id"], request, OTHER_AGENT)
    assert unassigned.value.status_code == 409
    with pytest.raises(HTTPException) as no_note:
        main.approve(case["case_id"], ActionRequest(customer_id=case["customer_id"]), MANAGER)
    assert no_note.value.status_code == 422

    database.claim_case(case["case_id"], tenant_id="tenant-demo", assignee="Test Agent")
    approved = main.approve(case["case_id"], request, AGENT)
    assert approved["status"] == "approved"
    audit = next(item for item in database.audits() if item["event_type"] == "human_approved")
    assert audit["decision"]["guardrail_override"] is True


def test_bulk_approval_still_never_overrides_a_guardrail(database):
    case = triaged_case(database, escalated=True)
    with pytest.raises(HTTPException) as error:
        main.approve(
            case["case_id"],
            ActionRequest(customer_id=case["customer_id"], note="Bulk approval attempt", require_automation_eligible=True),
            MANAGER,
        )
    assert error.value.status_code == 409


def test_any_open_case_can_be_resolved_once(database):
    case = triaged_case(database)
    main.approve(case["case_id"], ActionRequest(customer_id=case["customer_id"]), AGENT)
    resolved = main.resolve_case(case["case_id"], ResolveRequest(customer_id=case["customer_id"], resolution="Handled by phone."), AGENT)
    assert resolved["lifecycle"]["state"] == "resolved"
    with pytest.raises(HTTPException) as error:
        main.resolve_case(case["case_id"], ResolveRequest(customer_id=case["customer_id"], resolution="Again."), AGENT)
    assert error.value.status_code == 409


# 2. PII redaction -------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("My card 5399831234567890 was charged", "5399831234567890"),
        ("card 5399 8312 3456 7890 please", "5399 8312 3456 7890"),
        ("my BVN is 22212345678", "22212345678"),
        ("NIN 12345678901 attached", "12345678901"),
        ("call 0803 123 4567", "0803 123 4567"),
        ("call +234 803 123 4567", "+234 803 123 4567"),
        ("call 234-803-123-4567", "234-803-123-4567"),
        ("mail chika.o@example.com", "chika.o@example.com"),
    ],
)
def test_sensitive_numbers_never_reach_the_model(text, secret):
    redacted, _ = redact_for_model(text)
    assert secret not in redacted
    assert not re.search(r"\d{7,}", redacted.replace(" ", "")), redacted


def test_card_and_account_last_four_survive_for_reconciliation():
    redacted, entities = redact_for_model("Card 5399 8312 3456 7890 and account 0192846671")
    assert "CARD ENDING 7890" in redacted
    assert "ACCOUNT ENDING 6671" in redacted
    assert entities == {"account_last4": "6671", "card_last4": "7890"}


def test_references_and_amounts_are_not_mistaken_for_card_numbers():
    text = "Transfer TRX-1234567890123 for ₦1,250,000 on order ORD-44890"
    assert redact_for_model(text)[0] == text


def test_customer_name_is_removed_from_message_text():
    safe, _ = _redacted_request(
        TriageRequest(
            case_id="KOR-NAME",
            channel="email",
            message="Hello, I am Chidinma Okeke and my transfer failed.",
            customer=CustomerContext(customer_id="CUS-NAME", name="Chidinma Okeke"),
        )
    )
    assert "Chidinma" not in safe.message and "Okeke" not in safe.message
    assert safe.customer.name == "Customer"


# 11. Guardrail coverage ---------------------------------------------------------

@pytest.mark.parametrize(
    "draft",
    [
        "What is your OTP?",
        "Please confirm your PIN so we can help.",
        "Kindly send your BVN.",
        "Reply with your card number and CVV.",
        "Share your login details and we will fix it.",
    ],
)
def test_requests_for_secrets_are_detected(draft):
    assert requests_sensitive_data(draft)


@pytest.mark.parametrize(
    "draft",
    [
        "For your security, never share your PIN or OTP with anyone.",
        "Please confirm the last four digits of the card so we can find the debit.",
        "We will contact you once the review is complete.",
    ],
)
def test_safe_replies_are_not_flagged(draft):
    assert not requests_sensitive_data(draft)
    assert not claims_unverified_action(draft)


def test_promises_to_move_money_are_flagged_but_updates_are_not():
    assert claims_unverified_action("We'll refund you by tomorrow.")
    assert claims_unverified_action("I will contact the courier now.")
    assert not claims_unverified_action("We will update you through this channel.")


@pytest.mark.parametrize(
    ("message", "threat"),
    [
        ("Please press the reset button again", False),
        ("I will take this to the press", True),
        ("My lawyer will hear about this", True),
        ("I dey go EFCC if una no fix am", True),
    ],
)
def test_legal_threat_detection_avoids_common_words(message, threat):
    assert bool(LEGAL_OR_PUBLIC_THREAT.search(message)) is threat


# 12. Nigerian amount formats -------------------------------------------------

@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("N50,000", Decimal("50000")),
        ("n50k", Decimal("50000")),
        ("₦2.5m", Decimal("2500000")),
        ("50k naira", Decimal("50000")),
        ("50,000 naira", Decimal("50000")),
        ("NGN 1,500.50", Decimal("1500.50")),
    ],
)
def test_amount_formats_are_parsed(text, value):
    match = triage_policy.AMOUNT.search(text)
    assert match, text
    assert parse_amount(match.group(0)) == value


def fraud_result(amount=None) -> ModelTriage:
    return ModelTriage(
        intent=Intent.fraud_report,
        urgency=Urgency.medium,
        sentiment=Sentiment.concerned,
        route=Route.general_support,
        confidence=0.9,
        entities=ExtractedEntities(amount=amount, transaction_id=None, order_id=None, account_last4=None, card_last4=None),
        memory_used=False,
        evidence=["Customer denies the debit."],
        draft_response="Hello Customer, the fraud team will review this.",
    )


def policy_request(message: str) -> TriageRequest:
    return TriageRequest(
        case_id="KOR-POLICY",
        channel="whatsapp",
        message=message,
        customer=CustomerContext(customer_id="CUS-POLICY", name="Test Customer"),
    )


def test_material_fraud_in_n_notation_is_critical():
    result = apply_operational_policy(policy_request("Someone took N500,000 from my account, no be me."), fraud_result())
    assert result.triage.urgency == Urgency.critical
    assert result.triage.entities.amount == "N500,000"


# 3. The rules generalise and are not copied from the benchmark -----------------

def _policy_phrases() -> set[str]:
    source = Path(triage_policy.__file__).read_text(encoding="utf-8")
    phrases = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for alternative in re.split(r"[|()]", node.value):
                words = re.findall(r"[a-z]+", re.sub(r"\\[a-z]", " ", alternative.lower()))
                for size in range(3, len(words) + 1):
                    for start in range(len(words) - size + 1):
                        phrases.add(" ".join(words[start:start + size]))
    return phrases


def test_policy_rules_do_not_copy_evaluation_phrases():
    messages = [" ".join(re.findall(r"[a-z]+", case.message.lower())) for case in GOLD_CASES]
    leaked = sorted(phrase for phrase in _policy_phrases() if any(f" {phrase} " in f" {message} " for message in messages))
    assert leaked == []
    for phrase in ("four days overdue", "late four days", "block am", "rider carry", "human now", "stop production", "just need timeline", "leave warehouse", "new delivery estimate"):
        assert phrase not in Path(triage_policy.__file__).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("intent", "message", "urgency"),
    [
        (Intent.delivery_delayed, "The pharmacy parcel with insulin is 6 days late.", Urgency.high),
        (Intent.delivery_delayed, "My shoes are delayed, can I get the ETA?", Urgency.low),
        (Intent.transfer_pending, "I sent 20k 3 minutes ago, is it still processing?", Urgency.low),
        (Intent.transfer_pending, "The transfer from last night has not landed.", Urgency.high),
        (Intent.payment_failed, "Our N1.2m salary run failed after debit.", Urgency.critical),
        (Intent.delivery_change, "Please change the address before the courier picks it up.", Urgency.medium),
        (Intent.refund_pending, "The refund was approved 9 days ago and nothing yet.", Urgency.medium),
    ],
)
def test_policy_rules_handle_paraphrases_outside_the_gold_set(intent, message, urgency):
    result = fraud_result().model_copy(update={"intent": intent})
    assert apply_operational_policy(policy_request(message), result).triage.urgency == urgency


# 3b. Dashboard accuracy is not circular -----------------------------------------

def test_seeded_snapshots_and_human_corrections_do_not_count_as_model_accuracy(database):
    seed_demo_data(database)
    summary = evaluation_summary(database)
    assert summary["labelled"] == 0
    assert summary["intent_accuracy"] is None

    database.update_support_ticket_fields(
        "KOR-2402",
        {"source": "groq", "intent": "Delivery delayed", "modelIntent": "Refund pending", "modelUrgency": "low"},
    )
    main.record_feedback(
        "KOR-2402",
        FeedbackRequest(customer_id=database.support_ticket("KOR-2402")["customerId"], corrected_intent="Delivery missing"),
        AGENT,
    )
    summary = evaluation_summary(database)
    assert summary["labelled"] == 1
    assert summary["intent_accuracy"] == 0  # the model said Refund pending; truth is Delivery delayed
    assert database.support_ticket("KOR-2402")["intent"] == "Delivery missing"  # display shows the correction
    assert summary["intent_corrections"] == 1
    assert "routing_corrections" in summary and "urgency_corrections" in summary


@pytest.mark.asyncio
async def test_service_records_model_prediction_separately(database):
    class Model:
        model_name = "fake"

        async def classify(self, _request, _memory):
            return fraud_result("₦5,000").model_copy(update={"intent": Intent.account_access, "route": Route.account_support, "sentiment": Sentiment.calm, "confidence": 0.95})

    case = triaged_case(database)
    await TriageService(database, Model()).triage(
        TriageRequest(case_id=case["case_id"], channel="email", message="I cannot log in.", customer=CustomerContext(customer_id=case["customer_id"], name="Chika Okoro")),
    )
    ticket = database.support_ticket(case["case_id"])
    assert (ticket["modelIntent"], ticket["modelRoute"]) == ("Account access", "Account Support")


# 13. Policy retrieval ------------------------------------------------------------

def test_a_single_shared_word_does_not_count_as_a_policy_match(database):
    database.add_policy(
        tenant_id="tenant-demo",
        title="Card dispute handling",
        content="Card disputes are acknowledged within one hour and investigated by the disputes desk.",
        source_url=None,
        version="1",
    )
    assert relevant_policies(database, tenant_id="tenant-demo", message="My transfer is pending, please help with my account") == []
    assert relevant_policies(database, tenant_id="tenant-demo", message="I want to dispute a card charge")


def test_policy_excerpt_quotes_the_matching_passage(database):
    filler = "General introduction for all customers. " * 30
    database.add_policy(
        tenant_id="tenant-demo",
        title="Operations handbook",
        content=f"{filler}\n\nPending transfers are reviewed by the Transfers desk within one business day.",
        source_url=None,
        version="3",
    )
    [match] = relevant_policies(database, tenant_id="tenant-demo", message="My pending transfer has not arrived, which desk reviews transfers?")
    assert "Transfers desk within one business day" in match["excerpt"]
    assert len(match["excerpt"]) <= 710
