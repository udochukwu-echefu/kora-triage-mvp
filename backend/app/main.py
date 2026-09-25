from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from groq import APIConnectionError, APIStatusError, RateLimitError
from pydantic import ValidationError

from .api import deps
from .api.deps import (
    ai_rate_limit,
    consume_ai_budget,
    current_principal,
    manager_principal,
    require_ai_budget,
    validated_case,
    write_rate_limit,
)
from .api.webhook_auth import verify_postmark_webhook, verify_webhook_token, verify_whatsapp_signature
from .auth import ROLE_LEVEL, Principal, require_role
from .automation import recorded_automation_decision
from .config import DEFAULT_AUTOMATION
from .demo_seed import seed_demo_data
from .evaluation import evaluation_summary, regression_gate
from .evaluation_dataset import dataset_summary
from .guardrails import review_response
from .launch_features import PaystackVerifier, proof_report
from .schemas import (
    ActionRequest,
    AutomationSettings,
    CaseAssignmentRequest,
    CaseNoteRequest,
    CaseTriageRequest,
    CustomerContext,
    FeedbackRequest,
    InboundMessageRequest,
    KnowledgePolicyRequest,
    ManualAssessmentRequest,
    PolicyStateRequest,
    ProofCase,
    ProofRunRequest,
    ResolveRequest,
    RouteRequest,
    TeamAvailabilityRequest,
    TransactionVerifyRequest,
    TriageRequest,
    TriageResult,
)
from .workflow import WorkflowWorker, send_job_payload

logger = logging.getLogger("kora.api")

frontend_dist = Path(__file__).resolve().parents[2] / "dist"

# A case in one of these states has already been answered or closed; a new
# customer message moves it back to "replied"/"reopened" for fresh review.
ALREADY_HANDLED_STATES = {"approved", "queued", "sent", "delivered", "resolved"}
MAX_MESSAGE_LENGTH = 8000
MAX_NAME_LENGTH = 120
MAX_SUBJECT_LENGTH = 500


@asynccontextmanager
async def lifespan(_: FastAPI):
    deps.database.initialize()
    if deps.settings.seed_demo_data:
        seed_demo_data(deps.database, deps.settings.default_tenant_id)
    worker = WorkflowWorker(
        deps.database,
        deps.get_service,
        deps.gateway,
        poll_seconds=deps.settings.worker_poll_seconds,
        lease_seconds=deps.settings.job_lease_seconds,
    )
    deps.worker = worker
    if deps.settings.worker_enabled:
        deps.worker_task = asyncio.create_task(worker.run())
    try:
        yield
    finally:
        worker.stop()
        for task in [deps.worker_task, *deps.proof_tasks]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


app = FastAPI(
    title="Kora Triage API",
    version="2.1.0",
    description="LLM-assisted customer-support triage with deterministic guardrails.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(deps.settings.allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "Authorization", "X-Kora-Webhook-Token", "X-Hub-Signature-256"],
)


@app.exception_handler(ValidationError)
async def validation_error_handler(_: Request, error: ValidationError) -> JSONResponse:
    """Models built inside handlers (e.g. from webhook payloads) fail as 422, not 500."""
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"loc": list(item.get("loc", ())), "msg": item.get("msg")}
                for item in error.errors()
            ]
        },
    )


def _clip(value: object, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


_QUOTE_START = re.compile(
    r"^(?:On .{3,200}wrote:\s*$|-{2,}\s*Original Message\s*-{2,}|_{5,}\s*$|From:\s.+$|Sent from my \w+)",
    re.IGNORECASE | re.MULTILINE,
)


def strip_quoted_reply(text: str) -> str:
    """Drop quoted history from an email reply, keeping only the new text."""
    match = _QUOTE_START.search(text)
    new_text = text[: match.start()] if match else text
    lines = [line for line in new_text.splitlines() if not line.lstrip().startswith(">")]
    stripped = "\n".join(lines).strip()
    return stripped or text.strip()


@app.get("/api/health")
def health() -> dict:
    """Public liveness check. Operational detail lives behind authentication."""
    return {
        "status": "ready" if deps.settings.groq_api_key else "degraded",
        "operational_mode": "ai_assisted" if deps.settings.groq_api_key else "manual",
        "configured": bool(deps.settings.groq_api_key),
        "auth_mode": deps.settings.auth_mode,
        "alert": (
            "AI unavailable. Inbound cases remain available for manual handling."
            if not deps.settings.groq_api_key
            else None
        ),
    }


@app.get("/api/auth/me")
def auth_me(principal: Principal = Depends(current_principal)) -> dict:
    return {
        "tenant_id": principal.tenant_id,
        "user_id": principal.user_id,
        "display_name": principal.display_name,
        "role": principal.role,
        "auth_mode": deps.settings.auth_mode,
    }


@app.get("/api/integrations")
def integrations(principal: Principal = Depends(current_principal)) -> dict:
    return {
        **deps.gateway.status(),
        "model": deps.settings.groq_model,
        "worker_enabled": deps.settings.worker_enabled,
        "jobs": deps.database.job_counts(principal.tenant_id),
        "webhook_protected": bool(deps.settings.webhook_token),
        "limits": {
            "proof_cases": deps.settings.demo_proof_case_limit if deps.settings.auth_mode == "demo" else 100,
            "proof_concurrency": deps.settings.proof_concurrency,
        },
        "paystack": {
            "provider": "Paystack",
            "configured": bool(deps.settings.paystack_secret_key),
            "mode": "read_only",
        },
    }


@app.post("/api/triage", response_model=TriageResult)
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


@app.get("/api/audit")
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


@app.get("/api/cases")
def cases(principal: Principal = Depends(current_principal)) -> dict:
    return {"items": deps.database.support_tickets(principal.tenant_id)}


@app.get("/api/policies")
def policies(principal: Principal = Depends(current_principal)) -> dict:
    return {"items": deps.database.policies(principal.tenant_id)}


@app.post("/api/policies", status_code=201)
def create_policy(
    value: KnowledgePolicyRequest,
    principal: Principal = Depends(manager_principal),
    _: None = Depends(write_rate_limit),
) -> dict:
    policy = deps.database.add_policy(
        tenant_id=principal.tenant_id,
        **value.model_dump(),
    )
    deps.database.add_audit(
        case_id="POLICY",
        customer_id="workspace",
        event_type="policy_created",
        model=None,
        request={},
        decision={
            "policy_id": policy["id"],
            "title": policy["title"],
            "version": policy["version"],
        },
        guardrails={},
        actor=principal.display_name,
        tenant_id=principal.tenant_id,
    )
    return policy


@app.put("/api/policies/{policy_id}/state")
def update_policy_state(
    policy_id: int,
    value: PolicyStateRequest,
    principal: Principal = Depends(manager_principal),
    _: None = Depends(write_rate_limit),
) -> dict:
    policy = deps.database.set_policy_active(
        policy_id, value.active, principal.tenant_id
    )
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")
    deps.database.add_audit(
        case_id="POLICY",
        customer_id="workspace",
        event_type="policy_activated" if value.active else "policy_paused",
        model=None,
        request={},
        decision={"policy_id": policy_id, "title": policy["title"], "active": value.active},
        guardrails={},
        actor=principal.display_name,
        tenant_id=principal.tenant_id,
    )
    return policy


@app.get("/api/proof-runs")
def proof_runs(principal: Principal = Depends(manager_principal)) -> dict:
    return {"items": deps.database.proof_runs(principal.tenant_id)}


@app.get("/api/proof-runs/{run_id}")
def proof_run_detail(run_id: int, principal: Principal = Depends(manager_principal)) -> dict:
    run = deps.database.proof_run(run_id, principal.tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    return run


def _proof_progress(total: int, rows: list[dict]) -> dict:
    return {
        "total": total,
        "completed": sum(1 for row in rows if not row.get("error")),
        "failed": sum(1 for row in rows if row.get("error")),
        "processed": len(rows),
    }


async def execute_proof_run(
    run_id: int, cases: list[ProofCase], principal: Principal
) -> dict:
    """Run historical cases through the live decision path without delivery.

    Each run gets its own proof tenant and customer IDs, so memory from one run
    (or one case) can never leak into another.
    """
    proof_tenant = f"{principal.tenant_id}:proof:{run_id}"
    automation = deps.database.get_setting("automation", DEFAULT_AUTOMATION, principal.tenant_id)
    rows: list[dict | None] = [None] * len(cases)
    semaphore = asyncio.Semaphore(max(1, deps.settings.proof_concurrency))
    try:
        service = deps.get_service()
    except HTTPException as error:
        report = {**_proof_progress(len(cases), []), "error": error.detail}
        return deps.database.update_proof_run(run_id, principal.tenant_id, status="failed", report=report)

    async def run_case(index: int, case: ProofCase) -> None:
        async with semaphore:
            proof_case_id = f"PROOF-{run_id}-{index + 1}"
            try:
                if not consume_ai_budget():
                    raise RuntimeError("The public demo has reached today's AI limit.")
                result = await service.triage(
                    TriageRequest(
                        case_id=proof_case_id,
                        channel=case.channel,
                        message=case.message,
                        subject=case.subject,
                        customer={
                            "customer_id": f"proof-{run_id}-{index + 1}",
                            "name": case.customer_name or "Historical customer",
                            "previous_context": "",
                            "notes": ["Historical proof-mode case. Never deliver externally."],
                        },
                    ),
                    tenant_id=proof_tenant,
                    policy_tenant_id=principal.tenant_id,
                    simulate_automation=True,
                )
                expected = (
                    {key: value for key, value in case.expected.model_dump(mode="json").items()}
                    if case.expected
                    else None
                )
                rows[index] = {
                    "case_id": case.case_id,
                    "language": case.language,
                    "message": case.message[:300],
                    "expected": expected,
                    "predicted": {
                        "intent": result.intent.value,
                        "urgency": result.urgency.value,
                        "route": result.route.value,
                        "confidence": result.confidence,
                        "escalated": result.escalated,
                        "automation_eligible": result.automation.eligible,
                        "automation_reason": result.automation.reason,
                    },
                }
            except Exception as error:  # one bad case must not stop the run
                logger.warning("Proof case %s failed: %s", case.case_id, error)
                rows[index] = {
                    "case_id": case.case_id,
                    "language": case.language,
                    "message": case.message[:300],
                    "error": str(error)[:300],
                }
            finished = [row for row in rows if row is not None]
            deps.database.update_proof_run(
                run_id,
                principal.tenant_id,
                status="running",
                report=_proof_progress(len(cases), finished),
            )

    await asyncio.gather(*(run_case(index, case) for index, case in enumerate(cases)))
    report = proof_report([row for row in rows if row], auto_threshold=automation["auto_approve_threshold"])
    report["simulated_thresholds"] = {
        "auto_approve_threshold": automation["auto_approve_threshold"],
        "mandatory_review_threshold": automation["mandatory_review_threshold"],
    }
    run = deps.database.update_proof_run(
        run_id,
        principal.tenant_id,
        status="complete" if not report["failed"] else "complete_with_errors",
        report=report,
    )
    deps.database.add_audit(
        case_id=f"PROOF-{run_id}",
        customer_id="workspace",
        event_type="proof_run_completed",
        model=deps.settings.groq_model,
        request={"cases": len(cases)},
        decision={
            "readiness_score": report["readiness_score"],
            "recommendation": report["recommendation"],
        },
        guardrails={"silent_mode": True, "external_delivery": False},
        actor=principal.display_name,
        tenant_id=principal.tenant_id,
    )
    return run


@app.post("/api/proof-runs", status_code=202)
async def run_proof(
    value: ProofRunRequest,
    principal: Principal = Depends(manager_principal),
    _: None = Depends(ai_rate_limit),
) -> dict:
    deps.get_service()
    if deps.settings.auth_mode == "demo" and len(value.cases) > deps.settings.demo_proof_case_limit:
        raise HTTPException(
            status_code=422,
            detail=f"The public demo accepts up to {deps.settings.demo_proof_case_limit} cases per evaluation.",
        )
    if any(run["status"] == "running" for run in deps.database.proof_runs(principal.tenant_id, limit=5)):
        raise HTTPException(status_code=409, detail="An evaluation is already running.")
    run = deps.database.add_proof_run(
        tenant_id=principal.tenant_id,
        name=value.name,
        status="running",
        report=_proof_progress(len(value.cases), []),
    )
    # Long runs continue in the background; the client polls for progress.
    task = asyncio.create_task(execute_proof_run(run["id"], value.cases, principal))
    deps.proof_tasks.add(task)
    task.add_done_callback(deps.proof_tasks.discard)
    return run


@app.get("/api/settings/automation", response_model=AutomationSettings)
def automation_settings(
    principal: Principal = Depends(current_principal),
) -> AutomationSettings:
    value = deps.database.get_setting("automation", DEFAULT_AUTOMATION, principal.tenant_id)
    # Report what is actually in force without rewriting stored settings.
    if value.get("enabled") and (
        not deps.database.policies(principal.tenant_id, active_only=True) or not deps.settings.delivery_ready
    ):
        value = {**value, "enabled": False}
    return AutomationSettings.model_validate(value)


@app.put("/api/settings/automation", response_model=AutomationSettings)
def update_automation_settings(
    value: AutomationSettings,
    principal: Principal = Depends(manager_principal),
    _: None = Depends(write_rate_limit),
) -> AutomationSettings:
    if value.mandatory_review_threshold >= value.auto_approve_threshold:
        raise HTTPException(
            status_code=422,
            detail="Mandatory review threshold must be lower than auto-approve threshold.",
        )
    if value.enabled and not deps.database.policies(principal.tenant_id, active_only=True):
        raise HTTPException(
            status_code=422,
            detail="Add and activate an approved policy before enabling auto-approval.",
        )
    if value.enabled and not deps.settings.delivery_ready:
        raise HTTPException(
            status_code=422,
            detail="Connect a live customer delivery channel before enabling auto-approval.",
        )
    deps.database.set_setting("automation", value.model_dump(), principal.tenant_id)
    deps.database.add_audit(
        case_id="SETTINGS",
        customer_id="workspace",
        event_type="automation_settings_changed",
        model=None,
        request={},
        decision=value.model_dump(),
        guardrails={},
        actor=principal.display_name,
        tenant_id=principal.tenant_id,
    )
    return value


@app.get("/api/customers/{customer_id}/memory")
def customer_memory(
    customer_id: str, principal: Principal = Depends(current_principal)
) -> dict:
    return {
        "customer_id": customer_id,
        "items": deps.database.memories_for(customer_id, tenant_id=principal.tenant_id),
    }


def _can_override_guardrail(principal: Principal, lifecycle: dict) -> bool:
    return (
        ROLE_LEVEL.get(principal.role, 0) >= ROLE_LEVEL["support_manager"]
        or lifecycle.get("assigned_to") == principal.display_name
    )


@app.post("/api/cases/{case_id}/approve")
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


@app.post("/api/cases/{case_id}/sensitive-reveal")
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


@app.post("/api/cases/{case_id}/escalate")
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


@app.post("/api/cases/{case_id}/route")
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


@app.put("/api/cases/{case_id}/assignment")
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


@app.get("/api/cases/{case_id}/notes")
def case_notes(
    case_id: str, principal: Principal = Depends(current_principal)
) -> dict:
    if not deps.database.support_ticket(case_id, principal.tenant_id):
        raise HTTPException(status_code=404, detail="Case not found.")
    return {"items": deps.database.case_notes(case_id, principal.tenant_id)}


@app.post("/api/cases/{case_id}/notes", status_code=201)
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


@app.post("/api/cases/{case_id}/verify-transaction")
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


@app.post("/api/cases/{case_id}/manual-assessment")
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


@app.get("/api/cases/{case_id}/conversation")
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


@app.post("/api/cases/{case_id}/feedback")
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


@app.post("/api/cases/{case_id}/resolve")
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


@app.get("/api/team")
def team(principal: Principal = Depends(current_principal)) -> dict:
    return {"items": deps.database.team_members(principal.tenant_id)}


@app.put("/api/team/{member_id}/availability")
def set_team_availability(
    member_id: int,
    value: TeamAvailabilityRequest,
    principal: Principal = Depends(current_principal),
    _: None = Depends(write_rate_limit),
) -> dict:
    members = {member["id"]: member for member in deps.database.team_members(principal.tenant_id)}
    member = members.get(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Team member not found.")
    if member["name"] != principal.display_name:
        require_role(principal, "support_manager")
    return deps.database.set_team_availability(member_id, value.availability, principal.tenant_id)


@app.get("/api/evaluations/summary")
def evaluations(principal: Principal = Depends(current_principal)) -> dict:
    return evaluation_summary(deps.database, principal.tenant_id)


@app.get("/api/evaluations/dataset")
def evaluation_dataset(
    _: Principal = Depends(manager_principal),
) -> dict:
    return dataset_summary()


@app.get("/api/evaluations/gate")
def evaluation_gate(
    principal: Principal = Depends(manager_principal),
) -> dict:
    return regression_gate(deps.database, principal.tenant_id)


@app.get("/api/jobs")
def jobs(
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(manager_principal),
) -> dict:
    return {
        "counts": deps.database.job_counts(principal.tenant_id),
        "items": deps.database.jobs(principal.tenant_id, limit),
    }


@app.post("/api/jobs/run-once")
async def run_job_once(principal: Principal = Depends(manager_principal)) -> dict:
    if not deps.worker:
        raise HTTPException(status_code=503, detail="Workflow worker is not initialized.")
    return {"processed": await deps.worker.process_one(tenant_id=principal.tenant_id)}


@app.post("/api/webhooks/inbound", status_code=202)
def generic_inbound(
    message: InboundMessageRequest,
    x_kora_webhook_token: str | None = Header(default=None, alias="X-Kora-Webhook-Token"),
) -> dict:
    verify_webhook_token(x_kora_webhook_token)
    return deps.workflow.ingest(
        message, provider="kora_webhook", tenant_id=deps.settings.default_tenant_id
    )


def _postmark_header(payload: dict, name: str) -> str | None:
    for item in payload.get("Headers") or []:
        if str(item.get("Name", "")).lower() == name.lower():
            return item.get("Value")
    return None


def _email_tenant(payload: dict) -> str:
    candidates = [payload.get("OriginalRecipient"), payload.get("To")]
    candidates += [item.get("Email") for item in payload.get("ToFull") or [] if isinstance(item, dict)]
    for candidate in candidates:
        for address in re.findall(r"[\w.+-]+@[\w.-]+", str(candidate or "")):
            tenant = deps.settings.email_tenants.get(address.lower())
            if tenant:
                return tenant
    return deps.settings.default_tenant_id


@app.post("/api/webhooks/postmark/inbound", status_code=202)
def postmark_inbound(
    payload: dict,
    authorization: str | None = Header(default=None),
    x_kora_webhook_token: str | None = Header(default=None, alias="X-Kora-Webhook-Token"),
) -> dict:
    verify_postmark_webhook(authorization, x_kora_webhook_token)
    message_id = str(payload.get("MessageID") or "").strip()
    sender = str(payload.get("From") or (payload.get("FromFull") or {}).get("Email") or "").strip()
    if not message_id or not sender:
        raise HTTPException(status_code=422, detail="Postmark payload is missing MessageID or From.")
    # Postmark's StrippedTextReply already removes quoted history; fall back to
    # our own stripping so long reply chains never exceed the message limit.
    body = str(payload.get("StrippedTextReply") or "").strip() or strip_quoted_reply(
        str(payload.get("TextBody") or "")
    )
    if not body:
        # Acknowledge so Postmark does not retry an email that has no text.
        return {"accepted": False, "reason": "The email has no text body.", "message_id": message_id}
    references = str(_postmark_header(payload, "References") or "").split()
    in_reply_to = _postmark_header(payload, "In-Reply-To")
    if in_reply_to:
        references.append(in_reply_to)
    root = references[0].strip("<>") if references else None
    name = _clip(payload.get("FromName") or sender.split("@", 1)[0], MAX_NAME_LENGTH) or "Customer"
    return deps.workflow.ingest(
        InboundMessageRequest(
            event_id=f"postmark-inbound:{message_id}"[:200],
            provider_message_id=message_id[:200],
            channel="email",
            sender=sender[:320],
            customer_name=name,
            message=_clip(body, MAX_MESSAGE_LENGTH),
            subject=_clip(payload.get("Subject"), MAX_SUBJECT_LENGTH) or None,
            external_thread_id=root[:300] if root else None,
            rfc_message_id=(_postmark_header(payload, "Message-ID") or "")[:998] or None,
            references=[reference[:998] for reference in references[-50:]],
        ),
        provider="postmark",
        tenant_id=_email_tenant(payload),
    )


POSTMARK_RECORD_STATUS = {
    "delivery": "delivered",
    "bounce": "failed",
    "spamcomplaint": "failed",
    "open": "read",
}


@app.post("/api/webhooks/postmark/delivery")
def postmark_delivery(
    payload: dict,
    authorization: str | None = Header(default=None),
    x_kora_webhook_token: str | None = Header(default=None, alias="X-Kora-Webhook-Token"),
) -> dict:
    verify_postmark_webhook(authorization, x_kora_webhook_token)
    message_id = str(payload.get("MessageID") or "")
    record_type = str(payload.get("RecordType") or "").lower()
    status_value = POSTMARK_RECORD_STATUS.get(record_type)
    if not message_id or not status_value:
        return {"ignored": True, "record_type": record_type or None}
    event_id = (
        f"postmark-{record_type}:{message_id}:"
        f"{payload.get('DeliveredAt') or payload.get('BouncedAt') or payload.get('ReceivedAt') or ''}"
    )
    return _record_delivery_update(
        event_id=event_id,
        provider="postmark",
        provider_message_id=message_id,
        status_value=status_value,
        payload=payload,
    )


def _record_delivery_update(
    *,
    event_id: str,
    provider: str,
    provider_message_id: str,
    status_value: str,
    payload: dict,
) -> dict:
    # The deduplication marker must commit with the message, case, and audit.
    with deps.database.transaction():
        return _apply_delivery_update(
            event_id=event_id,
            provider=provider,
            provider_message_id=provider_message_id,
            status_value=status_value,
            payload=payload,
        )


def _apply_delivery_update(
    *,
    event_id: str,
    provider: str,
    provider_message_id: str,
    status_value: str,
    payload: dict,
) -> dict:
    if not deps.database.record_webhook(
        event_id=event_id,
        tenant_id=deps.settings.default_tenant_id,
        provider=provider,
        event_type=f"message_{status_value}",
        payload=payload,
    ):
        return {"duplicate": True}
    # Receipts are routed by provider message ID, which carries the tenant.
    updated = deps.database.update_message_delivery(
        provider_message_id, status_value, None, provider=provider
    )
    case_id, tenant_id = updated if updated else (None, None)
    if case_id:
        lifecycle_state = (
            "delivered"
            if status_value in {"delivered", "read"}
            else "failed" if status_value == "failed" else "sent"
        )
        lifecycle = deps.database.lifecycle(case_id, tenant_id) or {}
        conversation = deps.database.conversation(case_id, tenant_id)
        latest_message = conversation[-1] if conversation else {}
        # A receipt updates its message, but cannot undo a human decision or a
        # newer reply/send in the same conversation.
        updates_case = (
            lifecycle.get("state") not in {"resolved", "reopened", "replied", "review_required"}
            and latest_message.get("direction") == "outbound"
            and latest_message.get("provider") == provider
            and latest_message.get("provider_message_id") == provider_message_id
        )
        if updates_case:
            deps.database.set_lifecycle(case_id, lifecycle_state, tenant_id=tenant_id)
        ticket = deps.database.support_ticket(case_id, tenant_id)
        if ticket:
            if updates_case:
                deps.database.update_support_ticket_fields(
                    case_id,
                    {"status": lifecycle_state.capitalize()},
                    tenant_id,
                )
            deps.database.add_audit(
                case_id=case_id,
                customer_id=ticket["customerId"],
                event_type="delivery_updated",
                model=None,
                request={"provider": provider},
                decision={"status": status_value},
                guardrails={},
                actor=provider,
                tenant_id=tenant_id,
            )
    return {"duplicate": False, "case_id": case_id, "status": status_value}


@app.get("/api/webhooks/whatsapp")
def verify_whatsapp(
    mode: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    if (
        mode == "subscribe"
        and deps.settings.whatsapp_verify_token
        and token is not None
        and hmac.compare_digest(token, deps.settings.whatsapp_verify_token)
    ):
        return PlainTextResponse(challenge or "0")
    raise HTTPException(status_code=403, detail="WhatsApp webhook verification failed.")


@app.post("/api/webhooks/whatsapp", status_code=202)
async def whatsapp_inbound(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> dict:
    raw = await request.body()
    verify_whatsapp_signature(raw, x_hub_signature_256)
    try:
        payload = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="WhatsApp payload is not valid JSON.") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="WhatsApp payload must be a JSON object.")
    results: list[dict] = []
    delivery_results: list[dict] = []
    errors: list[dict] = []
    # Each message is processed on its own: one malformed item must not make
    # Meta retry (and re-deliver) the whole batch.
    for entry in payload.get("entry") or []:
        for change in (entry or {}).get("changes") or []:
            value = (change or {}).get("value") or {}
            phone_number_id = str((value.get("metadata") or {}).get("phone_number_id") or "")
            tenant_id = deps.settings.whatsapp_tenants.get(phone_number_id.lower(), deps.settings.default_tenant_id)
            contacts = value.get("contacts") or []
            name = (
                (contacts[0].get("profile") or {}).get("name") if contacts and isinstance(contacts[0], dict) else None
            ) or "WhatsApp customer"
            for status in value.get("statuses") or []:
                provider_message_id = str(status.get("id") or "")
                status_value = str(status.get("status") or "sent").lower()
                if not provider_message_id or status_value not in {"sent", "delivered", "read", "failed"}:
                    continue
                try:
                    delivery_results.append(
                        _record_delivery_update(
                            event_id=(
                                f"whatsapp-status:{provider_message_id}:"
                                f"{status_value}:{status.get('timestamp') or ''}"
                            ),
                            provider="whatsapp_cloud",
                            provider_message_id=provider_message_id,
                            status_value=status_value,
                            payload=status,
                        )
                    )
                except Exception as error:
                    logger.exception("WhatsApp status %s failed", provider_message_id)
                    errors.append({"id": provider_message_id, "error": type(error).__name__})
            for message in value.get("messages") or []:
                provider_message_id = str(message.get("id") or "")
                sender = str(message.get("from") or "")
                body = str((message.get("text") or {}).get("body") or "").strip()
                if message.get("type") != "text" or not body or not sender or not provider_message_id:
                    continue
                try:
                    results.append(
                        deps.workflow.ingest(
                            InboundMessageRequest(
                                event_id=f"whatsapp-inbound:{provider_message_id}"[:200],
                                provider_message_id=provider_message_id[:200],
                                channel="whatsapp",
                                sender=sender[:320],
                                customer_name=_clip(name, MAX_NAME_LENGTH) or "WhatsApp customer",
                                message=_clip(body, MAX_MESSAGE_LENGTH),
                                external_thread_id=f"wa:{sender}"[:300],
                            ),
                            provider="whatsapp_cloud",
                            tenant_id=tenant_id,
                        )
                    )
                except Exception as error:
                    logger.exception("WhatsApp message %s failed", provider_message_id)
                    errors.append({"id": provider_message_id, "error": type(error).__name__})
    return {
        "accepted": len(results),
        "delivery_updates": len(delivery_results),
        "items": results,
        "deliveries": delivery_results,
        "errors": errors,
    }


# Railway serves the compiled Vite frontend and API from the same origin.
# Explicit SPA entry routes keep direct /app visits and browser refreshes working.
if frontend_dist.is_dir():
    @app.get("/app", include_in_schema=False)
    @app.get("/app/", include_in_schema=False)
    async def workspace_entry() -> FileResponse:
        return FileResponse(frontend_dist / "index.html")


# API and SPA entry routes are registered first so the frontend mount cannot shadow them.
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
