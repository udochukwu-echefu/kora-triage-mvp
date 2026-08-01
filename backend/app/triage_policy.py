from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import Intent, ModelTriage, Route, TriageRequest, Urgency


REFERENCE = re.compile(r"\b(TRX|PAY|REF|SUB)-[A-Z0-9]+\b", re.IGNORECASE)
ORDER_REFERENCE = re.compile(r"\bORD-[A-Z0-9]+\b", re.IGNORECASE)
AMOUNT = re.compile(r"\bNGN\s*[\d,]+(?:\.\d{1,2})?\b|₦\s*[\d,]+(?:\.\d{1,2})?", re.IGNORECASE)

ROUTE_BY_INTENT = {
    Intent.transfer_pending: Route.transfers,
    Intent.payment_failed: Route.payments,
    Intent.duplicate_debit: Route.payments,
    Intent.fraud_report: Route.risk_fraud,
    Intent.delivery_delayed: Route.logistics,
    Intent.delivery_missing: Route.logistics,
    Intent.delivery_change: Route.logistics,
    Intent.account_access: Route.account_support,
    Intent.account_verification: Route.compliance,
    Intent.refund_pending: Route.payments,
}


@dataclass(frozen=True)
class PolicyResult:
    triage: ModelTriage
    overrides: tuple[str, ...]


def _numeric_amount(message: str) -> int | None:
    match = AMOUNT.search(message)
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(0))
    return int(digits) if digits else None


def _policy_urgency(request: TriageRequest, result: ModelTriage) -> Urgency:
    text = " ".join(
        value for value in (request.subject or "", request.message) if value
    ).lower()
    amount = _numeric_amount(text)
    intent = result.intent

    if intent == Intent.transfer_pending:
        recent = re.search(
            r"\b(?:five|5|ten|10)\s+minutes?\b|\bjust\b|\bnormal waiting time\b",
            text,
        )
        return Urgency.low if recent else Urgency.high

    if intent == Intent.payment_failed:
        critical_impact = re.search(
            r"\b(?:production|payroll|salary|business-critical|halted|"
            r"blocking (?:the )?business|stop production)\b",
            text,
        )
        return (
            Urgency.critical
            if critical_impact and (amount is None or amount >= 100_000)
            else Urgency.medium
        )

    if intent == Intent.duplicate_debit:
        return Urgency.high if amount is not None and amount >= 20_000 else Urgency.medium

    if intent == Intent.fraud_report:
        immediate = re.search(
            r"\b(?:block (?:the )?card|block am|sharp sharp|immediately|"
            r"urgent fraud|human now)\b",
            text,
        )
        material = amount is not None and amount >= 50_000
        return Urgency.critical if immediate or material else Urgency.high

    if intent == Intent.delivery_delayed:
        time_sensitive = re.search(
            r"\b(?:clinic|medical|supplies|before tomorrow|time-sensitive|"
            r"four days overdue|late four days)\b",
            text,
        )
        routine_transit = re.search(
            r"\b(?:in transit since yesterday|one day|new delivery estimate|"
            r"expected delivery time)\b",
            text,
        )
        if time_sensitive:
            return Urgency.high
        return Urgency.low if routine_transit else Urgency.medium

    if intent == Intent.delivery_missing:
        return Urgency.high

    if intent == Intent.delivery_change:
        dispatch_risk = re.search(
            r"\b(?:before dispatch|before (?:it|e) (?:is )?(?:sent|leave)|"
            r"leave warehouse|rider carry)\b",
            text,
        )
        return Urgency.medium if dispatch_risk else Urgency.low

    if intent == Intent.account_access:
        business_blocked = re.search(
            r"\b(?:merchant|shop|sales|processing orders|business.*"
            r"(?:blocked|unable|operate|stop))\b",
            text,
        )
        return Urgency.high if business_blocked else Urgency.medium

    if intent == Intent.account_verification:
        return Urgency.low

    if intent == Intent.refund_pending:
        recent = re.search(
            r"\b(?:yesterday|one day|1 day|expected timeline|just need timeline)\b",
            text,
        )
        return Urgency.low if recent else Urgency.medium

    if intent == Intent.general_enquiry and result.route == Route.payments:
        return Urgency.medium

    return result.urgency


def apply_operational_policy(
    request: TriageRequest,
    result: ModelTriage,
) -> PolicyResult:
    overrides: list[str] = []
    updates: dict = {}

    route = ROUTE_BY_INTENT.get(result.intent)
    if result.intent == Intent.general_enquiry and re.search(
        r"\b(?:fee|charge|billing|statement)\b",
        f"{request.subject or ''} {request.message}",
        re.IGNORECASE,
    ):
        route = Route.payments
    if route is not None and route != result.route:
        updates["route"] = route
        overrides.append(f"route:{result.route.value}->{route.value}")

    urgency = _policy_urgency(
        request,
        result.model_copy(update={"route": updates.get("route", result.route)}),
    )
    if urgency != result.urgency:
        updates["urgency"] = urgency
        overrides.append(f"urgency:{result.urgency.value}->{urgency.value}")

    entity_updates: dict[str, str] = {}
    transaction_match = REFERENCE.search(request.message)
    order_match = ORDER_REFERENCE.search(request.message)
    amount_match = AMOUNT.search(request.message)
    if transaction_match:
        reference = transaction_match.group(0).upper()
        if result.entities.transaction_id != reference:
            entity_updates["transaction_id"] = reference
            overrides.append("entity:transaction_reference")
        if result.entities.order_id == reference:
            entity_updates["order_id"] = None
    if order_match:
        order_id = order_match.group(0).upper()
        if result.entities.order_id != order_id:
            entity_updates["order_id"] = order_id
            overrides.append("entity:order_reference")
    if amount_match and not result.entities.amount:
        entity_updates["amount"] = amount_match.group(0)
        overrides.append("entity:amount")
    if entity_updates:
        updates["entities"] = result.entities.model_copy(update=entity_updates)

    if overrides:
        evidence = list(result.evidence)
        evidence.append(
            "Kora operational policy normalised routing, urgency, or references."
        )
        updates["evidence"] = list(dict.fromkeys(evidence))[:5]

    return PolicyResult(
        triage=result.model_copy(update=updates) if updates else result,
        overrides=tuple(overrides),
    )
