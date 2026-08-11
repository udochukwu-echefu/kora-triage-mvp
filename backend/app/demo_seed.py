from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .database import Database


MODEL_NAME = "openai/gpt-oss-20b (seed snapshot)"


def _customer(name: str, phone: str, tier: str, since: str, notes: list[str], context: str) -> dict:
    return {
        "name": name,
        "phone": phone,
        "tier": tier,
        "since": since,
        "notes": notes,
        "previousContext": context,
    }


def _ticket(
    *,
    case_id: str,
    customer_id: str,
    customer: dict,
    channel: str,
    received_at: str,
    minutes_ago: int,
    message: str,
    intent: str,
    urgency: str,
    sentiment: str,
    route: str,
    confidence: float,
    response: str,
    evidence: list[str],
    entities: dict | None = None,
    subject: str | None = None,
    memory_used: bool = False,
    escalated: bool = False,
    escalation_reason: str | None = None,
    processing_ms: int = 760,
    truth_intent: str | None = None,
    truth_urgency: str | None = None,
) -> dict:
    created_at = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
    return {
        "id": case_id,
        "customerId": customer_id,
        "customer": customer,
        "channel": channel,
        "receivedAt": received_at,
        "minutesAgo": minutes_ago,
        "subject": subject,
        "message": message,
        "truthIntent": truth_intent or intent,
        "truthUrgency": truth_urgency or urgency,
        "createdAt": created_at,
        "triage": {
            "intent": intent,
            "urgency": urgency,
            "sentiment": sentiment,
            "route": route,
            "confidence": confidence,
            "entities": entities or {},
            "memoryUsed": memory_used,
            "escalated": escalated,
            "escalationReason": escalation_reason,
            "evidence": evidence,
            "response": response,
            "status": "Needs review" if escalated else "AI draft ready",
            "source": "seeded",
            "model": MODEL_NAME,
            "processingMs": processing_ms,
            "estimatedMinutesSaved": round(12 - processing_ms / 60_000, 1),
        },
    }


CHIDINMA = _customer(
    "Chidinma Okeke", "+234 803 ••• 4412", "Business", "March 2024",
    ["Preferred channel: WhatsApp", "Previously reported a delayed transfer", "Identity verified 08 Jul"],
    "Transfer TRX-920184 for ₦82,500 was already reported. The transaction ID and recipient bank are on file.",
)
TUNDE = _customer(
    "Tunde Adebayo", "+234 706 ••• 1139", "Standard", "January 2025",
    ["Preferred channel: Email", "One resolved card dispute"],
    "Card ending 7721 was previously debited twice. One duplicate was reversed.",
)
AMINA = _customer(
    "Amina Bello", "+234 812 ••• 0883", "Standard", "September 2024",
    ["Preferred language: English", "Delivery address in Kaduna"],
    "Order ORD-44890 was expected in Kaduna on 10 July.",
)
EMEKA = _customer(
    "Emeka Nwosu", "+234 809 ••• 5620", "Business", "May 2023",
    ["High-value merchant", "Callback consent on file", "KYC reviewed 04 Jul"],
    "Account access was restored after a prior device change. Identity verification is already complete.",
)
BLESSING = _customer(
    "Blessing Eze", "+234 815 ••• 9034", "Standard", "February 2025",
    ["Preferred language: Pidgin", "No prior escalations"],
    "First payment complaint. No other open cases.",
)
SEYI = _customer(
    "Seyi Balogun", "+234 802 ••• 7701", "Standard", "August 2024",
    ["Preferred channel: WhatsApp", "Two completed deliveries"],
    "Order ORD-77401 is marked delivered, but the customer says it was not received.",
)
FATIMA = _customer(
    "Fatima Lawal", "+234 816 ••• 2860", "Standard", "April 2025",
    ["Prefers written instructions", "Identity not yet reverified"],
    "Two password-reset links expired. Do not request the same details again.",
)
IFEANYI = _customer(
    "Ifeanyi Obi", "+234 705 ••• 4198", "Business", "November 2023",
    ["Frequent transfers", "Previous fraud false positive"],
    "Customer recognises all recent transfers except the debit reported today.",
)
NGOZI = _customer(
    "Ngozi Umeh", "+234 814 ••• 7205", "Standard", "June 2024",
    ["Preferred channel: Email", "Statement delivery enabled"],
    "Customer queried a service fee once; it was explained and closed.",
)
KUNLE = _customer(
    "Kunle Ajayi", "+234 708 ••• 6140", "Standard", "October 2024",
    ["Preferred language: Pidgin", "No open disputes"],
    "First report of an unauthorised card transaction.",
)
ZAINAB = _customer(
    "Zainab Musa", "+234 810 ••• 9928", "Business", "December 2023",
    ["Payroll account", "Usually contacts support by email"],
    "Recipient details were supplied for transfer TRX-330871.",
)
CHUKS = _customer(
    "Chuks Ibe", "+234 806 ••• 3361", "Standard", "March 2025",
    ["Lagos delivery address", "Prefers WhatsApp updates"],
    "Order ORD-99014 left the warehouse two days ago.",
)


DEMO_TICKETS = [
    _ticket(
        case_id="KOR-2401", customer_id="CUS-1042", customer=CHIDINMA, channel="whatsapp", received_at="10:42", minutes_ago=4,
        message="Abeg this transfer still dey pending since morning. I don send the transaction ID before, na TRX-920184. ₦82,500 no reach the person and una don debit me.",
        intent="Transfer pending", urgency="high", sentiment="frustrated", route="Transfers", confidence=.97, memory_used=True,
        entities={"amount": "₦82,500", "transactionId": "TRX-920184", "orderId": None, "account": None, "card": None},
        evidence=["Customer says recipient has not received the transfer", "Transaction ID and amount are present", "Prior context contains the same transfer"],
        response="Hi Chidinma, I can see you already supplied TRX-920184, so you do not need to repeat the details. I have routed the pending ₦82,500 transfer for review, and the transfers team will update you here.", processing_ms=540,
    ),
    _ticket(
        case_id="KOR-2402", customer_id="CUS-3071", customer=AMINA, channel="email", received_at="10:38", minutes_ago=8,
        subject="Order still not delivered", message="Hello, my order ORD-44890 was meant to arrive on Thursday in Kaduna. The tracking has not changed for three days. Please advise.",
        intent="Delivery delayed", urgency="medium", sentiment="concerned", route="Logistics", confidence=.93,
        entities={"amount": None, "transactionId": None, "orderId": "ORD-44890", "account": None, "card": None},
        evidence=["Delivery date has passed", "Tracking has been unchanged for three days", "Order ID is supplied"],
        response="Hello Amina, I’m sorry the tracking for ORD-44890 has not moved. Your delivery case is with the logistics queue for review, and you will receive the next confirmed update by email.", processing_ms=680,
    ),
    _ticket(
        case_id="KOR-2403", customer_id="CUS-8234", customer=IFEANYI, channel="whatsapp", received_at="10:31", minutes_ago=15,
        message="I DID NOT MAKE THIS ₦145,000 DEBIT! If my money disappears you people will hear from me today. Account 0192846671. Block everything now.",
        intent="Fraud report", urgency="critical", sentiment="hostile", route="Fraud", confidence=.99, escalated=True,
        escalation_reason="Fraud report and hostile sentiment require immediate specialist review.",
        entities={"amount": "₦145,000", "transactionId": None, "orderId": None, "account": "••••••6671", "card": None},
        evidence=["Customer explicitly denies making the debit", "High-value amount is stated", "Customer requests an urgent account block"],
        response="Hi Ifeanyi, I understand the urgency. This unauthorised ₦145,000 debit has been routed to the fraud team for immediate human review. Do not share your PIN, OTP, password, or card details with anyone.", processing_ms=430,
    ),
    _ticket(
        case_id="KOR-2404", customer_id="CUS-2048", customer=TUNDE, channel="email", received_at="10:20", minutes_ago=26,
        subject="Duplicate card debit", message="My card ending 7721 was charged twice again for ₦18,400 at Market Square. Kindly reverse the duplicate transaction.",
        intent="Duplicate debit", urgency="high", sentiment="frustrated", route="Billing", confidence=.96, memory_used=True,
        entities={"amount": "₦18,400", "transactionId": None, "orderId": None, "account": None, "card": "•••• 7721"},
        evidence=["Customer reports two identical charges", "Amount and card suffix are supplied", "Previous context records a similar resolved dispute"],
        response="Hello Tunde, I can see the card suffix and prior duplicate-debit context, so you will not need to provide them again. The ₦18,400 duplicate charge is routed to Billing for review.", processing_ms=610,
    ),
    _ticket(
        case_id="KOR-2405", customer_id="CUS-5120", customer=BLESSING, channel="whatsapp", received_at="10:12", minutes_ago=34,
        message="I try pay ₦7,250 for light bill, e fail but una remove money. Wetin I go do? Ref PAY-551902.",
        intent="Payment failed", urgency="medium", sentiment="concerned", route="Billing", confidence=.88,
        entities={"amount": "₦7,250", "transactionId": "PAY-551902", "orderId": None, "account": None, "card": None},
        evidence=["Payment failed after debit", "Bill-payment amount is supplied", "Payment reference is present"],
        response="Hi Blessing, sorry about the failed light payment. Billing will review PAY-551902 and the ₦7,250 debit. No need to try the same payment repeatedly while the case is open.", processing_ms=920,
    ),
    _ticket(
        case_id="KOR-2406", customer_id="CUS-4096", customer=EMEKA, channel="email", received_at="09:58", minutes_ago=48,
        subject="Locked out after phone change", message="I changed my phone yesterday and cannot access the business account. I already completed verification last week. Please do not ask me to upload the same documents again.",
        intent="Account access", urgency="high", sentiment="frustrated", route="Account Support", confidence=.86, memory_used=True,
        evidence=["Customer cannot access a business account", "Issue followed a device change", "Prior memory confirms completed verification"],
        response="Hello Emeka, I can see the earlier verification context, so you should not be asked to upload the same documents again. Account Support will review the device-change access issue.", processing_ms=1150,
    ),
    _ticket(
        case_id="KOR-2407", customer_id="CUS-6113", customer=SEYI, channel="whatsapp", received_at="09:41", minutes_ago=65,
        message="Your app says delivered but I no see anything. Order ORD-77401. Rider no call me and nobody for my house collect am.",
        intent="Delivery missing", urgency="high", sentiment="frustrated", route="Logistics", confidence=.91, memory_used=True,
        entities={"amount": None, "transactionId": None, "orderId": "ORD-77401", "account": None, "card": None},
        evidence=["Order is marked delivered but customer denies receipt", "No delivery call was received", "Order ID matches stored context"],
        response="Hi Seyi, I’m sorry ORD-77401 is marked delivered when you have not received it. The case is routed to Logistics for proof-of-delivery review, and you do not need to repeat the order number.", processing_ms=740,
    ),
    _ticket(
        case_id="KOR-2408", customer_id="CUS-7188", customer=FATIMA, channel="email", received_at="09:27", minutes_ago=79,
        subject="Reset link keeps expiring", message="The password reset link has expired for the third time. I need access today to download my statement for an application.",
        intent="Account access", urgency="medium", sentiment="concerned", route="Account Support", confidence=.74, escalated=False, memory_used=True,
        evidence=["Repeated reset-link expiry", "Customer needs time-sensitive statement access", "Stored context prevents repeating prior troubleshooting"],
        response="Hello Fatima, I can see this is the third expired reset link. Account Support will review the reset flow without asking you to repeat the same troubleshooting steps.", processing_ms=1420,
        truth_urgency="high",
    ),
    _ticket(
        case_id="KOR-2409", customer_id="CUS-1042", customer=CHIDINMA, channel="whatsapp", received_at="09:02", minutes_ago=104,
        message="Una said wait 30 minutes yesterday but nothing happen. Same transfer issue. I no fit keep explaining myself every time.",
        intent="Transfer pending", urgency="high", sentiment="frustrated", route="Transfers", confidence=.79, memory_used=True,
        evidence=["Customer reports the same unresolved transfer", "Promised wait period has passed", "Stored memory supplies the missing transaction context"],
        response="Hi Chidinma, you do not need to explain the transfer again. I have linked this message to the existing pending-transfer context and kept it with Transfers for priority review.", processing_ms=1260,
    ),
    _ticket(
        case_id="KOR-2410", customer_id="CUS-3071", customer=AMINA, channel="email", received_at="08:44", minutes_ago=122,
        subject="Change delivery address", message="Can you redirect my package to Abuja instead? I will not be in Kaduna this week. It is the same order I emailed about earlier.",
        intent="Delivery change", urgency="low", sentiment="calm", route="Logistics", confidence=.92, memory_used=True,
        entities={"amount": None, "transactionId": None, "orderId": "ORD-44890", "account": None, "card": None},
        evidence=["Customer requests delivery-address change", "Stored context identifies the order", "Package destination is changing from Kaduna to Abuja"],
        response="Hello Amina, I have linked this request to ORD-44890 from your earlier email. Logistics will confirm whether the destination can still be changed before delivery.", processing_ms=880,
    ),
    _ticket(
        case_id="KOR-2411", customer_id="CUS-5120", customer=BLESSING, channel="whatsapp", received_at="08:16", minutes_ago=150,
        message="How long e dey take to verify account? I submit everything on Friday.",
        intent="Account verification", urgency="low", sentiment="calm", route="Compliance", confidence=.98,
        evidence=["Customer asks about verification timeline", "Documents were submitted on Friday"],
        response="Hi Blessing, your question is about the account-verification timeline. Compliance will review the submission status; please do not send documents or identity numbers again in this chat.", processing_ms=510,
    ),
    _ticket(
        case_id="KOR-2412", customer_id="CUS-2048", customer=TUNDE, channel="email", received_at="07:52", minutes_ago=174,
        subject="Refund timeline", message="Good morning. The merchant confirmed a refund of NGN 12,000 on 8 July. When should it reflect in my balance?",
        intent="Refund pending", urgency="low", sentiment="calm", route="Billing", confidence=.89,
        entities={"amount": "NGN 12,000", "transactionId": None, "orderId": None, "account": None, "card": None},
        evidence=["Merchant reportedly confirmed a refund", "Refund amount and date are supplied"],
        response="Hello Tunde, Billing will review the NGN 12,000 refund timeline from 8 July. The merchant confirmation is noted, but no refund outcome has been assumed.", processing_ms=970,
    ),
    _ticket(
        case_id="KOR-2413", customer_id="CUS-9301", customer=NGOZI, channel="email", received_at="07:35", minutes_ago=191,
        subject="Unexpected monthly service fee", message="Please explain the NGN 2,500 service charge on my July statement. I did not see this fee in June and I need a proper breakdown.",
        intent="General enquiry", urgency="medium", sentiment="concerned", route="Billing", confidence=.83,
        entities={"amount": "NGN 2,500", "transactionId": None, "orderId": None, "account": None, "card": None},
        evidence=["Customer disputes a statement fee", "Charge amount and billing month are supplied"],
        response="Hello Ngozi, Billing will review the NGN 2,500 July service fee and provide the applicable charge description. No adjustment has been made at this stage.", processing_ms=1090,
        truth_intent="Payment failed",
    ),
    _ticket(
        case_id="KOR-2414", customer_id="CUS-9402", customer=KUNLE, channel="whatsapp", received_at="07:18", minutes_ago=208,
        message="Who use my card pay ₦63,900 for online store? Na not me o. Card ends 4458. Make una help me sharp sharp.",
        intent="Fraud report", urgency="high", sentiment="frustrated", route="Fraud", confidence=.99, escalated=True,
        escalation_reason="Unauthorised card transaction requires mandatory fraud review.",
        entities={"amount": "₦63,900", "transactionId": None, "orderId": None, "account": None, "card": "•••• 4458"},
        evidence=["Customer denies the online purchase", "Amount and card suffix are supplied", "Customer requests urgent help"],
        response="Hi Kunle, this ₦63,900 card transaction has been routed to Fraud for urgent human review. Do not share your PIN, OTP, password, CVV, or full card number.", processing_ms=460,
    ),
    _ticket(
        case_id="KOR-2415", customer_id="CUS-9503", customer=ZAINAB, channel="email", received_at="06:54", minutes_ago=232,
        subject="Payroll transfer not received", message="Our employee has not received the NGN 310,000 payroll transfer sent yesterday. Reference TRX-330871. Please investigate before payroll closes.",
        intent="Transfer pending", urgency="medium", sentiment="concerned", route="Transfers", confidence=.72, escalated=True,
        escalation_reason="Confidence is close to the mandatory-review threshold and the payroll impact needs human confirmation.",
        entities={"amount": "NGN 310,000", "transactionId": "TRX-330871", "orderId": None, "account": None, "card": None},
        evidence=["Recipient has not received payroll transfer", "High-value amount and reference are supplied", "Payroll timing creates business impact"],
        response="Hello Zainab, the NGN 310,000 payroll transfer TRX-330871 requires human review before any outcome is stated. It is assigned to Transfers with the payroll timing noted.", processing_ms=1680,
        truth_urgency="high",
    ),
    _ticket(
        case_id="KOR-2416", customer_id="CUS-9604", customer=CHUKS, channel="whatsapp", received_at="06:27", minutes_ago=259,
        message="My package ORD-99014 never reach Lagos and tracking just dey show in transit since two days. Abeg when e go land?",
        intent="Delivery delayed", urgency="low", sentiment="concerned", route="Logistics", confidence=.87,
        entities={"amount": None, "transactionId": None, "orderId": "ORD-99014", "account": None, "card": None},
        evidence=["Package has remained in transit for two days", "Customer requests an updated delivery estimate", "Order ID is supplied"],
        response="Hi Chuks, sorry ORD-99014 has remained in transit. Logistics will review the delayed movement and provide the next confirmed delivery update here.", processing_ms=850,
        truth_urgency="medium",
    ),
    _ticket(
        case_id="KOR-2417", customer_id="CUS-9301", customer=NGOZI, channel="email", received_at="06:03", minutes_ago=283,
        subject="Two charges for one subscription", message="I was billed twice for the same NGN 9,999 subscription renewal this morning. Both entries have reference SUB-7018. Please remove the duplicate.",
        intent="Duplicate debit", urgency="medium", sentiment="frustrated", route="Billing", confidence=.95,
        entities={"amount": "NGN 9,999", "transactionId": "SUB-7018", "orderId": None, "account": None, "card": None},
        evidence=["Two charges share one renewal reference", "Amount and reference are supplied", "Customer identifies one charge as duplicate"],
        response="Hello Ngozi, Billing will review the two NGN 9,999 entries under SUB-7018 and identify the duplicate. No reversal has been claimed before that review.", processing_ms=590,
    ),
    _ticket(
        case_id="KOR-2418", customer_id="CUS-4096", customer=EMEKA, channel="whatsapp", received_at="05:38", minutes_ago=308,
        message="I still no fit enter the merchant dashboard after the security check. This thing don hold my shop since yesterday.",
        intent="Account access", urgency="high", sentiment="frustrated", route="Account Support", confidence=.70, escalated=True, memory_used=True,
        escalation_reason="Confidence is at the mandatory-review threshold and business access remains blocked.",
        evidence=["Merchant dashboard remains inaccessible", "Issue is blocking business activity", "Stored memory confirms prior security review"],
        response="Hi Emeka, I have linked this to the prior security-review context so you will not be asked to start again. Account Support must review the blocked merchant access manually.", processing_ms=1810,
    ),
]


DEMO_HUMAN_DECISIONS = [
    {
        "case_id": "KOR-2401",
        "event_type": "human_approved",
        "minutes_after": 2,
        "decision": {
            "status": "approved",
            "note": "Draft and transfer reference verified before approval.",
        },
        "guardrails": {
            "human_override": False,
            "reason": "Transaction ID and amount match the customer message and stored context.",
        },
        "ticket_updates": {"status": "Approved"},
    },
    {
        "case_id": "KOR-2402",
        "event_type": "human_routed",
        "minutes_after": 3,
        "decision": {"status": "routed", "route": "Logistics"},
        "guardrails": {
            "human_override": False,
            "reason": "Courier follow-up is required to confirm the delayed delivery window.",
        },
        "ticket_updates": {"status": "Routed to Logistics", "route": "Logistics"},
    },
    {
        "case_id": "KOR-2403",
        "event_type": "human_escalated",
        "minutes_after": 4,
        "decision": {
            "status": "assigned_to_specialist",
            "note": "Priority fraud investigation requested.",
        },
        "guardrails": {
            "human_override": True,
            "reason": "Hostile sentiment and an unauthorised high-value debit require Fraud review.",
        },
        "ticket_updates": {"status": "Assigned", "escalated": True},
    },
    {
        "case_id": "KOR-2404",
        "event_type": "human_approved",
        "minutes_after": 5,
        "decision": {
            "status": "approved",
            "note": "Duplicate-debit response verified and approved.",
        },
        "guardrails": {
            "human_override": False,
            "reason": "The amount, merchant, and card suffix provide enough evidence for the drafted response.",
        },
        "ticket_updates": {"status": "Approved"},
    },
    {
        "case_id": "KOR-2405",
        "event_type": "human_routed",
        "minutes_after": 6,
        "decision": {"status": "routed", "route": "Billing"},
        "guardrails": {
            "human_override": False,
            "reason": "The failed bill payment needs Billing to reconcile the debit and payment reference.",
        },
        "ticket_updates": {"status": "Routed to Billing", "route": "Billing"},
    },
    {
        "case_id": "KOR-2407",
        "event_type": "human_escalated",
        "minutes_after": 7,
        "decision": {
            "status": "assigned_to_specialist",
            "note": "Delivery investigation requested.",
        },
        "guardrails": {
            "human_override": True,
            "reason": "The order is marked delivered but the customer denies receipt, so proof of delivery needs review.",
        },
        "ticket_updates": {"status": "Assigned", "escalated": True},
    },
    {
        "case_id": "KOR-2408",
        "event_type": "human_routed",
        "minutes_after": 8,
        "decision": {"status": "routed", "route": "Account Support"},
        "guardrails": {
            "human_override": False,
            "reason": "Confidence is below the normal queue threshold and prior reset links have expired.",
        },
        "ticket_updates": {"status": "Routed to Account Support", "route": "Account Support"},
    },
    {
        "case_id": "KOR-2410",
        "event_type": "human_approved",
        "minutes_after": 9,
        "decision": {
            "status": "approved",
            "note": "Low-risk delivery-change guidance approved.",
        },
        "guardrails": {
            "human_override": False,
            "reason": "The order reference and requested destination are present, and no external action is claimed.",
        },
        "ticket_updates": {"status": "Approved"},
    },
    {
        "case_id": "KOR-2411",
        "event_type": "human_approved",
        "minutes_after": 10,
        "decision": {
            "status": "approved",
            "note": "Verification-timeline response approved.",
        },
        "guardrails": {
            "human_override": False,
            "reason": "This is a low-risk status enquiry with high classification confidence.",
        },
        "ticket_updates": {"status": "Approved"},
    },
    {
        "case_id": "KOR-2414",
        "event_type": "human_escalated",
        "minutes_after": 11,
        "decision": {
            "status": "assigned_to_specialist",
            "note": "Card fraud review requested.",
        },
        "guardrails": {
            "human_override": True,
            "reason": "An unauthorised card transaction cannot be resolved automatically.",
        },
        "ticket_updates": {"status": "Assigned", "escalated": True},
    },
    {
        "case_id": "KOR-2415",
        "event_type": "human_escalated",
        "minutes_after": 12,
        "decision": {
            "status": "assigned_to_specialist",
            "note": "Transfer dispute requires mandatory review.",
        },
        "guardrails": {
            "human_override": True,
            "reason": "Low confidence and a missing transaction reference require a specialist to gather evidence.",
        },
        "ticket_updates": {"status": "Assigned", "escalated": True},
    },
    {
        "case_id": "KOR-2417",
        "event_type": "human_approved",
        "minutes_after": 13,
        "decision": {
            "status": "approved",
            "note": "Duplicate-debit acknowledgement approved.",
        },
        "guardrails": {
            "human_override": False,
            "reason": "Two matching debit references are supplied and the response promises review, not reversal.",
        },
        "ticket_updates": {"status": "Approved"},
    },
]


def seed_demo_data(database: Database) -> None:
    for ticket in DEMO_TICKETS:
        database.add_support_ticket(ticket)
        triage = ticket["triage"]
        if database.latest_triage_for_case(ticket["id"]) is None:
            database.add_audit(
                case_id=ticket["id"],
                customer_id=ticket["customerId"],
                event_type="triage",
                model=MODEL_NAME,
                request={
                    "case_id": ticket["id"],
                    "channel": ticket["channel"],
                    "subject": ticket.get("subject"),
                    "message": ticket["message"],
                },
                decision={
                    "intent": triage["intent"],
                    "urgency": triage["urgency"],
                    "sentiment": triage["sentiment"],
                    "route": triage["route"],
                    "confidence": triage["confidence"],
                    "entities": triage["entities"],
                    "memory_used": triage["memoryUsed"],
                    "evidence": triage["evidence"],
                    "response": triage["response"],
                    "processing_ms": triage["processingMs"],
                    "estimated_minutes_saved": triage["estimatedMinutesSaved"],
                },
                guardrails={
                    "escalated": triage["escalated"],
                    "reason": triage["escalationReason"],
                    "flags": ["seed_snapshot"] + (["mandatory_review"] if triage["escalated"] else []),
                },
                actor="groq-model-seed",
                created_at=ticket["createdAt"],
            )
        database.add_memory(
            ticket["customerId"],
            ticket["id"],
            f'{triage["intent"]}; {triage["urgency"]} urgency; route {triage["route"]}; case {ticket["id"]}.',
            triage["entities"],
            created_at=ticket["createdAt"],
        )

    tickets_by_id = {ticket["id"]: ticket for ticket in DEMO_TICKETS}
    for action in DEMO_HUMAN_DECISIONS:
        ticket = tickets_by_id[action["case_id"]]
        if database.audit_event_exists(ticket["id"], action["event_type"]):
            continue
        event_time = (
            datetime.fromisoformat(ticket["createdAt"])
            + timedelta(minutes=action["minutes_after"])
        ).isoformat()
        database.add_audit(
            case_id=ticket["id"],
            customer_id=ticket["customerId"],
            event_type=action["event_type"],
            model=None,
            request={},
            decision=action["decision"],
            guardrails=action["guardrails"],
            actor="Ada Okafor",
            created_at=event_time,
        )
        database.update_support_ticket_fields(ticket["id"], action["ticket_updates"])

    specialist_by_route = {
        "Transfers": "Musa Ibrahim",
        "Billing": "Musa Ibrahim",
        "Fraud": "Nneka Eze",
        "Compliance": "Nneka Eze",
        "Logistics": "Bola Martins",
        "Account Support": "Bola Martins",
        "General Support": "Ada Okafor",
    }
    for action in DEMO_HUMAN_DECISIONS:
        if action["event_type"] != "human_escalated":
            continue
        ticket = tickets_by_id[action["case_id"]]
        database.set_lifecycle(
            ticket["id"],
            "review_required",
            assigned_to=specialist_by_route[ticket["triage"]["route"]],
        )
