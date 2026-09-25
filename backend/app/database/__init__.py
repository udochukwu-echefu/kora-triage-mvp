from __future__ import annotations

import json
import sqlite3
from datetime import timedelta

from .audit import AuditRepository
from .cases import CaseRepository
from .clock import utc_now
from .messages import MessageRepository
from .migrations import SchemaMigrations

__all__ = ["Database"]


class Database(SchemaMigrations, AuditRepository, CaseRepository, MessageRepository):
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
                (token_hash, tenant_id, user_id, display_name, role, utc_now().isoformat()),
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
                (stored_key, json.dumps(value), utc_now().isoformat()),
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
        now = utc_now().isoformat()
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
                (int(active), utc_now().isoformat(), policy_id, tenant_id),
            )
        return self.policy(policy_id, tenant_id)


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
        now = utc_now().isoformat()
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
                (status, json.dumps(report), utc_now().isoformat(), run_id, tenant_id),
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
                (tenant_id, name, role, json.dumps(teams), capacity, availability, utc_now().isoformat()),
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
                (availability, utc_now().isoformat(), member_id, tenant_id),
            )
            row = connection.execute(
                "SELECT * FROM team_member WHERE id = ? AND tenant_id = ?", (member_id, tenant_id)
            ).fetchone()
        return self._team_member(row) if row else None
