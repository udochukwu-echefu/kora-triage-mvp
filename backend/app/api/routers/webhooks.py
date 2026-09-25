"""Inbound messages and delivery receipts from email (Postmark) and WhatsApp."""

from __future__ import annotations

import hmac
import json
import logging
import re

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from ...schemas import InboundMessageRequest
from .. import deps
from ..webhook_auth import verify_postmark_webhook, verify_webhook_token, verify_whatsapp_signature

logger = logging.getLogger("kora.api")

router = APIRouter()


MAX_MESSAGE_LENGTH = 8000
MAX_NAME_LENGTH = 120
MAX_SUBJECT_LENGTH = 500


def _clip(value: object, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


_QUOTE_START = re.compile(
    r"^(?:On .{3,200}wrote:\s*$|-{2,}\s*Original Message\s*-{2,}|_{5,}\s*$|From:\s.+$|Sent from my \w+)",
    re.IGNORECASE | re.MULTILINE,
)


def strip_quoted_reply(text: str) -> str:
    """Drop quoted history from an email reply, keeping only the new text."""
    match = _QUOTE_START.search(text)
    new_text = text[: match.start()] if match else text
    lines = [line for line in new_text.splitlines() if not line.lstrip().startswith(">")]
    stripped = "\n".join(lines).strip()
    return stripped or text.strip()


@router.post("/api/webhooks/inbound", status_code=202)
def generic_inbound(
    message: InboundMessageRequest,
    x_kora_webhook_token: str | None = Header(default=None, alias="X-Kora-Webhook-Token"),
) -> dict:
    verify_webhook_token(x_kora_webhook_token)
    return deps.workflow.ingest(
        message, provider="kora_webhook", tenant_id=deps.settings.default_tenant_id
    )


def _postmark_header(payload: dict, name: str) -> str | None:
    for item in payload.get("Headers") or []:
        if str(item.get("Name", "")).lower() == name.lower():
            return item.get("Value")
    return None


def _email_tenant(payload: dict) -> str:
    candidates = [payload.get("OriginalRecipient"), payload.get("To")]
    candidates += [item.get("Email") for item in payload.get("ToFull") or [] if isinstance(item, dict)]
    for candidate in candidates:
        for address in re.findall(r"[\w.+-]+@[\w.-]+", str(candidate or "")):
            tenant = deps.settings.email_tenants.get(address.lower())
            if tenant:
                return tenant
    return deps.settings.default_tenant_id


@router.post("/api/webhooks/postmark/inbound", status_code=202)
def postmark_inbound(
    payload: dict,
    authorization: str | None = Header(default=None),
    x_kora_webhook_token: str | None = Header(default=None, alias="X-Kora-Webhook-Token"),
) -> dict:
    verify_postmark_webhook(authorization, x_kora_webhook_token)
    message_id = str(payload.get("MessageID") or "").strip()
    sender = str(payload.get("From") or (payload.get("FromFull") or {}).get("Email") or "").strip()
    if not message_id or not sender:
        raise HTTPException(status_code=422, detail="Postmark payload is missing MessageID or From.")
    # Postmark's StrippedTextReply already removes quoted history; fall back to
    # our own stripping so long reply chains never exceed the message limit.
    body = str(payload.get("StrippedTextReply") or "").strip() or strip_quoted_reply(
        str(payload.get("TextBody") or "")
    )
    if not body:
        # Acknowledge so Postmark does not retry an email that has no text.
        return {"accepted": False, "reason": "The email has no text body.", "message_id": message_id}
    references = str(_postmark_header(payload, "References") or "").split()
    in_reply_to = _postmark_header(payload, "In-Reply-To")
    if in_reply_to:
        references.append(in_reply_to)
    root = references[0].strip("<>") if references else None
    name = _clip(payload.get("FromName") or sender.split("@", 1)[0], MAX_NAME_LENGTH) or "Customer"
    return deps.workflow.ingest(
        InboundMessageRequest(
            event_id=f"postmark-inbound:{message_id}"[:200],
            provider_message_id=message_id[:200],
            channel="email",
            sender=sender[:320],
            customer_name=name,
            message=_clip(body, MAX_MESSAGE_LENGTH),
            subject=_clip(payload.get("Subject"), MAX_SUBJECT_LENGTH) or None,
            external_thread_id=root[:300] if root else None,
            rfc_message_id=(_postmark_header(payload, "Message-ID") or "")[:998] or None,
            references=[reference[:998] for reference in references[-50:]],
        ),
        provider="postmark",
        tenant_id=_email_tenant(payload),
    )


POSTMARK_RECORD_STATUS = {
    "delivery": "delivered",
    "bounce": "failed",
    "spamcomplaint": "failed",
    "open": "read",
}


@router.post("/api/webhooks/postmark/delivery")
def postmark_delivery(
    payload: dict,
    authorization: str | None = Header(default=None),
    x_kora_webhook_token: str | None = Header(default=None, alias="X-Kora-Webhook-Token"),
) -> dict:
    verify_postmark_webhook(authorization, x_kora_webhook_token)
    message_id = str(payload.get("MessageID") or "")
    record_type = str(payload.get("RecordType") or "").lower()
    status_value = POSTMARK_RECORD_STATUS.get(record_type)
    if not message_id or not status_value:
        return {"ignored": True, "record_type": record_type or None}
    event_id = (
        f"postmark-{record_type}:{message_id}:"
        f"{payload.get('DeliveredAt') or payload.get('BouncedAt') or payload.get('ReceivedAt') or ''}"
    )
    return _record_delivery_update(
        event_id=event_id,
        provider="postmark",
        provider_message_id=message_id,
        status_value=status_value,
        payload=payload,
    )


def _record_delivery_update(
    *,
    event_id: str,
    provider: str,
    provider_message_id: str,
    status_value: str,
    payload: dict,
) -> dict:
    # The deduplication marker must commit with the message, case, and audit.
    with deps.database.transaction():
        return _apply_delivery_update(
            event_id=event_id,
            provider=provider,
            provider_message_id=provider_message_id,
            status_value=status_value,
            payload=payload,
        )


def _apply_delivery_update(
    *,
    event_id: str,
    provider: str,
    provider_message_id: str,
    status_value: str,
    payload: dict,
) -> dict:
    if not deps.database.record_webhook(
        event_id=event_id,
        tenant_id=deps.settings.default_tenant_id,
        provider=provider,
        event_type=f"message_{status_value}",
        payload=payload,
    ):
        return {"duplicate": True}
    # Receipts are routed by provider message ID, which carries the tenant.
    updated = deps.database.update_message_delivery(
        provider_message_id, status_value, None, provider=provider
    )
    case_id, tenant_id = updated if updated else (None, None)
    if case_id:
        lifecycle_state = (
            "delivered"
            if status_value in {"delivered", "read"}
            else "failed" if status_value == "failed" else "sent"
        )
        lifecycle = deps.database.lifecycle(case_id, tenant_id) or {}
        conversation = deps.database.conversation(case_id, tenant_id)
        latest_message = conversation[-1] if conversation else {}
        # A receipt updates its message, but cannot undo a human decision or a
        # newer reply/send in the same conversation.
        updates_case = (
            lifecycle.get("state") not in {"resolved", "reopened", "replied", "review_required"}
            and latest_message.get("direction") == "outbound"
            and latest_message.get("provider") == provider
            and latest_message.get("provider_message_id") == provider_message_id
        )
        if updates_case:
            deps.database.set_lifecycle(case_id, lifecycle_state, tenant_id=tenant_id)
        ticket = deps.database.support_ticket(case_id, tenant_id)
        if ticket:
            if updates_case:
                deps.database.update_support_ticket_fields(
                    case_id,
                    {"status": lifecycle_state.capitalize()},
                    tenant_id,
                )
            deps.database.add_audit(
                case_id=case_id,
                customer_id=ticket["customerId"],
                event_type="delivery_updated",
                model=None,
                request={"provider": provider},
                decision={"status": status_value},
                guardrails={},
                actor=provider,
                tenant_id=tenant_id,
            )
    return {"duplicate": False, "case_id": case_id, "status": status_value}


@router.get("/api/webhooks/whatsapp")
def verify_whatsapp(
    mode: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    if (
        mode == "subscribe"
        and deps.settings.whatsapp_verify_token
        and token is not None
        and hmac.compare_digest(token, deps.settings.whatsapp_verify_token)
    ):
        return PlainTextResponse(challenge or "0")
    raise HTTPException(status_code=403, detail="WhatsApp webhook verification failed.")


@router.post("/api/webhooks/whatsapp", status_code=202)
async def whatsapp_inbound(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> dict:
    raw = await request.body()
    verify_whatsapp_signature(raw, x_hub_signature_256)
    try:
        payload = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="WhatsApp payload is not valid JSON.") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="WhatsApp payload must be a JSON object.")
    results: list[dict] = []
    delivery_results: list[dict] = []
    errors: list[dict] = []
    # Each message is processed on its own: one malformed item must not make
    # Meta retry (and re-deliver) the whole batch.
    for entry in payload.get("entry") or []:
        for change in (entry or {}).get("changes") or []:
            value = (change or {}).get("value") or {}
            phone_number_id = str((value.get("metadata") or {}).get("phone_number_id") or "")
            tenant_id = deps.settings.whatsapp_tenants.get(phone_number_id.lower(), deps.settings.default_tenant_id)
            contacts = value.get("contacts") or []
            name = (
                (contacts[0].get("profile") or {}).get("name") if contacts and isinstance(contacts[0], dict) else None
            ) or "WhatsApp customer"
            for status in value.get("statuses") or []:
                provider_message_id = str(status.get("id") or "")
                status_value = str(status.get("status") or "sent").lower()
                if not provider_message_id or status_value not in {"sent", "delivered", "read", "failed"}:
                    continue
                try:
                    delivery_results.append(
                        _record_delivery_update(
                            event_id=(
                                f"whatsapp-status:{provider_message_id}:"
                                f"{status_value}:{status.get('timestamp') or ''}"
                            ),
                            provider="whatsapp_cloud",
                            provider_message_id=provider_message_id,
                            status_value=status_value,
                            payload=status,
                        )
                    )
                except Exception as error:
                    logger.exception("WhatsApp status %s failed", provider_message_id)
                    errors.append({"id": provider_message_id, "error": type(error).__name__})
            for message in value.get("messages") or []:
                provider_message_id = str(message.get("id") or "")
                sender = str(message.get("from") or "")
                body = str((message.get("text") or {}).get("body") or "").strip()
                if message.get("type") != "text" or not body or not sender or not provider_message_id:
                    continue
                try:
                    results.append(
                        deps.workflow.ingest(
                            InboundMessageRequest(
                                event_id=f"whatsapp-inbound:{provider_message_id}"[:200],
                                provider_message_id=provider_message_id[:200],
                                channel="whatsapp",
                                sender=sender[:320],
                                customer_name=_clip(name, MAX_NAME_LENGTH) or "WhatsApp customer",
                                message=_clip(body, MAX_MESSAGE_LENGTH),
                                external_thread_id=f"wa:{sender}"[:300],
                            ),
                            provider="whatsapp_cloud",
                            tenant_id=tenant_id,
                        )
                    )
                except Exception as error:
                    logger.exception("WhatsApp message %s failed", provider_message_id)
                    errors.append({"id": provider_message_id, "error": type(error).__name__})
    return {
        "accepted": len(results),
        "delivery_updates": len(delivery_results),
        "items": results,
        "deliveries": delivery_results,
        "errors": errors,
    }
