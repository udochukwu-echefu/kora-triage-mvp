"""Regression tests for the worker, webhook, tenancy, proof-mode and limit fixes."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main, manage
from app.api import deps
from app.auth import Principal, resolve_principal
from app.channels import ChannelGateway, DeliveryResult
from app.config import Settings
from app.database import Database
from app.demo_seed import seed_demo_data
from app.limits import SlidingWindowLimiter
from app.schemas import (
    ExtractedEntities,
    InboundMessageRequest,
    Intent,
    ModelTriage,
    ProofCase,
    Route,
    Sentiment,
    Urgency,
)
from app.service import TriageService
from app.workflow import SupportWorkflow, WorkflowWorker, send_job_payload

MANAGER = Principal("tenant-demo", "manager", "Test Manager", "support_manager")


@pytest.fixture
def database(tmp_path: Path, monkeypatch) -> Database:
    db = Database(tmp_path / "reliability.db")
    db.initialize()
    monkeypatch.setattr(deps, "database", db)
    monkeypatch.setattr(deps, "workflow", SupportWorkflow(db))
    monkeypatch.setattr(deps, "settings", Settings(channel_mode="demo", webhook_token="hook-secret", whatsapp_app_secret=None, allow_unsigned_webhooks=True))
    deps.limiter.reset()
    return db


def ingest(database: Database, event: str = "event-1", channel: str = "email", sender: str = "ada@example.com", **extra) -> dict:
    return SupportWorkflow(database).ingest(
        InboundMessageRequest(
            event_id=event,
            provider_message_id=event,
            channel=channel,
            sender=sender,
            customer_name="Ada Obi",
            message="My transfer has not arrived.",
            **extra,
        ),
        provider="postmark" if channel == "email" else "whatsapp_cloud",
        tenant_id="tenant-demo",
    )


class CountingGateway:
    def __init__(self):
        self.calls: list[dict] = []

    async def send(self, **kwargs) -> DeliveryResult:
        self.calls.append(kwargs)
        return DeliveryResult(provider="postmark", provider_message_id=f"pm-{len(self.calls)}", status="sent")


def queue_send(database: Database, case: dict, state: str = "queued") -> int:
    database.set_lifecycle(case["case_id"], state)
    return database.enqueue_job(
        tenant_id="tenant-demo",
        job_type="send_response",
        idempotency_key=f"send-{case['case_id']}-{state}",
        payload=send_job_payload(
            database,
            case_id=case["case_id"],
            tenant_id="tenant-demo",
            response="We are reviewing your transfer.",
            actor="Agent",
            expected_states=[state],
        ),
    )


def drain_triage_jobs(database: Database) -> None:
    with database.connect() as connection:
        connection.execute("UPDATE delivery_job SET status = 'succeeded' WHERE job_type = 'triage'")


# 4. Worker reliability ---------------------------------------------------------

@pytest.mark.asyncio
async def test_worker_loop_survives_an_unexpected_error(database, monkeypatch):
    worker = WorkflowWorker(database, lambda: None, CountingGateway(), poll_seconds=0.001)
    calls = {"count": 0}

    async def flaky(tenant_id=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise sqlite3.OperationalError("database is locked")
        worker.stop()
        return False

    monkeypatch.setattr(worker, "process_one", flaky)
    await asyncio.wait_for(worker.run(), timeout=2)
    assert calls["count"] == 2


def test_job_orphaned_in_running_state_is_reclaimed_after_its_lease(database):
    job_id = database.enqueue_job(tenant_id="tenant-demo", job_type="triage", idempotency_key="k", payload={})
    assert database.claim_job()["id"] == job_id
    assert database.claim_job(lease_seconds=300) is None  # still leased
    stale = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    with database.connect() as connection:
        connection.execute("UPDATE delivery_job SET updated_at = ? WHERE id = ?", (stale, job_id))
    reclaimed = database.claim_job(lease_seconds=300)
    assert reclaimed["id"] == job_id and reclaimed["attempts"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda db, case: db.set_lifecycle(case["case_id"], "resolved"), "resolved"),
        (lambda db, case: db.set_lifecycle(case["case_id"], "review_required"), "escalated"),
        (lambda db, case: ingest(db, "event-2", references=["event-1"]), "new message"),
    ],
)
async def test_send_is_cancelled_when_the_case_changed_after_approval(database, change, reason):
    case = ingest(database)
    drain_triage_jobs(database)
    queue_send(database, case)
    change(database, case)
    gateway = CountingGateway()
    worker = WorkflowWorker(database, lambda: None, gateway)
    assert await worker.process_one() is True
    assert gateway.calls == []
    job = next(item for item in database.jobs() if item["job_type"] == "send_response")
    assert job["status"] == "cancelled"
    assert reason in job["last_error"]
    assert database.audit_event_exists(case["case_id"], "delivery_cancelled")


@pytest.mark.asyncio
async def test_retry_after_a_partial_failure_does_not_message_the_customer_twice(database, monkeypatch):
    case = ingest(database)
    drain_triage_jobs(database)
    queue_send(database, case)
    gateway = CountingGateway()
    worker = WorkflowWorker(database, lambda: None, gateway)
    original = database.add_audit

    def fail_once(**kwargs):
        if kwargs["event_type"] == "response_sent":
            monkeypatch.setattr(database, "add_audit", original)
            raise sqlite3.OperationalError("disk I/O error")
        return original(**kwargs)

    monkeypatch.setattr(database, "add_audit", fail_once)
    await worker.process_one()
    job = next(item for item in database.jobs() if item["job_type"] == "send_response")
    assert job["status"] == "retry"
    with database.connect() as connection:
        connection.execute("UPDATE delivery_job SET run_after = ? WHERE id = ?", (datetime.now(UTC).isoformat(), job["id"]))
    await worker.process_one()
    assert len(gateway.calls) == 1
    assert [m["direction"] for m in database.conversation(case["case_id"])] == ["inbound", "outbound"]
    assert database.lifecycle(case["case_id"])["state"] == "sent"


@pytest.mark.asyncio
async def test_whatsapp_reply_window_is_enforced(database):
    case = ingest(database, channel="whatsapp", sender="2348031234567")
    drain_triage_jobs(database)
    old = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    with database.connect() as connection:
        connection.execute("UPDATE support_message SET created_at = ?", (old,))
    queue_send(database, case)
    gateway = CountingGateway()
    await WorkflowWorker(database, lambda: None, gateway).process_one()
    assert gateway.calls == []
    job = next(item for item in database.jobs() if item["job_type"] == "send_response")
    assert job["status"] == "cancelled" and "24-hour" in job["last_error"]


@pytest.mark.asyncio
async def test_email_reply_threads_on_the_customers_message_id(database):
    case = ingest(database, rfc_message_id="<original-123@mail.example.com>")
    drain_triage_jobs(database)
    queue_send(database, case)
    gateway = CountingGateway()
    await WorkflowWorker(database, lambda: None, gateway).process_one()
    assert gateway.calls[0]["in_reply_to"] == "original-123@mail.example.com"

    # The customer's client replies to Postmark's <MessageID@mtasv.net> header.
    reply = ingest(database, "event-2", references=["<pm-1@mtasv.net>"])
    assert reply["case_id"] == case["case_id"]


@pytest.mark.asyncio
async def test_postmark_sends_bracketed_threading_headers(monkeypatch):
    captured = {}

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, _url, headers, json):
            captured.update(json)

            class Response:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"MessageID": "pm-99"}

            return Response()

    monkeypatch.setattr("app.channels.httpx.AsyncClient", Client)
    gateway = ChannelGateway(Settings(channel_mode="live", postmark_server_token="t", postmark_from_email="help@kora.test"))
    await gateway.send(channel="email", recipient="a@b.com", body="Hi", subject="Re: Help", in_reply_to="abc@mail", references=["root@mail"])
    headers = {item["Name"]: item["Value"] for item in captured["Headers"]}
    assert headers == {"In-Reply-To": "<abc@mail>", "References": "<root@mail> <abc@mail>"}


# 5. Webhooks accept real-world payloads ------------------------------------------

def client() -> TestClient:
    return TestClient(main.app, raise_server_exceptions=False)


def test_long_quoted_email_reply_is_accepted_and_stripped(database):
    body = "The transfer still has not arrived.\n\nOn Mon, 1 Sep 2026, Kora <help@kora.test> wrote:\n" + "> earlier text\n" * 2000
    response = client().post(
        "/api/webhooks/postmark/inbound",
        headers={"X-Kora-Webhook-Token": "hook-secret"},
        json={"MessageID": "m1", "From": "ada@example.com", "FromName": "N" * 300, "Subject": "S" * 900, "TextBody": body},
    )
    assert response.status_code == 202, response.text
    ticket = database.support_ticket(response.json()["case_id"])
    assert ticket["message"] == "The transfer still has not arrived."
    assert len(ticket["customer"]["name"]) <= 120 and len(ticket["subject"]) <= 500


def test_oversized_email_without_quotes_is_truncated_not_rejected(database):
    response = client().post(
        "/api/webhooks/postmark/inbound",
        headers={"X-Kora-Webhook-Token": "hook-secret"},
        json={"MessageID": "m2", "From": "ada@example.com", "TextBody": "x" * 20000},
    )
    assert response.status_code == 202
    assert len(database.support_ticket(response.json()["case_id"])["message"]) == 8000


def test_email_without_text_is_acknowledged(database):
    response = client().post(
        "/api/webhooks/postmark/inbound",
        headers={"X-Kora-Webhook-Token": "hook-secret"},
        json={"MessageID": "m3", "From": "ada@example.com", "TextBody": "   "},
    )
    assert response.status_code == 202 and response.json()["accepted"] is False


def test_whatsapp_invalid_json_is_a_client_error(database):
    assert client().post("/api/webhooks/whatsapp", content=b"not json").status_code == 400


def test_one_bad_whatsapp_message_does_not_fail_the_batch(database):
    payload = {
        "entry": [{"changes": [{"value": {"messages": [
            {"type": "text", "from": "2348031111111", "id": "w-empty", "text": {"body": ""}},
            {"type": "image", "from": "2348031111111", "id": "w-image"},
            {"type": "text", "from": "2348031111111", "id": "w-good", "text": {"body": "Help " * 3000}},
        ]}}]}]
    }
    response = client().post("/api/webhooks/whatsapp", content=json.dumps(payload))
    assert response.status_code == 202, response.text
    assert response.json()["accepted"] == 1


def test_webhooks_require_a_secret_unless_explicitly_allowed(database, monkeypatch):
    monkeypatch.setattr(deps, "settings", Settings(channel_mode="demo", webhook_token=None))
    body = {"event_id": "e", "provider_message_id": "p", "channel": "email", "sender": "x@y.com", "message": "spam"}
    assert client().post("/api/webhooks/inbound", json=body).status_code == 503


def test_unknown_postmark_record_types_are_ignored(database):
    response = client().post(
        "/api/webhooks/postmark/delivery",
        headers={"X-Kora-Webhook-Token": "hook-secret"},
        json={"MessageID": "x", "RecordType": "Click"},
    )
    assert response.status_code == 200 and response.json()["ignored"] is True


def test_health_check_is_minimal(database):
    body = client().get("/api/health").json()
    assert set(body) == {"status", "operational_mode", "configured", "auth_mode", "alert"}


# 7. SLA age is derived from timestamps --------------------------------------------

def test_minutes_ago_is_computed_from_the_last_customer_message(database):
    case = ingest(database)
    earlier = (datetime.now(UTC) - timedelta(minutes=90)).isoformat()
    with database.connect() as connection:
        connection.execute("UPDATE support_ticket SET last_message_at = ?", (earlier,))
    ticket = database.support_ticket(case["case_id"])
    assert 89 <= ticket["minutesAgo"] <= 91
    ingest(database, "event-2", references=["event-1"])
    assert database.support_ticket(case["case_id"])["minutesAgo"] == 0


def test_seed_reanchors_demo_ages_on_every_start(database):
    seed_demo_data(database)
    stale = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    with database.connect() as connection:
        connection.execute("UPDATE support_ticket SET last_message_at = ?", (stale,))
    seed_demo_data(database)
    ages = {ticket["id"]: ticket["minutesAgo"] for ticket in database.support_tickets()}
    assert max(ages.values()) < 24 * 60


def test_cases_include_lifecycle_in_one_query(database):
    seed_demo_data(database)
    items = main.cases(MANAGER)["items"]
    assert any(item.get("lifecycle", {}).get("assigned_to") for item in items)
    assert all("createdAt" in item and "lastMessageAt" in item for item in items)


# 9. Multi-tenancy ----------------------------------------------------------------

def _ticket(case_id: str, message: str) -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "id": case_id, "customerId": "CUS-1", "customer": {"name": "A"}, "channel": "email",
        "message": message, "receivedAt": now, "truthIntent": "Unlabelled", "truthUrgency": "unlabelled",
        "triage": {"source": "pending"}, "createdAt": now,
    }


def test_same_case_id_in_two_tenants_never_overwrites(database):
    database.add_support_ticket(_ticket("KOR-1", "tenant A message"), tenant_id="tenant-a")
    database.add_support_ticket(_ticket("KOR-1", "tenant B message"), tenant_id="tenant-b")
    database.set_lifecycle("KOR-1", "resolved", tenant_id="tenant-a")
    database.set_lifecycle("KOR-1", "new", tenant_id="tenant-b")
    assert database.support_ticket("KOR-1", "tenant-a")["message"] == "tenant A message"
    assert database.support_ticket("KOR-1", "tenant-b")["message"] == "tenant B message"
    assert database.lifecycle("KOR-1", "tenant-a")["state"] == "resolved"
    assert database.lifecycle("KOR-1", "tenant-b")["state"] == "new"


def test_legacy_single_key_tables_are_migrated(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE support_ticket (case_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, customer_json TEXT NOT NULL,
            channel TEXT NOT NULL, subject TEXT, message TEXT NOT NULL, received_at TEXT NOT NULL, minutes_ago INTEGER NOT NULL,
            truth_intent TEXT NOT NULL, truth_urgency TEXT NOT NULL, triage_json TEXT NOT NULL, created_at TEXT NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-demo');
        CREATE INDEX idx_ticket_received ON support_ticket(minutes_ago ASC);
        CREATE TABLE case_lifecycle (case_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, state TEXT NOT NULL,
            external_thread_id TEXT, provider TEXT, assigned_to TEXT, resolved_at TEXT, reopened_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL);
        INSERT INTO support_ticket VALUES ('KOR-9', 'CUS', '{"name": "A"}', 'email', NULL, 'hello', '10:00', 5,
            'Unlabelled', 'unlabelled', '{}', '2026-01-01T00:00:00+00:00', 'tenant-demo');
        INSERT INTO case_lifecycle VALUES ('KOR-9', 'tenant-demo', 'new', NULL, NULL, 'Ada', NULL, 0, '2026-01-01T00:00:00+00:00');
        """
    )
    connection.commit()
    connection.close()
    database = Database(path)
    database.initialize()
    database.initialize()  # idempotent
    ticket = database.support_ticket("KOR-9")
    assert ticket["message"] == "hello" and ticket["lifecycle"]["assigned_to"] == "Ada"
    database.add_support_ticket(_ticket("KOR-9", "other tenant"), tenant_id="tenant-other")
    assert database.support_ticket("KOR-9")["message"] == "hello"


def test_seed_uses_the_configured_tenant(tmp_path):
    database = Database(tmp_path / "seed.db")
    database.initialize()
    seed_demo_data(database, "tenant-acme")
    assert len(database.support_tickets("tenant-acme")) == 18
    assert database.support_tickets("tenant-demo") == []
    assert len(database.team_members("tenant-acme")) == 4


def test_token_cli_issues_and_revokes_access(tmp_path, monkeypatch, capsys):
    path = tmp_path / "tokens.db"
    monkeypatch.setattr(manage, "settings", Settings(database_path=path))
    manage.main(["create-token", "--tenant", "acme", "--user", "ada", "--name", "Ada Okafor", "--role", "support_manager"])
    token = capsys.readouterr().out.strip().splitlines()[-1]
    database = Database(path)
    required = Settings(database_path=path, auth_mode="required")
    assert resolve_principal(f"Bearer {token}", database, required).tenant_id == "acme"
    manage.main(["revoke-tokens", "--tenant", "acme", "--user", "ada"])
    with pytest.raises(HTTPException):
        resolve_principal(f"Bearer {token}", database, required)


def test_webhook_tenant_is_chosen_from_the_receiving_address(database, monkeypatch):
    monkeypatch.setattr(
        deps, "settings",
        Settings(channel_mode="demo", webhook_token="hook-secret", email_tenants={"help@acme.test": "tenant-acme"}),
    )
    response = client().post(
        "/api/webhooks/postmark/inbound",
        headers={"X-Kora-Webhook-Token": "hook-secret"},
        json={"MessageID": "m9", "From": "c@x.com", "OriginalRecipient": "help@acme.test", "TextBody": "Hi"},
    )
    assert database.support_ticket(response.json()["case_id"], "tenant-acme")


# 8. Proof mode ---------------------------------------------------------------------

class SafeModel:
    model_name = "fake"

    def __init__(self):
        self.memories: list[list] = []

    async def classify(self, request, memory):
        self.memories.append(memory)
        return ModelTriage(
            intent=Intent.general_enquiry, urgency=Urgency.low, sentiment=Sentiment.calm, route=Route.general_support,
            confidence=0.98,
            entities=ExtractedEntities(amount=None, transaction_id=None, order_id=None, account_last4=None, card_last4=None),
            memory_used=False, evidence=["Opening hours question."],
            draft_response="Hello Customer, our opening hours are in the help policy.",
        )


@pytest.mark.asyncio
async def test_proof_mode_simulates_automation_and_isolates_memory(database, monkeypatch):
    database.add_policy(tenant_id="tenant-demo", title="Opening hours", content="Opening hours are 8am to 6pm on weekdays for all enquiries.", source_url=None, version="1")
    model = SafeModel()
    service = TriageService(database, model)
    monkeypatch.setattr(deps, "get_service", lambda: service)
    cases = [
        ProofCase(case_id=f"H-{n}", channel="email", message="What are your opening hours?", expected={"intent": "General enquiry"})
        for n in range(3)
    ]
    for _ in range(2):
        run = database.add_proof_run(tenant_id="tenant-demo", name="Run", status="running", report={})
        finished = await main.execute_proof_run(run["id"], cases, MANAGER)
    assert finished["status"] == "complete"
    assert finished["report"]["safe_automation_candidates"] == 3
    assert finished["report"]["readiness_score"] == 100
    assert all(memory == [] for memory in model.memories), "memory leaked between proof cases or runs"
    assert database.support_tickets("tenant-demo") == []  # nothing entered the live queue
    assert database.job_counts("tenant-demo")["queued"] == 0


def test_proof_endpoint_returns_immediately_and_enforces_demo_size(database, monkeypatch):
    monkeypatch.setattr(deps, "get_service", lambda: object())
    monkeypatch.setattr(deps, "settings", Settings(auth_mode="demo", demo_proof_case_limit=2))
    too_many = {"name": "Big run", "cases": [{"case_id": f"H{n}", "channel": "email", "message": "Hi"} for n in range(3)]}
    assert client().post("/api/proof-runs", json=too_many).status_code == 422


# 10. Abuse limits -------------------------------------------------------------------

def test_sliding_window_limiter_blocks_after_the_limit():
    now = {"t": 0.0}
    limiter = SlidingWindowLimiter(clock=lambda: now["t"])
    for _ in range(3):
        limiter.check("ip:1", 3)
    with pytest.raises(HTTPException) as error:
        limiter.check("ip:1", 3)
    assert error.value.status_code == 429
    limiter.check("ip:2", 3)  # other clients are unaffected
    now["t"] = 61
    limiter.check("ip:1", 3)


def test_ai_endpoint_is_rate_limited_per_client(database, monkeypatch):
    seed_demo_data(database)
    monkeypatch.setattr(deps, "settings", Settings(auth_mode="demo", ai_requests_per_minute=2, groq_api_key=None))
    body = {"case_id": "KOR-2401", "customer_id": "CUS-1042"}
    statuses = [client().post("/api/triage", json=body).status_code for _ in range(3)]
    assert statuses == [503, 503, 429]


def test_demo_daily_ai_budget(database, monkeypatch):
    monkeypatch.setattr(deps, "settings", Settings(auth_mode="demo", demo_daily_ai_limit=2))
    assert deps.consume_ai_budget() and deps.consume_ai_budget()
    assert deps.consume_ai_budget() is False
    monkeypatch.setattr(deps, "settings", Settings(auth_mode="required", demo_daily_ai_limit=0))
    assert deps.consume_ai_budget() is True


def test_database_uses_write_ahead_logging(database):
    with database.connect() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


# Team roster --------------------------------------------------------------------------

def test_team_availability_is_editable_by_self_or_manager(database):
    seed_demo_data(database)
    members = {member["name"]: member for member in main.team(MANAGER)["items"]}
    musa = members["Musa Ibrahim"]
    agent = Principal("tenant-demo", "bola", "Bola Martins", "support_agent")
    with pytest.raises(HTTPException):
        main.set_team_availability(musa["id"], main.TeamAvailabilityRequest(availability="Online"), agent)
    assert main.set_team_availability(members["Bola Martins"]["id"], main.TeamAvailabilityRequest(availability="Away"), agent)["availability"] == "Away"
    assert main.set_team_availability(musa["id"], main.TeamAvailabilityRequest(availability="Online"), MANAGER)["availability"] == "Online"
