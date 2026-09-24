# Kora Groq backend

This is the real AI layer for Kora Triage. It uses Groq Structured Outputs, Pydantic validation, deterministic post-model guardrails, SQLite customer memory, and an audit log.

## Configure the key

From the project root:

```bash
cp backend/.env.example backend/.env
```

Open `backend/.env` and replace the placeholder with your Groq key:

```dotenv
GROQ_API_KEY=gsk_...
GROQ_MODEL=openai/gpt-oss-20b
```

Never commit `backend/.env`.

## Install and run

From the project root, the quickest path is:

```bash
npm run backend:setup
cp backend/.env.example backend/.env
# Add GROQ_API_KEY to backend/.env
npm run dev
```

This starts both the API and frontend. To run only the API:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8000
```

The API is available at `http://127.0.0.1:8000`, with interactive documentation at `http://127.0.0.1:8000/docs`.

## Endpoints

- `GET /api/health`: public liveness check (status and whether AI is configured only)
- `GET /api/integrations`: authenticated channel, job, model, and limit status
- `POST /api/triage`: re-run live triage for a stored case (`case_id`, `customer_id`); content is always read from the database
- `GET /api/cases`: the persisted processed support queue
- `GET /api/audit`: persisted model and human decisions
- `GET /api/settings/automation`: persisted confidence policy
- `PUT /api/settings/automation`: update confidence thresholds and toggle auto-approval
- `GET /api/customers/{customer_id}/memory`: stored customer context
- `POST /api/cases/{case_id}/approve`: guarded human approval (see "Approval rules")
- `POST /api/cases/{case_id}/escalate`: human escalation
- `POST /api/cases/{case_id}/route`: guarded queue routing
- `GET /api/cases/{case_id}/conversation`: persisted inbound and outbound thread
- `POST /api/cases/{case_id}/feedback`: corrected labels and response review outcome
- `POST /api/cases/{case_id}/resolve`: close a case so a later reply can reopen it
- `PUT /api/cases/{case_id}/assignment`: collision-checked claim, assignment, or release
- `GET|POST /api/cases/{case_id}/notes`: private internal collaboration notes
- `POST /api/cases/{case_id}/manual-assessment`: human-owned fallback when AI is unavailable
- `POST /api/cases/{case_id}/verify-transaction`: read-only Paystack verification
- `GET|POST /api/policies`: list and create approved tenant policy sources
- `PUT /api/policies/{policy_id}/state`: activate or pause a policy source
- `GET|POST /api/proof-runs`, `GET /api/proof-runs/{id}`: start (202, runs in the background) and poll isolated historical evaluations
- `GET /api/team`, `PUT /api/team/{id}/availability`: team roster and availability (self or manager)
- `GET /api/evaluations/summary`: human-feedback and labelled-set metrics
- `GET /api/evaluations/dataset`: manager-only metadata for the 100-case gold set
- `GET /api/evaluations/gate`: manager-only regression gate
- `GET /api/jobs`: manager-only delivery and triage job health
- `POST /api/webhooks/postmark/inbound`: authenticated inbound email adapter
- `POST /api/webhooks/postmark/delivery`: email delivery and bounce updates
- `GET|POST /api/webhooks/whatsapp`: WhatsApp verification and signed inbound messages
- `POST /api/webhooks/inbound`: provider-neutral integration endpoint

When `KORA_SEED_DEMO_DATA` is true (the default only in demo auth mode), startup
seeds 18 synthetic processed model snapshots and a four-person roster into
`KORA_DEFAULT_TENANT_ID`. Seeding is idempotent, never overwrites a later live
Groq triage result, and re-anchors the demo tickets' ages so SLA timers stay
realistic. It is off by default outside demo mode so synthetic data never mixes
with real customers.

## Approval rules

- The server records every human approval as `approved`; only the automation
  policy can write an auto-approval record.
- The final reply (AI draft or human edit) is re-checked by the same guardrails
  as AI drafts. Requests for PINs, OTPs, passwords, BVN/NIN, or card details,
  and unverified refund/reversal/contact claims are rejected with `422`.
- A case that is already approved, queued, sent, delivered, or resolved cannot
  be approved again (`409`). The check runs in one transaction, so a double
  click or two agents cannot queue two sends. A new customer message moves the
  case back to review.
- A guardrail-escalated case can be approved by the assigned specialist or a
  manager, with a review note of at least 10 characters. Bulk approval never
  overrides a guardrail.
- Queued sends are re-checked by the worker: a send is cancelled (not retried)
  if the case was resolved or escalated, the customer wrote again, or the
  WhatsApp 24-hour reply window closed.

## Safety boundary

The LLM recommends intent, urgency, routing, entities, and a draft. Deterministic Python code makes the final escalation decision. Fraud, critical urgency, hostile sentiment, low confidence, unsafe requests for credentials, and unverified financial-action claims are blocked or escalated.

## Delivery modes

`KORA_CHANNEL_MODE=demo` is the default. The worker completes the same durable
workflow and writes an outbound conversation record, but no external API is
called. For live email, configure Postmark and point its inbound, delivery, and
bounce webhooks at the endpoints above. For live WhatsApp, configure the Cloud
API token, phone-number ID, verification token, and app secret.

Postmark inbound and delivery webhooks use HTTP Basic authentication configured
with `POSTMARK_WEBHOOK_USERNAME` and `POSTMARK_WEBHOOK_PASSWORD`. Email replies
are threaded by either the original external thread reference or the Message-ID
of a response Kora previously sent. WhatsApp validates Meta's
`X-Hub-Signature-256` against the exact raw request body. Live mode refuses
unsigned or unprotected webhook traffic.

Every webhook is persisted before processing, every job uses a tenant-scoped
idempotency key, and transient failures retry with exponential backoff. A job
moves to `dead` after its final attempt and the case becomes visibly failed.
Jobs left `running` by a restart are reclaimed after `KORA_JOB_LEASE_SECONDS`.
The outbound message row is written as soon as the provider accepts a send, so
a retry after a later failure never messages the customer twice.

Webhooks accept real-world payloads: quoted email history is stripped
(Postmark's `StrippedTextReply` first), oversized bodies and names are clipped
instead of rejected, empty or non-text messages are acknowledged and skipped,
and one malformed WhatsApp item never fails the rest of its batch. Outbound
email sets RFC `In-Reply-To`/`References` headers from the customer's
`Message-ID`, and replies are matched on any referenced ID.

Inbound traffic is routed to a tenant by `KORA_EMAIL_TENANTS`
(`address:tenant,...`) and `KORA_WHATSAPP_TENANTS` (`phone_number_id:tenant`),
falling back to `KORA_DEFAULT_TENANT_ID`. Outbound credentials are shared by
all tenants on one deployment. Webhooks are refused unless
`KORA_WEBHOOK_TOKEN` (or the provider secret) is set;
`KORA_ALLOW_UNSIGNED_WEBHOOKS=true` exists for local development only.

## Authentication

The portfolio deployment uses `KORA_AUTH_MODE=demo`, which supplies a clearly
identified support-manager principal. Because every demo visitor is a manager,
demo mode also enforces a daily AI budget (`KORA_DEMO_DAILY_AI_LIMIT`) and a
smaller proof-run size (`KORA_DEMO_PROOF_CASE_LIMIT`). Per-client rate limits
(`KORA_AI_REQUESTS_PER_MINUTE`, `KORA_WRITE_REQUESTS_PER_MINUTE`) apply in every
mode; set `KORA_TRUST_PROXY_HEADERS=true` behind Railway's proxy so limits use
the real client IP.

Set `KORA_AUTH_MODE=required` to require tenant-scoped bearer tokens, stored
only as SHA-256 hashes. Issue and revoke them with:

```bash
cd backend
.venv/bin/python -m app.manage create-token --tenant acme --user ada --name "Ada Okafor" --role support_manager
.venv/bin/python -m app.manage list-tokens --tenant acme
.venv/bin/python -m app.manage revoke-tokens --tenant acme --user ada
```

The web client shows a sign-in screen that accepts the token and keeps it in
session storage (or local storage when "keep me signed in" is ticked).
Manager-only endpoints enforce role checks server-side.

## Privacy

Before any model call, messages, subjects, context, and notes are redacted:
emails, Nigerian phone numbers in any common format, card numbers (13–19
digits, grouped or not), 11-digit BVN/NIN values, 10-digit account numbers, and
the customer's own name. The last four digits of cards and accounts are kept
for reconciliation. The UI applies the same masking to the queue, the message,
and the conversation history until an agent uses the audited reveal.

## Tests

```bash
PYTHONPATH=backend backend/.venv/bin/pytest -q backend/tests
backend/.venv/bin/ruff check backend
```

## Gold-set evaluation

The demonstration queue remains intentionally small. A separate 100-case gold
set covers transfer disputes, fraud and unauthorised debits, delivery
complaints, duplicate charges, billing disputes, and account issues across
English, Pidgin, and mixed messages.

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.run_evaluation \
  --output backend/data/evaluation-report.json
```

Use `--limit 10` for a smoke run. The full report includes intent, urgency,
routing, entity, domain, and language metrics plus individual failures.
Use `--resume` with the same output path after a quota interruption. Successful
predictions are checkpointed after every case, and the evaluator stops after
the first rate-limit response rather than consuming retries.

Production triage applies `app/triage_policy.py` after the structured model
response. This deterministic layer owns operational urgency, specialist
routing, and reference normalisation; its overrides are included in the
persisted audit record. Its rules must stay general: a test fails if any
three-word phrase in the rules appears verbatim in the gold set. Reports
include a `model_only` block scored before the policy layer, so the model's
own accuracy is visible separately from the rules' contribution.
