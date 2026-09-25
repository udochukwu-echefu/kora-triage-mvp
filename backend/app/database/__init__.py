"""SQLite persistence for Kora.

Each module holds the queries for one domain (cases, messages, jobs, audit,
workspace). ``Database`` combines them so callers keep a single object to
pass around, and ``transaction()`` can span queries from several domains.
"""

from __future__ import annotations

from .audit import AuditRepository
from .cases import CaseRepository
from .jobs import JobRepository
from .messages import MessageRepository
from .migrations import SchemaMigrations
from .workspace import WorkspaceRepository

__all__ = ["Database"]


class Database(
    SchemaMigrations,
    AuditRepository,
    CaseRepository,
    MessageRepository,
    JobRepository,
    WorkspaceRepository,
):
    """The application's store: every repository sharing one SQLite file."""
