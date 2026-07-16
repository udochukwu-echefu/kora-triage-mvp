from __future__ import annotations

from .database import Database


def evaluation_summary(database: Database, tenant_id: str = "tenant-demo") -> dict:
    tickets = [
        item
        for item in database.support_tickets(tenant_id)
        if item.get("source") not in (None, "pending")
    ]
    labelled = [
        item
        for item in tickets
        if item.get("truthIntent") != "Unlabelled"
        and item.get("truthUrgency") != "unlabelled"
    ]
    feedback = database.feedback(tenant_id)
    intent_accuracy = (
        sum(item["intent"] == item["truthIntent"] for item in labelled) / len(labelled)
        if labelled
        else None
    )
    urgency_accuracy = (
        sum(item["urgency"] == item["truthUrgency"] for item in labelled) / len(labelled)
        if labelled
        else None
    )
    route_corrections = sum(
        bool(item["corrected"].get("route"))
        and item["corrected"].get("route") != item["predicted"].get("route")
        for item in feedback
    )
    draft_feedback = [item for item in feedback if item["response_accepted"] is not None]
    return {
        "processed": len(tickets),
        "labelled": len(labelled),
        "feedback_count": len(feedback),
        "intent_accuracy": intent_accuracy,
        "urgency_accuracy": urgency_accuracy,
        "combined_accuracy": (
            (intent_accuracy + urgency_accuracy) / 2
            if intent_accuracy is not None and urgency_accuracy is not None
            else None
        ),
        "routing_correction_rate": route_corrections / len(feedback) if feedback else 0,
        "draft_edit_rate": (
            sum(bool(item["response_edited"]) for item in draft_feedback)
            / len(draft_feedback)
            if draft_feedback
            else 0
        ),
        "response_acceptance_rate": (
            sum(bool(item["response_accepted"]) for item in draft_feedback)
            / len(draft_feedback)
            if draft_feedback
            else None
        ),
        "escalation_rate": (
            sum(bool(item.get("escalated")) for item in tickets) / len(tickets)
            if tickets
            else 0
        ),
    }


def regression_gate(database: Database, tenant_id: str = "tenant-demo") -> dict:
    summary = evaluation_summary(database, tenant_id)
    policy = database.get_setting(
        "evaluation_gate",
        {
            "minimum_combined_accuracy": 0.85,
            "maximum_routing_correction_rate": 0.15,
            "maximum_draft_edit_rate": 0.35,
        },
        tenant_id,
    )
    checks = [
        {
            "metric": "combined_accuracy",
            "passed": summary["combined_accuracy"] is not None
            and summary["combined_accuracy"] >= policy["minimum_combined_accuracy"],
            "actual": summary["combined_accuracy"],
            "threshold": policy["minimum_combined_accuracy"],
        },
        {
            "metric": "routing_correction_rate",
            "passed": summary["routing_correction_rate"]
            <= policy["maximum_routing_correction_rate"],
            "actual": summary["routing_correction_rate"],
            "threshold": policy["maximum_routing_correction_rate"],
        },
        {
            "metric": "draft_edit_rate",
            "passed": summary["draft_edit_rate"] <= policy["maximum_draft_edit_rate"],
            "actual": summary["draft_edit_rate"],
            "threshold": policy["maximum_draft_edit_rate"],
        },
    ]
    return {
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "policy": policy,
        "summary": summary,
    }
