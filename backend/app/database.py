from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    entities_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_customer ON customer_memory(customer_id, created_at DESC);
DELETE FROM customer_memory
WHERE id NOT IN (
    SELECT MAX(id) FROM customer_memory GROUP BY customer_id, case_id
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_customer_case
ON customer_memory(customer_id, case_id);

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
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_log(case_id, created_at DESC);

CREATE TABLE IF NOT EXISTS support_ticket (
    case_id TEXT PRIMARY KEY,
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
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ticket_received ON support_ticket(minutes_ago ASC);

CREATE TABLE IF NOT EXISTS app_setting (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def memories_for(self, customer_id: str, limit: int = 5) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT case_id, summary, entities_json, created_at FROM customer_memory "
                "WHERE customer_id = ? ORDER BY created_at DESC LIMIT ?",
                (customer_id, limit),
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
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO customer_memory (customer_id, case_id, summary, entities_json, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(customer_id, case_id) DO UPDATE SET "
                "summary = excluded.summary, entities_json = excluded.entities_json, "
                "created_at = excluded.created_at",
                (customer_id, case_id, summary, json.dumps(entities), created_at or datetime.now(UTC).isoformat()),
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
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO audit_log "
                "(case_id, customer_id, event_type, model, request_json, decision_json, guardrail_json, actor, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    case_id,
                    customer_id,
                    event_type,
                    model,
                    json.dumps(request),
                    json.dumps(decision),
                    json.dumps(guardrails),
                    actor,
                    created_at or datetime.now(UTC).isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def audits(self, limit: int = 100) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
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
            }
            for row in rows
        ]

    def latest_triage_for_case(self, case_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT customer_id, decision_json, guardrail_json FROM audit_log "
                "WHERE case_id = ? AND event_type = 'triage' ORDER BY created_at DESC LIMIT 1",
                (case_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "customer_id": row["customer_id"],
            "decision": json.loads(row["decision_json"]),
            "guardrails": json.loads(row["guardrail_json"]),
        }

    def audit_event_exists(self, case_id: str, event_type: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM audit_log WHERE case_id = ? AND event_type = ? LIMIT 1",
                (case_id, event_type),
            ).fetchone()
        return row is not None

    def add_support_ticket(self, ticket: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO support_ticket "
                "(case_id, customer_id, customer_json, channel, subject, message, received_at, "
                "minutes_ago, truth_intent, truth_urgency, triage_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(case_id) DO UPDATE SET "
                "customer_json = excluded.customer_json, channel = excluded.channel, "
                "subject = excluded.subject, message = excluded.message, "
                "received_at = excluded.received_at, minutes_ago = excluded.minutes_ago, "
                "truth_intent = excluded.truth_intent, truth_urgency = excluded.truth_urgency",
                (
                    ticket["id"],
                    ticket["customerId"],
                    json.dumps(ticket["customer"]),
                    ticket["channel"],
                    ticket.get("subject"),
                    ticket["message"],
                    ticket["receivedAt"],
                    ticket["minutesAgo"],
                    ticket["truthIntent"],
                    ticket["truthUrgency"],
                    json.dumps(ticket["triage"]),
                    ticket["createdAt"],
                ),
            )

    def update_support_ticket_triage(self, case_id: str, triage: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE support_ticket SET triage_json = ? WHERE case_id = ?",
                (json.dumps(triage), case_id),
            )

    def update_support_ticket_fields(self, case_id: str, updates: dict) -> None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT triage_json FROM support_ticket WHERE case_id = ?", (case_id,)
            ).fetchone()
            if not row:
                return
            triage = json.loads(row["triage_json"])
            triage.update(updates)
            connection.execute(
                "UPDATE support_ticket SET triage_json = ? WHERE case_id = ?",
                (json.dumps(triage), case_id),
            )

    def support_tickets(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM support_ticket ORDER BY minutes_ago ASC"
            ).fetchall()
        return [
            {
                "id": row["case_id"],
                "customerId": row["customer_id"],
                "customer": json.loads(row["customer_json"]),
                "channel": row["channel"],
                "subject": row["subject"],
                "message": row["message"],
                "receivedAt": row["received_at"],
                "minutesAgo": row["minutes_ago"],
                "truthIntent": row["truth_intent"],
                "truthUrgency": row["truth_urgency"],
                **json.loads(row["triage_json"]),
            }
            for row in rows
        ]

    def get_setting(self, key: str, default: dict) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM app_setting WHERE key = ?", (key,)
            ).fetchone()
        return json.loads(row["value_json"]) if row else default

    def set_setting(self, key: str, value: dict) -> dict:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO app_setting (key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
                "updated_at = excluded.updated_at",
                (key, json.dumps(value), datetime.now(UTC).isoformat()),
            )
        return value
