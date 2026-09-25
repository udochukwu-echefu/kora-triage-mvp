"""Knowledge policies and the automation settings that depend on them."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...auth import Principal
from ...config import DEFAULT_AUTOMATION
from ...schemas import (
    AutomationSettings,
    KnowledgePolicyRequest,
    PolicyStateRequest,
)
from .. import deps
from ..deps import (
    current_principal,
    manager_principal,
    write_rate_limit,
)

router = APIRouter()


@router.get("/api/policies")
def policies(principal: Principal = Depends(current_principal)) -> dict:
    return {"items": deps.database.policies(principal.tenant_id)}


@router.post("/api/policies", status_code=201)
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


@router.put("/api/policies/{policy_id}/state")
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


@router.get("/api/settings/automation", response_model=AutomationSettings)
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


@router.put("/api/settings/automation", response_model=AutomationSettings)
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
