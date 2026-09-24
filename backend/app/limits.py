"""In-process request limits.

Kora runs as a single replica (SQLite), so an in-memory sliding window is
enough to stop one client from exhausting the model quota or flooding writes.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from .config import Settings


class SlidingWindowLimiter:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: float = 60) -> None:
        if limit <= 0:
            return
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = max(1, int(window_seconds - (now - hits[0])) + 1)
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please wait a moment and try again.",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def client_key(request: Request, settings: Settings) -> str:
    """Identify the caller: bearer token if present, otherwise the client IP."""
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer ") and settings.auth_mode != "demo":
        # Hash-free prefix is enough to separate callers without storing tokens.
        return f"token:{authorization[7:19]}"
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded.strip():
            return f"ip:{forwarded.split(',')[0].strip()}"
    return f"ip:{request.client.host if request.client else 'unknown'}"
