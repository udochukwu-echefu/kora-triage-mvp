from __future__ import annotations

import hashlib
from dataclasses import dataclass

from fastapi import HTTPException

from .config import Settings
from .database import Database


ROLE_LEVEL = {"support_agent": 1, "support_manager": 2, "admin": 3}


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str
    display_name: str
    role: str


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def resolve_principal(
    authorization: str | None, database: Database, settings: Settings
) -> Principal:
    if settings.auth_mode == "demo":
        return Principal(
            tenant_id=settings.default_tenant_id,
            user_id="ada-okafor",
            display_name="Ada Okafor",
            role="support_manager",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="A Kora bearer token is required.")
    record = database.principal_for_hash(token_hash(authorization.removeprefix("Bearer ").strip()))
    if not record:
        raise HTTPException(status_code=401, detail="The Kora bearer token is invalid.")
    return Principal(**record)


def require_role(principal: Principal, minimum: str) -> None:
    if ROLE_LEVEL.get(principal.role, 0) < ROLE_LEVEL[minimum]:
        raise HTTPException(status_code=403, detail="Your role cannot perform this action.")
