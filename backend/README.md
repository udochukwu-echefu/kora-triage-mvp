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
backend/.venv/bin/pip install -r backend/requirements.txt
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8000
```

The API is available at `http://127.0.0.1:8000`, with interactive documentation at `http://127.0.0.1:8000/docs`.

## Endpoints

- `GET /api/health`: provider, model, memory, guardrail, and key status
- `POST /api/triage`: live Groq classification, extraction, response drafting, memory, and audit
- `GET /api/cases`: the persisted processed support queue
- `GET /api/audit`: persisted model and human decisions
- `GET /api/settings/automation`: persisted confidence policy
- `PUT /api/settings/automation`: update confidence thresholds and toggle auto-approval
- `GET /api/customers/{customer_id}/memory`: stored customer context
- `POST /api/cases/{case_id}/approve`: guarded human approval
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
- `GET|POST /api/proof-runs`: run and inspect isolated historical inbox evaluations
- `GET /api/evaluations/summary`: human-feedback and labelled-set metrics
- `GET /api/evaluations/dataset`: manager-only metadata for the 100-case gold set
- `GET /api/evaluations/gate`: manager-only regression gate
- `GET /api/jobs`: manager-only delivery and triage job health
- `POST /api/webhooks/postmark/inbound`: authenticated inbound email adapter
- `POST /api/webhooks/postmark/delivery`: email delivery and bounce updates
- `GET|POST /api/webhooks/whatsapp`: WhatsApp verification and signed inbound messages
- `POST /api/webhooks/inbound`: provider-neutral integration endpoint

On first startup, the API seeds 18 synthetic processed model snapshots into SQLite. Seeding is idempotent and never overwrites a later live Groq triage result for the same case.

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

## Authentication

The portfolio deployment uses `KORA_AUTH_MODE=demo`, which supplies a clearly
identified support-manager principal. Set `KORA_AUTH_MODE=required` to require a
tenant-scoped bearer token stored as a SHA-256 hash in `api_principal`. The web
client reads a provisioned token from the `kora_token` browser local-storage
key. Manager-only endpoints enforce role checks server-side.

## Tests

```bash
PYTHONPATH=backend backend/.venv/bin/pytest -q backend/tests
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
persisted audit record.
