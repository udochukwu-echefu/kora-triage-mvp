from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from .evaluation_dataset import GoldCase


ENTITY_FIELDS = ("amount", "transactionId", "orderId", "account", "card")
DEFAULT_THRESHOLDS = {
    "intent_accuracy": 0.90,
    "urgency_accuracy": 0.80,
    "route_accuracy": 0.90,
    "entity_required_accuracy": 0.90,
}
MINIMUM_FULL_DATASET_CASES = 100


def _normalise_entity(field: str, value: str | None) -> str | None:
    if value is None:
        return None
    compact = re.sub(r"\s+", "", str(value)).upper()
    if field == "amount":
        digits = re.sub(r"\D", "", compact)
        return digits or None
    if field in {"account", "card"}:
        digits = re.sub(r"\D", "", compact)
        return digits[-4:] if digits else None
    return re.sub(r"[^A-Z0-9]", "", compact) or None


def _case_scores(case: GoldCase, prediction: dict) -> dict:
    predicted_entities = prediction.get("entities") or {}
    entity_matches = {
        field: _normalise_entity(field, predicted_entities.get(field))
        == _normalise_entity(field, case.entities.get(field))
        for field in ENTITY_FIELDS
    }
    required_fields = [
        field for field in ENTITY_FIELDS if case.entities.get(field) is not None
    ]
    return {
        "intent": prediction.get("intent") == case.intent,
        "urgency": prediction.get("urgency") == case.urgency,
        "route": prediction.get("route") == case.route,
        "entity_exact": all(entity_matches.values()),
        "entity_required": (
            all(entity_matches[field] for field in required_fields)
            if required_fields
            else True
        ),
        "unexpected_entity": any(
            case.entities.get(field) is None
            and _normalise_entity(field, predicted_entities.get(field)) is not None
            for field in ENTITY_FIELDS
        ),
    }


def score_predictions(
    cases: Iterable[GoldCase], predictions: dict[str, dict]
) -> dict:
    case_list = list(cases)
    items = [case for case in case_list if case.case_id in predictions]
    scored = [(case, _case_scores(case, predictions[case.case_id])) for case in items]

    def accuracy(metric: str, rows=scored) -> float | None:
        return (
            sum(int(scores[metric]) for _, scores in rows) / len(rows)
            if rows
            else None
        )

    groups: dict[str, dict[str, list[tuple[GoldCase, dict]]]] = {
        "domain": defaultdict(list),
        "language": defaultdict(list),
    }
    for case, scores in scored:
        groups["domain"][case.domain].append((case, scores))
        groups["language"][case.language].append((case, scores))

    def grouped(rows_by_name: dict[str, list[tuple[GoldCase, dict]]]) -> dict:
        return {
            name: {
                "cases": len(rows),
                "intent_accuracy": accuracy("intent", rows),
                "urgency_accuracy": accuracy("urgency", rows),
                "route_accuracy": accuracy("route", rows),
                "entity_required_accuracy": accuracy("entity_required", rows),
            }
            for name, rows in sorted(rows_by_name.items())
        }

    intent = accuracy("intent")
    urgency = accuracy("urgency")
    route = accuracy("route")
    core = [metric for metric in (intent, urgency, route) if metric is not None]
    report = {
        "processed": len(scored),
        "expected": len(case_list),
        "intent_accuracy": intent,
        "urgency_accuracy": urgency,
        "route_accuracy": route,
        "combined_accuracy": sum(core) / len(core) if core else None,
        "entity_required_accuracy": accuracy("entity_required"),
        "entity_exact_match": accuracy("entity_exact"),
        "unexpected_entity_rate": (
            sum(int(scores["unexpected_entity"]) for _, scores in scored)
            / len(scored)
            if scored
            else None
        ),
        "by_domain": grouped(groups["domain"]),
        "by_language": grouped(groups["language"]),
        "failures": [
            {
                "case_id": case.case_id,
                "domain": case.domain,
                "language": case.language,
                "expected": {
                    "intent": case.intent,
                    "urgency": case.urgency,
                    "route": case.route,
                    "entities": case.entities,
                },
                "predicted": predictions[case.case_id],
                "checks": scores,
            }
            for case, scores in scored
            if not all(
                scores[key]
                for key in ("intent", "urgency", "route", "entity_required")
            )
        ],
    }
    fraud_rows = [
        (case, scores)
        for case, scores in scored
        if case.domain == "fraud_unauthorised"
    ]
    fraud_recall = (
        sum(int(scores["intent"]) for _, scores in fraud_rows) / len(fraud_rows)
        if fraud_rows
        else None
    )
    report["fraud_recall"] = fraud_recall
    checks = {
        metric: report[metric] is not None
        and report[metric] >= threshold
        for metric, threshold in DEFAULT_THRESHOLDS.items()
    }
    checks["fraud_recall"] = fraud_recall is not None and fraud_recall >= 0.95
    checks["complete_run"] = (
        len(case_list) >= MINIMUM_FULL_DATASET_CASES
        and len(scored) == len(case_list)
    )
    report["release_gate"] = {
        "passed": all(checks.values()),
        "thresholds": {**DEFAULT_THRESHOLDS, "fraud_recall": 0.95},
        "checks": checks,
    }
    return report
