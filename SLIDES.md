# Market Intelligence Platform — Presentation Slides
**Really Big Bank · Post-trade operations · Case study**

---

## Opening spiel (before slide 1 — say this, don't show it)

> "Management asked how markets are trending and whether we can benchmark performance against industry data. What I built answers that question — but built the way you'd build it if you were going to scale it, not just answer it once.
>
> Two sources, three metrics, one dashboard — that's the brief. Underneath that is a medallion architecture with quality enforcement at every hop, a full audit trail, governance definitions, data lineage, and an AI layer that explains what signals mean and recommends what to do. Every design decision has a production upgrade path. The code is the same code you'd write on day one of a real post-trade data platform — it just runs locally."

---

## Slide 1 — Title

**Market Intelligence Platform**
*From manual data pulls to automated market benchmarks*

Post-trade operations management needs external market data to benchmark bank performance against industry conditions. No automated source exists today — pulls are manual, inconsistent, with no audit trail or lineage.

This platform is the measurement and intelligence layer: automated ingestion, enforced quality at every hop, and a decision cockpit surfacing what market conditions mean and what to do about them.

`Medallion architecture` · `DQ at every hop` · `Market + macro benchmarks` · `AI-native workflow` · `Full audit & governance`

*Assessment scope met: 2 sources · 3 metrics · 1 dashboard · built as production-patterned foundation*

---

## Slide 2 — Medallion Architecture

**Three sources. Three quality-enforced layers. Two dashboards.**

```
Alpha Vantage (SPY)  ──┐
FRED · FEDFUNDS      ──┼──▶  Bronze  ──▶  Silver  ──▶  Gold  ──▶  Dashboard
FRED · GS10          ──┘     B1–B4        S1–S5        G1–G5    Market :8501
                             raw parquet  DuckDB views  metrics  Obs.  :8502
                             immutable    cleaned+joined computed
```

**Why these choices**

| Decision | Chosen | Trade-off | Production |
|---|---|---|---|
| SQL store | DuckDB | No multi-user writes | AWS — S3 + Redshift/Athena |
| Bronze format | Parquet | Not human-readable | S3 with versioning |
| Scheduling | `schedule` lib | No DAG/retry | Airflow, no refactor needed |
| Dashboard | Streamlit | Not prod UI | Figma → Looker / custom |
| Layer model | Medallion | More pipeline steps | Same model, cloud infra |

---

## Slide 3 — Metrics & Business KPIs

**Technical signals · assessment scope**

| Metric | Formula | Signal |
|---|---|---|
| VWAP 20d | `SUM((H+L+C)/3 × V) / SUM(V)` | Price vs volume benchmark |
| RSI-14 | Wilder's EMA · α=1/14 | >70 overbought · <30 oversold |
| EMA vs SMA 3m | On FEDFUNDS series | Blue above orange = accelerating |

**Business KPIs · risk-adjusted**

| KPI | Formula | Alert threshold |
|---|---|---|
| Sharpe Ratio 20d | `MEAN(excess return) / STDDEV × √252` | <0 = risk not compensated |
| Max Drawdown 90d | Peak-to-trough % · 90d rolling | <-20% = HIGH |
| Volatility 20d | `STDDEV(returns) × √252 × 100` | >20% = elevated |
| VWAP Efficiency | `100 - AVG(ABS(close-vwap)/vwap, 20d)` | <94 = deviation signal |

**Market context · yield curve**

| Indicator | Source | Signal |
|---|---|---|
| 10Y Treasury (GS10) | FRED GS10 | Bond market benchmark |
| Yield spread | GS10 − FEDFUNDS | Negative = inversion = recession signal |

> **The key insight:** FEDFUNDS / 252 = daily risk-free rate for Sharpe Ratio. The macro source isn't just a chart overlay — it's the input to risk-adjusted return calculations. Same join built in Sprint 1, higher analytical value. Standard used by Charles River IMS and Bloomberg PORT.

---

## Slide 4 — See → Judge → Act Dashboard

**One screen. Market conditions, risk signal, recommended action.**

**Single combined header — two rows:**
```
Close $718.66 ▼1.2%  |  VWAP 20d $692.28  |  RSI-14 70.5  |  Fed Funds 3.64%  |  🔴 Overbought
10Y Treasury 4.21%  |  Spread +0.57% ▲  |  Vol 14.2%  |  MDD -4.1%  |  Run: abc12345 · PASS
```

**KPI scorecard — compact tiles:**
```
Sharpe 20d 0.87 ✅  |  Max DD -4.1% ✅  |  Volatility 14.2% ✅  |  VWAP Eff. 93.8 🟡
```

**Three-column layout:**

| Market conditions (SEE) | Signal analysis (JUDGE) | Recommended actions (ACT) |
|---|---|---|
| Price + VWAP chart | RAG card — large, colour-filled | NBA recommendation cards |
| Volume bars — green/red days | AI explanation — auto-loads on open | 📨 Back office |
| RSI-14 · y-axis forced 0–100 | Triggered rules as chips | 👁 For review |
| EMA vs SMA two clean lines | Regenerate button | 💬 Slack alert |
| Lookback slider filter | | 📋 Add to report |
| | | ⬇ Export PDF |

*Footer: Last run timestamp · Gold rows · DQ 12/12 PASS · Quarantined: 0 · Data: Alpha Vantage · FRED*

**Governance tab (separate tab alongside market view):**
- Metric definitions with formula and source
- Field definitions with sensitivity classification
- Data lineage table — every hop from API to dashboard with DQ rules applied

---

## Slide 5 — Data Quality & Governance

**14 DQ rules across three layers. Every failure logged. Every record accounted for.**

**Bronze — ingest**
| ID | Rule | On Failure |
|---|---|---|
| B1 | Retry 3× with 5s backoff | Log ERROR, skip run |
| B2 | AV rate limit via JSON key — not HTTP status | Log ERROR, skip run |
| B3 | Schema validation before writing | Log ERROR, do not write |
| B4 | FRED `"."` → null with count logged | Log WARNING |

**Silver — transform**
| ID | Rule | On Failure |
|---|---|---|
| S1 | Null check on close, volume | Quarantine rows |
| S2 | Completeness ≥ 60 rows | Log WARNING |
| S3 | No future dates | Quarantine rows |
| S4 | Join ≥ 3 shared months | Log ERROR, halt |
| S5 | All dates → UTC | Enforced |

**Gold — metrics**
| ID | Rule | On Failure |
|---|---|---|
| G1 | RSI null first 14 rows — window warmup | Expected |
| G2 | VWAP excludes zero-volume rows | Log count |
| G3 | ≥ 3 months macro before EMA/SMA | Log ERROR, halt |
| G4 | Sharpe/Vol null first 20 rows | Expected |
| G5 | Sharpe uses FEDFUNDS/252 as risk-free rate | Verify on run |

**Audit & governance tables in DuckDB:**

| Table | Purpose |
|---|---|
| `audit_pipeline_runs` | Rows in/out/quarantined per step per run |
| `audit_dq_results` | PASS/FAIL per rule per run with detail |
| `quarantine_records` | Failed records — rule ID + raw record — never silently dropped |
| `governance_definitions` | Metric and field definitions, formula, source, sensitivity |
| `governance_lineage` | Every data hop from source API to dashboard with DQ rules applied |

> *"A record either passes and moves forward, or is explicitly accounted for in the quarantine table. There is no third option where data disappears silently. The same principle applies to definitions — every metric has a definition, a formula, a source, and an owner, stored in the same database the pipeline writes to."*

---

## Slide 6 — AI Governance & Production Roadmap

**How AI was used, where human correction was applied, and the path to production.**

**AI governance model**

| | |
|---|---|
| AI wrote | Pipeline code, transforms, dashboard shell, audit tables |
| Humans wrote | Benchmark tests with independently computed expected values |
| Gate | `validate.py` exits 0 before any commit — 12 checks across all layers |
| LLM in dashboard | AI analyst grounded in gold_metrics snapshot — not general knowledge |

**Where AI needed correction**

| Issue | What happened | Caught by |
|---|---|---|
| Threshold lowering | Lowered DQ thresholds to pass its own checks | validate.py |
| RSI formula | Used SMA not Wilder's EMA | Human benchmark test |
| API assumption | AXJO unavailable on free tier — not flagged until runtime | Human review |

> *"Governance applies to AI-generated code the same as any other code. The LLM analyst in the dashboard is constrained to the current data snapshot — it cannot hallucinate context it doesn't have. Every LLM call is logged with prompt type, model, latency, and fallback status."*

**Sprint roadmap**

| Tag | What | Status |
|---|---|---|
| `v1-pipeline` | Bronze→Silver→Gold · 14 DQ rules · audit tables · validate.py | ✅ Done |
| `v2-dashboard` | See→Judge→Act · KPI scorecard · market pulse · governance tab · observability | ✅ Done |
| `v3-intelligence` | NBA rules engine · LLM rationale · PDF export · compliance audit trail | 🔲 In build |

**Production path:**
DuckDB → AWS (S3 + Redshift/Athena) · schedule → Airflow · Streamlit → Looker/custom · Governance tables → Alation or Collibra · Premium API for 12-month history · Compliance review before NBA in production

---

## Closing spiel (after demo — say this, don't show it)

> "What I've shown you is a market intelligence platform. What I've actually built is the data engineering foundation you'd need for any analytics product in this space — medallion architecture, DQ enforcement, quarantine not drop, audit tables, governance definitions, lineage from source to dashboard, and a human-in-the-loop governance model for AI-generated code.
>
> The metrics are market benchmarks today. The pattern scales to post-trade operational KPIs — settlement rates, exception volumes, STP rates — same pipeline, different measures. That's the point. You're not just getting an answer to the brief. You're getting the foundation."

---

## If asked "why did you go beyond the brief?"

> "Because the brief said two sources and three metrics, but the role says build the measurement and intelligence layer that underpins operational performance. Those are different problems. The platform answers the brief. The architecture answers the role."

---

## Key lines to remember

| Moment | Line |
|---|---|
| On DuckDB | "Zero infra, reads parquet natively, window functions for RSI and VWAP. Production upgrade is swapping the engine, not the SQL." |
| On quarantine | "A record either passes or is explicitly accounted for. There is no third option." |
| On FRED as risk-free rate | "The macro join isn't just context — it's the input to risk-adjusted returns. Same data, higher analytical value." |
| On AI governance | "The AI optimised for passing checks rather than raising blockers. validate.py caught it. That's why governance applies to AI code too." |
| On governance tab | "Definitions and lineage live in the same database the pipeline writes to. In production, Alation or Collibra. Same pattern, different source." |
| On scope | "The platform answers the brief. The architecture answers the role." |
