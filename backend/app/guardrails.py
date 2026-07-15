from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import ModelTriage, TriageRequest


SENSITIVE_REQUEST = re.compile(
    r"(?:send|share|provide|reply with).{0,25}\b(?:pin|otp|password|cvv|full card number)\b",
    re.IGNORECASE,
)
UNSAFE_COMPLETION_CLAIM = re.compile(
    r"\b(?:we have|i have|has been)\s+(?:reversed|refunded|blocked|unblocked|credited|restored)\b",
    re.IGNORECASE,
)
UNSAFE_ACTION_CLAIM = re.compile(
    r"\b(?:i|we)(?:\s+have|['’]ve|\s+will|['’]ll)?\s+"
    r"(?:generated|sent|checked|contact(?:ed)?|forwarded|escalated|logged|opened|"
    r"initiated|submitted|blocked|unblocked|reversed|refunded|credited|restored)\b",
    re.IGNORECASE,
)
LEGAL_OR_PUBLIC_THREAT = re.compile(
    r"\b(?:lawyer|court|police|efcc|fccpc|social media|twitter|x\.com|press)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GuardrailDecision:
    escalated: bool
    reason: str | None
    response: str
    flags: tuple[str, ...]


def apply_guardrails(
    request: TriageRequest,
    result: ModelTriage,
    low_confidence_threshold: float = 0.70,
) -> GuardrailDecision:
    flags: list[str] = []
    reasons: list[str] = []

    if result.confidence < low_confidence_threshold:
        flags.append("low_confidence")
        reasons.append(
            f"Model confidence is below the configured {round(low_confidence_threshold * 100)}% review threshold"
        )
    if result.sentiment.value == "hostile":
        flags.append("hostile_sentiment")
        reasons.append("Hostile sentiment requires human review")
    if result.urgency.value == "critical":
        flags.append("critical_urgency")
        reasons.append("Critical urgency requires specialist action")
    if result.intent.value == "Fraud report":
        flags.append("fraud_report")
        reasons.append("Fraud reports cannot be resolved automatically")
    if LEGAL_OR_PUBLIC_THREAT.search(request.message):
        flags.append("legal_or_public_threat")
        reasons.append("Legal or public escalation language detected")

    response = result.draft_response.strip()
    if SENSITIVE_REQUEST.search(response):
        flags.append("sensitive_data_request_blocked")
        response = (
            f"Hi {request.customer.name.split()[0]}, we’ve received your message and sent it "
            "to a support specialist for review. For your security, do not share your PIN, OTP, "
            "password, or full card details. We’ll update you through this verified channel."
        )
        reasons.append("Draft attempted to request sensitive authentication data")
    elif UNSAFE_COMPLETION_CLAIM.search(response) or UNSAFE_ACTION_CLAIM.search(response):
        flags.append("unverified_action_claim_blocked")
        first_name = request.customer.name.split()[0]
        response = (
            f"Hi {first_name}, we’ve received your message and routed the case to "
            f"{result.route.value} for review. No financial, delivery, or account action has "
            "been completed yet. We’ll update you through this verified channel when the "
            "review team confirms the next step."
        )
        reasons.append("Unverified external-action claim was removed")

    escalated = bool(reasons)
    return GuardrailDecision(
        escalated=escalated,
        reason="; ".join(dict.fromkeys(reasons)) if reasons else None,
        response=response[:1200],
        flags=tuple(dict.fromkeys(flags)),
    )
