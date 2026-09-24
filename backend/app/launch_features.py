"""Launch-readiness services for knowledge, proof mode, and verified actions."""

from __future__ import annotations

import json
import re
from collections import Counter

import httpx

from .database import Database

TOKEN = re.compile(r"[a-z0-9₦]+", re.IGNORECASE)
STOP_WORDS = {
    "about", "after", "again", "been", "before", "customer", "from", "have",
    "into", "just", "that", "their", "there", "they", "this", "what", "when",
    "where", "which", "with", "your", "please", "help", "abeg", "need", "want",
    "the", "and", "for", "are", "was", "were", "has", "not", "but", "can",
    "will", "our", "una", "dey", "don", "never", "still", "since", "today",
    "yesterday", "morning", "money", "account", "kora", "support", "team",
    "must", "should", "may", "only", "any", "all", "within", "also",
}
# A policy must share this many distinct meaningful terms with the message,
# or match its title, before it is cited as approved grounding.
MIN_CONTENT_OVERLAP = 3
EXCERPT_LENGTH = 700


def _terms(value: str) -> set[str]:
    terms = set()
    for token in TOKEN.findall(value):
        term = token.lower()
        if len(term) <= 2 or term in STOP_WORDS or term.isdigit():
            continue
        terms.add(term[:-1] if len(term) > 4 and term.endswith("s") else term)
    return terms


def _best_excerpt(content: str, query_terms: set[str]) -> str:
    """Quote the passage that matched rather than the policy's opening lines."""
    if len(content) <= EXCERPT_LENGTH:
        return content
    passages = [part.strip() for part in re.split(r"\n\s*\n|(?<=[.!?])\s+", content) if part.strip()]
    best_index = max(
        range(len(passages)),
        key=lambda index: (len(query_terms & _terms(passages[index])), -index),
    )
    excerpt = passages[best_index]
    following = best_index + 1
    while following < len(passages) and len(excerpt) + len(passages[following]) + 1 <= EXCERPT_LENGTH:
        excerpt = f"{excerpt} {passages[following]}"
        following += 1
    excerpt = excerpt[:EXCERPT_LENGTH]
    prefix = "… " if best_index else ""
    suffix = " …" if following < len(passages) else ""
    return f"{prefix}{excerpt}{suffix}"


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
        title_overlap = query_terms & _terms(policy["title"])
        content_overlap = query_terms & _terms(policy["content"])
        if not title_overlap and len(content_overlap) < MIN_CONTENT_OVERLAP:
            continue
        score = len(content_overlap) + 2 * len(title_overlap)
        scored.append((score, policy, content_overlap | title_overlap))
    scored.sort(key=lambda item: (item[0], item[1]["updated_at"]), reverse=True)
    return [
        {
            "id": policy["id"],
            "title": policy["title"],
            "version": policy["version"],
            "source_url": policy["source_url"],
            "excerpt": _best_excerpt(policy["content"], query_terms),
            "matched_terms": sorted(matched)[:8],
        }
        for _, policy, matched in scored[:limit]
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
    # Only labelled candidates can be judged; unlabelled ones are reported but
    # neither reward nor penalise the readiness score.
    judged_auto = [
        row for row in auto
        if any((row.get("expected") or {}).get(key) for key in ("intent", "urgency", "route"))
    ]
    auto_errors = sum(
        1
        for row in judged_auto
        if any(
            row["expected"].get(key) and row["expected"][key] != row["predicted"].get(key)
            for key in ("intent", "urgency", "route")
        )
    )
    language_counts = Counter(row.get("language", "unspecified") for row in completed)
    accuracy = correct / label_total if label_total else None
    if judged_auto:
        safety_points = 20 * (1 - auto_errors / len(judged_auto))
    else:
        # Nothing would be automated (or nothing can be judged): neutral score.
        safety_points = 10
    readiness = max(
        0,
        min(
            100,
            round(
                (accuracy * 70 if accuracy is not None else 35)
                + safety_points
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
        "automation_simulated": True,
        "safe_automation_candidates": len(auto),
        "judged_automation_candidates": len(judged_auto),
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
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise RuntimeError("Paystack returned an invalid response.") from error
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
