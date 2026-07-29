from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from groq import APIConnectionError, APIStatusError, RateLimitError

from .auth import Principal, require_role, resolve_principal
from .channels import ChannelGateway
from .config import settings
from .database import Database
from .demo_seed import seed_demo_data
from .evaluation import evaluation_summary, regression_gate
from .evaluation_dataset import dataset_summary
from .groq_triage import GroqTriageModel
from .launch_features import PaystackVerifier, proof_report
from .schemas import (
    ActionRequest,
    AutomationSettings,
    CaseAssignmentRequest,
    CaseNoteRequest,
    FeedbackRequest,
    InboundMessageRequest,
    KnowledgePolicyRequest,
    ManualAssessmentRequest,
    PolicyStateRequest,
    ProofRunRequest,
    ResolveRequest,
    RouteRequest,
    TransactionVerifyRequest,
    TriageRequest,
    TriageResult,
)
from .service import TriageService
from .workflow import SupportWorkflow, WorkflowWorker


database = Database(settings.database_path)
frontend_dist = Path(__file__).resolve().parents[2] / "dist"
gateway = ChannelGateway(settings)
workflow = SupportWorkflow(database)
worker: WorkflowWorker | None = None
worker_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global worker, worker_task
    database.initialize()
    seed_demo_data(database)
    worker = WorkflowWorker(
        database,
        get_service,
        gateway,
        poll_seconds=settings.worker_poll_seconds,
    )
    if settings.worker_enabled:
        worker_task = asyncio.create_task(worker.run())
    try:
        yield
    finally:
        worker.stop()
        if worker_task:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="Kora Triage API",
    version="1.0.0",
    description="LLM-assisted customer-support triage with deterministic guardrails.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "Authorization", "X-Kora-Webhook-Token", "X-Hub-Signature-256"],
)


def get_service() -> TriageService:
    if not settings.groq_api_key:
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY is not configured. Add it to backend/.env or the environment.",
        )
    return TriageService(
        database,
        GroqTriageModel(settings.groq_api_key, settings.groq_model),
        settings.manual_baseline_minutes,
    )


def current_principal(authorization: str | None = Header(default=None)) -> Principal:
    return resolve_principal(authorization, database, settings)


def manager_principal(principal: Principal = Depends(current_principal)) -> Principal:
    require_role(principal, "support_manager")
    return principal


def validated_case(
    case_id: str, customer_id: str, tenant_id: str = "tenant-demo"
) -> dict:
    latest = database.latest_triage_for_case(case_id, tenant_id)
    if not latest:
        raise HTTPException(status_code=409, detail="Case must be triaged before this action.")
    if latest["customer_id"] != customer_id:
        raise HTTPException(status_code=409, detail="Customer does not match the triaged case.")
    return latest


def verify_webhook_token(received: str | None) -> None:
    if not settings.webhook_token:
        if settings.channel_mode == "live":
            raise HTTPException(
                status_code=503,
                detail="KORA_WEBHOOK_TOKEN must be configured in live channel mode.",
            )
        return
    if not hmac.compare_digest(received or "", settings.webhook_token):
        raise HTTPException(status_code=401, detail="Invalid webhook token.")


def verify_postmark_webhook(
    authorization: str | None, fallback_token: str | None
) -> None:
    if settings.postmark_webhook_username and settings.postmark_webhook_password:
        try:
            scheme, encoded = (authorization or "").split(" ", 1)
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError, binascii.Error):
            raise HTTPException(
                status_code=401, detail="Invalid Postmark webhook credentials."
            ) from None
        valid = scheme.lower() == "basic" and hmac.compare_digest(
            username, settings.postmark_webhook_username
        ) and hmac.compare_digest(password, settings.postmark_webhook_password)
        if not valid:
            raise HTTPException(
                status_code=401, detail="Invalid Postmark webhook credentials."
            )
        return
    verify_webhook_token(fallback_token)


def _message_reference(value: str | None) -> str | None:
    if not value:
        return None
    references = [item.strip().strip("<>") for item in value.split() if item.strip()]
    return references[-1] if references else None


def verify_whatsapp_signature(raw: bytes, received: str | None) -> None:
    if settings.channel_mode == "live" and not settings.whatsapp_app_secret:
        raise HTTPException(
            status_code=503,
            detail="WHATSAPP_APP_SECRET must be configured in live channel mode.",
        )
    if not settings.whatsapp_app_secret:
        return
    expected = "sha256=" + hmac.new(
        settings.whatsapp_app_secret.encode("utf-8"), raw, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(received or "", expected):
        raise HTTPException(status_code=401, detail="Invalid WhatsApp signature.")


@app.get("/api/health")
async def health() -> dict:
    counts = database.job_counts(settings.default_tenant_id)
    degraded = not settings.groq_api_key or counts.get("dead", 0) > 0
    return {
        "status": "degraded" if degraded else "ready",
        "operational_mode": "manual" if not settings.groq_api_key else "ai_assisted",
        "provider": "groq",
        "model": settings.groq_model,
        "configured": bool(settings.groq_api_key),
        "memory": "sqlite",
        "guardrails": "enabled",
        "auth_mode": settings.auth_mode,
        "channels": gateway.status(),
        "paystack": {
            "configured": bool(settings.paystack_secret_key),
            "mode": "read_only",
        },
        "jobs": counts,
        "alert": (
            "AI unavailable. Inbound cases remain available for manual handling."
            if not settings.groq_api_key
            else f"{counts.get('dead', 0)} workflow jobs require manual review."
            if counts.get("dead", 0)
            else None
        ),
    }


@app.get("/api/auth/me")
async def auth_me(principal: Principal = Depends(current_principal)) -> dict:
    return {
        "tenant_id": principal.tenant_id,
        "user_id": principal.user_id,
        "display_name": principal.display_name,
        "role": principal.role,
        "auth_mode": settings.auth_mode,
    }


@app.get("/api/integrations")
async def integrations(principal: Principal = Depends(current_principal)) -> dict:
    return {
        **gateway.status(),
        "worker_enabled": settings.worker_enabled,
        "jobs": database.job_counts(principal.tenant_id),
        "webhook_protected": bool(settings.webhook_token),
        "paystack": {
            "provider": "Paystack",
            "configured": bool(settings.paystack_secret_key),
            "mode": "read_only",
        },
    }


@app.post("/api/triage", response_model=TriageResult)
async def triage(
    request: TriageRequest, principal: Principal = Depends(current_principal)
) -> TriageResult:
    try:
        return await get_service().triage(request, tenant_id=principal.tenant_id)
    except RateLimitError as error:
        raise HTTPException(status_code=429, detail="Groq rate limit reached. Try again shortly.") from error
    except APIConnectionError as error:
        raise HTTPException(status_code=502, detail="Could not reach Groq.") from error
    except APIStatusError as error:
        raise HTTPException(status_code=502, detail=f"Groq rejected the request: {error.status_code}") from error
    except ValueError as error:
        raise HTTPException(status_code=502, detail="Groq returned an invalid structured response.") from error


@app.get("/api/audit")
async def audit(
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(current_principal),
) -> dict:
    return {"items": database.audits(limit, principal.tenant_id)}


@app.get("/api/cases")
async def cases(principal: Principal = Depends(current_principal)) -> dict:
    items = database.support_tickets(principal.tenant_id)
    for item in items:
        lifecycle = database.lifecycle(item["id"], principal.tenant_id)
        if lifecycle:
            item["lifecycle"] = lifecycle
    return {"items": items}


@app.get("/api/policies")
async def policies(principal: Principal = Depends(current_principal)) -> dict:
    return {"items": database.policies(principal.tenant_id)}


@app.post("/api/policies", status_code=201)
async def create_policy(
    value: KnowledgePolicyRequest,
    principal: Principal = Depends(manager_principal),
) -> dict:
    policy = database.add_policy(
        tenant_id=principal.tenant_id,
        **value.model_dump(),
    )
    database.add_audit(
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
async def update_policy_state(
    policy_id: int,
    value: PolicyStateRequest,
    principal: Principal = Depends(manager_principal),
) -> dict:
    policy = database.set_policy_active(
        policy_id, value.active, principal.tenant_id
    )
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")
    return policy


@app.get("/api/proof-runs")
async def proof_runs(principal: Principal = Depends(manager_principal)) -> dict:
    return {"items": database.proof_runs(principal.tenant_id)}


@app.post("/api/proof-runs")
async def run_proof(
    value: ProofRunRequest,
    principal: Principal = Depends(manager_principal),
) -> dict:
    service = get_service()
    settings_value = database.get_setting(
        "automation",
        {"enabled": True, "auto_approve_threshold": 95, "mandatory_review_threshold": 70},
        principal.tenant_id,
    )
    rows = []
    proof_tenant = f"{principal.tenant_id}:proof"
    for index, case in enumerate(value.cases):
        try:
            result = await service.triage(
                TriageRequest(
                    case_id=f"PROOF-{index + 1}-{case.case_id}"[:80],
                    channel=case.channel,
                    message=case.message,
                    subject=case.subject,
                    customer={
                        "customer_id": f"proof-customer-{index + 1}",
                        "name": case.customer_name,
                        "previous_context": "",
                        "notes": ["Historical proof-mode case. Never deliver externally."],
                    },
                ),
                tenant_id=proof_tenant,
                policy_tenant_id=principal.tenant_id,
            )
            expected = (
                {
                    key: item.value if hasattr(item, "value") else item
                    for key, item in case.expected.model_dump().items()
                }
                if case.expected
                else None
            )
            rows.append(
                {
                    "case_id": case.case_id,
                    "language": case.language,
                    "expected": expected,
                    "predicted": {
                        "intent": result.intent.value,
                        "urgency": result.urgency.value,
                        "route": result.route.value,
                        "confidence": result.confidence,
                        "escalated": result.escalated,
                    },
                }
            )
        except Exception as error:
            rows.append(
                {
                    "case_id": case.case_id,
                    "language": case.language,
                    "error": str(error),
                }
            )
    report = proof_report(
        rows, auto_threshold=settings_value["auto_approve_threshold"]
    )
    run = database.add_proof_run(
        tenant_id=principal.tenant_id,
        name=value.name,
        status="complete" if not report["failed"] else "complete_with_errors",
        report=report,
    )
    database.add_audit(
        case_id=f"PROOF-{run['id']}",
        customer_id="workspace",
        event_type="proof_run_completed",
        model=settings.groq_model,
        request={"cases": len(value.cases)},
        decision={
            "readiness_score": report["readiness_score"],
            "recommendation": report["recommendation"],
        },
        guardrails={"silent_mode": True, "external_delivery": False},
        actor=principal.display_name,
        tenant_id=principal.tenant_id,
    )
    return run


@app.get("/api/settings/automation", response_model=AutomationSettings)
async def automation_settings(
    _: Principal = Depends(current_principal),
) -> AutomationSettings:
    return AutomationSettings.model_validate(
        database.get_setting(
            "automation",
            {"enabled": True, "auto_approve_threshold": 95, "mandatory_review_threshold": 70},
            _.tenant_id,
        )
    )


@app.put("/api/settings/automation", response_model=AutomationSettings)
async def update_automation_settings(
    value: AutomationSettings,
    _: Principal = Depends(manager_principal),
) -> AutomationSettings:
    if value.mandatory_review_threshold >= value.auto_approve_threshold:
        raise HTTPException(
            status_code=422,
            detail="Mandatory review threshold must be lower than auto-approve threshold.",
        )
    database.set_setting("automation", value.model_dump(), _.tenant_id)
    return value


@app.get("/api/customers/{customer_id}/memory")
async def customer_memory(
    customer_id: str, principal: Principal = Depends(current_principal)
) -> dict:
    return {
        "customer_id": customer_id,
        "items": database.memories_for(customer_id, tenant_id=principal.tenant_id),
    }


@app.post("/api/cases/{case_id}/approve")
async def approve(
    case_id: str,
    action: ActionRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    latest = validated_case(case_id, action.customer_id, principal.tenant_id)
    if latest["guardrails"].get("escalated"):
        raise HTTPException(
            status_code=409,
            detail="This case is blocked from direct approval by a guardrail. Escalate it instead.",
        )
    status = "auto_approved" if action.note == "confidence_policy_auto_approve" else "approved"
    audit_id = database.add_audit(
        case_id=case_id,
        customer_id=action.customer_id,
        event_type="human_approved",
        model=None,
        request={},
        decision={"status": status, "note": action.note, "response": action.response},
        guardrails={},
        actor=principal.display_name,
        tenant_id=principal.tenant_id,
    )
    predicted_response = latest["decision"].get("response") or ""
    reviewed_response = action.response or predicted_response
    database.add_feedback(
        case_id=case_id,
        customer_id=action.customer_id,
        actor=principal.display_name,
        predicted=latest["decision"],
        corrected={},
        response_accepted=True,
        response_edited=reviewed_response.strip() != predicted_response.strip(),
        reason=action.note,
        tenant_id=principal.tenant_id,
    )
    conversation = database.conversation(case_id, principal.tenant_id)
    job_id = None
    if conversation:
        job_id = database.enqueue_job(
            tenant_id=principal.tenant_id,
            job_type="send_response",
            idempotency_key=f"approved-send:{audit_id}",
            payload={
                "case_id": case_id,
                "response": reviewed_response,
                "actor": principal.display_name,
            },
        )
        database.set_lifecycle(case_id, "queued", tenant_id=principal.tenant_id)
        ticket_status = "Queued to send"
    else:
        database.set_lifecycle(case_id, "approved", tenant_id=principal.tenant_id)
        ticket_status = "Auto-approved" if status == "auto_approved" else "Approved"
    database.update_support_ticket_fields(
        case_id, {"status": ticket_status}, principal.tenant_id
    )
    return {
        "case_id": case_id,
        "status": "queued" if job_id else status,
        "audit_id": audit_id,
        "job_id": job_id,
    }


@app.post("/api/cases/{case_id}/escalate")
async def escalate(
    case_id: str,
    action: ActionRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    latest = validated_case(case_id, action.customer_id, principal.tenant_id)
    audit_id = database.add_audit(
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
    database.add_feedback(
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
    database.set_lifecycle(
        case_id,
        "review_required",
        tenant_id=principal.tenant_id,
        assigned_to=principal.display_name,
    )
    database.update_support_ticket_fields(
        case_id, {"status": "Assigned", "escalated": True}, principal.tenant_id
    )
    return {"case_id": case_id, "status": "assigned_to_specialist", "audit_id": audit_id}


@app.post("/api/cases/{case_id}/route")
async def route_case(
    case_id: str,
    action: RouteRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    validated_case(case_id, action.customer_id, principal.tenant_id)
    audit_id = database.add_audit(
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
    database.update_support_ticket_fields(
        case_id,
        {"status": f"Routed to {action.team}", "route": action.team},
        principal.tenant_id,
    )
    return {"case_id": case_id, "status": "routed", "route": action.team, "audit_id": audit_id}


@app.put("/api/cases/{case_id}/assignment")
async def assign_case(
    case_id: str,
    action: CaseAssignmentRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    ticket = database.support_ticket(case_id, principal.tenant_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Case not found.")
    assignee = action.assignee
    claiming_self = assignee == "me"
    if claiming_self:
        assignee = principal.display_name
    try:
        lifecycle = database.claim_case(
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
    database.update_support_ticket_fields(
        case_id,
        {
            "assignee": assignee,
            "status": f"Assigned to {assignee}" if assignee else "Unassigned",
        },
        principal.tenant_id,
    )
    database.add_audit(
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
async def case_notes(
    case_id: str, principal: Principal = Depends(current_principal)
) -> dict:
    if not database.support_ticket(case_id, principal.tenant_id):
        raise HTTPException(status_code=404, detail="Case not found.")
    return {"items": database.case_notes(case_id, principal.tenant_id)}


@app.post("/api/cases/{case_id}/notes", status_code=201)
async def add_case_note(
    case_id: str,
    value: CaseNoteRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    ticket = database.support_ticket(case_id, principal.tenant_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Case not found.")
    note = database.add_case_note(
        case_id=case_id,
        tenant_id=principal.tenant_id,
        actor=principal.display_name,
        body=value.body,
        mentions=value.mentions,
    )
    database.add_audit(
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
) -> dict:
    latest = validated_case(case_id, value.customer_id, principal.tenant_id)
    extracted = latest["decision"].get("entities", {}).get("transactionId")
    if not extracted or extracted.lower() != value.reference.lower():
        raise HTTPException(
            status_code=409,
            detail="Verification is restricted to the transaction reference extracted from this case.",
        )
    if not settings.paystack_secret_key:
        raise HTTPException(
            status_code=503,
            detail="Paystack read-only verification is not configured.",
        )
    try:
        result = await PaystackVerifier(
            settings.paystack_secret_key, settings.paystack_base_url
        ).verify(value.reference)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (httpx.HTTPError, RuntimeError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    audit_id = database.add_audit(
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
    database.update_support_ticket_fields(
        case_id,
        {"verifiedTransaction": result},
        principal.tenant_id,
    )
    return {**result, "audit_id": audit_id}


@app.post("/api/cases/{case_id}/manual-assessment")
async def manual_assessment(
    case_id: str,
    value: ManualAssessmentRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    ticket = database.support_ticket(case_id, principal.tenant_id)
    if not ticket or ticket["customerId"] != value.customer_id:
        raise HTTPException(status_code=404, detail="Case not found.")
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
    audit_id = database.add_audit(
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
    database.update_support_ticket_triage(
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
    lifecycle = database.set_lifecycle(
        case_id, "review_required", tenant_id=principal.tenant_id
    )
    return {
        "case_id": case_id,
        "audit_id": audit_id,
        "lifecycle": lifecycle,
        "ticket": database.support_ticket(case_id, principal.tenant_id),
    }


@app.get("/api/cases/{case_id}/conversation")
async def case_conversation(
    case_id: str, principal: Principal = Depends(current_principal)
) -> dict:
    if not database.support_ticket(case_id, principal.tenant_id):
        raise HTTPException(status_code=404, detail="Case not found.")
    return {
        "case_id": case_id,
        "lifecycle": database.lifecycle(case_id, principal.tenant_id),
        "messages": database.conversation(case_id, principal.tenant_id),
        "notes": database.case_notes(case_id, principal.tenant_id),
    }


@app.post("/api/cases/{case_id}/feedback")
async def record_feedback(
    case_id: str,
    feedback: FeedbackRequest,
    principal: Principal = Depends(current_principal),
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
    feedback_id = database.add_feedback(
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
        database.update_support_ticket_fields(case_id, corrected, principal.tenant_id)
    audit_id = database.add_audit(
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
async def resolve_case(
    case_id: str,
    action: ResolveRequest,
    principal: Principal = Depends(current_principal),
) -> dict:
    validated_case(case_id, action.customer_id, principal.tenant_id)
    lifecycle = database.set_lifecycle(case_id, "resolved", tenant_id=principal.tenant_id)
    database.update_support_ticket_fields(
        case_id, {"status": "Resolved"}, principal.tenant_id
    )
    audit_id = database.add_audit(
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


@app.get("/api/evaluations/summary")
async def evaluations(principal: Principal = Depends(current_principal)) -> dict:
    return evaluation_summary(database, principal.tenant_id)


@app.get("/api/evaluations/dataset")
async def evaluation_dataset(
    _: Principal = Depends(manager_principal),
) -> dict:
    return dataset_summary()


@app.get("/api/evaluations/gate")
async def evaluation_gate(
    _: Principal = Depends(manager_principal),
) -> dict:
    return regression_gate(database, _.tenant_id)


@app.get("/api/jobs")
async def jobs(
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(manager_principal),
) -> dict:
    return {
        "counts": database.job_counts(principal.tenant_id),
        "items": database.jobs(principal.tenant_id, limit),
    }


@app.post("/api/jobs/run-once")
async def run_job_once(_: Principal = Depends(manager_principal)) -> dict:
    if not worker:
        raise HTTPException(status_code=503, detail="Workflow worker is not initialized.")
    return {"processed": await worker.process_one()}


@app.post("/api/webhooks/inbound", status_code=202)
async def generic_inbound(
    message: InboundMessageRequest,
    x_kora_webhook_token: str | None = Header(default=None, alias="X-Kora-Webhook-Token"),
) -> dict:
    verify_webhook_token(x_kora_webhook_token)
    return workflow.ingest(
        message, provider="kora_webhook", tenant_id=settings.default_tenant_id
    )


def _postmark_header(payload: dict, name: str) -> str | None:
    for item in payload.get("Headers") or []:
        if str(item.get("Name", "")).lower() == name.lower():
            return item.get("Value")
    return None


@app.post("/api/webhooks/postmark/inbound", status_code=202)
async def postmark_inbound(
    payload: dict,
    authorization: str | None = Header(default=None),
    x_kora_webhook_token: str | None = Header(default=None, alias="X-Kora-Webhook-Token"),
) -> dict:
    verify_postmark_webhook(authorization, x_kora_webhook_token)
    message_id = str(payload.get("MessageID") or "")
    sender = str(payload.get("From") or "")
    body = str(payload.get("TextBody") or "").strip()
    if not message_id or not sender or not body:
        raise HTTPException(status_code=422, detail="Postmark payload is missing MessageID, From, or TextBody.")
    return workflow.ingest(
        InboundMessageRequest(
            event_id=f"postmark-inbound:{message_id}",
            provider_message_id=message_id,
            channel="email",
            sender=sender,
            customer_name=str(payload.get("FromName") or sender.split("@", 1)[0]),
            message=body,
            subject=payload.get("Subject"),
            external_thread_id=_message_reference(
                _postmark_header(payload, "In-Reply-To")
                or _postmark_header(payload, "References")
            ),
        ),
        provider="postmark",
        tenant_id=settings.default_tenant_id,
    )


@app.post("/api/webhooks/postmark/delivery")
async def postmark_delivery(
    payload: dict,
    authorization: str | None = Header(default=None),
    x_kora_webhook_token: str | None = Header(default=None, alias="X-Kora-Webhook-Token"),
) -> dict:
    verify_postmark_webhook(authorization, x_kora_webhook_token)
    message_id = str(payload.get("MessageID") or "")
    record_type = str(payload.get("RecordType") or "").lower()
    status_value = "delivered" if record_type == "delivery" else "failed" if record_type == "bounce" else "sent"
    event_id = f"postmark-{record_type}:{message_id}:{payload.get('DeliveredAt') or payload.get('BouncedAt') or ''}"
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
    if not database.record_webhook(
        event_id=event_id,
        tenant_id=settings.default_tenant_id,
        provider=provider,
        event_type=f"message_{status_value}",
        payload=payload,
    ):
        return {"duplicate": True}
    case_id = database.update_message_delivery(
        provider_message_id, status_value, settings.default_tenant_id
    )
    if case_id:
        lifecycle_state = (
            "delivered"
            if status_value in {"delivered", "read"}
            else "failed" if status_value == "failed" else "sent"
        )
        database.set_lifecycle(
            case_id,
            lifecycle_state,
            tenant_id=settings.default_tenant_id,
        )
        ticket = database.support_ticket(case_id, settings.default_tenant_id)
        if ticket:
            database.update_support_ticket_fields(
                case_id,
                {"status": lifecycle_state.capitalize()},
                settings.default_tenant_id,
            )
            database.add_audit(
                case_id=case_id,
                customer_id=ticket["customerId"],
                event_type="delivery_updated",
                model=None,
                request={"provider": provider},
                decision={"status": status_value},
                guardrails={},
                actor=provider,
                tenant_id=settings.default_tenant_id,
            )
    return {"duplicate": False, "case_id": case_id, "status": status_value}


@app.get("/api/webhooks/whatsapp")
async def verify_whatsapp(
    mode: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    if (
        mode == "subscribe"
        and settings.whatsapp_verify_token
        and token == settings.whatsapp_verify_token
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
    payload = json.loads(raw or b"{}")
    results = []
    delivery_results = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = value.get("contacts") or []
            name = contacts[0].get("profile", {}).get("name", "WhatsApp customer") if contacts else "WhatsApp customer"
            for status in value.get("statuses") or []:
                provider_message_id = str(status.get("id") or "")
                status_value = str(status.get("status") or "sent").lower()
                if provider_message_id and status_value in {"sent", "delivered", "read", "failed"}:
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
            for message in value.get("messages") or []:
                if message.get("type") != "text":
                    continue
                sender = str(message.get("from") or "")
                provider_message_id = str(message.get("id") or "")
                results.append(
                    workflow.ingest(
                        InboundMessageRequest(
                            event_id=f"whatsapp-inbound:{provider_message_id}",
                            provider_message_id=provider_message_id,
                            channel="whatsapp",
                            sender=sender,
                            customer_name=name,
                            message=message.get("text", {}).get("body", ""),
                            external_thread_id=f"wa:{sender}",
                        ),
                        provider="whatsapp_cloud",
                        tenant_id=settings.default_tenant_id,
                    )
                )
    return {
        "accepted": len(results),
        "delivery_updates": len(delivery_results),
        "items": results,
        "deliveries": delivery_results,
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
