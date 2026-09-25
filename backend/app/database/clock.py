"""Time helpers shared by the repositories."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def minutes_since(value: str | None, now: datetime) -> int:
    if not value:
        return 0
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return 0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0, int((now - moment).total_seconds() // 60))
