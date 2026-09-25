"""Human decisions on a triaged case: approve, escalate, route, resolve and correct."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ...auth import ROLE_LEVEL, Principal
from ...automation import recorded_automation_decision
from ...guardrails import review_response
from ...launch_features import PaystackVerifier
from ...schemas import (
    ActionRequest,
    FeedbackRequest,
    ManualAssessmentRequest,
    ResolveRequest,
    RouteRequest,
    TransactionVerifyRequest,
)
from ...workflow import send_job_payload
from .. import deps
from ..deps import (
    current_principal,
    validated_case,
    write_rate_limit,
)

router = APIRouter()


# A case in one of these states has already been answered or closed; a new
# customer message moves it back to "replied"/"reopened" for fresh review.
ALREADY_HANDLED_STATES = {"approved", "queued", "sent", "delivered", "resolved"}


def _can_override_guardrail(principal: Principal, lifecycle: dict) -> bool:
    return (
        ROLE_LEVEL.get(principal.role, 0) >= ROLE_LEVEL["support_manager"]
        or lifecycle.get("assigned_to") == principal.display_name
    )


@router.post("/api/cases/{case_id}/approve")
def approve(
    case_id: str,
    action: ActionRequest,
    principal: Principal = Depends(current_principal),
    _: None = Depends(write_rate_limit),
) -> dict:
    # One transaction: the state check and the approval cannot interleave with
    # a concurrent approval (double click, two agents).
    with deps.database.transaction():
        latest = validated_case(case_id, action.customer_id, principal.tenant_id)
        lifecycle = deps.database.lifecycle(case_id, principal.tenant_id) or {}
        if lifecycle.get("state") in ALREADY_HANDLED_STATES:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This case is already {lifecycle['state']}. A new customer message "
                    "reopens it for review."
                ),
            )
        automation_decision = recorded_automation_decision(
            latest["decision"].get("automation")
        )
        if action.require_automation_eligible and not automation_decision.eligible:
            raise HTTPException(status_code=409, detail=automation_decision.reason)
        guardrail_override = bool(latest["guardrails"].get("escalated"))
        if guardrail_override:
            if action.require_automation_eligible or not _can_override_guardrail(principal, lifecycle):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "A guardrail blocked this case. Only the assigned specialist or a "
                        "manager can approve a reviewed reply."
                    ),
                )
            if not action.note or len(action.note.strip()) < 10:
                raise HTTPException(
                    status_code=422,
                    detail="Add a review note (10+ characters) explaining why this reply is safe to send.",
                )
        predicted_response = latest["decision"].get("response") or ""
        reviewed_response = (action.response or predicted_response).strip()
        if not reviewed_response:
            raise HTTPException(status_code=422, detail="Write a reply before approving.")
        # Human edits get the same checks as AI drafts.
        flags = review_response(reviewed_response)
        if flags:
            problems = {
                "sensitive_data_request_blocked": "asks the customer for a PIN, OTP, password, BVN or card details",
                "unverified_action_claim_blocked": "claims or promises an action (refund, reversal, contact) that has not been verified",
            }
            raise HTTPException(
                status_code=422,
                detail="This reply " + " and ".join(problems[flag] for flag in flags) + ". Edit it before approving.",
            )
        audit_id = deps.database.add_audit(
            case_id=case_id,
            customer_id=action.customer_id,
            event_type="human_approved",
            model=None,
            request={},
            decision={
                "status": "approved",
                "note": action.note,
                "response": reviewed_response,
                "guardrail_override": guardrail_override,
            },
            guardrails={"reviewed_response_checked": True, "override": guardrail_override},
            actor=principal.display_name,
            tenant_id=principal.tenant_id,
        )
        deps.database.add_feedback(
            case_id=case_id,
            customer_id=action.customer_id,
            actor=principal.display_name,
            predicted=latest["decision"],
            corrected={},
            response_accepted=True,
            response_edited=reviewed_response != predicted_response.strip(),
            reason=action.note,
            tenant_id=principal.tenant_id,
        )
        has_inbound = deps.database.latest_inbound_message(case_id, principal.tenant_id) is not None
        job_id = None
        if has_inbound and deps.settings.delivery_ready:
            job_id = deps.database.enqueue_job(
                tenant_id=principal.tenant_id,
                job_type="send_response",
                idempotency_key=f"approved-send:{audit_id}",
                payload=send_job_payload(
                    deps.database,
                    case_id=case_id,
                    tenant_id=principal.tenant_id,
                    response=reviewed_response,
                    actor=principal.display_name,
                    expected_states=["queued"],
                ),
            )
            deps.database.set_lifecycle(case_id, "queued", tenant_id=principal.tenant_id)
            ticket_status = "Queued to send"
        else:
            deps.database.set_lifecycle(case_id, "approved", tenant_id=principal.tenant_id)
            ticket_status = "Approved"
        deps.database.update_support_ticket_fields(
            case_id, {"status": ticket_status, "escalated": False}, principal.tenant_id
        )
    return {
        "case_id": case_id,
        "status": "queued" if job_id else "approved",
        "audit_id": audit_id,
        "job_id": job_id,
    }


@router.post("/api/cases/{case_id}/sensitive-reveal")
def record_sensitive_reveal(
    case_id: str,
    action: ActionRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    validated_case(case_id, action.customer_id, principal.tenant_id)
    audit_id = deps.database.add_audit(
        case_id=case_id,
        customer_id=action.customer_id,
        event_type="sensitive_data_revealed",
        model=None,
        request={},
        decision={"status": "revealed", "reason": action.note or "Agent requested reveal"},
        guardrails={"sensitive_access": True},
        actor=principal.display_name,
        tenant_id=principal.tenant_id,
    )
    return {"case_id": case_id, "status": "recorded", "audit_id": audit_id}


@router.post("/api/cases/{case_id}/escalate")
def escalate(
    case_id: str,
    action: ActionRequest,
    principal: Principal = Depends(current_principal),
    _: None = Depends(write_rate_limit),
) -> dict:
    latest = validated_case(case_id, action.customer_id, principal.tenant_id)
    audit_id = deps.database.add_audit(
        case_id=case_id,
        customer_id=action.customer_id,
        event_type="human_escalated",
        model=None,
        request={},
        decision={
            "status": "assigned_to_specialist",
            "note": action.note,
            "reviewed_draft": action.response,
        },
        guardrails={"human_override": True},
        actor=principal.display_name,
        tenant_id=principal.tenant_id,
    )
    deps.database.add_feedback(
        case_id=case_id,
        customer_id=action.customer_id,
        actor=principal.display_name,
        predicted=latest["decision"],
        corrected={},
        response_accepted=False,
        response_edited=bool(action.response and action.response != latest["decision"].get("response")),
        reason=action.note or latest["guardrails"].get("reason"),
        tenant_id=principal.tenant_id,
    )
    lifecycle = deps.database.set_lifecycle(
        case_id,
        "review_required",
        tenant_id=principal.tenant_id,
        assigned_to=principal.display_name,
    )
    deps.database.update_support_ticket_fields(
        case_id, {"status": "Assigned", "escalated": True}, principal.tenant_id
    )
    return {
        "case_id": case_id,
        "status": "assigned_to_specialist",
        "audit_id": audit_id,
        "lifecycle": lifecycle,
    }


@router.post("/api/cases/{case_id}/route")
def route_case(
    case_id: str,
    action: RouteRequest,
    principal: Principal = Depends(current_principal),
    _: None = Depends(write_rate_limit),
) -> dict:
    validated_case(case_id, action.customer_id, principal.tenant_id)
    audit_id = deps.database.add_audit(
        case_id=case_id,
        customer_id=action.customer_id,
        event_type="human_routed",
        model=None,
        request={},
        decision={"status": "routed", "route": action.team},
        guardrails={},
        actor=principal.display_name,
        tenant_id=principal.tenant_id,
    )
    deps.database.update_support_ticket_fields(
        case_id,
        {"status": f"Routed to {action.team}", "route": action.team},
        principal.tenant_id,
    )
    return {"case_id": case_id, "status": "routed", "route": action.team, "audit_id": audit_id}


@router.post("/api/cases/{case_id}/verify-transaction")
async def verify_transaction(
    case_id: str,
    value: TransactionVerifyRequest,
    principal: Principal = Depends(current_principal),
    _: None = Depends(write_rate_limit),
) -> dict:
    latest = validated_case(case_id, value.customer_id, principal.tenant_id)
    extracted = latest["decision"].get("entities", {}).get("transactionId")
    if not extracted or extracted.lower() != value.reference.lower():
        raise HTTPException(
            status_code=409,
            detail="Verification is restricted to the transaction reference extracted from this case.",
        )
    if not deps.settings.paystack_secret_key:
        raise HTTPException(
            status_code=503,
            detail="Paystack read-only verification is not configured.",
        )
    try:
        result = await PaystackVerifier(
            deps.settings.paystack_secret_key, deps.settings.paystack_base_url
        ).verify(value.reference)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (httpx.HTTPError, RuntimeError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    audit_id = deps.database.add_audit(
        case_id=case_id,
        customer_id=value.customer_id,
        event_type="transaction_verified",
        model=None,
        request={"provider": "Paystack", "reference": value.reference},
        decision=result,
        guardrails={"read_only": True, "financial_action": False},
        actor=principal.display_name,
        tenant_id=principal.tenant_id,
    )
    deps.database.update_support_ticket_fields(
        case_id,
        {"verifiedTransaction": result},
        principal.tenant_id,
    )
    return {**result, "audit_id": audit_id}


@router.post("/api/cases/{case_id}/manual-assessment")
def manual_assessment(
    case_id: str,
    value: ManualAssessmentRequest,
    principal: Principal = Depends(current_principal),
    _: None = Depends(write_rate_limit),
) -> dict:
    ticket = deps.database.support_ticket(case_id, principal.tenant_id)
    if not ticket or ticket["customerId"] != value.customer_id:
        raise HTTPException(status_code=404, detail="Case not found.")
    flags = review_response(value.response)
    if flags:
        raise HTTPException(
            status_code=422,
            detail="This reply asks for sensitive data or claims an unverified action. Edit it first.",
        )
    decision = {
        "intent": value.intent.value,
        "urgency": value.urgency.value,
        "sentiment": "human reviewed",
        "route": value.route.value,
        "confidence": 1,
        "entities": {},
        "memory_used": False,
        "evidence": ["Manual assessment recorded while AI assistance was unavailable."],
        "response": value.response,
        "policy_citations": [],
    }
    audit_id = deps.database.add_audit(
        case_id=case_id,
        customer_id=value.customer_id,
        event_type="manual_triage",
        model=None,
        request={},
        decision=decision,
        guardrails={"human_owned": True, "auto_approval": False},
        actor=principal.display_name,
        tenant_id=principal.tenant_id,
    )
    deps.database.update_support_ticket_triage(
        case_id,
        {
            **decision,
            "memoryUsed": False,
            "escalated": False,
            "escalationReason": None,
            "status": "Manual draft ready",
            "source": "human",
            "model": None,
            "processingMs": 0,
            "estimatedMinutesSaved": 0,
            "policyCitations": [],
        },
        principal.tenant_id,
    )
    lifecycle = deps.database.set_lifecycle(
        case_id, "review_required", tenant_id=principal.tenant_id
    )
    return {
        "case_id": case_id,
        "audit_id": audit_id,
        "lifecycle": lifecycle,
        "ticket": deps.database.support_ticket(case_id, principal.tenant_id),
    }


@router.post("/api/cases/{case_id}/feedback")
def record_feedback(
    case_id: str,
    feedback: FeedbackRequest,
    principal: Principal = Depends(current_principal),
    _: None = Depends(write_rate_limit),
) -> dict:
    latest = validated_case(case_id, feedback.customer_id, principal.tenant_id)
    corrected = {
        key: value.value
        for key, value in {
            "intent": feedback.corrected_intent,
            "urgency": feedback.corrected_urgency,
            "route": feedback.corrected_route,
        }.items()
        if value is not None
    }
    if not corrected and feedback.response_accepted is None and not feedback.reason:
        raise HTTPException(status_code=422, detail="Record at least one correction or review outcome.")
    feedback_id = deps.database.add_feedback(
        case_id=case_id,
        customer_id=feedback.customer_id,
        actor=principal.display_name,
        predicted=latest["decision"],
        corrected=corrected,
        response_accepted=feedback.response_accepted,
        response_edited=False,
        reason=feedback.reason,
        tenant_id=principal.tenant_id,
    )
    if corrected:
        # The displayed values change; the model's own prediction is kept in
        # modelIntent/modelUrgency/modelRoute for accuracy measurement.
        deps.database.update_support_ticket_fields(case_id, corrected, principal.tenant_id)
    audit_id = deps.database.add_audit(
        case_id=case_id,
        customer_id=feedback.customer_id,
        event_type="human_feedback",
        model=None,
        request={},
        decision={"feedback_id": feedback_id, "corrected": corrected},
        guardrails={},
        actor=principal.display_name,
        tenant_id=principal.tenant_id,
    )
    return {"case_id": case_id, "feedback_id": feedback_id, "audit_id": audit_id}


@router.post("/api/cases/{case_id}/resolve")
def resolve_case(
    case_id: str,
    action: ResolveRequest,
    principal: Principal = Depends(current_principal),
    _: None = Depends(write_rate_limit),
) -> dict:
    validated_case(case_id, action.customer_id, principal.tenant_id)
    current = deps.database.lifecycle(case_id, principal.tenant_id) or {}
    if current.get("state") == "resolved":
        raise HTTPException(status_code=409, detail="This case is already resolved.")
    lifecycle = deps.database.set_lifecycle(case_id, "resolved", tenant_id=principal.tenant_id)
    deps.database.update_support_ticket_fields(
        case_id, {"status": "Resolved"}, principal.tenant_id
    )
    audit_id = deps.database.add_audit(
        case_id=case_id,
        customer_id=action.customer_id,
        event_type="case_resolved",
        model=None,
        request={},
        decision={"status": "resolved", "resolution": action.resolution},
        guardrails={},
        actor=principal.display_name,
        tenant_id=principal.tenant_id,
    )
    return {"case_id": case_id, "lifecycle": lifecycle, "audit_id": audit_id}
