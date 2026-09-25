"""Leased background job queue with retries and idempotency keys."""

from __future__ import annotations

import json
from datetime import timedelta

from .clock import utc_now
from .connection import SQLiteStore


class JobRepository(SQLiteStore):
    def enqueue_job(
        self,
        *,
        tenant_id: str,
        job_type: str,
        idempotency_key: str,
        payload: dict,
        max_attempts: int = 5,
    ) -> int:
        now = utc_now().isoformat()
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
        now = utc_now()
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
                (utc_now().isoformat(), job_id),
            )

    def cancel_job(self, job_id: int, reason: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE delivery_job SET status = 'cancelled', last_error = ?, updated_at = ? WHERE id = ?",
                (reason[:1000], utc_now().isoformat(), job_id),
            )

    def fail_job(self, job_id: int, error: str) -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT attempts, max_attempts FROM delivery_job WHERE id = ?", (job_id,)
            ).fetchone()
            dead = int(row["attempts"]) >= int(row["max_attempts"])
            status = "dead" if dead else "retry"
            delay = min(300, 2 ** int(row["attempts"]))
            run_after = (utc_now() + timedelta(seconds=delay)).isoformat()
            connection.execute(
                "UPDATE delivery_job SET status = ?, run_after = ?, last_error = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    status,
                    run_after,
                    error[:1000],
                    utc_now().isoformat(),
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
