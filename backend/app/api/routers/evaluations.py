"""Triage quality summaries, the labelled dataset and the regression gate."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...auth import Principal
from ...evaluation import evaluation_summary, regression_gate
from ...evaluation_dataset import dataset_summary
from .. import deps
from ..deps import (
    current_principal,
    manager_principal,
)

router = APIRouter()


@router.get("/api/evaluations/summary")
def evaluations(principal: Principal = Depends(current_principal)) -> dict:
    return evaluation_summary(deps.database, principal.tenant_id)


@router.get("/api/evaluations/dataset")
def evaluation_dataset(
    _: Principal = Depends(manager_principal),
) -> dict:
    return dataset_summary()


@router.get("/api/evaluations/gate")
def evaluation_gate(
    principal: Principal = Depends(manager_principal),
) -> dict:
    return regression_gate(deps.database, principal.tenant_id)
