"""Operator commands for non-demo deployments.

    python -m app.manage create-token --tenant acme --user ada --name "Ada Okafor" --role support_manager
    python -m app.manage list-tokens [--tenant acme]
    python -m app.manage revoke-tokens --tenant acme --user ada

Tokens are printed once and stored only as SHA-256 hashes.
"""

from __future__ import annotations

import argparse
import secrets
import sys

from .auth import ROLE_LEVEL, token_hash
from .config import settings
from .database import Database


def create_token(
    database: Database, *, tenant_id: str, user_id: str, display_name: str, role: str
) -> str:
    if role not in ROLE_LEVEL:
        raise ValueError(f"Role must be one of: {', '.join(ROLE_LEVEL)}")
    token = f"kora_{secrets.token_urlsafe(32)}"
    database.add_principal(
        token_hash=token_hash(token),
        tenant_id=tenant_id,
        user_id=user_id,
        display_name=display_name,
        role=role,
    )
    return token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage Kora access tokens.")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-token", help="Issue a bearer token for a user.")
    create.add_argument("--tenant", required=True)
    create.add_argument("--user", required=True)
    create.add_argument("--name", required=True, help="Display name recorded in the audit trail.")
    create.add_argument("--role", default="support_agent", choices=sorted(ROLE_LEVEL))

    listing = commands.add_parser("list-tokens", help="List issued tokens (hashes are never shown).")
    listing.add_argument("--tenant")

    revoke = commands.add_parser("revoke-tokens", help="Revoke every active token for a user.")
    revoke.add_argument("--tenant", required=True)
    revoke.add_argument("--user", required=True)

    args = parser.parse_args(argv)
    database = Database(settings.database_path)
    database.initialize()

    if args.command == "create-token":
        token = create_token(
            database,
            tenant_id=args.tenant,
            user_id=args.user,
            display_name=args.name,
            role=args.role,
        )
        print("Store this token now; it cannot be shown again:\n")
        print(token)
    elif args.command == "list-tokens":
        for item in database.principals(args.tenant):
            state = "active" if item["active"] else "revoked"
            print(f"{item['tenant_id']}\t{item['user_id']}\t{item['display_name']}\t{item['role']}\t{state}")
    elif args.command == "revoke-tokens":
        count = database.deactivate_principals(tenant_id=args.tenant, user_id=args.user)
        print(f"Revoked {count} token(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
