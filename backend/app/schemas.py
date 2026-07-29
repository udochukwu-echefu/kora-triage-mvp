from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Intent(str, Enum):
    transfer_pending = "Transfer pending"
    payment_failed = "Payment failed"
    duplicate_debit = "Duplicate debit"
    fraud_report = "Fraud report"
    delivery_delayed = "Delivery delayed"
    delivery_missing = "Delivery missing"
    delivery_change = "Delivery change"
    account_access = "Account access"
    account_verification = "Account verification"
    refund_pending = "Refund pending"
    general_enquiry = "General enquiry"


class Urgency(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Sentiment(str, Enum):
    calm = "calm"
    concerned = "concerned"
    frustrated = "frustrated"
    hostile = "hostile"


class Route(str, Enum):
    payments = "Billing"
    transfers = "Transfers"
    logistics = "Logistics"
    account_support = "Account Support"
    compliance = "Compliance"
    risk_fraud = "Fraud"
    general_support = "General Support"


class LifecycleStatus(str, Enum):
    new = "new"
    triaged = "triaged"
    review_required = "review_required"
    approved = "approved"
    queued = "queued"
    sent = "sent"
    delivered = "delivered"
    replied = "replied"
    resolved = "resolved"
    reopened = "reopened"
    failed = "failed"


class ExtractedEntities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: str | None
    transaction_id: str | None
    order_id: str | None
    account_last4: str | None
    card_last4: str | None


class ModelTriage(BaseModel):
    """Exact schema requested from Groq Structured Outputs."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    urgency: Urgency
    sentiment: Sentiment
    route: Route
    confidence: float = Field(ge=0, le=1)
    entities: ExtractedEntities
    memory_used: bool
    evidence: list[str] = Field(min_length=1, max_length=5)
    draft_response: str = Field(min_length=1, max_length=1200)


class CustomerContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    previous_context: str = Field(default="", max_length=3000)
    notes: list[str] = Field(default_factory=list, max_length=20)


class TriageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=80)
    channel: str = Field(pattern="^(whatsapp|email)$")
    message: str = Field(min_length=1, max_length=8000)
    subject: str | None = Field(default=None, max_length=500)
    customer: CustomerContext


class TriageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent
    urgency: Urgency
    sentiment: Sentiment
    route: Route
    confidence: float
    entities: dict[str, str | None]
    memory_used: bool
    escalated: bool
    escalation_reason: str | None
    evidence: list[str]
    response: str
    status: str
    source: str
    model: str
    audit_id: int
    processing_ms: int
    estimated_minutes_saved: float
    policy_citations: list[dict] = Field(default_factory=list)


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str = Field(default="support-agent", min_length=1, max_length=120)
    customer_id: str = Field(min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=1000)
    response: str | None = Field(default=None, max_length=1200)


class RouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str = Field(default="support-agent", min_length=1, max_length=120)
    customer_id: str = Field(min_length=1, max_length=80)
    team: str = Field(pattern="^(Transfers|Fraud|Logistics|Billing|Account Support|Compliance|General Support)$")


class AutomationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    auto_approve_threshold: int = Field(default=95, ge=80, le=99)
    mandatory_review_threshold: int = Field(default=70, ge=50, le=90)


class InboundMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=200)
    provider_message_id: str = Field(min_length=1, max_length=200)
    channel: str = Field(pattern="^(whatsapp|email)$")
    sender: str = Field(min_length=1, max_length=320)
    customer_name: str = Field(default="Customer", min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=8000)
    subject: str | None = Field(default=None, max_length=500)
    external_thread_id: str | None = Field(default=None, max_length=300)


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str = Field(default="support-agent", min_length=1, max_length=120)
    customer_id: str = Field(min_length=1, max_length=80)
    corrected_intent: Intent | None = None
    corrected_urgency: Urgency | None = None
    corrected_route: Route | None = None
    response_accepted: bool | None = None
    reason: str | None = Field(default=None, max_length=1000)


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str = Field(default="support-agent", min_length=1, max_length=120)
    customer_id: str = Field(min_length=1, max_length=80)
    resolution: str = Field(min_length=2, max_length=1000)


class DeliveryEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=200)
    provider_message_id: str = Field(min_length=1, max_length=200)
    status: str = Field(pattern="^(sent|delivered|bounced|failed)$")
    detail: str | None = Field(default=None, max_length=1000)


class KnowledgePolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=160)
    content: str = Field(min_length=20, max_length=30_000)
    source_url: str | None = Field(default=None, max_length=1000)
    version: str = Field(default="1.0", min_length=1, max_length=40)


class PolicyStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool


class CaseAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee: str | None = Field(default=None, max_length=120)
    expected_assignee: str | None = Field(default=None, max_length=120)


class CaseNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=2, max_length=2000)
    mentions: list[str] = Field(default_factory=list, max_length=20)


class TransactionVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(min_length=1, max_length=80)
    reference: str = Field(min_length=3, max_length=100)


class ManualAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(min_length=1, max_length=80)
    intent: Intent
    urgency: Urgency
    route: Route
    response: str = Field(min_length=2, max_length=1200)


class ProofExpected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent | None = None
    urgency: Urgency | None = None
    route: Route | None = None


class ProofCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=80)
    channel: str = Field(pattern="^(whatsapp|email)$")
    message: str = Field(min_length=1, max_length=8000)
    subject: str | None = Field(default=None, max_length=500)
    language: str = Field(default="unspecified", max_length=40)
    customer_name: str = Field(default="Historical customer", max_length=120)
    expected: ProofExpected | None = None


class ProofRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Historical inbox proof", min_length=3, max_length=160)
    cases: list[ProofCase] = Field(min_length=1, max_length=100)
