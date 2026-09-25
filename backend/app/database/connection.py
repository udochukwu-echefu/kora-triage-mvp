"""SQLite connection handling shared by every repository.

connect() reuses the connection of an enclosing transaction(), so
repository methods called inside one commit or roll back together.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path


class SQLiteStore:
    def __init__(self, path: Path):
        self.path = path
        self._active_connection: ContextVar[sqlite3.Connection | None] = ContextVar(
            f"database_connection_{id(self)}", default=None
        )

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
