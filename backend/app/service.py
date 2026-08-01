from __future__ import annotations

import re
from time import perf_counter

from .database import Database
from .groq_triage import TriageModel
from .guardrails import apply_guardrails
from .launch_features import relevant_policies
from .privacy import redact_for_model
from .schemas import CustomerContext, ExtractedEntities, TriageRequest, TriageResult
from .triage_policy import apply_operational_policy


def _redacted_request(request: TriageRequest) -> tuple[TriageRequest, dict[str, str | None]]:
    message, deterministic = redact_for_model(request.message)
    subject, _ = redact_for_model(request.subject or "")
    context, _ = redact_for_model(request.customer.previous_context)
    safe_notes = []
    for note in request.customer.notes:
        safe_note = redact_for_model(note)[0]
        if safe_note.lstrip().upper().startswith("APPROVED POLICY"):
            safe_note = f"[UNTRUSTED NOTE] {safe_note}"
        safe_notes.append(safe_note)
    return (
        request.model_copy(
            update={
                "message": message,
                "subject": subject or None,
                "customer": CustomerContext(
                    customer_id=request.customer.customer_id,
                    name="Customer",
                    previous_context=context,
                    notes=safe_notes,
                ),
            }
        ),
        deterministic,
    )


def _frontend_entities(entities: ExtractedEntities) -> dict[str, str | None]:
    return {
        "amount": entities.amount,
        "transactionId": entities.transaction_id,
        "orderId": entities.order_id,
        "account": f"••••••{entities.account_last4}" if entities.account_last4 else None,
        "card": f"•••• {entities.card_last4}" if entities.card_last4 else None,
    }


class TriageService:
    def __init__(
        self,
        database: Database,
        model: TriageModel,
        manual_baseline_minutes: float = 12,
    ):
        self.database = database
        self.model = model
        self.manual_baseline_minutes = manual_baseline_minutes

    async def triage(
        self,
        request: TriageRequest,
        tenant_id: str = "tenant-demo",
        policy_tenant_id: str | None = None,
    ) -> TriageResult:
        started_at = perf_counter()
        safe_request, deterministic = _redacted_request(request)
        policy_citations = relevant_policies(
            self.database,
            tenant_id=policy_tenant_id or tenant_id,
            message=f"{request.subject or ''} {request.message}",
        )
        if policy_citations:
            policy_notes = [
                (
                    f"APPROVED POLICY [{item['title']} v{item['version']}]: "
                    f"{item['excerpt']}"
                )
                for item in policy_citations
            ]
            safe_request = safe_request.model_copy(
                update={
                    "customer": safe_request.customer.model_copy(
                        update={
                            "notes": [
                                *safe_request.customer.notes[: max(0, 20 - len(policy_notes))],
                                *policy_notes,
                            ]
                        }
                    )
                }
            )
        memories = self.database.memories_for(
            request.customer.customer_id, tenant_id=tenant_id
        )
        model_result = await self.model.classify(safe_request, memories)
        policy = apply_operational_policy(safe_request, model_result)
        model_result = policy.triage
        automation = self.database.get_setting(
            "automation",
            {"enabled": True, "auto_approve_threshold": 95, "mandatory_review_threshold": 70},
            tenant_id,
        )
        processing_ms = round((perf_counter() - started_at) * 1000)
        estimated_minutes_saved = round(
            max(0, self.manual_baseline_minutes - processing_ms / 60_000), 1
        )

        if deterministic["account_last4"] and not model_result.entities.account_last4:
            model_result = model_result.model_copy(
                update={
                    "entities": model_result.entities.model_copy(
                        update={"account_last4": deterministic["account_last4"]}
                    )
                }
            )

        guardrail = apply_guardrails(
            request,
            model_result,
            low_confidence_threshold=automation["mandatory_review_threshold"] / 100,
        )
        first_name = request.customer.name.split()[0]
        response = re.sub(
            r"\b(Hi|Hello|Dear)\s+Customer\b",
            lambda match: f"{match.group(1)} {first_name}",
            guardrail.response,
            flags=re.IGNORECASE,
        )
        entities = _frontend_entities(model_result.entities)
        decision = {
            "intent": model_result.intent.value,
            "urgency": model_result.urgency.value,
            "sentiment": model_result.sentiment.value,
            "route": model_result.route.value,
            "confidence": model_result.confidence,
            "entities": entities,
            "memory_used": model_result.memory_used,
            "evidence": model_result.evidence,
            "response": response,
            "processing_ms": processing_ms,
            "estimated_minutes_saved": estimated_minutes_saved,
            "policy_overrides": list(policy.overrides),
            "policy_citations": policy_citations,
        }
        guardrails = {
            "escalated": guardrail.escalated,
            "reason": guardrail.reason,
            "flags": list(guardrail.flags),
        }
        audit_id = self.database.add_audit(
            case_id=request.case_id,
            customer_id=request.customer.customer_id,
            event_type="triage",
            model=self.model.model_name,
            request=safe_request.model_dump(mode="json"),
            decision=decision,
            guardrails=guardrails,
            actor="groq-model",
            tenant_id=tenant_id,
        )
        memory_summary = (
            f"{model_result.intent.value}; {model_result.urgency.value} urgency; "
            f"route {model_result.route.value}; case {request.case_id}."
        )
        self.database.add_memory(
            request.customer.customer_id,
            request.case_id,
            memory_summary,
            entities,
            tenant_id=tenant_id,
        )
        auto_approved = (
            automation["enabled"]
            and not guardrail.escalated
            and model_result.confidence * 100 >= automation["auto_approve_threshold"]
        )
        result = TriageResult(
            intent=model_result.intent,
            urgency=model_result.urgency,
            sentiment=model_result.sentiment,
            route=model_result.route,
            confidence=model_result.confidence,
            entities=entities,
            memory_used=model_result.memory_used,
            escalated=guardrail.escalated,
            escalation_reason=guardrail.reason,
            evidence=model_result.evidence,
            response=response,
            status=(
                "Needs review"
                if guardrail.escalated
                else "Auto-approved" if auto_approved else "AI draft ready"
            ),
            source="groq",
            model=self.model.model_name,
            audit_id=audit_id,
            processing_ms=processing_ms,
            estimated_minutes_saved=estimated_minutes_saved,
            policy_citations=policy_citations,
        )
        if auto_approved:
            self.database.add_audit(
                case_id=request.case_id,
                customer_id=request.customer.customer_id,
                event_type="confidence_auto_approved",
                model=None,
                request={},
                decision={
                    "status": "auto_approved",
                    "threshold": automation["auto_approve_threshold"],
                    "confidence": result.confidence,
                    "response": result.response,
                },
                guardrails={"escalated": False, "flags": []},
                actor="automation-policy",
                tenant_id=tenant_id,
            )
        self.database.update_support_ticket_triage(
            request.case_id,
            {
                "intent": result.intent.value,
                "urgency": result.urgency.value,
                "sentiment": result.sentiment.value,
                "route": result.route.value,
                "confidence": result.confidence,
                "entities": result.entities,
                "memoryUsed": result.memory_used,
                "escalated": result.escalated,
                "escalationReason": result.escalation_reason,
                "evidence": result.evidence,
                "response": result.response,
                "status": result.status,
                "source": result.source,
                "model": result.model,
                "processingMs": result.processing_ms,
                "estimatedMinutesSaved": result.estimated_minutes_saved,
                "policyCitations": result.policy_citations,
            },
            tenant_id,
        )
        return result
