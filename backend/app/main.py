from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from groq import APIConnectionError, APIStatusError, RateLimitError

from .config import settings
from .database import Database
from .demo_seed import seed_demo_data
from .groq_triage import GroqTriageModel
from .schemas import ActionRequest, AutomationSettings, RouteRequest, TriageRequest, TriageResult
from .service import TriageService


database = Database(settings.database_path)
frontend_dist = Path(__file__).resolve().parents[2] / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    seed_demo_data(database)
    yield


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
    allow_headers=["Content-Type"],
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


def validated_case(case_id: str, customer_id: str) -> dict:
    latest = database.latest_triage_for_case(case_id)
    if not latest:
        raise HTTPException(status_code=409, detail="Case must be triaged before this action.")
    if latest["customer_id"] != customer_id:
        raise HTTPException(status_code=409, detail="Customer does not match the triaged case.")
    return latest


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ready" if settings.groq_api_key else "configuration_required",
        "provider": "groq",
        "model": settings.groq_model,
        "configured": bool(settings.groq_api_key),
        "memory": "sqlite",
        "guardrails": "enabled",
    }


@app.post("/api/triage", response_model=TriageResult)
async def triage(request: TriageRequest) -> TriageResult:
    try:
        return await get_service().triage(request)
    except RateLimitError as error:
        raise HTTPException(status_code=429, detail="Groq rate limit reached. Try again shortly.") from error
    except APIConnectionError as error:
        raise HTTPException(status_code=502, detail="Could not reach Groq.") from error
    except APIStatusError as error:
        raise HTTPException(status_code=502, detail=f"Groq rejected the request: {error.status_code}") from error
    except ValueError as error:
        raise HTTPException(status_code=502, detail="Groq returned an invalid structured response.") from error


@app.get("/api/audit")
async def audit(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    return {"items": database.audits(limit)}


@app.get("/api/cases")
async def cases() -> dict:
    return {"items": database.support_tickets()}


@app.get("/api/settings/automation", response_model=AutomationSettings)
async def automation_settings() -> AutomationSettings:
    return AutomationSettings.model_validate(
        database.get_setting(
            "automation",
            {"enabled": True, "auto_approve_threshold": 95, "mandatory_review_threshold": 70},
        )
    )


@app.put("/api/settings/automation", response_model=AutomationSettings)
async def update_automation_settings(value: AutomationSettings) -> AutomationSettings:
    if value.mandatory_review_threshold >= value.auto_approve_threshold:
        raise HTTPException(
            status_code=422,
            detail="Mandatory review threshold must be lower than auto-approve threshold.",
        )
    database.set_setting("automation", value.model_dump())
    return value


@app.get("/api/customers/{customer_id}/memory")
async def customer_memory(customer_id: str) -> dict:
    return {"customer_id": customer_id, "items": database.memories_for(customer_id)}


@app.post("/api/cases/{case_id}/approve")
async def approve(case_id: str, action: ActionRequest) -> dict:
    latest = validated_case(case_id, action.customer_id)
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
        actor=action.actor,
    )
    database.update_support_ticket_fields(case_id, {"status": "Auto-approved" if status == "auto_approved" else "Approved"})
    return {"case_id": case_id, "status": status, "audit_id": audit_id}


@app.post("/api/cases/{case_id}/escalate")
async def escalate(case_id: str, action: ActionRequest) -> dict:
    validated_case(case_id, action.customer_id)
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
        actor=action.actor,
    )
    database.update_support_ticket_fields(case_id, {"status": "Assigned", "escalated": True})
    return {"case_id": case_id, "status": "assigned_to_specialist", "audit_id": audit_id}


@app.post("/api/cases/{case_id}/route")
async def route_case(case_id: str, action: RouteRequest) -> dict:
    validated_case(case_id, action.customer_id)
    audit_id = database.add_audit(
        case_id=case_id,
        customer_id=action.customer_id,
        event_type="human_routed",
        model=None,
        request={},
        decision={"status": "routed", "route": action.team},
        guardrails={},
        actor=action.actor,
    )
    database.update_support_ticket_fields(case_id, {"status": f"Routed to {action.team}", "route": action.team})
    return {"case_id": case_id, "status": "routed", "route": action.team, "audit_id": audit_id}


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
