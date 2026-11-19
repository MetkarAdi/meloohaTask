_Example format only; values below use a mocked writer and judge._

# Astrology answer evaluation

- Questions evaluated: **1** across three engine-verified synthetic charts.
- Deterministic fact checks compare answers with the chart engine's D1/D9/D10, house-lord, nakshatra/pada and Vimshottari values. The LLM judge is supplementary.

## Provider comparison

| Writer | Factual accuracy | Grounding | Interpretation / 5 | Avg latency ms | Avg writer tokens | Avg cost / answer | Critical failures |
|---|---:|---:|---:|---:|---:|---:|---:|
| groq | 100.0% | 100.0% | 4.67 | 0.0 | 38.0 | $0.000074 | 0 |

Judge dimensions are relevance, plain-English clarity, completeness, consistency, grounding and avoidance of unsupported certainty. A missing judge score is reported as unavailable and does not itself fail CI.

## Previous run comparison

No previous JSON report was supplied for comparison.

## Five worst answers

### synthetic-a-ascendant · groq

**Question:** What is my ascendant sign?

**Answer:** Your ascendant is Virgo [F001]. This is a chart starting point for reflection.

**Checks:** factual=pass, grounded=pass, missing expected=none, judge={'relevance': 5, 'clarity': 5, 'completeness': 4, 'consistency': 5, 'grounding': 5, 'certainty_avoidance': 5}.

## Thresholds

- groq critical factual checks: PASS (0 critical violations)
- groq factual accuracy: PASS (100.0% >= 100.0%)
- groq grounding: PASS (100.0% >= 100.0%)
- groq interpretation quality: PASS (4.67 >= 3.00)

## Per-answer details

| Case | Writer | Category | Factual | Grounded | Judge avg | Latency ms | Writer tokens | Total cost USD |
|---|---|---|---|---|---:|---:|---:|---:|
| synthetic-a-ascendant | groq | basic | pass | pass | 4.83 | 0.0 | 38 | 0.000074 |
