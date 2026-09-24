"""Deterministic operational policy applied after model classification.

These rules encode general support policy (routing by intent, SLA urgency by
business impact). They must stay general: phrases copied from the labelled
evaluation set would make the benchmark measure the rules instead of the
system. ``test_policy_rules_do_not_copy_evaluation_phrases`` guards against that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .schemas import Intent, ModelTriage, Route, TriageRequest, Urgency

REFERENCE = re.compile(r"\b(TRX|PAY|REF|SUB)-[A-Z0-9]+\b", re.IGNORECASE)
ORDER_REFERENCE = re.compile(r"\bORD-[A-Z0-9]+\b", re.IGNORECASE)

_NUMBER = r"\d[\d,]*(?:\.\d{1,2})?"
_MULTIPLIER = r"(?:k|m|million|thousand)"
# Nigerian amounts: ₦45,000 · NGN 45000 · N45,000 · N50k · ₦2.5m · 50k naira ·
# 50,000 naira. A bare "N" only counts when a digit follows immediately.
AMOUNT = re.compile(
    rf"(?:₦|\bNGN\s?|\bN(?=\d))\s?{_NUMBER}(?:\s?{_MULTIPLIER}\b)?"
    rf"|\b{_NUMBER}\s?{_MULTIPLIER}?\s?(?:naira|ngn)\b"
    rf"|\b\d+(?:\.\d+)?k\b",
    re.IGNORECASE,
)

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

_COUNT_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "several": 3, "many": 3,
}

# Business impact cues, grouped by policy meaning rather than by example text.
RECENT_TRANSFER = re.compile(
    r"\b(?:\d{1,2}|a few|few|five|ten|fifteen|twenty|thirty)\s*(?:min|mins|minutes?)\b"
    r"|\bjust now\b|\bnormal (?:wait|waiting|processing)\b|\bstill processing\b"
)
BUSINESS_CRITICAL = re.compile(
    r"\b(?:payroll|salary|salaries|production|halted|business[- ]critical|"
    r"shut(?:ting)? down|cannot operate|can't operate|stopped operations|materials)\b"
)
IMMEDIATE_FRAUD = re.compile(
    r"\b(?:block|freeze|immediately|urgent|urgently|asap|right now|emergency)\b"
)
TIME_SENSITIVE_DELIVERY = re.compile(
    r"\b(?:clinic|hospital|medical|medicine|drugs|pharmacy|patient|wedding|funeral|"
    r"exam|flight|time-sensitive|urgent|urgently)\b"
)
ROUTINE_TRANSIT = re.compile(
    r"\bsince yesterday\b|\bone day\b|\b1 day\b|\beta\b|\bestimate[ds]?\b|\bexpected delivery\b"
)
DISPATCH_RISK = re.compile(
    r"\bbefore (?:it|e|the order|the parcel)?\s*(?:is |has )?"
    r"(?:dispatch|dispatched|sent|shipped|ships|leave|leaves|left)\b"
    r"|\bbefore dispatch\b|\bwarehouse\b|\brider\b|\bcourier\b"
)
BUSINESS_BLOCKED = re.compile(
    r"\b(?:merchant|shop|store|sales|orders|business|customers are waiting)\b"
)
RECENT_REFUND = re.compile(
    r"\b(?:today|yesterday|one day|1 day|24 hours|timeline|how long|when should|when will)\b"
)


@dataclass(frozen=True)
class PolicyResult:
    triage: ModelTriage
    overrides: tuple[str, ...]


def parse_amount(value: str) -> Decimal | None:
    """Return the naira value of an amount string such as ``N50k`` or ``₦2.5m``."""
    lowered = value.lower()
    number = re.search(r"\d[\d,]*(?:\.\d+)?", lowered)
    if not number:
        return None
    try:
        amount = Decimal(number.group(0).replace(",", ""))
    except InvalidOperation:
        return None
    suffix = lowered[number.end():]
    if re.match(r"\s?(?:m\b|million)", suffix):
        amount *= 1_000_000
    elif re.match(r"\s?(?:k\b|thousand)", suffix):
        amount *= 1_000
    return amount


def _numeric_amount(message: str) -> Decimal | None:
    match = AMOUNT.search(message)
    return parse_amount(match.group(0)) if match else None


def _days_overdue(text: str) -> int:
    """Largest "N days late/overdue/delayed/stuck" count mentioned."""
    longest = 0
    for match in re.finditer(r"\b(\d{1,2}|[a-z]+)\s+days?\b", text):
        token = match.group(1)
        count = int(token) if token.isdigit() else _COUNT_WORDS.get(token, 0)
        window = text[max(0, match.start() - 40): match.end() + 40]
        if count and re.search(r"\b(?:late|overdue|delay|delayed|stuck|no movement|not moved|not changed)\b", window):
            longest = max(longest, count)
    return longest


def _policy_urgency(request: TriageRequest, result: ModelTriage) -> Urgency:
    text = " ".join(
        value for value in (request.subject or "", request.message) if value
    ).lower()
    amount = _numeric_amount(text)
    intent = result.intent

    if intent == Intent.transfer_pending:
        return Urgency.low if RECENT_TRANSFER.search(text) else Urgency.high

    if intent == Intent.payment_failed:
        return (
            Urgency.critical
            if BUSINESS_CRITICAL.search(text) and (amount is None or amount >= 100_000)
            else Urgency.medium
        )

    if intent == Intent.duplicate_debit:
        return Urgency.high if amount is not None and amount >= 20_000 else Urgency.medium

    if intent == Intent.fraud_report:
        material = amount is not None and amount >= 50_000
        return Urgency.critical if IMMEDIATE_FRAUD.search(text) or material else Urgency.high

    if intent == Intent.delivery_delayed:
        if TIME_SENSITIVE_DELIVERY.search(text) or _days_overdue(text) >= 4:
            return Urgency.high
        return Urgency.low if ROUTINE_TRANSIT.search(text) else Urgency.medium

    if intent == Intent.delivery_missing:
        return Urgency.high

    if intent == Intent.delivery_change:
        return Urgency.medium if DISPATCH_RISK.search(text) else Urgency.low

    if intent == Intent.account_access:
        return Urgency.high if BUSINESS_BLOCKED.search(text) else Urgency.medium

    if intent == Intent.account_verification:
        return Urgency.low

    if intent == Intent.refund_pending:
        overdue = _days_overdue(text) >= 3 or re.search(
            r"\b(?:\d{1,2}|three|four|five|six|seven|several)\s+days?\s+ago\b", text
        )
        return Urgency.medium if overdue or not RECENT_REFUND.search(text) else Urgency.low

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
        entity_updates["amount"] = amount_match.group(0).strip()
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
