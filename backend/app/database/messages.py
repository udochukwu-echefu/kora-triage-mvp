"""Inbound and outbound messages, webhook deduplication and delivery receipts."""

from __future__ import annotations

import json
from collections.abc import Iterable

from .clock import utc_now
from .connection import SQLiteStore


class MessageRepository(SQLiteStore):
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
                    utc_now().isoformat(),
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
                    created_at or utc_now().isoformat(),
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
