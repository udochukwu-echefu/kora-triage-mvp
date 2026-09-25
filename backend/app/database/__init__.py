from __future__ import annotations

import json
import sqlite3

from .audit import AuditRepository
from .cases import CaseRepository
from .clock import utc_now
from .jobs import JobRepository
from .messages import MessageRepository
from .migrations import SchemaMigrations

__all__ = ["Database"]


class Database(SchemaMigrations, AuditRepository, CaseRepository, MessageRepository, JobRepository):
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
