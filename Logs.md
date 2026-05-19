# Epic 1 — Core Data Pipeline Foundation

## Overview

Epic 1 established the complete end-to-end market data pipeline foundation, including ingestion, data quality auditing, bronze/silver/gold transformation layers, governance logging, and validation coverage.

All pipeline layers were validated successfully and prepared for production tagging.

---

## Stories Completed

### 1.1 — Project Scaffold

Initial repository structure and project foundations created:

- `requirements.txt`
- `.env.example`
- `.gitignore`
- Complete project folder structure

---

### 1.2 — Data Quality & Governance Framework (`quality.py`)

Implemented the full governance and audit framework:

- Audit tables
- NBA evaluation tables
- `get_run_id()`
- `log_audit_run()`
- `log_dq_result()`
- Quarantine handling framework

This established traceability and observability across all pipeline stages.

---

### 1.3 — Bronze Layer Ingestion

Implemented raw ingestion workflows:

#### `ingest.py`

Integrated:

- Alpha Vantage market ingestion
- FRED macroeconomic ingestion:
  - `FEDFUNDS`
  - `GS10`

Implemented Bronze-stage checks:

- B1–B4 validation rules

#### `register_bronze.py`

Created and registered:

- 3 Bronze DuckDB views

---

### 1.4 — Silver Layer Transformation

Implemented `transform_silver.py`:

- S1–S5 transformation rules
- UTC-standardized joins
- Data quarantine integration
- Cleaned and normalized analytical layer

---

### 1.5 — Gold Layer Metrics + Validation

Implemented `transform_gold.py` with full analytical metric generation.

#### Metrics Generated

- VWAP
- RSI
- EMA
- SMA
- Sharpe Ratio
- Maximum Drawdown (MDD)
- Volatility

#### Validation

Implemented `validate.py`:

- `12/12` validation checks passing
- `25/25` tests passing

---

## Epic 1 Gate Status

- `python pipeline/validate.py` exits successfully with code `0`
- Production-ready for tag: `v1-pipeline`
- Approved to proceed to Epic 2

---

# Epic 2 — Dashboard & User Experience Platform

## Overview

Epic 2 introduced the full interactive analytics dashboard, including:

- SEE / JUDGE / ACT workflow
- Interactive visualizations
- AI-assisted explanations
- PDF reporting
- Operational observability
- Market pulse analytics

---

## Stories Completed

### 2.1 — Application Shell

Implemented `app.py` with:

- `VALIDATION_CONFIG`
- Checkpoint error handling
- Metadata footer
- Application framework initialization

---

### 2.2 — SEE Column Visualization System

Implemented the analytics visualization stack:

- Sticky dashboard header
- 4 vertically stacked charts:
  - Price + VWAP
  - Volume
  - RSI
  - EMA vs SMA

Additional improvements:

- Correct chart sizing
- Theme-consistent colour handling

---

### 2.3 — JUDGE Column Intelligence Layer

Implemented AI-assisted reasoning system:

- RAG-powered recommendation card
- Auto-loaded explanations using `session_state`
- Triggered rule explanations
- Full custom rule CRUD support

---

### 2.4 — ACT Column + PDF Reporting

Implemented action execution layer:

- NBA recommendation cards
- 4 action buttons
- `REF-{uuid8}` audit references
- ReportLab PDF generation
- Session-level action logging

---

### 2.5 — Observability Platform

Implemented `observability.py`.

#### Features

- Health status banner
- Issues monitoring panel
- Pipeline hop cards
- Data flow visualization
- Quarantine log tracking
- Run-history sparkline analytics
- Governance inspection expander

---

### 2.6 — Market Pulse Bar

Implemented compact market analytics row:

- Inline equity metrics
- Macro benchmark metrics
- Yield spread calculations
- Colour-coded indicators
- ▲ / ▼ directional trend indicators

---

## Epic 2 Gate Status

- Both applications return HTTP `200`
- `validate.py` continues to exit successfully with code `0`
- Ready for production tag: `v2-dashboard`
- Approved to proceed to Epic 3

---

# Epic 3 — Intelligence, Rules Engine & Compliance

## Overview

Epic 3 added institutional-grade intelligence capabilities, including:

- KPI validation
- NBA rule orchestration
- LLM rationale generation
- Compliance-grade auditing
- Governance persistence

---

## Stories Completed

### 3.1 — Business KPI Validation

Resolved and validated analytical KPI calculations.

#### Improvements

- Fixed MDD calculation using rolling peak logic with `min_periods=1`
- Verified all 4 KPI metrics in `gold_metrics`

#### Testing

Added `test_sharpe_mdd.py`:

- `10/10` benchmark tests passing

---

### 3.2 — NBA Rule Engine

Implemented enterprise-grade rule engine.

#### Included Rules

##### Technical Rules

- 4 technical indicators

##### KPI Rules

- 4 KPI-based rules

##### Macro Rules

- 4 macroeconomic rules

#### Features

- User rule CRUD inside JUDGE expander
- Severity ranking:
  - `HIGH`
  - `MEDIUM`
  - `LOW`
  - `USER`
- `audit_nba_evaluations` logged on every page load

---

### 3.3 — LLM Rationale Generation

Integrated Kimi LLM:

- Model: `moonshot-v1-8k`

#### Context Includes

- KPI metrics
- Signals
- Triggered rules

#### Failure Handling

- `401` → user-friendly authorization message
- All other failures → deterministic rule-based summary
- Raw errors never exposed to users

---

### 3.4 — Compliance Audit Framework

Enhanced audit persistence.

#### `audit_nba_evaluations`

Stores:

- Triggered rule IDs
- Highest severity
- Recommendation JSON
- LLM rationale
- Data snapshot JSON

#### `audit_nba_actions`

Stores:

- Action reference IDs

#### Additional Compliance Features

- PDF disclaimer enforcement
- NBA audit visibility in observability dashboard

---

## Epic 3 Gate Status

- `validate.py` exits successfully with code `0`
- `35/35` tests passing
- Ready for production tag: `v3-intelligence`

---

# Epic 4 — UI & UX Refinement Sprint

## Overview

Comprehensive UI refinement sprint focused on:

- Typography consistency
- Information hierarchy
- Dashboard readability
- Theming consistency
- Observability redesign

All refinements validated successfully.

---

## Sub-Fixes Completed — `12/12 PASS`

| Fix | Improvement |
|---|---|
| 4.1 | Dashboard title updated from `15px / 500` → `22px / 700` |
| 4.2 | Added `MARKET OVERVIEW` and `MACRO / YIELD` section labels |
| 4.3 | Added `RISK ANALYTICS` section label and synchronized PDF styling |
| 4.4 | Updated all 3 column headers to `13px / 600` with themed divider borders |
| 4.5 | Refactored `observability.py` styling with `_obs_section()` helper, themed cards, chip styling, and improved health banners |

### Result

- All sub-fixes validated successfully
- `12/12 PASS`

---

# Epic 5 — Dashboard Controls & Filtering Improvements

## Overview

Introduced enhanced filtering, preset controls, and dark-mode-compatible UI chips.

---

## Sub-Fixes Completed

| Fix | Improvement |
|---|---|
| 5.1 | Renamed labels: `Ticker` → `Index / instrument`, `Macro Series` → `Benchmark series` |
| 5.2 | Added `1M / 3M / 6M / Max` preset buttons with session-state integration |
| 5.3 | Added compact chip CSS using `_P` palette for dark-mode compatibility |
| 5.4 | Added `VIEW CONTROLS` label and renamed expander to `Filter & period selection` |

### Additional Update

- `lookback_min` adjusted from `30` → `21` trading days for accurate 1M behavior

---

# Epic 6 — Scenario Intelligence & Alerts Expansion

## Overview

Expanded scenario analysis, KPI comparison tooling, projected-rule filtering, AI prompting, and alert workflows.

All updates validated successfully.

---

## Sub-Fixes Completed — `12/12 PASS`

| Fix | Improvement |
|---|---|
| 6.1 | Added expandable scenario explanation cards with: What / How / Assumptions / Watch For |
| 6.2 | Added `render_kpi_comparison()` side-by-side KPI comparison grids |
| 6.3 | Improved volatility shock formula using `equity × annual_vol × √(20/252)` with explanatory expander |
| 6.4 | Added `filter_projected_rules()` using `RULE_METRIC_MAP` with contextual filtering |
| 6.5 | Added AI question chips, scoped prompting context, and `"Reading the data…"` loading state |
| 6.6 | Enhanced alerts UX with plain-English operators, preview cards, and historical backtesting |

---

# Epic 7 — Governance & Pipeline Operations Enhancements

## Overview

Final operational hardening sprint focused on:

- Governance simplification
- Pipeline execution control
- Auto-refresh workflows
- Lock handling
- Production observability

---

## Sub-Fixes Completed

| Fix | Improvement |
|---|---|
| 7.1 | Removed duplicate definitions catalogue from Data Lineage tab |
| 7.2 | Replaced governance subtitle with compact production metadata line |
| 7.3 | Added `run_pipeline()` orchestration with lock-file guard, stale-lock handling, live status updates, and timeout control |
| 7.4 | Added auto-rerun every 2 seconds during active pipeline execution and manual cache-clearing refresh |

---

# Final Validation Status

## Platform Status

- All validation gates passing
- All observability checks operational
- All audit tables functioning
- Full dashboard workflow operational
- Governance + compliance framework active
- LLM fallback handling validated
- PDF export operational
- Pipeline orchestration production-ready

---

# Final Release Readiness

| Version | Status |
|---|---|
| `v1-pipeline` | Ready |
| `v2-dashboard` | Ready |
| `v3-intelligence` | Ready |

---

# Final Test Summary

| Area | Result |
|---|---|
| Validation checks | PASS |
| Unit tests | PASS |
| KPI benchmark tests | PASS |
| Dashboard rendering | PASS |
| Audit logging | PASS |
| Observability | PASS |
| LLM fallback handling | PASS |
| PDF generation | PASS |
| Pipeline orchestration | PASS |


# Epic 8 — Final Layout Alignment & KPI Context Refinements

## Overview

Epic 8 finalized the dashboard structure and interaction model to fully match the approved wireframe layout.

This sprint focused on:

- KPI filtering correctness
- SEE/JUDGE/ACT structural alignment
- Contextual risk analytics placement
- Compact control flows
- Final dashboard hierarchy consistency

All updates validated successfully.

---

## Sub-Fixes Completed — `12/12 PASS`

| Fix | Improvement |
|---|---|
| 8.1 | Added `safe_float(row, col, default)` helper — fully NaN-proof and KeyError-proof KPI access |
| 8.2 | All 5 KPI tiles now source values from `safe_float(latest, col)` using the actively filtered dataframe tied to selected symbol + lookback |
| 8.3 | Moved all 4 charts directly into the SEE column above the divider |
| 8.4 | Relocated Risk Analytics section directly below chart divider with contextual subtitle |
| 8.5 | Removed obsolete full-width `Market detail` section |
| 8.6 | Updated column ratio layout to `[1.3, 1.2, 1.0]` |
| 8.7 | Preserved compact single-line RAG bar behavior from Fix 18.2 |
| 8.8 | Moved filter controls to a full-width control bar above all three dashboard columns |
| 8.9 | Added contextual subtitle: `"contextualises market conditions against performance benchmarks"` |
| 8.10 | Final SEE/JUDGE/ACT structure aligned exactly to approved wireframe |
| 8.11 | Header metric ordering standardized across market + macro rows |
| 8.12 | Final layout spacing, dividers, and footer hierarchy validated across all sections |

---

## Final Dashboard Structure

```text
TOPBAR
title | print | dark toggle

HEADER
Close · VWAP · RSI · Fed Funds | 10Y · Spread · Vol · MDD

LLM PULSE
amber tile

VIEW CONTROLS (full width)
Index ▾ | Macro ▾ | 1M 3M 6M YTD Max [slider]

SEE →
Charts
(Price+VWAP,
Volume,
RSI,
EMA/SMA)

─ divider ─

Risk Analytics
(Sharpe
MDD
Vol
VWAP Eff
Spread)

JUDGE →
RSI signal bar
AI interpretation

─ divider ─

Signals
Ask (collapsed)
My alerts (collapsed)

ACT →
Severity summary
NBA cards
Action buttons
PDF + log

────────────────────────────────────────────

FOOTER
```

---

## Epic 8 Result

- Structure matches approved wireframe exactly
- KPI tiles correctly synchronized to active filters
- SEE / JUDGE / ACT hierarchy finalized
- Risk Analytics repositioned for contextual flow
- Full dashboard layout validated successfully
- `12/12 PASS`