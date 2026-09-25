"""Proof runs: replay historical cases through the live decision path without delivering anything."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from ...auth import Principal
from ...config import DEFAULT_AUTOMATION
from ...launch_features import proof_report
from ...schemas import (
    ProofCase,
    ProofRunRequest,
    TriageRequest,
)
from .. import deps
from ..deps import (
    ai_rate_limit,
    consume_ai_budget,
    manager_principal,
)

logger = logging.getLogger("kora.api")

router = APIRouter()


@router.get("/api/proof-runs")
def proof_runs(principal: Principal = Depends(manager_principal)) -> dict:
    return {"items": deps.database.proof_runs(principal.tenant_id)}


@router.get("/api/proof-runs/{run_id}")
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


@router.post("/api/proof-runs", status_code=202)
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
