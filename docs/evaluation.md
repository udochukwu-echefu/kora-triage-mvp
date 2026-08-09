# Kora evaluation evidence

All evaluation data in this repository is synthetic and authored for this portfolio demonstration. Results show that the implemented workflow behaves as specified on these cases. They do not establish performance on real customer traffic.

## Suite definitions

| Suite | Cases | Calls Groq | Purpose | Current status |
| --- | ---: | --- | --- | --- |
| Demonstration queue | 18 | No | Populate the first-run interface with stored model-output snapshots | 32 of 36 stored intent and urgency labels match their references (89%) |
| Gold policy dataset | 100 | No during pytest | Exercise deterministic routing, urgency, entities, language, and domain coverage | Included in the 132 passing pytest cases |
| Live Groq smoke set | 11 | Yes | Check schema-constrained model integration across all 11 supported intents | 11/11 passed on 8 August 2026; see `evidence/live-smoke-report.json` |
| Full live benchmark | 100 | Yes | Exploratory model-quality measurement | Latest attempt stopped at 24 of 100 because of provider quota; it is not a completed result |

The suites overlap by design: the fixed 11-case smoke set is selected from the 100-case gold dataset. The 18 demonstration snapshots are a separate UI dataset and must not be described as a live evaluation.

## Gold dataset composition

- 100 cases across six operational domains and 11 intents.
- 50 English, 25 Nigerian Pidgin, and 25 mixed-language cases.
- 56 WhatsApp-style and 44 email-style cases.
- Labels cover intent, urgency, specialist route, and required entities.
- Four phrasing variants are grouped into each authored scenario, so the 100 rows are not 100 independently sourced incidents.

## Fixed smoke set

The smoke command selects one case for every supported intent while retaining all six domains, both channels, and a language mix of four English, four Pidgin, and three mixed-language cases.

```bash
npm run evaluate:smoke
```

The public report records the model, Git commit, start time, dataset composition, completion status, per-case latency, p50-style median and p95 latency, and prompt/completion/total token usage. Provider details and credentials are never written to the public report.

## Latest live smoke result

- **Model:** `openai/gpt-oss-20b`
- **Result:** 11 of 11 synthetic cases completed with correct intent, urgency, route, and required entities.
- **Errors:** None.
- **Latency:** 1.040-second minimum, 13.669-second median, and 16.605-second p95.
- **Token use:** 22,275 total tokens, averaging 2,025 per case.
- **Provenance:** Run on 8 August 2026 from commit `579a44d` with uncommitted evidence instrumentation changes; the public JSON records `git_dirty: true`.

This is an integration smoke result, not a production latency target or broad model-quality claim. The full-benchmark release gate remains false because that gate deliberately requires all 100 cases.

## Scoring

The benchmark scores exact intent, urgency, and specialist route labels. Entity scoring normalises currency formatting and compares only the last four digits of account and card numbers. A live full-run release gate requires all 100 cases, intent accuracy of at least 90%, urgency accuracy of at least 80%, route accuracy of at least 90%, required-entity accuracy of at least 90%, and fraud recall of at least 95%.

An incomplete run can be useful for debugging, but it is never valid evidence for a completed 100-case claim.

## Reproduction

```bash
npm install
npm run backend:setup
cp backend/.env.example backend/.env
npm test
npm run build
npm run evaluate:smoke
```

The test suite does not require a Groq key. A live smoke run requires `GROQ_API_KEY` in `backend/.env` and consumes provider quota.

See [synthetic failure examples](failure-examples.md) and [limitations](limitations.md) before interpreting the results.
