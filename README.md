# Kora

[![CI](https://github.com/udochukwu-echefu/kora-triage-mvp/actions/workflows/ci.yml/badge.svg)](https://github.com/udochukwu-echefu/kora-triage-mvp/actions/workflows/ci.yml)

Kora is a support inbox for a Nigerian fintech or online store. Customers write in on WhatsApp or email, often in Pidgin or a mix of Pidgin and English, and Kora works out what they need before an agent even opens the message: what the problem is, how urgent it is, which team should handle it, and a first draft of the reply. An agent still reads every draft and decides what gets sent.

It's a portfolio project. The public demo runs on made-up customers with a demo login, and sending is simulated, so nothing there reaches a real person.

**Live demo:** [kora-web-production-3c3c.up.railway.app](https://kora-web-production-3c3c.up.railway.app) (the workspace itself is at `/app`)

## What happens to a message

1. A message arrives through the Postmark (email) or WhatsApp Cloud API webhook and is saved immediately, so nothing gets lost if the AI is down.
2. Before anything leaves the server, phone numbers, email addresses, card and account numbers, BVNs and the customer's name are stripped out. The last four digits of cards and accounts are kept so agents can still match transactions.
3. A model hosted on Groq (`openai/gpt-oss-20b` by default) classifies the message, pulls out amounts and references, and drafts a reply based on any company policies you've approved.
4. Plain Python rules have the final say on routing and urgency. Fraud always goes to the Fraud team, and a failed payroll payment over ₦100,000 is always critical, whatever the model thinks.
5. Guardrails hand the case to a person when something looks risky: a fraud report, an angry customer, low confidence, a threat to involve a lawyer or the press, or a draft that asks for a PIN or promises a refund nobody has approved.
6. An agent reviews the case, edits the reply if needed, and approves, escalates or resolves it. Every step is written to an audit log.

Auto-approval exists, but it's off by default and deliberately hard to switch on. A case only qualifies if an approved policy matches it, a delivery channel is connected, every guardrail passes and the model is highly confident.

If you add a Paystack key, agents can check a transaction's status from inside the case. It's read-only: Kora can't move money.

## Things to try in the demo

- Open a fraud case. It can't be approved until a specialist or manager signs off with a note explaining why.
- Edit a draft so it asks the customer for their OTP, then try to approve it. The server refuses.
- Click **Reveal sensitive details** on a case, then look at the audit trail. The reveal is logged.
- Upload a CSV of past conversations under **Historical evaluation** to see how Kora would have handled them, without contacting anyone. The public demo takes up to 12 cases per run.

## Running it locally

You'll need Node 22 and Python 3.12 or newer.

```bash
npm install
npm run backend:setup
cp backend/.env.example backend/.env
```

Add a Groq API key to `backend/.env`, then start everything:

```bash
npm run dev
```

The API runs on port 8000 and the app on [localhost:4173](http://localhost:4173). Without a Groq key the app still works, but new messages have to be classified by hand. There's no offline model.

To run the tests (pytest for the backend, Vitest for the frontend) and the linters:

```bash
npm test
npm run lint
```

## How well does it work?

Not proven yet. There's a set of 100 synthetic complaints (English, Pidgin and mixed, across six kinds of problem), and `npm run evaluate` scores the model against it. `npm run evaluate:smoke` runs a quicker 11-case version and saves the result to `evidence/live-smoke-report.json`.

The last smoke run, in August 2026, scored 11 out of 11, but I don't trust that number. At the time, the routing rules contained phrases copied straight from the test set, so part of the score came from the rules recognising the questions rather than understanding them. The rules have since been rewritten, a test now fails if that happens again, and reports show the model's own accuracy separately from the rules. The benchmark needs re-running before any number is worth quoting.

Even then, the test set is small, synthetic and labelled by one person. [docs/limitations.md](docs/limitations.md) covers the rest.

## Deploying

Kora is set up for Railway: one Docker container serves both the API and the built frontend, and every push to `main` deploys automatically.

For the public demo, these variables are enough:

```dotenv
GROQ_API_KEY=your-groq-key
KORA_DATABASE_PATH=/data/kora.db
KORA_TRUST_PROXY_HEADERS=true
```

Everything else defaults to demo mode. A few things worth knowing:

- Attach a volume at `/data`, or the database is wiped on every deploy. Stick to one replica, since it's SQLite.
- In demo mode every visitor is a manager, so there's a per-visitor rate limit and a daily cap on AI calls to protect your Groq quota.
- For real use, set `KORA_AUTH_MODE=required` and give each teammate a login token with `python -m app.manage create-token`. The details are in [backend/README.md](backend/README.md).
- To actually send replies, add your Postmark or WhatsApp credentials (listed in [backend/.env.example](backend/.env.example)), set `KORA_CHANNEL_MODE=live` and set `KORA_WEBHOOK_TOKEN`. Webhooks are refused until a secret is configured.

## Built with

FastAPI, Pydantic and SQLite on the backend; React, Vite, Tailwind CSS and Radix UI on the frontend; Groq for the model.

## More detail

- [Architecture](docs/architecture.md)
- [How the evaluation works](docs/evaluation.md)
- [Examples of where it gets things wrong](docs/failure-examples.md)
- [Limitations](docs/limitations.md)
- [API endpoints and safety rules](backend/README.md)
