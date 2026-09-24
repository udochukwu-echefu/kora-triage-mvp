from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import ModelTriage, TriageRequest

SECRET_TERMS = re.compile(
    r"\b(?:pin|otp|one[- ]time (?:password|code|pin)|password|passcode|cvv|cvc|"
    r"security (?:code|question|answer)|full card (?:number|details)|card number|"
    r"bvn|nin|login (?:details|credentials))\b",
    re.IGNORECASE,
)
# Any request, instruction, or question in the same sentence as a secret term.
REQUEST_CUE = re.compile(
    r"\b(?:send|share|provide|reply with|give|tell|confirm|enter|type|verify|submit|"
    r"input|drop|forward|what is|what's|whats|kindly|please|need)\b|\?",
    re.IGNORECASE,
)
# Safety advice ("never share your PIN") is allowed.
NEGATION = re.compile(
    r"\b(?:never|do not|don['’]t|dont|not to|avoid|won['’]t ask|will not ask|no one)\b",
    re.IGNORECASE,
)
PARTIAL_CARD = re.compile(r"\b(?:last (?:four|4)|ending)\b", re.IGNORECASE)

UNSAFE_COMPLETION_CLAIM = re.compile(
    r"\b(?:we have|i have|has been|have been)\s+(?:reversed|refunded|blocked|unblocked|credited|restored)\b",
    re.IGNORECASE,
)
# A completed external action the agent cannot know happened.
UNSAFE_ACTION_CLAIM = re.compile(
    r"\b(?:i|we)(?:\s+have|['’]ve)?\s+"
    r"(?:generated|sent|checked|contacted|logged|opened|initiated|submitted|"
    r"blocked|unblocked|reversed|refunded|credited|restored)\b",
    re.IGNORECASE,
)
# A promise of an external action. Promising to contact or update the customer
# is fine; promising to move money or contact a third party is not.
UNSAFE_PROMISE = re.compile(
    r"\b(?:i|we)(?:\s+will|['’]ll)\s+"
    r"(?:generate|check|contact(?!\s+you\b)|initiate|submit|block|unblock|reverse|"
    r"refund|credit|restore|send(?!\s+you\b))\b",
    re.IGNORECASE,
)
LEGAL_OR_PUBLIC_THREAT = re.compile(
    r"\b(?:lawyer|solicitor|lawsuit|sue|suing|court|police|efcc|fccpc|cbn|"
    r"social media|twitter|tiktok|x\.com|journalist|newspaper|press release|go(?:ing)? viral)\b"
    r"|\b(?:go|going|went|take (?:this|it|you))\s+to\s+(?:the\s+)?(?:press|media)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GuardrailDecision:
    escalated: bool
    reason: str | None
    response: str
    flags: tuple[str, ...]


def requests_sensitive_data(text: str) -> bool:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if not SECRET_TERMS.search(sentence):
            continue
        if NEGATION.search(sentence):
            continue
        if PARTIAL_CARD.search(sentence) and not re.search(
            r"\b(?:pin|otp|password|passcode|cvv|cvc|bvn|nin)\b", sentence, re.IGNORECASE
        ):
            continue
        if REQUEST_CUE.search(sentence):
            return True
    return False


def claims_unverified_action(text: str) -> bool:
    return bool(
        UNSAFE_COMPLETION_CLAIM.search(text)
        or UNSAFE_ACTION_CLAIM.search(text)
        or UNSAFE_PROMISE.search(text)
    )


def review_response(text: str) -> list[str]:
    """Flags for a customer-facing reply, whether drafted by AI or edited by a person."""
    flags = []
    if requests_sensitive_data(text):
        flags.append("sensitive_data_request_blocked")
    if claims_unverified_action(text):
        flags.append("unverified_action_claim_blocked")
    return flags


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
    first_name = (request.customer.name.split() or ["there"])[0]
    if requests_sensitive_data(response):
        flags.append("sensitive_data_request_blocked")
        response = (
            f"Hi {first_name}, we’ve received your message and passed it "
            "to a support specialist for review. For your security, do not share your PIN, OTP, "
            "password, or full card details. We’ll update you through this verified channel."
        )
        reasons.append("Draft attempted to request sensitive authentication data")
    elif claims_unverified_action(response):
        flags.append("unverified_action_claim_blocked")
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
