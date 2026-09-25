"""Health, identity and integration status."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...auth import Principal
from .. import deps
from ..deps import (
    current_principal,
)

router = APIRouter()


@router.get("/api/health")
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


@router.get("/api/auth/me")
def auth_me(principal: Principal = Depends(current_principal)) -> dict:
    return {
        "tenant_id": principal.tenant_id,
        "user_id": principal.user_id,
        "display_name": principal.display_name,
        "role": principal.role,
        "auth_mode": deps.settings.auth_mode,
    }


@router.get("/api/integrations")
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
