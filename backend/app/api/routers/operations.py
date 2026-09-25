"""Team availability and the background job queue."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...auth import Principal, require_role
from ...schemas import TeamAvailabilityRequest
from .. import deps
from ..deps import (
    current_principal,
    manager_principal,
    write_rate_limit,
)

router = APIRouter()


@router.get("/api/team")
def team(principal: Principal = Depends(current_principal)) -> dict:
    return {"items": deps.database.team_members(principal.tenant_id)}


@router.put("/api/team/{member_id}/availability")
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


@router.get("/api/jobs")
def jobs(
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(manager_principal),
) -> dict:
    return {
        "counts": deps.database.job_counts(principal.tenant_id),
        "items": deps.database.jobs(principal.tenant_id, limit),
    }


@router.post("/api/jobs/run-once")
async def run_job_once(principal: Principal = Depends(manager_principal)) -> dict:
    if not deps.worker:
        raise HTTPException(status_code=503, detail="Workflow worker is not initialized.")
    return {"processed": await deps.worker.process_one(tenant_id=principal.tenant_id)}
