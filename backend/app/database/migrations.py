"""Creates the schema and upgrades databases written by older versions in place."""

from __future__ import annotations

import json
import sqlite3

from ..automation import NOT_EVALUATED, recorded_automation_decision
from .clock import utc_now
from .connection import SQLiteStore
from .schema import INDEXES, TABLES


class SchemaMigrations(SQLiteStore):
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
                (utc_now().isoformat(),),
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
