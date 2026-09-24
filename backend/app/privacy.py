from __future__ import annotations

import re
from collections.abc import Iterable

# Numeric identifiers must not be glued to letters or a hyphen, so references
# such as TRX-1234567890123 stay intact for routing and verification.
_START = r"(?<![\w-])"
_END = r"(?![\w])"

# Nigerian mobile numbers in local or international form, with optional spaces,
# dots, or hyphens between digit groups: 08031234567, +234 803 123 4567, ...
PHONE = re.compile(
    _START + r"(?:\+?234[\s.-]?|0)[789][01]\d(?:[\s.-]?\d){7}" + _END
)
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
# Payment card numbers: 13-19 digits, optionally grouped with spaces/hyphens.
CARD = re.compile(_START + r"\d(?:[\s-]?\d){12,18}" + _END)
# BVN and NIN are both 11 digits.
NATIONAL_ID = re.compile(_START + r"\d{11}" + _END)
# NUBAN bank account numbers are 10 digits.
ACCOUNT = re.compile(_START + r"\d{10}" + _END)

_NAME_STOP_WORDS = {"customer", "historical", "whatsapp", "evaluation", "test", "unknown"}


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def _name_pattern(names: Iterable[str]) -> re.Pattern[str] | None:
    parts = {
        part
        for name in names
        for part in re.split(r"[\s,.]+", name or "")
        if len(part) >= 3 and part.lower() not in _NAME_STOP_WORDS
    }
    if not parts:
        return None
    alternatives = "|".join(sorted((re.escape(part) for part in parts), key=len, reverse=True))
    return re.compile(rf"\b(?:{alternatives})\b", re.IGNORECASE)


def redact_for_model(
    text: str, names: Iterable[str] = ()
) -> tuple[str, dict[str, str | None]]:
    """Remove direct identifiers while preserving the last four for reconciliation.

    Order matters: phone numbers are removed before the generic digit patterns
    so an 11-digit mobile number is never mistaken for a BVN/NIN.
    """

    card_match = CARD.search(PHONE.sub(" ", text))
    account_match = ACCOUNT.search(CARD.sub(" ", PHONE.sub(" ", text)))
    deterministic = {
        "account_last4": account_match.group(0)[-4:] if account_match else None,
        "card_last4": _digits(card_match.group(0))[-4:] if card_match else None,
    }
    redacted = EMAIL.sub("[EMAIL REDACTED]", text)
    redacted = PHONE.sub("[PHONE REDACTED]", redacted)
    redacted = CARD.sub(
        lambda match: f"[CARD ENDING {_digits(match.group(0))[-4:]}]", redacted
    )
    redacted = NATIONAL_ID.sub("[ID NUMBER REDACTED]", redacted)
    redacted = ACCOUNT.sub(
        lambda match: f"[ACCOUNT ENDING {match.group(0)[-4:]}]", redacted
    )
    pattern = _name_pattern(names)
    if pattern:
        redacted = pattern.sub("[NAME]", redacted)
    return redacted, deterministic
