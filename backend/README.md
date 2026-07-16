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
- `GET /api/evaluations/summary`: human-feedback and labelled-set metrics
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
