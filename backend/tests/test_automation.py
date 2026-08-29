from __future__ import annotations

import pytest

from app.automation import auto_approval_decision, recorded_automation_decision


def eligible_inputs() -> dict:
    return {
        "enabled": True,
        "confidence": 0.97,
        "threshold": 95,
        "intent": "General enquiry",
        "route": "General Support",
        "message": "What time do you open?",
        "response": "Hello Customer, our approved opening hours are 08:00 to 17:00.",
        "policy_citations": [{"id": 1, "title": "Opening hours"}],
        "guardrail_escalated": False,
        "guardrail_flags": [],
        "verification_available": True,
        "delivery_available": True,
        "required_information_complete": True,
    }


@pytest.mark.parametrize(
    ("updates", "expected_code"),
    [
        ({"policy_citations": []}, "no_policy"),
        ({"enabled": False}, "disabled"),
        ({"guardrail_flags": ["unsafe_claim"]}, "guardrail"),
        ({"intent": "Fraud report"}, "high_risk"),
        ({"message": "Why was my transfer delayed?", "verification_available": False}, "verification"),
        ({"response": "We have refunded the payment."}, "unsupported_action"),
        ({"required_information_complete": False}, "incomplete_information"),
        ({"delivery_available": False}, "delivery"),
        ({"confidence": 0.9499}, "confidence"),
    ],
)
def test_automation_policy_has_one_ordered_reason_surface(
    updates: dict, expected_code: str
) -> None:
    inputs = eligible_inputs()
    inputs.update(updates)

    decision = auto_approval_decision(**inputs)

    assert decision.eligible is False
    assert decision.code == expected_code
    assert decision.reason.startswith("Human review required:")


def test_automation_policy_records_eligible_result() -> None:
    decision = auto_approval_decision(**eligible_inputs())

    assert decision.as_dict() == {
        "eligible": True,
        "reason": "Eligible for auto-approval under the active safety policy.",
        "code": "eligible",
    }


def test_invalid_or_missing_record_fails_closed() -> None:
    assert recorded_automation_decision(None).code == "not_evaluated"
    assert recorded_automation_decision({"eligible": "yes"}).eligible is False
