"""Authentication for inbound provider webhooks (generic, Postmark, WhatsApp)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac

from fastapi import HTTPException

from . import deps


def verify_webhook_token(received: str | None) -> None:
    if not deps.settings.webhook_token:
        if deps.settings.channel_mode == "live" or not deps.settings.allow_unsigned_webhooks:
            raise HTTPException(
                status_code=503,
                detail="KORA_WEBHOOK_TOKEN must be configured before webhooks are accepted.",
            )
        return
    if not hmac.compare_digest(received or "", deps.settings.webhook_token):
        raise HTTPException(status_code=401, detail="Invalid webhook token.")


def verify_postmark_webhook(
    authorization: str | None, fallback_token: str | None
) -> None:
    if deps.settings.postmark_webhook_username and deps.settings.postmark_webhook_password:
        try:
            scheme, encoded = (authorization or "").split(" ", 1)
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError, binascii.Error):
            raise HTTPException(
                status_code=401, detail="Invalid Postmark webhook credentials."
            ) from None
        valid = scheme.lower() == "basic" and hmac.compare_digest(
            username, deps.settings.postmark_webhook_username
        ) and hmac.compare_digest(password, deps.settings.postmark_webhook_password)
        if not valid:
            raise HTTPException(
                status_code=401, detail="Invalid Postmark webhook credentials."
            )
        return
    verify_webhook_token(fallback_token)


def verify_whatsapp_signature(raw: bytes, received: str | None) -> None:
    if not deps.settings.whatsapp_app_secret:
        if deps.settings.channel_mode == "live" or not deps.settings.allow_unsigned_webhooks:
            raise HTTPException(
                status_code=503,
                detail="WHATSAPP_APP_SECRET must be configured before WhatsApp webhooks are accepted.",
            )
        return
    expected = "sha256=" + hmac.new(
        deps.settings.whatsapp_app_secret.encode("utf-8"), raw, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(received or "", expected):
        raise HTTPException(status_code=401, detail="Invalid WhatsApp signature.")
