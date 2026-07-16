from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import httpx

from .config import Settings


@dataclass(frozen=True)
class DeliveryResult:
    provider: str
    provider_message_id: str
    status: str


class ChannelGateway:
    """Provider-neutral outbound gateway.

    Demo mode records a deterministic delivery receipt without contacting an external
    service. Live mode requires the channel-specific credentials.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def status(self) -> dict:
        return {
            "mode": self.settings.channel_mode,
            "email": {
                "provider": "postmark",
                "configured": bool(
                    self.settings.postmark_server_token
                    and self.settings.postmark_from_email
                ),
            },
            "whatsapp": {
                "provider": "whatsapp_cloud",
                "configured": bool(
                    self.settings.whatsapp_access_token
                    and self.settings.whatsapp_phone_number_id
                ),
            },
        }

    async def send(
        self,
        *,
        channel: str,
        recipient: str,
        body: str,
        subject: str | None,
        external_thread_id: str | None,
    ) -> DeliveryResult:
        if self.settings.channel_mode == "demo":
            return DeliveryResult(
                provider="kora_demo",
                provider_message_id=f"demo-{channel}-{uuid4().hex}",
                status="sent",
            )
        if channel == "email":
            return await self._send_postmark(
                recipient=recipient,
                body=body,
                subject=subject,
                external_thread_id=external_thread_id,
            )
        if channel == "whatsapp":
            return await self._send_whatsapp(recipient=recipient, body=body)
        raise ValueError(f"Unsupported channel: {channel}")

    async def _send_postmark(
        self,
        *,
        recipient: str,
        body: str,
        subject: str | None,
        external_thread_id: str | None,
    ) -> DeliveryResult:
        if not self.settings.postmark_server_token or not self.settings.postmark_from_email:
            raise RuntimeError("Postmark is not configured")
        payload: dict = {
            "From": self.settings.postmark_from_email,
            "To": recipient,
            "Subject": subject or "Re: Your support request",
            "TextBody": body,
            "MessageStream": "outbound",
            "Tag": "kora-support",
        }
        if external_thread_id:
            payload["Headers"] = [
                {"Name": "In-Reply-To", "Value": external_thread_id},
                {"Name": "References", "Value": external_thread_id},
            ]
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://api.postmarkapp.com/email",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Postmark-Server-Token": self.settings.postmark_server_token,
                },
                json=payload,
            )
        response.raise_for_status()
        result = response.json()
        return DeliveryResult(
            provider="postmark",
            provider_message_id=result["MessageID"],
            status="sent",
        )

    async def _send_whatsapp(self, *, recipient: str, body: str) -> DeliveryResult:
        if not self.settings.whatsapp_access_token or not self.settings.whatsapp_phone_number_id:
            raise RuntimeError("WhatsApp Cloud API is not configured")
        url = (
            f"https://graph.facebook.com/{self.settings.whatsapp_graph_version}/"
            f"{self.settings.whatsapp_phone_number_id}/messages"
        )
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.settings.whatsapp_access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": recipient,
                    "type": "text",
                    "text": {"preview_url": False, "body": body},
                },
            )
        response.raise_for_status()
        result = response.json()
        return DeliveryResult(
            provider="whatsapp_cloud",
            provider_message_id=result["messages"][0]["id"],
            status="sent",
        )
