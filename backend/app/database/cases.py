"""Support tickets, case lifecycle, assignment and internal notes."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from .clock import minutes_since, utc_now
from .connection import SQLiteStore


class CaseRepository(SQLiteStore):
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
                (message, subject, received_at, last_message_at or utc_now().isoformat(), case_id, tenant_id),
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
            "minutesAgo": minutes_since(last_message_at, now),
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
        now = utc_now()
        return [self._ticket_from_row(row, now) for row in rows]

    def support_ticket(
        self, case_id: str, tenant_id: str = "tenant-demo"
    ) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                self._TICKET_QUERY + "WHERE t.tenant_id = ? AND t.case_id = ?",
                (tenant_id, case_id),
            ).fetchone()
        return self._ticket_from_row(row, utc_now()) if row else None

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
        now = utc_now().isoformat()
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

    def claim_case(
        self,
        case_id: str,
        *,
        tenant_id: str,
        assignee: str | None,
        expected_assignee: str | None = None,
    ) -> dict:
        now = utc_now().isoformat()
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
        now = utc_now().isoformat()
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
