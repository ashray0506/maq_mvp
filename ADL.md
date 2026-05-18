# ADL — Architecture Decision Log
**Project:** MAQ_MVP | **Owner:** Analytics Engineering Lead

---

## Decision Summary

| ID | Decision | Chosen | Key Trade-off | Production Path |
|---|---|---|---|---|
| 001 | SQL store | DuckDB | No concurrency | AWS (Macquarie stack) |
| 002 | Bronze format | Parquet | Not human-readable | S3 with versioning |
| 003 | Scheduling | `schedule` lib | No retry/DAG | Airflow, no refactor |
| 004 | Dashboard | Streamlit | Not prod UI | Figma → Looker/Tableau |
| 005 | Layer model | Medallion | More pipeline steps | AWS lakehouse + dbt |
| 006 | Data sources | AV + FRED | Free tier limits | Premium AV, 4 changes |
| 007 | Risk-free rate | FEDFUNDS/252 | Monthly not daily | Same, no change needed |
| 008 | Bad data | Quarantine | More tables | Dedicated schema + alerts |
| 009 | Metrics | VWAP+RSI+Sharpe+MDD | Daily proxy VWAP | Intraday data source |
| 010 | LLM | Kimi API | Smaller model | GPT-4o or Claude, 1 swap |
| 011 | AI governance | Human benchmarks | Human effort | CI gate, same approach |
| 012 | Dashboard split | Two apps | Two commands | Reverse proxy routing |

---

## ADL-001 — DuckDB over PostgreSQL

**Decision:** DuckDB embedded database.

Postgres requires Docker, a daemon, and port management — setup overhead that's out of scope for this assessment. DuckDB needs no infrastructure, reads parquet natively as SQL views, and supports window functions needed for VWAP and RSI-14.

**Trade-off:** DuckDB doesn't support concurrent writes from multiple processes. Fine for a single-user local pipeline, not for a team.

**Out of scope:** Connection pooling, multi-user write access.

**Production:** AWS — most likely given Macquarie's investment in Amazon infrastructure. DuckDB SQL is portable — same queries, different engine underneath.

---

## ADL-002 — Parquet for Bronze

**Decision:** Parquet files, one file per source per run.

DuckDB reads parquet directly so there's no separate load step. Schema is enforced on write. Naming by date (e.g. `av_SPY_2026-05-17.parquet`) gives a natural audit trail with no extra work.

**Trade-off:** Not human-readable without tooling. A CSV is easier to inspect by eye.

**Out of scope:** Compression tuning, partition strategies.

**Production:** S3 with versioning enabled. No pipeline logic changes — just a path swap.

---

## ADL-003 — `schedule` Library over Airflow

**Decision:** `schedule` library with a daily poll loop.

Airflow requires Docker or a dedicated server — out of scope here. `schedule` is 5 lines and self-documenting. The pipeline functions are already modular so the upgrade path is clean.

**Trade-off:** Process must stay alive. No DAG visualisation, no built-in retry on step failure (only on API calls). A killed process means a missed run.

**Out of scope:** DAG dependencies, backfill, alerting on failure.

**Production:** Wrap the existing functions in Airflow tasks. No refactoring of pipeline logic.

---

## ADL-004 — Streamlit over Dash/Flask

**Decision:** Streamlit.

Single command to run, no JS, native Plotly support, hot reload. Enough layout control to demonstrate the See → Judge → Act framework clearly. Non-technical stakeholders can run it themselves.

**Trade-off:** Not a production UI. No multi-user session management, limited layout control compared to a full frontend.

**Out of scope:** Authentication, responsive design, mobile.

**Production:** Streamlit is still good for quick MVPs and demos with non-technical stakeholders who benefit from seeing something working. For a real data product — Figma for design, then build into Looker, Tableau, or a custom frontend depending on the use case.

---

## ADL-005 — Medallion Architecture (Bronze/Silver/Gold)

**Decision:** Three-layer medallion model.

Scalable architecture with a built-in audit trail. Bronze = raw and immutable. Silver = trusted, cleaned, joined. Gold = consumption-ready, metrics computed. Each layer has a defined contract — if something breaks, you know exactly which hop introduced the problem. Maps directly to dbt stages (staging → intermediate → mart).

**Trade-off:** More steps to run than a single-transform approach. Adds pipeline complexity upfront.

**Out of scope:** dbt integration, automated lineage tracking.

**Production:** Replace DuckDB views with an AWS lakehouse — S3 for storage, Glue or dbt for transforms, Redshift or Athena for query. The layer model doesn't change, the infrastructure under it does.

---

## ADL-006 — Alpha Vantage + FRED

**Decision:** Alpha Vantage (market) + FRED (macro).

Both have official documented APIs with free tiers. FRED is the institutional standard for US macro series — used by central banks, academics, and research desks. Yahoo Finance (`yfinance`) is unofficial and scraping-based; it breaks without notice and has no SLA.

**Trade-off:** AV free tier limits output to ~100 days and AXJO isn't reliably available. SPY used for MVP instead.

**MVP delta:** 4 constant changes + premium subscription to get full 12-month history and international symbols. No architecture change.

**Out of scope:** AXJO on free tier, multi-symbol ingestion.

---

## ADL-007 — FRED as Risk-Free Rate Input

**Decision:** FEDFUNDS / 252 = daily risk-free rate for Sharpe Ratio.

The macro data source was designed from the start as an input to risk-adjusted calculations, not just a chart overlay. FEDFUNDS / 252 is the standard daily risk-free rate used by Charles River IMS, Bloomberg PORT, and every institutional risk platform. The silver join we built for EMA/SMA crossover is the same join that feeds Sharpe — same data, higher analytical value.

**Trade-off:** FEDFUNDS is monthly, not daily. We interpolate across the month. A daily risk-free rate series (e.g. SOFR) would be more precise.

**Out of scope:** SOFR integration, daily risk-free rate source.

---

## ADL-008 — Quarantine over Silent Drop

**Decision:** Failed records written to `quarantine_records`, not dropped.

`df.dropna()` destroys the audit trail — you lose the ability to know what was dropped and why. Quarantine means every failed record is accounted for with rule ID, the raw record, and the failure reason. Pipeline continues with clean records. Halts if quarantine exceeds 10% of total rows — that signals a systemic problem, not isolated bad data.

Maps directly to enterprise DQ tools: Great Expectations `store_failures`, dbt `store_failures: true`, Soda quarantine tables.

**Trade-off:** More tables to maintain. Slightly more complex pipeline.

**Out of scope:** Notification on breach, remediation workflow, quarantine sign-off process.

**Production:** Promote quarantine to a dedicated schema. Add Slack/email alert on threshold breach. Compliance team owns the sign-off on quarantined financial data.

---

## ADL-009 — Metric Selection

**Decision:** VWAP + RSI-14 + EMA/SMA crossover (technical) · Sharpe + MDD + Volatility + VWAP Efficiency (business KPIs) · GS10 yield spread (macro context).

**Rejected:**
- Bollinger Bands — redundant with VWAP for this use case
- MACD — overlaps with RSI, adds complexity without differentiation
- SMA-only — EMA/SMA crossover is more informative than either alone

Three analytical dimensions: price structure (VWAP), momentum (RSI), macro regime (EMA/SMA). Four risk dimensions: risk-adjusted return (Sharpe), downside exposure (MDD), market risk (Volatility), price efficiency (VWAP Efficiency). One macro context layer: yield curve spread (GS10 − FEDFUNDS).

**Trade-off:** Daily VWAP is a proxy — true VWAP is intraday. Acknowledged limitation.

**RSI note:** Wilder's smoothed average (α=1/14), not SMA. This was an AI code review finding — the AI defaulted to SMA, caught by human benchmark test.

**Out of scope:** Intraday VWAP, options Greeks, credit spreads.

---

## ADL-010 — Kimi API for LLM

**Decision:** Kimi API (`moonshot-v1-8k`) with rule-based fallback.

Cost-effective for assessment scope. The API format is OpenAI-compatible so swapping to GPT-4o or Claude is one function change — endpoint and model name only. If the API is unavailable, the fallback generates a rule-based summary from current metric values. The dashboard never crashes and never shows raw errors.

**Trade-off:** Smaller model than GPT-4o. Financial reasoning quality is adequate for this use case but wouldn't pass a quant desk standard.

**Out of scope:** Fine-tuning, prompt caching, streaming responses.

**Production:** One function change to swap provider. Compliance review required before any LLM-generated content is used in a regulated trading context.

---

## ADL-011 — Human-in-the-Loop AI Governance

**Decision:** AI writes pipeline code. Humans write benchmark tests with independently computed expected values.

AI can write tests that pass against its own logic — that's not a safeguard. Human-written tests with known values (computed by hand or in a spreadsheet) catch systematic errors the AI can't self-validate against. `validate.py` gates every merge with 12 checks across all layers.

**Observed AI deviations during this build:**
1. Lowered DQ thresholds to pass its own checks — caught by validate.py
2. Didn't flag AXJO API limitation until runtime — human decision required
3. Used SMA instead of Wilder's EMA for RSI — caught by benchmark test
4. Module path error (PYTHONPATH) — didn't verify environment before writing import paths

**Trade-off:** Requires human effort to compute benchmark values independently. Worth it — these are the catches that matter.

**Key principle:** Governance applies to AI-generated code the same as any other code.

---

## ADL-012 — Two Dashboard Apps

**Decision:** `app.py` (market, port 8501) + `observability.py` (pipeline health, port 8502).

Portfolio managers and data engineers have different needs. Mixing them in one app conflates two audiences. The market dashboard is a product for business users. The observability dashboard is an operational tool for engineers. Keeping them separate means each can evolve independently without one audience's requirements breaking the other's experience.

**Trade-off:** Two commands to launch instead of one.

**Out of scope:** Shared authentication, unified navigation, role-based view switching.

**Production:** Deploy both behind a reverse proxy with path-based routing (`/market`, `/ops`). One URL, two apps, one auth layer.
