# Kora Operations

A polished support triage operations dashboard for a Nigerian fintech or e-commerce SMB.

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

## Frontend stack

- React and Vite
- Tailwind CSS with custom OKLCH theme tokens
- shadcn-style local components customized for this product
- Radix UI dropdowns and tooltips
- Recharts for operational charts
- Lucide React icons
- Self-hosted Manrope font through Fontsource

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

Confidence automation records qualifying approval decisions inside Kora. It does not transmit messages to WhatsApp or email until a delivery provider is integrated.

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
```

Attach a Railway volume at `/data` before relying on customer memory or the
audit trail. Keep the service at one replica while it uses SQLite. Configure the
health check path as `/api/health`.
