"""Process-wide API state and the FastAPI dependencies built on it.

Routers read state as ``deps.database``, ``deps.settings`` and so on at call
time rather than importing the names, so one assignment here (or a
monkeypatch in tests) changes what every route sees.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import Depends, Header, HTTPException, Request

from ..auth import Principal, require_role, resolve_principal
from ..channels import ChannelGateway
from ..config import settings
from ..database import Database
from ..groq_triage import GroqTriageModel
from ..limits import SlidingWindowLimiter, client_key
from ..service import TriageService
from ..workflow import SupportWorkflow, WorkflowWorker

database = Database(settings.database_path)
gateway = ChannelGateway(settings)
workflow = SupportWorkflow(database)
limiter = SlidingWindowLimiter()
worker: WorkflowWorker | None = None
worker_task: asyncio.Task | None = None
proof_tasks: set[asyncio.Task] = set()
_service_cache: dict[tuple, TriageService] = {}


def get_service() -> TriageService:
    if not settings.groq_api_key:
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY is not configured. Add it to backend/.env or the environment.",
        )
    key = (
        settings.groq_api_key,
        settings.groq_model,
        settings.manual_baseline_minutes,
        settings.delivery_ready,
        bool(settings.paystack_secret_key),
        id(database),
    )
    # One service (and one pooled Groq client) per configuration.
    if key not in _service_cache:
        _service_cache.clear()
        _service_cache[key] = TriageService(
            database,
            GroqTriageModel(settings.groq_api_key, settings.groq_model),
            settings.manual_baseline_minutes,
            delivery_available=settings.delivery_ready,
            verification_available=bool(settings.paystack_secret_key),
        )
    return _service_cache[key]


def current_principal(authorization: str | None = Header(default=None)) -> Principal:
    return resolve_principal(authorization, database, settings)


def manager_principal(principal: Principal = Depends(current_principal)) -> Principal:
    require_role(principal, "support_manager")
    return principal


def ai_rate_limit(request: Request) -> None:
    limiter.check(f"ai:{client_key(request, settings)}", settings.ai_requests_per_minute)


def write_rate_limit(request: Request) -> None:
    limiter.check(f"write:{client_key(request, settings)}", settings.write_requests_per_minute)


def consume_ai_budget(units: int = 1) -> bool:
    """Daily model-call budget for the public demo, where everyone is a manager."""
    if settings.auth_mode != "demo":
        return True
    day = datetime.now(UTC).date().isoformat()
    return all(
        database.consume_quota(f"demo-ai:{day}", settings.demo_daily_ai_limit)
        for _ in range(units)
    )


def require_ai_budget() -> None:
    if not consume_ai_budget():
        raise HTTPException(
            status_code=429,
            detail="The public demo has reached today's AI limit. Try again tomorrow.",
        )


def validated_case(
    case_id: str, customer_id: str, tenant_id: str = "tenant-demo"
) -> dict:
    latest = database.latest_triage_for_case(case_id, tenant_id)
    if not latest:
        raise HTTPException(status_code=409, detail="Case must be triaged before this action.")
    if latest["customer_id"] != customer_id:
        raise HTTPException(status_code=409, detail="Customer does not match the triaged case.")
    return latest
