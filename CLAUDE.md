# CLAUDE.md — Build Instructions
**Read PRD.md and RUNBOOK.md before writing any code.**

---

## Ground Rules

- Build one story at a time. Confirm it runs before moving to the next.
- No hardcoded secrets, thresholds, or symbols — all via `.env` or `VALIDATION_CONFIG`
- No silent exceptions — every `except` block must log with context
- Gold layer is the only permitted dashboard data source
- DuckDB opened `read_only=False` always — NBA tables need writes
- `python pipeline/validate.py` must exit 0 before moving to next epic

---

## Environment

```bash
python -m venv .venv
source .venv/bin/activate        # mac/linux
pip install -r requirements.txt
cp .env.example .env             # add your keys
```

Required `.env` vars:
```
ALPHA_VANTAGE_API_KEY=
FRED_API_KEY=
SYMBOL=SPY
FRED_SERIES=FEDFUNDS
FRED_SERIES_2=GS10
KIMI_API_KEY=
```

---

## File Structure

```
pipeline/
  quality.py          ← DQ helpers, audit tables — build first
  ingest.py           ← bronze ingestion
  register_bronze.py  ← DuckDB bronze views
  transform_silver.py ← silver layer
  transform_gold.py   ← gold metrics + business KPIs
  validate.py         ← 12 checks, exits 0 or 1
dashboard/
  app.py              ← market dashboard (port 8501)
  observability.py    ← pipeline health (port 8502)
tests/                ← human-written benchmark tests only
```

---
## Tech Stack — Use Exactly These

| Component | Library |
|---|---|
| HTTP requests | `requests` |
| Data | `pandas`, `pyarrow` |
| Database | `duckdb` |
| Scheduling | `schedule` |
| Secrets | `python-dotenv` |
| Dashboard | `streamlit` |
| Tests | `pytest` |

No additional libraries without asking first. No SQLAlchemy, no Airflow, no dbt.
---
## Epic 1 — Pipeline (Stories 1.1–1.5)

Build order: `quality.py` → `ingest.py` → `register_bronze.py` → `transform_silver.py` → `transform_gold.py` → `validate.py`

**Story 1.1 — Scaffold**
- `requirements.txt`, `.env.example`, `.gitignore`, folder structure
- Gitignore: `.env`, `data/`, `*.duckdb`, `.venv/`, `logs/`

**Story 1.2 — quality.py**
- Creates audit tables on import: `audit_pipeline_runs`, `audit_dq_results`, `quarantine_records`
- Functions: `get_run_id()`, `log_audit_run()`, `log_dq_result()`, `quarantine()`
- Halt if quarantine > 10% of rows in run
- Also creates NBA tables: `user_nba_rules`, `audit_nba_actions`, `audit_nba_evaluations`

**Story 1.3 — Bronze**
- `ingest.py`: Alpha Vantage `TIME_SERIES_DAILY` + FRED `series/observations`
- Implement B1–B4 per PRD DQ rules
- `--schedule` flag: daily at 07:00 — runs once without flag
- `register_bronze.py`: DuckDB views `bronze_av`, `bronze_fred` over `data/bronze/*.parquet`

**Story 1.4 — Silver**
- Implement S1–S5 per PRD DQ rules
- Join AV daily to FRED monthly on `DATE_TRUNC('month', date)`
- Output columns: date, month, symbol, close, high, low, volume, macro_value, macro_series, loaded_at
- Write audit row per DQ step. Quarantine failed rows — do not drop.

**Story 1.5 — Gold + Validate**
- Technical: VWAP 20d, RSI-14 (Wilder's α=1/14), EMA 3m, SMA 3m
- Business KPIs: Sharpe 20d, MDD 90d, Volatility 20d, VWAP Efficiency — formulas in PRD
- Sharpe MUST use `macro_value / 252` as daily risk-free rate
- Implement G1–G5
- `validate.py`: 12 checks, PASS/FAIL per line, exit 0 or 1
- `tests/`: 5 benchmark files — RSI, VWAP, bronze schema, silver join, DQ null logging
- Expected values computed independently — not from pipeline code

**Gate:** `python pipeline/validate.py` exits 0 → commit + tag `v1-pipeline`

---

## Epic 2 — Dashboard (Stories 2.1–2.5)

**Story 2.1 — Shell**
- `VALIDATION_CONFIG` at top of `app.py` — all thresholds here only
- Checkpoint error handling: label each block, show label on failure, `st.stop()`
- Metadata footer from `audit_pipeline_runs`

**Story 2.2 — SEE Column**
- Sticky header: close, VWAP, RSI, Fed Funds, RAG badge
- Filters: ticker, macro series, days slider 30–90
- 4 charts: Price+VWAP (220px) · Volume green/red (150px) · RSI y-axis forced 0–100 (180px) · EMA vs SMA two lines (180px)
- EMA = blue solid, SMA = orange dashed, caption explains signal

**Story 2.3 — JUDGE Column**
- RAG card: full colour fill, RSI value + label
- AI explanation auto-loads on open via `st.session_state`
- Triggered rules listed, regenerate button

**Story 2.4 — ACT Column + PDF**
- NBA cards with action buttons per rule
- Every action logs `REF-{uuid8}` to `audit_nba_actions`
- PDF: ReportLab — snapshot + KPI scorecard + rules + rationale + disclaimer
- Action log: last 10 this session

**Story 2.5 — Observability**
- Separate file `observability.py` — never touch `app.py` during this story
- Order: health banner → issues panel → hop cards (Bronze/Silver/Gold) → row flow chart → quarantine log → run history sparkline → governance expander

**Story 2.6 — Market Pulse Bar**
- Single condensed row between sticky header and KPI scorecard
- Fetch GS10 from FRED using same ingest pattern as FEDFUNDS — add to `ingest.py`, register as `bronze_fred_gs10` view
- Join in silver on month as `gs10_value` column in `silver_market`
- Compute `yield_spread = gs10_value - macro_value` in gold
- Spread trend: compare current spread to 30d average — ▲ widening, ▼ compressing
- Render as two groups inline: equity metrics left, macro/yield metrics right
- Spread colour: green > 0.5% · amber -0.5% to 0.5% · red < -0.5%
- No NBA trigger — observation only

**Gate:** both apps run, validate.py exits 0 → commit + tag `v2-dashboard`

---

## Epic 3 — Intelligence (Stories 3.1–3.4)

**Story 3.1 — Business KPIs**
- Add Sharpe, MDD, Volatility, VWAP Efficiency to `transform_gold.py`
- KPI scorecard panel in `app.py` between header and columns
- RAG per PRD thresholds
- Benchmark tests for Sharpe and MDD

**Story 3.2 — NBA Rules**
- `evaluate_nba_rules(df, con)`: 12 pre-configured rules (4 technical + 4 KPI + 4 macro)
- User rule CRUD in JUDGE column expander
- Log to `audit_nba_evaluations` every evaluation

**Story 3.3 — LLM**
- Kimi API only — `moonshot-v1-8k`
- 401 → specific message. Any other failure → rule-based summary. Never raw error.
- Context includes technical signals AND business KPIs

**Story 3.4 — Compliance Audit**
- `audit_nba_evaluations`: store recommendations JSON + rationale + data snapshot
- PDF disclaimer: "Decision support only. Not financial advice."
- NBA data visible in observability dashboard

**Gate:** full demo runs end-to-end → commit + tag `v3-intelligence`

---

## What NOT to Do

- Read bronze/silver in dashboard
- Hardcode any threshold, symbol, or key
- Show raw exceptions to users
- Write silver/gold as parquet — views only
- Modify `observability.py` when working on `app.py` or vice versa
- Adjust validate.py thresholds to force a pass
- Generate benchmark test values from pipeline code
- Batch stories
