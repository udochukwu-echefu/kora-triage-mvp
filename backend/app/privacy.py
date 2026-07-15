from __future__ import annotations

import re


PHONE = re.compile(r"(?:\+?234|0)[789][01]\d{8}\b")
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
ACCOUNT = re.compile(r"\b\d{10}\b")


def redact_for_model(text: str) -> tuple[str, dict[str, str | None]]:
    """Remove direct identifiers while preserving the last four for reconciliation."""

    account_match = ACCOUNT.search(text)
    deterministic = {
        "account_last4": account_match.group(0)[-4:] if account_match else None,
    }
    redacted = PHONE.sub("[PHONE REDACTED]", text)
    redacted = EMAIL.sub("[EMAIL REDACTED]", redacted)
    redacted = ACCOUNT.sub(
        lambda match: f"[ACCOUNT ENDING {match.group(0)[-4:]}]", redacted
    )
    return redacted, deterministic
