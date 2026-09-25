"""Audit log, customer memory and reviewer feedback."""

from __future__ import annotations

import json

from .clock import utc_now
from .connection import SQLiteStore


class AuditRepository(SQLiteStore):
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
                (customer_id, case_id, summary, json.dumps(entities), created_at or utc_now().isoformat(), tenant_id),
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
                    created_at or utc_now().isoformat(),
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
                    utc_now().isoformat(),
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
