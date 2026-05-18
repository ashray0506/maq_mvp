# PRD — Market Intelligence Platform
**Version:** 1.0 | **Owner:** Analytics Engineering Lead | **Status:** Active

---

## Problem

Post-trade operations management needs external market benchmarks to contextualise bank performance. Currently no automated, auditable source exists — data is pulled manually, inconsistently, with no quality controls.

## Platform Goal

Local-first, production-patterned platform that ingests → transforms → presents → recommends. Use Framework: **See. Judge. Act.**

---

## Architecture

```
Alpha Vantage (SPY daily OHLCV)  ──┐
FRED (FEDFUNDS monthly)          ──┼──▶ Bronze ──▶ Silver ──▶ Gold ──▶ Dashboard
FRED (GS10 10Y Treasury)         ──┘     DQ         DQ         DQ
```

**Bronze:** raw parquet, immutable, one file per source per run  
**Silver:** cleaned, joined on date, UTC-normalised, dimensional model  
**Gold:** computed metrics + business KPIs + market context, dashboard-ready views  
**Dashboard:** two apps — `app.py` (market) · `observability.py` (pipeline health)

**Three FRED series, one ingest pattern.** FEDFUNDS = risk-free rate for Sharpe. GS10 = 10Y Treasury yield for yield curve spread. Same pipe, different `FRED_SERIES` call.

---

## Metrics & KPIs

### Technical Metrics (Gold Layer)
| Metric | Formula | Signal |
|---|---|---|
| VWAP 20d | `SUM((H+L+C)/3 * V) / SUM(V)` rolling | Price vs volume benchmark |
| RSI-14 | Wilder's EMA, 14d | Momentum / overbought-oversold |
| EMA vs SMA 3m | EMA(3) - SMA(3) on FEDFUNDS | Macro regime direction |

### Business KPIs (Gold Layer)
| KPI | Formula | Threshold |
|---|---|---|
| Sharpe Ratio 20d | `MEAN(excess_return) / STDDEV(excess_return) * √252` | <0 = HIGH alert |
| Max Drawdown 90d | Peak-to-trough % over 90d window | <-20% = HIGH alert |
| Volatility 20d | `STDDEV(daily_return) * √252 * 100` | >20% = MEDIUM, >30% = HIGH |
| VWAP Efficiency | `100 - AVG(ABS(close-vwap)/vwap*100, 20d)` | <94 = deviation signal |

**Key join:** FEDFUNDS / 252 = daily risk-free rate for Sharpe. The macro source is not just context — it's an input to risk-adjusted return calculations.

### Market Context (Gold Layer — Pulse Bar)
| Indicator | Source | Signal |
|---|---|---|
| 10Y Treasury Yield (GS10) | FRED `GS10` | Bond market rate benchmark |
| Yield Curve Spread | GS10 - FEDFUNDS | Positive = normal · Negative = inverted (recession signal) |
| Spread trend | 30d change in spread | Widening = bullish macro · Compressing = caution |

**Yield curve spread interpretation:**
- Spread > 0 and widening → bond market pricing future rate cuts → equities historically supportive
- Spread < 0 (inverted) → yield curve inversion → historically precedes recession → caution
- Spread compressing toward 0 → transition regime → watch closely

This is a passive observation layer — no NBA trigger, no RAG signal. It provides macro environmental context for all other signals and KPIs.

---

## Data Quality Rules

### Bronze
| ID | Rule | On Failure |
|---|---|---|
| B1 | API retry 3x, 5s backoff | Log ERROR, skip run |
| B2 | AV rate limit — detect `Note`/`Information` key in JSON | Log ERROR, skip run |
| B3 | Schema validation — expected columns present | Log ERROR, do not write |
| B4 | FRED `"."` → null coercion | Log WARNING with count |

### Silver
| ID | Rule | On Failure |
|---|---|---|
| S1 | Null check on close, volume | Quarantine rows |
| S2 | Completeness ≥ 60 rows | Log WARNING |
| S3 | No future dates | Quarantine rows |
| S4 | Join produces ≥ 3 shared months | Log ERROR, halt |
| S5 | All dates → UTC | Enforced |

### Gold
| ID | Rule | On Failure |
|---|---|---|
| G1 | RSI: null for first 14 rows | Expected — window warmup |
| G2 | VWAP: exclude zero-volume rows | Log count |
| G3 | EMA/SMA: ≥ 3 months macro required | Log ERROR, halt |
| G4 | Sharpe/Vol: null for first 20 rows | Expected — window warmup |
| G5 | Sharpe uses FEDFUNDS/252 as risk-free rate | Verify on every run |

---

## Governance Principles

1. Bronze is immutable — never edited after write
2. Gold is the only permitted dashboard data source
3. No silent failures — every exception logged with context
4. No hardcoded thresholds — all in `VALIDATION_CONFIG`
5. Quarantine not drop — failed records always accounted for
6. Human-written benchmark tests — values computed independently of AI code
7. AI code reviewed — `validate.py` exits 0 before any merge

---

## Epic 1 — Data Pipeline

**Goal:** Working Bronze → Silver → Gold with DQ, audit tables, validate.  
**Git tag:** `v1-pipeline`  
**Done when:** `python pipeline/validate.py` exits 0

### Story 1.1 — Project Scaffold
As an engineer I can clone the repo and install dependencies in under 5 minutes.

**Acceptance:**
- `requirements.txt` installs clean in fresh venv
- `.env.example` documents all required keys
- `data/bronze/`, `logs/` directories exist
- `.gitignore` excludes `.env`, `data/`, `*.duckdb`, `.venv/`

### Story 1.2 — DQ & Audit Framework
As an engineer I have shared DQ helpers before writing any pipeline code.

**Acceptance:**
- `pipeline/quality.py` creates audit tables on import: `audit_pipeline_runs`, `audit_dq_results`, `quarantine_records`
- `get_run_id()`, `log_audit_run()`, `log_dq_result()`, `quarantine()` functions exist
- Quarantine threshold: halt pipeline if >10% of rows quarantined
- No silent exceptions anywhere in this file

### Story 1.3 — Bronze Ingestion
As a data engineer I can ingest raw OHLCV and macro data to bronze parquet files daily.

**Acceptance:**
- `pipeline/ingest.py` fetches Alpha Vantage `TIME_SERIES_DAILY` and FRED `series/observations`
- All secrets via `.env` — no hardcoded keys
- Rules B1–B4 implemented and logged
- `--schedule` flag runs daily at 07:00 via `schedule` library
- Bronze parquet files: `av_SPY_YYYY-MM-DD.parquet`, `fred_FEDFUNDS_YYYY-MM-DD.parquet`
- `pipeline/register_bronze.py` creates DuckDB views `bronze_av`, `bronze_fred`

### Story 1.4 — Silver Transformation
As a data engineer I can promote bronze to a clean, joined, trusted silver layer.

**Acceptance:**
- `pipeline/transform_silver.py` implements rules S1–S5
- Silver view `silver_market` has: date, month, symbol, close, high, low, volume, macro_value, macro_series, loaded_at
- Failed rows quarantined with rule ID, not silently dropped
- All dates UTC-normalised
- Audit rows written for every DQ step

### Story 1.5 — Gold Metrics + Validate
As a data analyst I can query a single gold view containing all metrics and KPIs.

**Acceptance:**
- `pipeline/transform_gold.py` computes: VWAP 20d, RSI-14 (Wilder's EMA), EMA 3m, SMA 3m, Sharpe 20d, MDD 90d, Volatility 20d, VWAP Efficiency
- Sharpe uses `macro_value / 252` as daily risk-free rate
- Gold view `gold_metrics` is the only source for dashboard
- `pipeline/validate.py` runs 12 checks, exits 0 on pass, 1 on any fail
- `tests/` contains 5 human-written benchmark tests with known expected values

---

## Epic 2 — Dashboard

**Goal:** See → Judge → Act in a browser. Pipeline health in a second app.  
**Git tag:** `v2-dashboard`  
**Done when:** both apps run, validate.py still exits 0

### Story 2.1 — Market Dashboard Shell
As a portfolio manager I can open a dashboard that shows current market conditions.

**Acceptance:**
- `streamlit run dashboard/app.py` runs on port 8501
- `VALIDATION_CONFIG` dict at top of file — all thresholds defined here, nowhere else
- DuckDB opened `read_only=False` (NBA tables need writes)
- Checkpoint error handling wraps all logic — user sees which step failed, not a raw traceback
- Metadata footer reads from `audit_pipeline_runs`

### Story 2.2 — See Column
As a portfolio manager I can see price, volume, RSI, and macro trend charts in one column.

**Acceptance:**
- Sticky header: close, VWAP, RSI, Fed Funds, RAG badge
- Filters: ticker dropdown, macro dropdown, lookback slider (30–90 days)
- 4 charts stacked: Price+VWAP (220px), Volume bars (150px), RSI with y-axis 0–100 (180px), EMA vs SMA two lines — blue solid + orange dashed (180px)
- EMA/SMA chart has caption explaining blue=accelerating, orange=lagging

### Story 2.3 — Judge Column
As a portfolio manager I can see what the signals mean and get an AI explanation.

**Acceptance:**
- RAG card large, colour-filled (red/amber/green)
- AI explanation auto-loads on page open — no button press required
- Triggered rules listed below explanation
- Regenerate button clears session state and re-calls LLM
- Custom rule manager in collapsed expander

### Story 2.4 — Act Column + PDF
As a portfolio manager I can take action on a recommendation and export a summary.

**Acceptance:**
- NBA recommendation cards with severity icon
- Action buttons: Send to Trader, Send for Analysis, Add to Report, Flag for Review
- Every action logs a reference ID (`REF-XXXXXXXX`) to `audit_nba_actions`
- PDF export: snapshot table + KPI scorecard + triggered rules + AI rationale + disclaimer
- Action log shows this session's history

### Story 2.5 — Observability Dashboard
As a data engineer I can see pipeline health without opening a terminal.

**Acceptance:**
- `streamlit run dashboard/observability.py` runs on port 8502
- Header: HEALTHY / DEGRADED banner based on last run status
- Issues panel: shows FAIL/WARN DQ results — green if clean
- Three hop cards: Bronze / Silver / Gold — status, rows in/out, DQ rules
- Row flow chart: grouped bar across all three hops
- Quarantine log: table or green empty state
- Run history: sparkline last 7 runs
- Governance expander: metric definitions, DQ standards, data lineage

### Story 2.6 — Market Pulse Bar
As a portfolio manager I can see overall market conditions at a glance in one condensed row.

**Acceptance:**
- Single horizontal bar rendered between sticky header and KPI scorecard
- Left side — equity: SPY close, day change %, RSI value + colour, Volatility
- Right side — macro: Fed Funds rate, 10Y Treasury yield (GS10), yield curve spread (GS10 - FEDFUNDS), spread direction arrow
- Spread colour: green if > 0.5%, amber if -0.5% to 0.5%, red if < -0.5% (inverted)
- Spread trend: ▲ if spread wider vs 30d ago, ▼ if tighter
- No NBA trigger from this bar — observation only, no action
- GS10 ingested from FRED as second macro series alongside FEDFUNDS — same ingest pattern, add `FRED_SERIES_2=GS10` to `.env`
- Data joined in silver on month, surfaced in gold as `gs10_value` column

**Git tag:** `v2-dashboard` → commit + tag after Story 2.5 and 2.6 both done

---

## Epic 3 — Intelligence

**Goal:** Risk-adjusted NBA engine with LLM rationale, business KPIs, PDF.  
**Git tag:** `v3-intelligence`  
**Done when:** full demo flows from signal → KPI → recommendation → PDF

### Story 3.1 — Business KPI Layer
As a portfolio manager I can see risk-adjusted performance KPIs alongside technical signals.

**Acceptance:**
- Sharpe 20d, MDD 90d, Volatility 20d, VWAP Efficiency in `gold_metrics`
- KPI scorecard panel between sticky header and three columns
- Each KPI has RAG colouring: green/amber/red per thresholds in PRD
- Human benchmark tests for Sharpe and MDD with independently computed expected values

### Story 3.2 — NBA Rule Engine
As a portfolio manager I get structured recommendations when market or risk conditions trigger a rule.

**Acceptance:**
- 12 pre-configured rules: 4 technical (RSI, VWAP) + 4 business KPI (Sharpe, MDD, Vol, VWAP Efficiency) + 4 macro (EMA/SMA)
- User-defined rule CRUD via dashboard — save, list, deactivate
- Rules ranked: HIGH → MEDIUM → LOW → USER
- `audit_nba_evaluations` logged on every page load

### Story 3.3 — LLM Rationale
As a portfolio manager I get a plain English explanation of why a recommendation was triggered.

**Acceptance:**
- `call_llm()` uses Kimi API (`moonshot-v1-8k`) — no local model references
- Graceful fallback: if API unavailable, show rule-based summary — never a raw error
- LLM context includes both technical signals AND business KPIs
- `KIMI_API_KEY` in `.env`

### Story 3.4 — Compliance & Audit
As a compliance officer I can retrieve the exact recommendation and data snapshot for any action taken.

**Acceptance:**
- `audit_nba_evaluations` stores: triggered rule IDs, highest severity, full recommendations JSON, LLM rationale text, data snapshot JSON
- `audit_nba_actions` stores: action type, reference ID, session ID, timestamp
- PDF includes disclaimer: "Decision support only. Not financial advice."
- All NBA audit tables queryable from observability dashboard
