from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..automation import NOT_EVALUATED, recorded_automation_decision

TABLES = """
CREATE TABLE IF NOT EXISTS customer_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    entities_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'tenant-demo'
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    model TEXT,
    request_json TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    guardrail_json TEXT NOT NULL,
    actor TEXT,
    created_at TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'tenant-demo'
);

CREATE TABLE IF NOT EXISTS support_ticket (
    case_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    customer_json TEXT NOT NULL,
    channel TEXT NOT NULL,
    subject TEXT,
    message TEXT NOT NULL,
    received_at TEXT NOT NULL,
    minutes_ago INTEGER NOT NULL,
    truth_intent TEXT NOT NULL,
    truth_urgency TEXT NOT NULL,
    triage_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'tenant-demo',
    last_message_at TEXT,
    PRIMARY KEY (tenant_id, case_id)
);

CREATE TABLE IF NOT EXISTS app_setting (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_lifecycle (
    case_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    state TEXT NOT NULL,
    external_thread_id TEXT,
    provider TEXT,
    assigned_to TEXT,
    resolved_at TEXT,
    reopened_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, case_id)
);

CREATE TABLE IF NOT EXISTS support_message (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    direction TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_message_id TEXT,
    external_thread_id TEXT,
    contact TEXT,
    subject TEXT,
    body TEXT NOT NULL,
    delivery_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    rfc_message_id TEXT
);

CREATE TABLE IF NOT EXISTS webhook_event (
    event_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    processed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery_job (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    job_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    run_after TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS human_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    predicted_json TEXT NOT NULL,
    corrected_json TEXT NOT NULL,
    response_accepted INTEGER,
    response_edited INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_principal (
    token_hash TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_sequence (
    name TEXT PRIMARY KEY,
    next_value INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_policy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_url TEXT,
    version TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_note (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    body TEXT NOT NULL,
    mentions_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proof_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS team_member (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    teams_json TEXT NOT NULL,
    capacity INTEGER NOT NULL,
    availability TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS usage_counter (
    key TEXT PRIMARY KEY,
    count INTEGER NOT NULL
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_memory_customer ON customer_memory(customer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_log(tenant_id, case_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_tenant_time ON audit_log(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ticket_recent ON support_ticket(tenant_id, last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_lifecycle_tenant_state
ON case_lifecycle(tenant_id, state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_message_case ON support_message(tenant_id, case_id, created_at ASC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_message_provider_id
ON support_message(provider, provider_message_id)
WHERE provider_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_message_rfc_id ON support_message(tenant_id, rfc_message_id)
WHERE rfc_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_job_ready ON delivery_job(status, run_after, id);
CREATE INDEX IF NOT EXISTS idx_feedback_case ON human_feedback(case_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_policy_tenant_active
ON knowledge_policy(tenant_id, active, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_case_note_case
ON case_note(tenant_id, case_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_proof_run_tenant
ON proof_run(tenant_id, created_at DESC);
"""

# Kept for callers that referenced the previous single schema constant.
SCHEMA = TABLES + INDEXES

# Lifecycle states in which a customer is still waiting for a first/next reply.
AWAITING_REPLY_STATES = {"new", "triaged", "review_required", "replied", "reopened", "failed"}


def _now() -> datetime:
    return datetime.now(UTC)


def _minutes_since(value: str | None, now: datetime) -> int:
    if not value:
        return 0
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return 0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0, int((now - moment).total_seconds() // 60))


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._active_connection: ContextVar[sqlite3.Connection | None] = ContextVar(
            f"database_connection_{id(self)}", default=None
        )

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            # WAL lets the API read while the worker writes; the connection
            # timeout doubles as SQLite's busy timeout.
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(TABLES)
            self._ensure_column(connection, "customer_memory", "tenant_id", "TEXT NOT NULL DEFAULT 'tenant-demo'")
            self._ensure_column(connection, "audit_log", "tenant_id", "TEXT NOT NULL DEFAULT 'tenant-demo'")
            self._ensure_column(connection, "support_ticket", "tenant_id", "TEXT NOT NULL DEFAULT 'tenant-demo'")
            self._ensure_column(connection, "support_ticket", "last_message_at", "TEXT")
            self._ensure_column(connection, "support_message", "contact", "TEXT")
            self._ensure_column(connection, "support_message", "rfc_message_id", "TEXT")
            self._ensure_column(connection, "proof_run", "updated_at", "TEXT")
            connection.execute("DROP INDEX IF EXISTS idx_ticket_received")
            self._ensure_tenant_primary_key(connection, "support_ticket")
            self._ensure_tenant_primary_key(connection, "case_lifecycle")
            connection.execute(
                "UPDATE support_ticket SET last_message_at = created_at WHERE last_message_at IS NULL"
            )
            connection.executescript(INDEXES)
            connection.execute(
                "DELETE FROM customer_memory WHERE id NOT IN ("
                "SELECT MAX(id) FROM customer_memory GROUP BY tenant_id, customer_id, case_id)"
            )
            connection.execute("DROP INDEX IF EXISTS idx_memory_customer_case")
            connection.execute(
                "CREATE UNIQUE INDEX idx_memory_customer_case "
                "ON customer_memory(tenant_id, customer_id, case_id)"
            )
            self._backfill_automation_records(connection)
            # A proof run cannot survive a process restart; surface it instead of
            # leaving it "running" forever.
            connection.execute(
                "UPDATE proof_run SET status = 'interrupted', updated_at = ? WHERE status = 'running'",
                (_now().isoformat(),),
            )

    @staticmethod
    def _ensure_tenant_primary_key(connection: sqlite3.Connection, table: str) -> None:
        """Rebuild legacy tables whose primary key was case_id alone."""
        columns = list(connection.execute(f"PRAGMA table_info({table})"))
        key = [row["name"] for row in sorted(columns, key=lambda row: row["pk"]) if row["pk"]]
        if key == ["tenant_id", "case_id"]:
            return
        names = [row["name"] for row in columns]
        legacy = f"{table}_legacy"
        connection.execute(f"ALTER TABLE {table} RENAME TO {legacy}")
        definition = TABLES.split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)[1].split(");", 1)[0]
        connection.execute(f"CREATE TABLE {table} ({definition})")
        new_names = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        shared = ", ".join(name for name in names if name in new_names)
        connection.execute(
            f"INSERT OR REPLACE INTO {table} ({shared}) SELECT {shared} FROM {legacy}"
        )
        connection.execute(f"DROP TABLE {legacy}")

    @staticmethod
    def _backfill_automation_records(connection: sqlite3.Connection) -> None:
        """Give legacy tickets a safe persisted policy result instead of client inference."""
        rows = connection.execute(
            "SELECT case_id, tenant_id, triage_json FROM support_ticket"
        ).fetchall()
        for row in rows:
            triage = json.loads(row["triage_json"])
            if recorded_automation_decision(triage.get("automation")).code != "not_evaluated":
                continue
            audit = connection.execute(
                "SELECT decision_json FROM audit_log "
                "WHERE tenant_id = ? AND case_id = ? AND event_type = 'triage' "
                "ORDER BY created_at DESC LIMIT 1",
                (row["tenant_id"], row["case_id"]),
            ).fetchone()
            record = NOT_EVALUATED
            if audit:
                record = recorded_automation_decision(
                    json.loads(audit["decision_json"]).get("automation")
                )
            triage["automation"] = record.as_dict()
            connection.execute(
                "UPDATE support_ticket SET triage_json = ? "
                "WHERE case_id = ? AND tenant_id = ?",
                (json.dumps(triage), row["case_id"], row["tenant_id"]),
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _open(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        active = self._active_connection.get()
        if active is not None:
            yield active
            return
        connection = self._open()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Share one atomic SQLite transaction across repository operations."""
        active = self._active_connection.get()
        if active is not None:
            yield active
            return
        connection = self._open()
        token = self._active_connection.set(connection)
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._active_connection.reset(token)
            connection.close()

    def memories_for(
        self, customer_id: str, limit: int = 5, tenant_id: str = "tenant-demo"
    ) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT case_id, summary, entities_json, created_at FROM customer_memory "
                "WHERE tenant_id = ? AND customer_id = ? ORDER BY created_at DESC LIMIT ?",
                (tenant_id, customer_id, limit),
            ).fetchall()
        return [
            {
                "case_id": row["case_id"],
                "summary": row["summary"],
                "entities": json.loads(row["entities_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def add_memory(
        self,
        customer_id: str,
        case_id: str,
        summary: str,
        entities: dict,
        created_at: str | None = None,
        tenant_id: str = "tenant-demo",
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO customer_memory (customer_id, case_id, summary, entities_json, created_at, tenant_id) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(tenant_id, customer_id, case_id) DO UPDATE SET "
                "summary = excluded.summary, entities_json = excluded.entities_json, "
                "created_at = excluded.created_at",
                (customer_id, case_id, summary, json.dumps(entities), created_at or _now().isoformat(), tenant_id),
            )

    def add_audit(
        self,
        *,
        case_id: str,
        customer_id: str,
        event_type: str,
        model: str | None,
        request: dict,
        decision: dict,
        guardrails: dict,
        actor: str | None = None,
        created_at: str | None = None,
        tenant_id: str = "tenant-demo",
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO audit_log "
                "(case_id, customer_id, event_type, model, request_json, decision_json, guardrail_json, actor, created_at, tenant_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    case_id,
                    customer_id,
                    event_type,
                    model,
                    json.dumps(request),
                    json.dumps(decision),
                    json.dumps(guardrails),
                    actor,
                    created_at or _now().isoformat(),
                    tenant_id,
                ),
            )
            return int(cursor.lastrowid)

    def audits(self, limit: int = 100, tenant_id: str = "tenant-demo") -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_log WHERE tenant_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (tenant_id, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "case_id": row["case_id"],
                "customer_id": row["customer_id"],
                "event_type": row["event_type"],
                "model": row["model"],
                "decision": json.loads(row["decision_json"]),
                "guardrails": json.loads(row["guardrail_json"]),
                "actor": row["actor"],
                "created_at": row["created_at"],
                "tenant_id": row["tenant_id"],
            }
            for row in rows
        ]

    def latest_triage_for_case(
        self, case_id: str, tenant_id: str = "tenant-demo"
    ) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, customer_id, decision_json, guardrail_json FROM audit_log "
                "WHERE tenant_id = ? AND case_id = ? AND event_type IN ('triage', 'manual_triage') "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (tenant_id, case_id),
            ).fetchone()
        if not row:
            return None
        return {
            "audit_id": row["id"],
            "customer_id": row["customer_id"],
            "decision": json.loads(row["decision_json"]),
            "guardrails": json.loads(row["guardrail_json"]),
        }

    def audit_event_exists(
        self, case_id: str, event_type: str, tenant_id: str = "tenant-demo"
    ) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM audit_log WHERE tenant_id = ? AND case_id = ? AND event_type = ? LIMIT 1",
                (tenant_id, case_id, event_type),
            ).fetchone()
        return row is not None

    def add_support_ticket(self, ticket: dict, tenant_id: str = "tenant-demo") -> None:
        last_message_at = ticket.get("lastMessageAt") or ticket["createdAt"]
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO support_ticket "
                "(case_id, customer_id, customer_json, channel, subject, message, received_at, "
                "minutes_ago, truth_intent, truth_urgency, triage_json, created_at, tenant_id, last_message_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(tenant_id, case_id) DO UPDATE SET "
                "customer_json = excluded.customer_json, channel = excluded.channel, "
                "subject = excluded.subject, message = excluded.message, "
                "received_at = excluded.received_at, minutes_ago = excluded.minutes_ago, "
                "truth_intent = excluded.truth_intent, truth_urgency = excluded.truth_urgency, "
                "last_message_at = excluded.last_message_at",
                (
                    ticket["id"],
                    ticket["customerId"],
                    json.dumps(ticket["customer"]),
                    ticket["channel"],
                    ticket.get("subject"),
                    ticket["message"],
                    ticket["receivedAt"],
                    ticket.get("minutesAgo", 0),
                    ticket["truthIntent"],
                    ticket["truthUrgency"],
                    json.dumps(ticket["triage"]),
                    ticket["createdAt"],
                    tenant_id,
                    last_message_at,
                ),
            )

    def update_support_ticket_triage(
        self, case_id: str, triage: dict, tenant_id: str = "tenant-demo"
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE support_ticket SET triage_json = ? WHERE case_id = ? AND tenant_id = ?",
                (json.dumps(triage), case_id, tenant_id),
            )

    def update_support_ticket_fields(
        self, case_id: str, updates: dict, tenant_id: str = "tenant-demo"
    ) -> None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT triage_json FROM support_ticket WHERE case_id = ? AND tenant_id = ?",
                (case_id, tenant_id),
            ).fetchone()
            if not row:
                return
            triage = json.loads(row["triage_json"])
            triage.update(updates)
            connection.execute(
                "UPDATE support_ticket SET triage_json = ? WHERE case_id = ? AND tenant_id = ?",
                (json.dumps(triage), case_id, tenant_id),
            )

    def update_support_ticket_message(
        self,
        case_id: str,
        *,
        message: str,
        subject: str | None,
        received_at: str,
        tenant_id: str = "tenant-demo",
        last_message_at: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE support_ticket SET message = ?, subject = ?, received_at = ?, minutes_ago = 0, "
                "last_message_at = ? WHERE case_id = ? AND tenant_id = ?",
                (message, subject, received_at, last_message_at or _now().isoformat(), case_id, tenant_id),
            )

    _TICKET_QUERY = (
        "SELECT t.*, l.state AS l_state, l.external_thread_id AS l_external_thread_id, "
        "l.provider AS l_provider, l.assigned_to AS l_assigned_to, l.resolved_at AS l_resolved_at, "
        "l.reopened_count AS l_reopened_count, l.updated_at AS l_updated_at "
        "FROM support_ticket t LEFT JOIN case_lifecycle l "
        "ON l.tenant_id = t.tenant_id AND l.case_id = t.case_id "
    )

    @staticmethod
    def _ticket_from_row(row: sqlite3.Row, now: datetime) -> dict:
        last_message_at = row["last_message_at"] or row["created_at"]
        ticket = {
            "id": row["case_id"],
            "customerId": row["customer_id"],
            "customer": json.loads(row["customer_json"]),
            "channel": row["channel"],
            "subject": row["subject"],
            "message": row["message"],
            "receivedAt": row["received_at"],
            # Derived from timestamps on every read so SLA age never freezes.
            "minutesAgo": _minutes_since(last_message_at, now),
            "createdAt": row["created_at"],
            "lastMessageAt": last_message_at,
            "truthIntent": row["truth_intent"],
            "truthUrgency": row["truth_urgency"],
            "tenantId": row["tenant_id"],
            **json.loads(row["triage_json"]),
        }
        if row["l_state"] is not None:
            ticket["lifecycle"] = {
                "case_id": row["case_id"],
                "tenant_id": row["tenant_id"],
                "state": row["l_state"],
                "external_thread_id": row["l_external_thread_id"],
                "provider": row["l_provider"],
                "assigned_to": row["l_assigned_to"],
                "resolved_at": row["l_resolved_at"],
                "reopened_count": row["l_reopened_count"],
                "updated_at": row["l_updated_at"],
            }
        return ticket

    def support_tickets(self, tenant_id: str = "tenant-demo") -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                self._TICKET_QUERY
                + "WHERE t.tenant_id = ? ORDER BY COALESCE(t.last_message_at, t.created_at) DESC",
                (tenant_id,),
            ).fetchall()
        now = _now()
        return [self._ticket_from_row(row, now) for row in rows]

    def support_ticket(
        self, case_id: str, tenant_id: str = "tenant-demo"
    ) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                self._TICKET_QUERY + "WHERE t.tenant_id = ? AND t.case_id = ?",
                (tenant_id, case_id),
            ).fetchone()
        return self._ticket_from_row(row, _now()) if row else None

    def next_case_id(self, tenant_id: str = "tenant-demo") -> str:
        # BEGIN IMMEDIATE serializes allocation so simultaneous webhooks cannot
        # claim the same human-readable case number. The sequence is global, so
        # case numbers are also unique across tenants.
        with self.connect() as connection:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            sequence = connection.execute(
                "SELECT next_value FROM case_sequence WHERE name = 'support_case'"
            ).fetchone()
            if sequence:
                value = int(sequence["next_value"])
                connection.execute(
                    "UPDATE case_sequence SET next_value = ? WHERE name = 'support_case'",
                    (value + 1,),
                )
            else:
                rows = connection.execute(
                    "SELECT case_id FROM support_ticket WHERE case_id LIKE 'KOR-%'"
                ).fetchall()
                numbers = [
                    int(row["case_id"].replace("KOR-", ""))
                    for row in rows
                    if row["case_id"].replace("KOR-", "").isdigit()
                ]
                value = max(numbers, default=2400) + 1
                connection.execute(
                    "INSERT INTO case_sequence (name, next_value) VALUES ('support_case', ?)",
                    (value + 1,),
                )
        return f"KOR-{value}"

    def record_webhook(
        self,
        *,
        event_id: str,
        tenant_id: str,
        provider: str,
        event_type: str,
        payload: dict,
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO webhook_event "
                "(event_id, tenant_id, provider, event_type, payload_json, processed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"{tenant_id}:{provider}:{event_id}",
                    tenant_id,
                    provider,
                    event_type,
                    json.dumps(payload),
                    _now().isoformat(),
                ),
            )
            return cursor.rowcount == 1

    def add_message(
        self,
        *,
        message_id: str,
        case_id: str,
        tenant_id: str,
        customer_id: str,
        channel: str,
        direction: str,
        provider: str,
        body: str,
        subject: str | None = None,
        provider_message_id: str | None = None,
        external_thread_id: str | None = None,
        contact: str | None = None,
        delivery_status: str = "received",
        created_at: str | None = None,
        rfc_message_id: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO support_message "
                "(id, case_id, tenant_id, customer_id, channel, direction, provider, "
                "provider_message_id, external_thread_id, contact, subject, body, delivery_status, "
                "created_at, rfc_message_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    case_id,
                    tenant_id,
                    customer_id,
                    channel,
                    direction,
                    provider,
                    provider_message_id,
                    external_thread_id,
                    contact,
                    subject,
                    body,
                    delivery_status,
                    created_at or _now().isoformat(),
                    rfc_message_id,
                ),
            )

    def message(self, message_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM support_message WHERE id = ?", (message_id,)
            ).fetchone()
        return dict(row) if row else None

    def conversation(self, case_id: str, tenant_id: str = "tenant-demo") -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM support_message WHERE tenant_id = ? AND case_id = ? "
                "ORDER BY created_at ASC, rowid ASC",
                (tenant_id, case_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_inbound_message(
        self, case_id: str, tenant_id: str = "tenant-demo"
    ) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM support_message WHERE tenant_id = ? AND case_id = ? "
                "AND direction = 'inbound' ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (tenant_id, case_id),
            ).fetchone()
        return dict(row) if row else None

    def find_case_by_thread(
        self, external_thread_id: str, tenant_id: str, *,
        customer_id: str, channel: str, provider: str,
    ) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT c.case_id FROM case_lifecycle c JOIN support_ticket t "
                "ON t.case_id = c.case_id AND t.tenant_id = c.tenant_id "
                "WHERE c.tenant_id = ? AND c.external_thread_id = ? "
                "AND t.customer_id = ? AND t.channel = ? AND c.provider = ? "
                "ORDER BY c.updated_at DESC LIMIT 1",
                (tenant_id, external_thread_id, customer_id, channel, provider),
            ).fetchone()
        return row["case_id"] if row else None

    def find_case_by_message_reference(
        self, references: str | Iterable[str], tenant_id: str, *,
        customer_id: str, channel: str, provider: str,
    ) -> str | None:
        """Resolve an email reply from any inbound or outbound message reference.

        Accepts provider IDs, RFC Message-IDs and thread IDs, since mail clients
        quote whichever header they received.
        """
        candidates = [references] if isinstance(references, str) else list(references)
        candidates = [value for value in dict.fromkeys(candidates) if value]
        if not candidates:
            return None
        marks = ", ".join("?" for _ in candidates)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT m.case_id FROM support_message m JOIN support_ticket t "
                "ON t.case_id = m.case_id AND t.tenant_id = m.tenant_id "
                "WHERE m.tenant_id = ? "
                f"AND (m.provider_message_id IN ({marks}) OR m.external_thread_id IN ({marks}) "
                f"OR m.rfc_message_id IN ({marks})) "
                "AND t.customer_id = ? AND t.channel = ? AND m.provider = ? "
                "ORDER BY m.created_at DESC LIMIT 1",
                (tenant_id, *candidates, *candidates, *candidates, customer_id, channel, provider),
            ).fetchone()
        return row["case_id"] if row else None

    def set_lifecycle(
        self,
        case_id: str,
        state: str,
        *,
        tenant_id: str = "tenant-demo",
        external_thread_id: str | None = None,
        provider: str | None = None,
        assigned_to: str | None = None,
    ) -> dict:
        now = _now().isoformat()
        resolved_at = now if state == "resolved" else None
        with self.connect() as connection:
            previous = connection.execute(
                "SELECT * FROM case_lifecycle WHERE case_id = ? AND tenant_id = ?",
                (case_id, tenant_id),
            ).fetchone()
            reopened = int(previous["reopened_count"]) if previous else 0
            if state == "reopened" and previous and previous["state"] == "resolved":
                reopened += 1
            connection.execute(
                "INSERT INTO case_lifecycle "
                "(case_id, tenant_id, state, external_thread_id, provider, assigned_to, resolved_at, reopened_count, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(tenant_id, case_id) DO UPDATE SET "
                "state = excluded.state, external_thread_id = COALESCE(excluded.external_thread_id, case_lifecycle.external_thread_id), "
                "provider = COALESCE(excluded.provider, case_lifecycle.provider), "
                "assigned_to = COALESCE(excluded.assigned_to, case_lifecycle.assigned_to), "
                "resolved_at = excluded.resolved_at, reopened_count = excluded.reopened_count, "
                "updated_at = excluded.updated_at",
                (
                    case_id,
                    tenant_id,
                    state,
                    external_thread_id,
                    provider,
                    assigned_to,
                    resolved_at,
                    reopened,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM case_lifecycle WHERE case_id = ? AND tenant_id = ?",
                (case_id, tenant_id),
            ).fetchone()
        return dict(row)

    def lifecycle(self, case_id: str, tenant_id: str = "tenant-demo") -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM case_lifecycle WHERE case_id = ? AND tenant_id = ?",
                (case_id, tenant_id),
            ).fetchone()
        return dict(row) if row else None

    def enqueue_job(
        self,
        *,
        tenant_id: str,
        job_type: str,
        idempotency_key: str,
        payload: dict,
        max_attempts: int = 5,
    ) -> int:
        now = _now().isoformat()
        stored_key = f"{tenant_id}:{idempotency_key}"
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO delivery_job "
                "(tenant_id, job_type, idempotency_key, payload_json, status, attempts, "
                "max_attempts, run_after, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?)",
                (
                    tenant_id,
                    job_type,
                    stored_key,
                    json.dumps(payload),
                    max_attempts,
                    now,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT id FROM delivery_job WHERE idempotency_key = ?", (stored_key,)
            ).fetchone()
        return int(row["id"])

    def claim_job(
        self, tenant_id: str | None = None, lease_seconds: int = 300
    ) -> dict | None:
        now = _now()
        stale_before = (now - timedelta(seconds=lease_seconds)).isoformat()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM delivery_job WHERE "
                "((status IN ('queued', 'retry') AND run_after <= ?) "
                # A "running" job whose lease expired was orphaned by a restart.
                " OR (status = 'running' AND updated_at <= ?)) "
                "AND (? IS NULL OR tenant_id = ?) ORDER BY id ASC LIMIT 1",
                (now.isoformat(), stale_before, tenant_id, tenant_id),
            ).fetchone()
            if not row:
                return None
            cursor = connection.execute(
                "UPDATE delivery_job SET status = 'running', attempts = attempts + 1, updated_at = ? "
                "WHERE id = ? AND status = ? AND updated_at = ?",
                (now.isoformat(), row["id"], row["status"], row["updated_at"]),
            )
            if cursor.rowcount != 1:
                return None
            claimed = connection.execute(
                "SELECT * FROM delivery_job WHERE id = ?", (row["id"],)
            ).fetchone()
        item = dict(claimed)
        item["payload"] = json.loads(item.pop("payload_json"))
        return item

    def finish_job(self, job_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE delivery_job SET status = 'succeeded', updated_at = ? WHERE id = ?",
                (_now().isoformat(), job_id),
            )

    def cancel_job(self, job_id: int, reason: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE delivery_job SET status = 'cancelled', last_error = ?, updated_at = ? WHERE id = ?",
                (reason[:1000], _now().isoformat(), job_id),
            )

    def fail_job(self, job_id: int, error: str) -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT attempts, max_attempts FROM delivery_job WHERE id = ?", (job_id,)
            ).fetchone()
            dead = int(row["attempts"]) >= int(row["max_attempts"])
            status = "dead" if dead else "retry"
            delay = min(300, 2 ** int(row["attempts"]))
            run_after = (_now() + timedelta(seconds=delay)).isoformat()
            connection.execute(
                "UPDATE delivery_job SET status = ?, run_after = ?, last_error = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    status,
                    run_after,
                    error[:1000],
                    _now().isoformat(),
                    job_id,
                ),
            )
        return status

    def jobs(self, tenant_id: str = "tenant-demo", limit: int = 100) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, tenant_id, job_type, idempotency_key, status, attempts, max_attempts, "
                "run_after, last_error, created_at, updated_at FROM delivery_job "
                "WHERE tenant_id = ? ORDER BY id DESC LIMIT ?",
                (tenant_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def job_counts(self, tenant_id: str = "tenant-demo") -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM delivery_job WHERE tenant_id = ? GROUP BY status",
                (tenant_id,),
            ).fetchall()
        counts = {row["status"]: row["count"] for row in rows}
        return {
            status: int(counts.get(status, 0))
            for status in ("queued", "running", "retry", "succeeded", "dead", "cancelled")
        }

    def pending_send_jobs(self, case_id: str, tenant_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, payload_json FROM delivery_job WHERE tenant_id = ? "
                "AND job_type = 'send_response' AND status IN ('queued', 'retry', 'running')",
                (tenant_id,),
            ).fetchall()
        return [
            {"id": row["id"], **json.loads(row["payload_json"])}
            for row in rows
            if json.loads(row["payload_json"]).get("case_id") == case_id
        ]

    def update_message_delivery(
        self, provider_message_id: str, status: str, tenant_id: str | None, *, provider: str,
    ) -> tuple[str, str] | None:
        """Apply a provider receipt; returns (case_id, tenant_id) when it changed state.

        ``tenant_id`` may be None when the receiving webhook cannot know the
        tenant; the provider message ID is globally unique per provider.
        """
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, case_id, tenant_id, delivery_status FROM support_message "
                "WHERE provider_message_id = ? AND provider = ? AND direction = 'outbound' "
                "AND (? IS NULL OR tenant_id = ?)",
                (provider_message_id, provider, tenant_id, tenant_id),
            ).fetchone()
            if row:
                # Providers can retry or deliver callbacks out of order.
                progress = {"sent": 1, "delivered": 2, "read": 3}
                previous = row["delivery_status"]
                if (
                    previous == status
                    or (previous == "failed" and status == "sent")
                    or (
                        previous in progress and status in progress
                        and progress[status] < progress[previous]
                    )
                ):
                    return None
                connection.execute(
                    "UPDATE support_message SET delivery_status = ? WHERE id = ?",
                    (status, row["id"]),
                )
        return (row["case_id"], row["tenant_id"]) if row else None

    def add_feedback(
        self,
        *,
        case_id: str,
        customer_id: str,
        actor: str,
        predicted: dict,
        corrected: dict,
        response_accepted: bool | None,
        response_edited: bool,
        reason: str | None,
        tenant_id: str = "tenant-demo",
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO human_feedback "
                "(case_id, tenant_id, customer_id, actor, predicted_json, corrected_json, "
                "response_accepted, response_edited, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    case_id,
                    tenant_id,
                    customer_id,
                    actor,
                    json.dumps(predicted),
                    json.dumps(corrected),
                    None if response_accepted is None else int(response_accepted),
                    int(response_edited),
                    reason,
                    _now().isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def feedback(self, tenant_id: str = "tenant-demo", limit: int = 500) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM human_feedback WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
                (tenant_id, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["predicted"] = json.loads(item.pop("predicted_json"))
            item["corrected"] = json.loads(item.pop("corrected_json"))
            items.append(item)
        return items

    def add_principal(
        self,
        *,
        token_hash: str,
        tenant_id: str,
        user_id: str,
        display_name: str,
        role: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO api_principal "
                "(token_hash, tenant_id, user_id, display_name, role, active, created_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?)",
                (token_hash, tenant_id, user_id, display_name, role, _now().isoformat()),
            )

    def deactivate_principals(self, *, tenant_id: str, user_id: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE api_principal SET active = 0 WHERE tenant_id = ? AND user_id = ? AND active = 1",
                (tenant_id, user_id),
            )
            return cursor.rowcount

    def principals(self, tenant_id: str | None = None) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT tenant_id, user_id, display_name, role, active, created_at FROM api_principal "
                "WHERE (? IS NULL OR tenant_id = ?) ORDER BY tenant_id, user_id, created_at",
                (tenant_id, tenant_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def principal_for_hash(self, token_hash: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT tenant_id, user_id, display_name, role FROM api_principal "
                "WHERE token_hash = ? AND active = 1",
                (token_hash,),
            ).fetchone()
        return dict(row) if row else None

    def get_setting(
        self, key: str, default: dict, tenant_id: str | None = None
    ) -> dict:
        stored_key = f"{tenant_id}:{key}" if tenant_id else key
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM app_setting WHERE key = ?", (stored_key,)
            ).fetchone()
            if not row and tenant_id == "tenant-demo":
                row = connection.execute(
                    "SELECT value_json FROM app_setting WHERE key = ?", (key,)
                ).fetchone()
        return {**default, **json.loads(row["value_json"])} if row else dict(default)

    def set_setting(
        self, key: str, value: dict, tenant_id: str | None = None
    ) -> dict:
        stored_key = f"{tenant_id}:{key}" if tenant_id else key
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO app_setting (key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (stored_key, json.dumps(value), _now().isoformat()),
            )
        return value

    def consume_quota(self, key: str, limit: int) -> bool:
        """Atomically count one use of ``key``; False once ``limit`` is reached."""
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT count FROM usage_counter WHERE key = ?", (key,)
            ).fetchone()
            used = int(row["count"]) if row else 0
            if used >= limit:
                return False
            connection.execute(
                "INSERT INTO usage_counter (key, count) VALUES (?, 1) "
                "ON CONFLICT(key) DO UPDATE SET count = count + 1",
                (key,),
            )
        return True

    def add_policy(
        self,
        *,
        tenant_id: str,
        title: str,
        content: str,
        source_url: str | None,
        version: str,
    ) -> dict:
        now = _now().isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO knowledge_policy "
                "(tenant_id, title, content, source_url, version, active, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (tenant_id, title, content, source_url, version, now, now),
            )
            policy_id = int(cursor.lastrowid)
        return self.policy(policy_id, tenant_id)

    def policy(self, policy_id: int, tenant_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_policy WHERE id = ? AND tenant_id = ?",
                (policy_id, tenant_id),
            ).fetchone()
        return dict(row) if row else None

    def policies(self, tenant_id: str, active_only: bool = False) -> list[dict]:
        query = "SELECT * FROM knowledge_policy WHERE tenant_id = ?"
        values: list[object] = [tenant_id]
        if active_only:
            query += " AND active = 1"
        query += " ORDER BY updated_at DESC, id DESC"
        with self.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [dict(row) for row in rows]

    def set_policy_active(
        self, policy_id: int, active: bool, tenant_id: str
    ) -> dict | None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE knowledge_policy SET active = ?, updated_at = ? "
                "WHERE id = ? AND tenant_id = ?",
                (int(active), _now().isoformat(), policy_id, tenant_id),
            )
        return self.policy(policy_id, tenant_id)

    def claim_case(
        self,
        case_id: str,
        *,
        tenant_id: str,
        assignee: str | None,
        expected_assignee: str | None = None,
    ) -> dict:
        now = _now().isoformat()
        with self.connect() as connection:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT assigned_to FROM case_lifecycle "
                "WHERE case_id = ? AND tenant_id = ?",
                (case_id, tenant_id),
            ).fetchone()
            if not row:
                raise ValueError("Case lifecycle does not exist")
            current = row["assigned_to"]
            if expected_assignee == "__unassigned__":
                if current is not None:
                    raise RuntimeError(current)
            elif expected_assignee is not None and current != expected_assignee:
                raise RuntimeError(current or "unassigned")
            connection.execute(
                "UPDATE case_lifecycle SET assigned_to = ?, updated_at = ? "
                "WHERE case_id = ? AND tenant_id = ?",
                (assignee, now, case_id, tenant_id),
            )
        return self.lifecycle(case_id, tenant_id) or {}

    def add_case_note(
        self,
        *,
        case_id: str,
        tenant_id: str,
        actor: str,
        body: str,
        mentions: list[str],
    ) -> dict:
        now = _now().isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO case_note "
                "(tenant_id, case_id, actor, body, mentions_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (tenant_id, case_id, actor, body, json.dumps(mentions), now),
            )
            note_id = int(cursor.lastrowid)
            row = connection.execute(
                "SELECT * FROM case_note WHERE id = ?", (note_id,)
            ).fetchone()
        item = dict(row)
        item["mentions"] = json.loads(item.pop("mentions_json"))
        return item

    def case_notes(self, case_id: str, tenant_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM case_note WHERE tenant_id = ? AND case_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (tenant_id, case_id),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["mentions"] = json.loads(item.pop("mentions_json"))
            items.append(item)
        return items

    @staticmethod
    def _proof_run(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "name": row["name"],
            "status": row["status"],
            "report": json.loads(row["report_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"] or row["created_at"],
        }

    def add_proof_run(
        self, *, tenant_id: str, name: str, status: str, report: dict
    ) -> dict:
        now = _now().isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO proof_run (tenant_id, name, status, report_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (tenant_id, name, status, json.dumps(report), now, now),
            )
            run_id = int(cursor.lastrowid)
        return self.proof_run(run_id, tenant_id)

    def update_proof_run(
        self, run_id: int, tenant_id: str, *, status: str, report: dict
    ) -> dict | None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE proof_run SET status = ?, report_json = ?, updated_at = ? "
                "WHERE id = ? AND tenant_id = ?",
                (status, json.dumps(report), _now().isoformat(), run_id, tenant_id),
            )
        return self.proof_run(run_id, tenant_id)

    def proof_run(self, run_id: int, tenant_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM proof_run WHERE id = ? AND tenant_id = ?", (run_id, tenant_id)
            ).fetchone()
        return self._proof_run(row) if row else None

    def proof_runs(self, tenant_id: str, limit: int = 20) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM proof_run WHERE tenant_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (tenant_id, limit),
            ).fetchall()
        return [self._proof_run(row) for row in rows]

    @staticmethod
    def _team_member(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "role": row["role"],
            "teams": json.loads(row["teams_json"]),
            "capacity": row["capacity"],
            "availability": row["availability"],
            "updated_at": row["updated_at"],
        }

    def upsert_team_member(
        self,
        *,
        tenant_id: str,
        name: str,
        role: str,
        teams: list[str],
        capacity: int,
        availability: str = "Online",
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO team_member (tenant_id, name, role, teams_json, capacity, availability, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(tenant_id, name) DO UPDATE SET "
                "role = excluded.role, teams_json = excluded.teams_json, capacity = excluded.capacity",
                (tenant_id, name, role, json.dumps(teams), capacity, availability, _now().isoformat()),
            )

    def team_members(self, tenant_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM team_member WHERE tenant_id = ? ORDER BY name", (tenant_id,)
            ).fetchall()
        return [self._team_member(row) for row in rows]

    def set_team_availability(
        self, member_id: int, availability: str, tenant_id: str
    ) -> dict | None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE team_member SET availability = ?, updated_at = ? WHERE id = ? AND tenant_id = ?",
                (availability, _now().isoformat(), member_id, tenant_id),
            )
            row = connection.execute(
                "SELECT * FROM team_member WHERE id = ? AND tenant_id = ?", (member_id, tenant_id)
            ).fetchone()
        return self._team_member(row) if row else None
