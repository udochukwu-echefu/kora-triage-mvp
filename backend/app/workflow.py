from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .channels import ChannelGateway, DeliveryResult
from .database import Database
from .schemas import CustomerContext, InboundMessageRequest, TriageRequest

logger = logging.getLogger("kora.workflow")

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

# WhatsApp only allows free-form replies within 24 hours of the customer's
# last message; later replies need a pre-approved template.
WHATSAPP_REPLY_WINDOW = timedelta(hours=24)
# States in which a queued response may still be delivered.
DELIVERABLE_STATES = {"queued", "approved", "triaged"}


def customer_id_for_contact(contact: str) -> str:
    digest = hashlib.sha256(contact.strip().lower().encode("utf-8")).hexdigest()[:10]
    return f"CUS-{digest.upper()}"


def reference_candidates(values: list[str | None]) -> list[str]:
    """Normalise email references so provider IDs and Message-IDs both match.

    ``<abc123@mtasv.net>`` yields ``abc123@mtasv.net`` and ``abc123``.
    """
    candidates: list[str] = []
    for value in values:
        if not value:
            continue
        for item in value.split():
            reference = item.strip().strip("<>").strip()
            if not reference:
                continue
            candidates.append(reference)
            if "@" in reference:
                candidates.append(reference.split("@", 1)[0])
    return list(dict.fromkeys(candidates))


class JobCancelled(Exception):
    """A job that must not run any more (not a failure to retry)."""


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
        with self.database.transaction():
            return self._ingest(message, provider=provider, tenant_id=tenant_id)

    def _ingest(
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
        thread_scope = {
            "customer_id": customer_id,
            "channel": message.channel,
            "provider": provider,
        }
        existing_case = None
        # A thread reference alone is not authority to join another customer.
        if message.external_thread_id:
            existing_case = self.database.find_case_by_thread(
                message.external_thread_id, tenant_id, **thread_scope
            )
        references = reference_candidates([message.external_thread_id, *message.references])
        if not existing_case and references:
            existing_case = self.database.find_case_by_message_reference(
                references, tenant_id, **thread_scope
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
                    "receivedAt": now.isoformat(),
                    "truthIntent": "Unlabelled",
                    "truthUrgency": "unlabelled",
                    "triage": dict(PENDING_TRIAGE),
                    "createdAt": now.isoformat(),
                    "lastMessageAt": now.isoformat(),
                },
                tenant_id=tenant_id,
            )
            state = "new"
        else:
            self.database.update_support_ticket_message(
                case_id,
                message=message.message,
                subject=message.subject,
                received_at=now.isoformat(),
                tenant_id=tenant_id,
                last_message_at=now.isoformat(),
            )
            lifecycle = self.database.lifecycle(case_id, tenant_id)
            state = "reopened" if lifecycle and lifecycle["state"] == "resolved" else "replied"

        thread_id = (
            message.external_thread_id
            or (message.rfc_message_id.strip("<> ") if message.rfc_message_id else None)
            or message.provider_message_id
        )
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
            created_at=now.isoformat(),
            rfc_message_id=message.rfc_message_id.strip("<> ") if message.rfc_message_id else None,
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


def send_job_payload(
    database: Database,
    *,
    case_id: str,
    tenant_id: str,
    response: str,
    actor: str,
    expected_states: list[str],
) -> dict:
    """Snapshot what an approval was based on, so stale sends can be stopped."""
    inbound = database.latest_inbound_message(case_id, tenant_id)
    return {
        "case_id": case_id,
        "response": response,
        "actor": actor,
        "inbound_message_id": inbound["id"] if inbound else None,
        "expected_states": expected_states,
    }


class WorkflowWorker:
    def __init__(
        self,
        database: Database,
        service_factory,
        gateway: ChannelGateway,
        poll_seconds: float = 1.5,
        lease_seconds: int = 300,
    ):
        self.database = database
        self.service_factory = service_factory
        self.gateway = gateway
        self.poll_seconds = poll_seconds
        self.lease_seconds = lease_seconds
        self._stopped = False

    async def run(self) -> None:
        while not self._stopped:
            try:
                processed = await self.process_one()
            except asyncio.CancelledError:
                raise
            except Exception:  # never let one bad iteration stop all delivery
                logger.exception("Workflow worker iteration failed; continuing")
                processed = False
            if not processed:
                await asyncio.sleep(self.poll_seconds)

    def stop(self) -> None:
        self._stopped = True

    async def process_one(self, tenant_id: str | None = None) -> bool:
        job = self.database.claim_job(tenant_id, lease_seconds=self.lease_seconds)
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
        except JobCancelled as cancelled:
            self._record_cancellation(job, str(cancelled))
        except Exception as error:  # worker boundary intentionally captures provider failures
            try:
                self._record_failure(job, error)
            except Exception:
                logger.exception("Could not record failure for job %s", job["id"])
        return True

    def _record_cancellation(self, job: dict, reason: str) -> None:
        self.database.cancel_job(job["id"], reason)
        case_id = job["payload"].get("case_id")
        ticket = self.database.support_ticket(case_id, job["tenant_id"]) if case_id else None
        if not ticket:
            return
        self.database.update_support_ticket_fields(
            case_id, {"status": "Send cancelled", "deliveryNote": reason}, job["tenant_id"]
        )
        self.database.add_audit(
            case_id=case_id,
            customer_id=ticket["customerId"],
            event_type="delivery_cancelled",
            model=None,
            request={"job_id": job["id"]},
            decision={"status": "cancelled", "reason": reason},
            guardrails={"external_delivery": False},
            actor="workflow-worker",
            tenant_id=job["tenant_id"],
        )

    def _record_failure(self, job: dict, error: Exception) -> None:
        state = self.database.fail_job(job["id"], str(error))
        case_id = job["payload"].get("case_id")
        ticket = self.database.support_ticket(case_id, job["tenant_id"]) if case_id else None
        if job["job_type"] == "triage":
            status = "Manual review required" if state == "dead" else "AI retry queued"
            updates = {"status": status, "degradedMode": True, "degradedReason": str(error)[:300]}
            event_type = "manual_queue_required" if state == "dead" else "ai_retry_scheduled"
        else:
            status = "Delivery failed" if state == "dead" else "Delivery retry queued"
            updates = {"status": status, "deliveryNote": str(error)[:300]}
            event_type = "delivery_failed" if state == "dead" else "delivery_retry_scheduled"
        if case_id:
            self.database.update_support_ticket_fields(case_id, updates, job["tenant_id"])
        if ticket:
            self.database.add_audit(
                case_id=case_id,
                customer_id=ticket["customerId"],
                event_type=event_type,
                model=None,
                request={"job_id": job["id"], "attempt": job["attempts"]},
                decision={"status": state, "manual_workflow_available": True},
                guardrails={"external_delivery": False},
                actor="workflow-worker",
                tenant_id=job["tenant_id"],
            )
        if state == "dead" and case_id:
            self.database.set_lifecycle(case_id, "failed", tenant_id=job["tenant_id"])

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
                    notes=ticket["customer"].get("notes", [])[:20],
                ),
            ),
            tenant_id=tenant_id,
        )
        state = "review_required" if result.escalated else "triaged"
        self.database.set_lifecycle(ticket["id"], state, tenant_id=tenant_id)
        if result.automation.eligible and not result.automation.simulated:
            self.database.enqueue_job(
                tenant_id=tenant_id,
                job_type="send_response",
                idempotency_key=f"auto-send:{result.audit_id}",
                payload=send_job_payload(
                    self.database,
                    case_id=ticket["id"],
                    tenant_id=tenant_id,
                    response=result.response,
                    actor="automation-policy",
                    expected_states=["triaged"],
                ),
            )

    def _check_still_deliverable(self, job: dict, lifecycle: dict, inbound: dict | None, channel: str) -> None:
        payload = job["payload"]
        state = lifecycle.get("state")
        expected = set(payload.get("expected_states") or DELIVERABLE_STATES)
        if state == "resolved":
            raise JobCancelled("The case was resolved before the reply was sent.")
        if state == "review_required":
            raise JobCancelled("The case was escalated for review after approval.")
        approved_inbound = payload.get("inbound_message_id")
        if approved_inbound and inbound and inbound["id"] != approved_inbound:
            raise JobCancelled("The customer sent a new message after approval; review it again.")
        if state not in expected:
            raise JobCancelled(f"The case moved to '{state}' after approval; review it again.")
        if channel == "whatsapp" and inbound:
            received = datetime.fromisoformat(inbound["created_at"])
            if received.tzinfo is None:
                received = received.replace(tzinfo=UTC)
            if datetime.now(UTC) - received > WHATSAPP_REPLY_WINDOW:
                raise JobCancelled(
                    "WhatsApp's 24-hour reply window has closed. Reply with an approved "
                    "message template or another channel."
                )

    async def _send(self, job: dict) -> None:
        tenant_id = job["tenant_id"]
        case_id = job["payload"]["case_id"]
        ticket = self.database.support_ticket(case_id, tenant_id)
        inbound = self.database.latest_inbound_message(case_id, tenant_id)
        if not ticket or not inbound or not inbound.get("contact"):
            raise ValueError("The case has no deliverable customer contact")
        lifecycle = self.database.lifecycle(case_id, tenant_id) or {}
        # The outbound row is keyed by job, so a retry after a partial failure
        # finds the message it already sent instead of messaging the customer twice.
        message_id = f"msg-job-{job['id']}"
        existing = self.database.message(message_id)
        if existing:
            result = DeliveryResult(
                provider=existing["provider"],
                provider_message_id=existing["provider_message_id"],
                status=existing["delivery_status"],
            )
        else:
            self._check_still_deliverable(job, lifecycle, inbound, ticket["channel"])
            references = [
                reference
                for reference in (lifecycle.get("external_thread_id"), inbound.get("rfc_message_id"))
                if reference
            ]
            result = await self.gateway.send(
                channel=ticket["channel"],
                recipient=inbound["contact"],
                body=job["payload"]["response"],
                subject=(f"Re: {ticket['subject']}" if ticket.get("subject") else None),
                in_reply_to=inbound.get("rfc_message_id") or lifecycle.get("external_thread_id"),
                references=list(dict.fromkeys(references)),
            )
            self.database.add_message(
                message_id=message_id,
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
        with self.database.transaction():
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
                case_id, {"status": "Sent", "deliveryNote": None}, tenant_id
            )
            self.database.add_audit(
                case_id=case_id,
                customer_id=ticket["customerId"],
                event_type="response_sent",
                model=None,
                request={"channel": ticket["channel"], "job_id": job["id"]},
                decision={
                    "status": "sent",
                    "provider": result.provider,
                    "provider_message_id": result.provider_message_id,
                },
                guardrails={},
                actor=job["payload"].get("actor", "support-agent"),
                tenant_id=tenant_id,
            )
