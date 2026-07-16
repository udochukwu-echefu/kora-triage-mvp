from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from .channels import ChannelGateway
from .database import Database
from .schemas import CustomerContext, InboundMessageRequest, TriageRequest
from .service import TriageService


PENDING_TRIAGE = {
    "intent": "Awaiting triage",
    "urgency": "pending",
    "sentiment": "pending",
    "route": "Unassigned",
    "confidence": 0,
    "entities": {},
    "memoryUsed": False,
    "escalated": False,
    "escalationReason": None,
    "evidence": [],
    "response": "",
    "status": "Live triage pending",
    "source": "pending",
    "model": "pending",
    "processingMs": 0,
    "estimatedMinutesSaved": 0,
}


def customer_id_for_contact(contact: str) -> str:
    digest = hashlib.sha256(contact.strip().lower().encode("utf-8")).hexdigest()[:10]
    return f"CUS-{digest.upper()}"


class SupportWorkflow:
    def __init__(self, database: Database):
        self.database = database

    def ingest(
        self,
        message: InboundMessageRequest,
        *,
        provider: str,
        tenant_id: str,
    ) -> dict:
        payload = message.model_dump(mode="json")
        if not self.database.record_webhook(
            event_id=message.event_id,
            tenant_id=tenant_id,
            provider=provider,
            event_type="inbound_message",
            payload=payload,
        ):
            return {"duplicate": True, "event_id": message.event_id}

        customer_id = customer_id_for_contact(message.sender)
        existing_case = (
            self.database.find_case_by_thread(message.external_thread_id, tenant_id)
            if message.external_thread_id
            else None
        )
        case_id = existing_case or self.database.next_case_id(tenant_id)
        now = datetime.now(UTC)
        if not existing_case:
            self.database.add_support_ticket(
                {
                    "id": case_id,
                    "customerId": customer_id,
                    "customer": {
                        "name": message.customer_name,
                        "initials": "".join(
                            part[0].upper() for part in message.customer_name.split()[:2]
                        ),
                        "previousContext": "",
                        "notes": [f"Inbound via {message.channel}"],
                    },
                    "channel": message.channel,
                    "subject": message.subject,
                    "message": message.message,
                    "receivedAt": now.strftime("%H:%M"),
                    "minutesAgo": 0,
                    "truthIntent": "Unlabelled",
                    "truthUrgency": "unlabelled",
                    "triage": dict(PENDING_TRIAGE),
                    "createdAt": now.isoformat(),
                },
                tenant_id=tenant_id,
            )
            state = "new"
        else:
            self.database.update_support_ticket_message(
                case_id,
                message=message.message,
                subject=message.subject,
                received_at=now.strftime("%H:%M"),
                tenant_id=tenant_id,
            )
            lifecycle = self.database.lifecycle(case_id, tenant_id)
            state = "reopened" if lifecycle and lifecycle["state"] == "resolved" else "replied"

        thread_id = message.external_thread_id or message.provider_message_id
        self.database.set_lifecycle(
            case_id,
            state,
            tenant_id=tenant_id,
            external_thread_id=thread_id,
            provider=provider,
        )
        self.database.add_message(
            message_id=f"msg-{uuid4().hex}",
            case_id=case_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel=message.channel,
            direction="inbound",
            provider=provider,
            provider_message_id=message.provider_message_id,
            external_thread_id=thread_id,
            contact=message.sender,
            subject=message.subject,
            body=message.message,
            delivery_status="received",
        )
        job_id = self.database.enqueue_job(
            tenant_id=tenant_id,
            job_type="triage",
            idempotency_key=f"triage:{message.event_id}",
            payload={"case_id": case_id},
        )
        self.database.add_audit(
            case_id=case_id,
            customer_id=customer_id,
            event_type="message_received",
            model=None,
            request={"channel": message.channel, "provider": provider},
            decision={"status": state, "job_id": job_id},
            guardrails={},
            actor=provider,
            tenant_id=tenant_id,
        )
        return {
            "duplicate": False,
            "case_id": case_id,
            "customer_id": customer_id,
            "state": state,
            "job_id": job_id,
        }


class WorkflowWorker:
    def __init__(
        self,
        database: Database,
        service_factory,
        gateway: ChannelGateway,
        poll_seconds: float = 1.5,
    ):
        self.database = database
        self.service_factory = service_factory
        self.gateway = gateway
        self.poll_seconds = poll_seconds
        self._stopped = False

    async def run(self) -> None:
        while not self._stopped:
            processed = await self.process_one()
            if not processed:
                await asyncio.sleep(self.poll_seconds)

    def stop(self) -> None:
        self._stopped = True

    async def process_one(self) -> bool:
        job = self.database.claim_job()
        if not job:
            return False
        try:
            if job["job_type"] == "triage":
                await self._triage(job)
            elif job["job_type"] == "send_response":
                await self._send(job)
            else:
                raise ValueError(f"Unknown job type: {job['job_type']}")
            self.database.finish_job(job["id"])
        except Exception as error:  # worker boundary intentionally captures provider failures
            state = self.database.fail_job(job["id"], str(error))
            if state == "dead":
                case_id = job["payload"].get("case_id")
                if case_id:
                    self.database.set_lifecycle(
                        case_id, "failed", tenant_id=job["tenant_id"]
                    )
        return True

    async def _triage(self, job: dict) -> None:
        tenant_id = job["tenant_id"]
        ticket = self.database.support_ticket(job["payload"]["case_id"], tenant_id)
        if not ticket:
            raise ValueError("Queued case no longer exists")
        result = await self.service_factory().triage(
            TriageRequest(
                case_id=ticket["id"],
                channel=ticket["channel"],
                message=ticket["message"],
                subject=ticket.get("subject"),
                customer=CustomerContext(
                    customer_id=ticket["customerId"],
                    name=ticket["customer"]["name"],
                    previous_context=ticket["customer"].get("previousContext", ""),
                    notes=ticket["customer"].get("notes", []),
                ),
            ),
            tenant_id=tenant_id,
        )
        state = "review_required" if result.escalated else "triaged"
        self.database.set_lifecycle(ticket["id"], state, tenant_id=tenant_id)
        if result.status == "Auto-approved":
            self.database.enqueue_job(
                tenant_id=tenant_id,
                job_type="send_response",
                idempotency_key=f"auto-send:{result.audit_id}",
                payload={
                    "case_id": ticket["id"],
                    "response": result.response,
                    "actor": "automation-policy",
                },
            )

    async def _send(self, job: dict) -> None:
        tenant_id = job["tenant_id"]
        case_id = job["payload"]["case_id"]
        ticket = self.database.support_ticket(case_id, tenant_id)
        conversation = self.database.conversation(case_id, tenant_id)
        inbound = next(
            (item for item in reversed(conversation) if item["direction"] == "inbound"),
            None,
        )
        if not ticket or not inbound or not inbound.get("contact"):
            raise ValueError("The case has no deliverable customer contact")
        lifecycle = self.database.lifecycle(case_id, tenant_id) or {}
        result = await self.gateway.send(
            channel=ticket["channel"],
            recipient=inbound["contact"],
            body=job["payload"]["response"],
            subject=(f"Re: {ticket['subject']}" if ticket.get("subject") else None),
            external_thread_id=lifecycle.get("external_thread_id"),
        )
        self.database.add_message(
            message_id=f"msg-{uuid4().hex}",
            case_id=case_id,
            tenant_id=tenant_id,
            customer_id=ticket["customerId"],
            channel=ticket["channel"],
            direction="outbound",
            provider=result.provider,
            provider_message_id=result.provider_message_id,
            external_thread_id=lifecycle.get("external_thread_id"),
            contact=inbound["contact"],
            subject=ticket.get("subject"),
            body=job["payload"]["response"],
            delivery_status=result.status,
        )
        self.database.set_lifecycle(
            case_id,
            "sent",
            tenant_id=tenant_id,
            external_thread_id=(
                lifecycle.get("external_thread_id") or result.provider_message_id
            ),
            provider=result.provider,
        )
        self.database.update_support_ticket_fields(
            case_id, {"status": "Sent"}, tenant_id
        )
        self.database.add_audit(
            case_id=case_id,
            customer_id=ticket["customerId"],
            event_type="response_sent",
            model=None,
            request={"channel": ticket["channel"]},
            decision={
                "status": "sent",
                "provider": result.provider,
                "provider_message_id": result.provider_message_id,
            },
            guardrails={},
            actor=job["payload"].get("actor", "support-agent"),
            tenant_id=tenant_id,
        )
