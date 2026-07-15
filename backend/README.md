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

On first startup, the API seeds 18 synthetic processed model snapshots into SQLite. Seeding is idempotent and never overwrites a later live Groq triage result for the same case.

## Safety boundary

The LLM recommends intent, urgency, routing, entities, and a draft. Deterministic Python code makes the final escalation decision. Fraud, critical urgency, hostile sentiment, low confidence, unsafe requests for credentials, and unverified financial-action claims are blocked or escalated.

## Tests

```bash
PYTHONPATH=backend backend/.venv/bin/pytest -q backend/tests
```
