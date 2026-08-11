"""Launch-readiness services for knowledge, proof mode, and verified actions."""

from __future__ import annotations

import re
from collections import Counter

import httpx

from .database import Database


TOKEN = re.compile(r"[a-z0-9₦]+", re.IGNORECASE)
STOP_WORDS = {
    "about", "after", "again", "been", "before", "customer", "from", "have",
    "into", "just", "that", "their", "there", "they", "this", "what", "when",
    "where", "which", "with", "your",
}


def _terms(value: str) -> set[str]:
    terms = set()
    for token in TOKEN.findall(value):
        term = token.lower()
        if len(term) <= 2 or term in STOP_WORDS:
            continue
        terms.add(term[:-1] if len(term) > 4 and term.endswith("s") else term)
    return terms


def relevant_policies(
    database: Database,
    *,
    tenant_id: str,
    message: str,
    limit: int = 3,
) -> list[dict]:
    """Return transparent lexical matches without introducing an embedding service."""
    query_terms = _terms(message)
    scored = []
    for policy in database.policies(tenant_id, active_only=True):
        title_terms = _terms(policy["title"])
        content_terms = _terms(policy["content"])
        overlap = query_terms & content_terms
        score = len(overlap) + (2 * len(query_terms & title_terms))
        if score:
            scored.append((score, policy))
    scored.sort(key=lambda item: (item[0], item[1]["updated_at"]), reverse=True)
    return [
        {
            "id": policy["id"],
            "title": policy["title"],
            "version": policy["version"],
            "source_url": policy["source_url"],
            "excerpt": policy["content"][:700],
            "matched_terms": sorted(query_terms & _terms(policy["content"]))[:8],
        }
        for _, policy in scored[:limit]
    ]


def proof_report(rows: list[dict], auto_threshold: int = 95) -> dict:
    completed = [row for row in rows if not row.get("error")]
    labelled = [row for row in completed if row.get("expected")]
    correct = 0
    label_total = 0
    accuracy_by_label = {}
    for row in labelled:
        expected = row["expected"]
        for key in ("intent", "urgency", "route"):
            if expected.get(key):
                label_total += 1
                correct += int(row["predicted"].get(key) == expected[key])
    for key in ("intent", "urgency", "route"):
        measured = [row for row in labelled if row["expected"].get(key)]
        accuracy_by_label[key] = (
            sum(row["predicted"].get(key) == row["expected"][key] for row in measured) / len(measured)
            if measured else None
        )
    auto = [
        row for row in completed
        if row["predicted"].get("automation_eligible") is True
    ]
    auto_errors = 0
    for row in auto:
        expected = row.get("expected") or {}
        if expected and any(
            expected.get(key) and expected[key] != row["predicted"].get(key)
            for key in ("intent", "urgency", "route")
        ):
            auto_errors += 1
    language_counts = Counter(row.get("language", "unspecified") for row in completed)
    accuracy = correct / label_total if label_total else None
    readiness = max(
        0,
        min(
            100,
            round(
                (accuracy * 70 if accuracy is not None else 35)
                + (20 if not auto_errors else max(0, 20 - auto_errors * 5))
                + (10 if completed and len(completed) == len(rows) else 0)
            ),
        ),
    )
    return {
        "total": len(rows),
        "completed": len(completed),
        "failed": len(rows) - len(completed),
        "label_accuracy": accuracy,
        "intent_accuracy": accuracy_by_label["intent"],
        "urgency_accuracy": accuracy_by_label["urgency"],
        "routing_accuracy": accuracy_by_label["route"],
        "labels_correct": correct,
        "labels_total": label_total,
        "safe_automation_candidates": len(auto),
        "unsafe_automation_candidates": auto_errors,
        "guardrail_failures": auto_errors,
        "human_review_cases": sum(
            1 for row in completed if row["predicted"]["escalated"]
        ),
        "language_mix": dict(language_counts),
        "readiness_score": readiness,
        "recommendation": (
            "Ready for a guarded pilot"
            if readiness >= 85
            else "Run with mandatory human review"
            if readiness >= 65
            else "Refine policies and labels before activation"
        ),
        "cases": rows,
    }


class PaystackVerifier:
    def __init__(
        self,
        secret_key: str,
        base_url: str = "https://api.paystack.co",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    async def verify(self, reference: str) -> dict:
        safe_reference = reference.strip()
        if not re.fullmatch(r"[A-Za-z0-9.=_-]{3,100}", safe_reference):
            raise ValueError("Transaction reference contains unsupported characters.")
        async with httpx.AsyncClient(timeout=12, transport=self.transport) as client:
            response = await client.get(
                f"{self.base_url}/transaction/verify/{safe_reference}",
                headers={"Authorization": f"Bearer {self.secret_key}"},
            )
        payload = response.json()
        if response.status_code >= 400 or not payload.get("status"):
            raise RuntimeError(payload.get("message") or "Paystack verification failed.")
        data = payload.get("data") or {}
        return {
            "provider": "Paystack",
            "reference": data.get("reference") or safe_reference,
            "status": data.get("status") or "unknown",
            "amount": (
                round(data["amount"] / 100, 2)
                if isinstance(data.get("amount"), (int, float))
                else None
            ),
            "currency": data.get("currency"),
            "channel": data.get("channel"),
            "gateway_response": data.get("gateway_response"),
            "paid_at": data.get("paid_at"),
            "verified": True,
        }
