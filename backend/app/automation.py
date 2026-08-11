"""Safety-first eligibility checks for unattended customer responses."""

from __future__ import annotations

from dataclasses import dataclass


HIGH_RISK_INTENTS = {
    "Fraud report",
    "Duplicate debit",
    "Payment failed",
    "Transfer pending",
    "Account access",
}
HIGH_RISK_ROUTES = {"Fraud", "Transfers", "Billing", "Account Support", "Compliance"}
FINANCIAL_TERMS = ("refund", "reverse", "reversal", "debited", "credited", "transfer")
UNSUPPORTED_ACTION_TERMS = (
    "i have reversed",
    "we have reversed",
    "has been reversed",
    "i have refunded",
    "we have refunded",
    "has been refunded",
    "i have contacted",
    "we have contacted",
    "has been sent",
    "i have updated",
    "we have updated",
)


@dataclass(frozen=True)
class AutomationDecision:
    eligible: bool
    reason: str
    code: str


def auto_approval_decision(
    *,
    enabled: bool,
    confidence: float,
    threshold: int,
    intent: str,
    route: str,
    message: str,
    response: str,
    policy_citations: list[dict],
    guardrail_escalated: bool,
    guardrail_flags: list[str],
    verification_available: bool,
    delivery_available: bool,
    required_information_complete: bool,
) -> AutomationDecision:
    """Return one authoritative decision, with confidence treated as one input only."""
    if not policy_citations:
        return AutomationDecision(False, "Human review required: no approved policy matched.", "no_policy")
    if not enabled:
        return AutomationDecision(False, "Human review required: auto-approval is off.", "disabled")
    if guardrail_escalated or guardrail_flags:
        return AutomationDecision(False, "Human review required: a safety guardrail was triggered.", "guardrail")
    if intent in HIGH_RISK_INTENTS or route in HIGH_RISK_ROUTES:
        return AutomationDecision(False, "Human review required: this case involves security or financial risk.", "high_risk")
    combined = f"{message} {response}".lower()
    if any(term in combined for term in FINANCIAL_TERMS) and not verification_available:
        return AutomationDecision(False, "Human review required: transaction verification is unavailable.", "verification")
    if any(term in response.lower() for term in UNSUPPORTED_ACTION_TERMS):
        return AutomationDecision(False, "Human review required: the draft claims an unverified external action.", "unsupported_action")
    if not required_information_complete:
        return AutomationDecision(False, "Human review required: customer information is incomplete.", "incomplete_information")
    if not delivery_available:
        return AutomationDecision(False, "Human review required: customer delivery is not connected.", "delivery")
    if confidence * 100 < threshold:
        return AutomationDecision(False, f"Human review required: confidence is below {threshold}%.", "confidence")
    return AutomationDecision(True, "Eligible for auto-approval under the active safety policy.", "eligible")
