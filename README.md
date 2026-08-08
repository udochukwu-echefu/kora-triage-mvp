# Kora Operations

[![CI](https://github.com/udochukwu-echefu/kora-triage-mvp/actions/workflows/ci.yml/badge.svg)](https://github.com/udochukwu-echefu/kora-triage-mvp/actions/workflows/ci.yml)

A support-triage portfolio demonstration for a Nigerian fintech or e-commerce SMB. The public deployment uses synthetic data, demo authentication, and simulated delivery; it is not connected to a real support operation.

**Evidence:** [architecture](docs/architecture.md) · [evaluation methodology](docs/evaluation.md) · [11-case live smoke report](evidence/live-smoke-report.json) · [failure examples](docs/failure-examples.md) · [limitations](docs/limitations.md) · [132-test summary](evidence/test-summary.json)

Latest verification: 132 backend tests pass. A fresh 11-case synthetic Groq smoke run on 8 August 2026 passed 11/11 with 13.669-second median latency, 16.605-second p95 latency, and 22,275 total tokens. These are demo measurements, not customer-traffic evidence.

## Product capabilities

- Synthetic WhatsApp and email messages in English and Nigerian Pidgin
- Intent, urgency, and sentiment classification
- Extraction of amounts, transaction IDs, order IDs, account suffixes, and card suffixes
- Confidence, hostility, and critical-risk escalation rules
- Customer memory for repeat conversations
- Editable response drafts with explicit human approval
- Operational metrics, routing insights, and a decision audit trail
- 18 realistic processed model snapshots for a useful first-run queue
- Confidence-threshold automation controls with mandatory-review boundaries
- SLA-at-risk flags, queue filters, and guarded bulk actions
- Loading, empty, filtered, and responsive interface states
- Idempotent inbound email and WhatsApp webhook adapters
- Persistent conversation threads with resolved and reopened case states
- Durable background triage and delivery jobs with retries and dead-letter status
- Human correction capture and a release regression gate
- Tenant-scoped bearer-token roles for non-demo deployments
- A separate 100-case gold evaluation set covering six operational domains,
  English, Nigerian Pidgin, mixed language, WhatsApp, and email
- Tenant-scoped approved policy knowledge with versioned citations in each decision
- Silent Proof Mode for evaluating up to 100 historical cases without delivery
- Read-only Paystack verification restricted to references extracted from the case
- Collision-checked case claiming, named ownership, internal notes, and mentions
- Explicit degraded mode with AI retries and a human-owned manual assessment path

## Frontend stack

- React and Vite
- Tailwind CSS with custom OKLCH theme tokens
- shadcn-style local components customized for this product
- Radix UI dropdowns and tooltips
- Recharts for operational charts
- Lucide React icons
- Self-hosted Elms Sans Variable font through Fontsource

## Run locally

```bash
npm install
npm run backend:setup
cp backend/.env.example backend/.env
npm test
npm run dev
```

Add a real `GROQ_API_KEY` to `backend/.env`, then open `http://localhost:4173`.
`npm run dev` starts both FastAPI on port 8000 and Vite on port 4173. Live triage remains blocked if the Groq key is missing or invalid; there is no local classification fallback.

## Production build

```bash
npm run build
npm run preview
```

The first run seeds 18 labelled, fully processed model snapshots into SQLite so the queue, insights, routing mix, memory, and audit views are immediately useful. These records are clearly labelled **Model snapshot** in the interface and can be refreshed through Groq with **Refresh with live AI**. There is no local classification fallback for new live requests. Before a Groq request, the backend redacts phone numbers, email addresses, full account numbers, customer names, and identifiers embedded in customer notes. Fraud, critical urgency, hostile sentiment, low confidence, unsafe credential requests, invented external actions, and unverified completion claims are handled by deterministic guardrails.

The dashboard calculates live intent-and-urgency accuracy against the labelled synthetic dataset and estimates handling-time savings against the configurable `KORA_MANUAL_BASELINE_MINUTES` baseline. The Audit tab loads persisted model and human decisions from SQLite and can export them as CSV. Customer memory is deduplicated by customer and case before it is supplied to Groq.

Run the live 100-case model benchmark separately from the demonstration queue:

```bash
npm run evaluate
```

The report is written to the ignored
`backend/data/evaluation-report.json`. It scores intent, urgency, route,
required entities, unexpected entities, language groups, and operational
domains without adding benchmark records to the agent queue.
If Groq's daily quota interrupts a run, repeat the underlying command with
`--resume`; successful predictions are loaded from the adjacent ignored
checkpoint instead of being requested again.

Run the fixed 11-case live smoke set with latency and token tracking:

```bash
npm run evaluate:smoke
```

The smoke report is written to the public `evidence/live-smoke-report.json` file. It uses synthetic cases and must not be interpreted as customer-traffic validation.

Kora uses a hybrid decision path: Groq performs language understanding,
classification, entity extraction, and response drafting. A deterministic
operational-policy layer then normalises specialist routing, SLA urgency, and
reference placement. Every policy override is persisted with the audit decision.

Confidence automation can queue eligible responses for delivery. `KORA_CHANNEL_MODE=demo` safely records an outbound message without contacting a customer. Switch to `live` only after configuring Postmark or WhatsApp Cloud API credentials and their signed webhooks.

Approved policies are managed in **Settings**. Matching is tenant-scoped and
transparent: Kora includes the matched title, version, excerpt, and source URL
in the decision record. Customer-supplied notes are never trusted as policy.

**Proof mode** runs historical JSON cases through the same live model, policy,
and guardrail path under an isolated proof tenant. Proof cases are not inserted
into the support queue and no delivery job is created, including for
high-confidence results.

Set `PAYSTACK_SECRET_KEY` to enable read-only transaction verification. Kora
only verifies the reference already extracted and audited for the selected
case. The connector does not initialize payments, transfers, reversals, or
refunds.

If Groq is unavailable, inbound webhooks still create durable cases. Failed
triage jobs retry with backoff and then move to a visible manual-review state.
Agents can record a human assessment and response draft without model output;
manual assessments never auto-approve.

See `backend/README.md` for API endpoints and the production safety boundary.

## Deploy to Railway

The production container builds the Vite frontend and serves it from FastAPI on
the same domain.

Set these Railway variables:

```dotenv
GROQ_API_KEY=your_live_groq_key
GROQ_MODEL=openai/gpt-oss-20b
KORA_DATABASE_PATH=/data/kora.db
KORA_MANUAL_BASELINE_MINUTES=12
KORA_AUTH_MODE=demo
KORA_CHANNEL_MODE=demo
KORA_WEBHOOK_TOKEN=replace-with-a-long-random-value
```

Attach a Railway volume at `/data` before relying on customer memory or the
audit trail. Keep the service at one replica while it uses SQLite. Configure the
health check path as `/api/health`.

For live channels, add the provider variables listed in `backend/.env.example`,
change `KORA_CHANNEL_MODE` to `live`, and register the Railway webhook URLs.
Keep the public portfolio deployment in demo auth unless it is placed behind a
real identity provider or provisioned bearer tokens.

Postmark webhook endpoints support HTTP Basic authentication because Postmark
cannot be assumed to attach Kora's custom header. Set
`POSTMARK_WEBHOOK_USERNAME` and `POSTMARK_WEBHOOK_PASSWORD`, then include those
credentials in the inbound and delivery webhook URLs. WhatsApp webhook
signatures are verified against the exact raw request body using
`WHATSAPP_APP_SECRET`. Live channel mode fails closed when the relevant
webhook secret is absent.
