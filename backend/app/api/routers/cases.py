"""Case inbox, triage, conversation history, internal notes and assignment."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from groq import APIConnectionError, APIStatusError, RateLimitError

from ...auth import Principal
from ...schemas import (
    CaseAssignmentRequest,
    CaseNoteRequest,
    CaseTriageRequest,
    CustomerContext,
    TriageRequest,
    TriageResult,
)
from .. import deps
from ..deps import (
    ai_rate_limit,
    current_principal,
    require_ai_budget,
    write_rate_limit,
)

router = APIRouter()


@router.post("/api/triage", response_model=TriageResult)
async def triage(
    request: CaseTriageRequest,
    principal: Principal = Depends(current_principal),
    _: None = Depends(ai_rate_limit),
) -> TriageResult:
    ticket = deps.database.support_ticket(request.case_id, principal.tenant_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Case not found.")
    if ticket["customerId"] != request.customer_id:
        raise HTTPException(
            status_code=409,
            detail="Customer does not match the requested case.",
        )
    service = deps.get_service()
    require_ai_budget()
    # Content always comes from the stored case, never from the browser.
    canonical_request = TriageRequest(
        case_id=ticket["id"],
        channel=ticket["channel"],
        message=ticket["message"],
        subject=ticket.get("subject"),
        customer=CustomerContext(
            customer_id=ticket["customerId"],
            name=ticket["customer"]["name"],
            previous_context=ticket["customer"].get("previousContext", ""),
            notes=ticket["customer"].get("notes", [])[:20],
        ),
    )
    try:
        return await service.triage(canonical_request, tenant_id=principal.tenant_id)
    except RateLimitError as error:
        raise HTTPException(status_code=429, detail="Groq rate limit reached. Try again shortly.") from error
    except APIConnectionError as error:
        raise HTTPException(status_code=502, detail="Could not reach Groq.") from error
    except APIStatusError as error:
        raise HTTPException(status_code=502, detail=f"Groq rejected the request: {error.status_code}") from error
    except ValueError as error:
        raise HTTPException(status_code=502, detail="Groq returned an invalid structured response.") from error


@router.get("/api/audit")
def audit(
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(current_principal),
) -> dict:
    items = deps.database.audits(limit, principal.tenant_id)
    value_labels = {
        "assigned_to_specialist": "Assigned to specialist",
        "routed": "Routed by agent",
        "auto_approved": "Auto-approved",
        "approved": "Approved by agent",
    }
    for item in items:
        if item["event_type"] == "triage":
            item["actor"] = "Kora automation"
        status_value = item["decision"].get("status")
        if status_value in value_labels:
            item["decision"]["status"] = value_labels[status_value]
    return {"items": items}


@router.get("/api/cases")
def cases(principal: Principal = Depends(current_principal)) -> dict:
    return {"items": deps.database.support_tickets(principal.tenant_id)}


@router.get("/api/customers/{customer_id}/memory")
def customer_memory(
    customer_id: str, principal: Principal = Depends(current_principal)
) -> dict:
    return {
        "customer_id": customer_id,
        "items": deps.database.memories_for(customer_id, tenant_id=principal.tenant_id),
    }


@router.put("/api/cases/{case_id}/assignment")
def assign_case(
    case_id: str,
    action: CaseAssignmentRequest,
    principal: Principal = Depends(current_principal),
    _: None = Depends(write_rate_limit),
) -> dict:
    ticket = deps.database.support_ticket(case_id, principal.tenant_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Case not found.")
    assignee = action.assignee
    claiming_self = assignee == "me"
    if claiming_self:
        assignee = principal.display_name
    try:
        lifecycle = deps.database.claim_case(
            case_id,
            tenant_id=principal.tenant_id,
            assignee=assignee,
            expected_assignee=(
                "__unassigned__"
                if claiming_self and action.expected_assignee is None
                else action.expected_assignee
            ),
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(
            status_code=409,
            detail=f"Case ownership changed. It is currently assigned to {error}.",
        ) from error
    deps.database.update_support_ticket_fields(
        case_id,
        {
            "assignee": assignee,
            "status": f"Assigned to {assignee}" if assignee else "Unassigned",
        },
        principal.tenant_id,
    )
    deps.database.add_audit(
        case_id=case_id,
        customer_id=ticket["customerId"],
        event_type="case_assignment_changed",
        model=None,
        request={"expected_assignee": action.expected_assignee},
        decision={"assignee": assignee},
        guardrails={"collision_checked": action.expected_assignee is not None},
        actor=principal.display_name,
        tenant_id=principal.tenant_id,
    )
    return {"case_id": case_id, "assignee": assignee, "lifecycle": lifecycle}


@router.get("/api/cases/{case_id}/notes")
def case_notes(
    case_id: str, principal: Principal = Depends(current_principal)
) -> dict:
    if not deps.database.support_ticket(case_id, principal.tenant_id):
        raise HTTPException(status_code=404, detail="Case not found.")
    return {"items": deps.database.case_notes(case_id, principal.tenant_id)}


@router.post("/api/cases/{case_id}/notes", status_code=201)
def add_case_note(
    case_id: str,
    value: CaseNoteRequest,
    principal: Principal = Depends(current_principal),
    _: None = Depends(write_rate_limit),
) -> dict:
    ticket = deps.database.support_ticket(case_id, principal.tenant_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Case not found.")
    note = deps.database.add_case_note(
        case_id=case_id,
        tenant_id=principal.tenant_id,
        actor=principal.display_name,
        body=value.body,
        mentions=value.mentions,
    )
    deps.database.add_audit(
        case_id=case_id,
        customer_id=ticket["customerId"],
        event_type="internal_note_added",
        model=None,
        request={},
        decision={"note_id": note["id"], "mentions": note["mentions"]},
        guardrails={"customer_visible": False},
        actor=principal.display_name,
        tenant_id=principal.tenant_id,
    )
    return note


@router.get("/api/cases/{case_id}/conversation")
def case_conversation(
    case_id: str, principal: Principal = Depends(current_principal)
) -> dict:
    if not deps.database.support_ticket(case_id, principal.tenant_id):
        raise HTTPException(status_code=404, detail="Case not found.")
    return {
        "case_id": case_id,
        "lifecycle": deps.database.lifecycle(case_id, principal.tenant_id),
        "messages": deps.database.conversation(case_id, principal.tenant_id),
        "notes": deps.database.case_notes(case_id, principal.tenant_id),
    }
