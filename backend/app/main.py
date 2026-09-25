from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .api import deps
from .api.routers import case_actions, cases, evaluations, operations, policies, proof_runs, system, webhooks
from .demo_seed import seed_demo_data
from .workflow import WorkflowWorker

frontend_dist = Path(__file__).resolve().parents[2] / "dist"


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


app.include_router(system.router)
app.include_router(policies.router)
app.include_router(proof_runs.router)
app.include_router(operations.router)
app.include_router(evaluations.router)
app.include_router(cases.router)
app.include_router(case_actions.router)
app.include_router(webhooks.router)


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
