# Melooha

Astrology Q&A app with a Next.js and Tailwind web client and a FastAPI backend.

## Local development

1. Copy `.env.example` to `.env.local` and fill in the private credentials and database URLs you need.
2. Run `npm run setup` to install the web dependencies and prepare the API virtual environment.
3. Run `npm run dev` to apply Alembic migrations, then start the web app, API, and daily-insight worker.

The web app is served at `http://localhost:3000`; FastAPI is served at `http://127.0.0.1:8000`.

## LLM answer provider order

Astrology answers use one backend orchestration entry point. Gemini is primary (`GEMINI_API_KEY`, `GEMINI_MODEL`, default `gemini-3.5-flash-lite`). On a provider failure or a response that remains invalid after one grounding correction, the orchestrator tries Groq (`GROQ_MODEL`, default `openai/gpt-oss-20b`). Groq uses `GROQ_API_KEY` followed by `GROQ_API_KEY_2`, `_3`, and `_4`; failed keys rotate to the next configured key. Transient provider failures use bounded exponential backoff. Invalid requests are not retried.

Each provider has a configurable request timeout. Gemini transient retries and the shared backoff base are configurable with `GEMINI_MAX_TRANSIENT_RETRIES` and `LLM_RETRY_BASE_DELAY_SECONDS`. See `.env.example` for all variable names. Keep API keys server-side; do not add them to `NEXT_PUBLIC_*` variables.

Chat answers use one model generation with semantic `[[SECTION: title]]...[[/SECTION]]` boundaries. The API checks and emits completed sections over SSE (`response_start`, `message_start`, `message_delta`, `message_complete`, then `response_complete`). The web client renders each section in its own assistant bubble and persists the completed section list on the existing question record. If a provider attempt must be replaced after emitting sections, the stream signals a restart and clears that attempt before showing replacement content. Legacy history rows with only `answer_text` continue to render as one bubble. `/ask` reserves one credit and creates one question record before generation. Success updates that record; complete provider failure marks it failed and refunds the reserved credit in the same ledger flow.

The Groq speech-transcription path is a separate feature and keeps its transcription-specific provider behavior.

The eval harness compares both answer providers and pairs each writer with a judge from the other provider.

## Answer quality evaluation

Run the fixed paired provider evaluation with `npm run eval` (full set) or `npm run eval:smoke` (six cases). Both commands use `api/.venv` and the checked-in synthetic fixture inputs; no application database or `.env` file is loaded. Live evaluation requires server-side `GEMINI_API_KEY`, `GEMINI_MODEL`, and at least one `GROQ_API_KEY*`. Gemini answers are judged with Groq; Groq answers are judged with the configured Gemini model, which switches to `gemma-4-26b-a4b-it` if Gemini reports its daily request quota exhausted. Judges must return validated JSON scores for relevance, plain-English clarity, completeness, consistency, grounding, and avoidance of unsupported certainty.

Fixtures use fixed birth inputs and a pinned `2026-11-15T12:00:00Z` evaluation instant. The expected chart snapshots in `docs/eval-chart-fixtures.json` are re-calculated through the app's Kerykeion Lahiri/whole-sign engine on every run; drift fails deterministically and requires reviewing the baseline. D9 and D10 placements use Kerykeion's sidereal absolute ecliptic longitude (`abs_pos`) with the traditional sign-division rules: [Kerykeion subject schema](https://kerykeion.net/python-library/docs/v6/schemas), [Navamsa D9](https://jyotishya.date/learn/navamsa-d9/), and [Dasamsa D10](https://astroword.in/learn/u6-l7). Questions cover D1 basics and placements, house rulers, D9/D10, Vimshottari periods, a coded same-sign Budha-Aditya condition, and requests the chart cannot answer.

The production chart-claim checker plus evaluator checks compare claims with routed facts and exact expected fixture values. Provider runs use the same questions, context, generation settings and checker. Reports include per-provider factual accuracy, grounding, judge interpretation scores, latency, token use, estimated cost, failure examples, and deltas against the previous JSON report. `npm run eval` writes `docs/eval-report.md` and `docs/eval-report.json`; pass `--provider gemini|groq` or threshold flags to narrow/configure a run. Environment thresholds are `EVAL_MIN_FACTUAL_ACCURACY`, `EVAL_MIN_GROUNDING_RATE`, and `EVAL_MIN_INTERPRETATION_QUALITY`. Deterministic factual/grounding failures can fail CI; subjective judge thresholds are advisory by default (`EVAL_STRICT_SUBJECTIVE=1` opts into gating). `docs/eval-report.example.md` and `.json` show the output format with mock results. `npm test` runs deterministic validator and hallucination tests without live providers; CI runs the live smoke set only when both provider credentials are configured.

## Tests

Run backend tests from the repository root with `api/.venv/Scripts/python.exe -m pytest` on Windows or `api/.venv/bin/python -m pytest` on macOS/Linux. API tests use `TEST_DATABASE_URL` when set, otherwise an isolated temporary SQLite database. Run web checks with `npm test`, `npm run lint`, and `npm run typecheck`.
