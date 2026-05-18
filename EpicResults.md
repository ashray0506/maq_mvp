## Epic 1 Complete

| Story | Status |
|---|---|
| 1.1 Scaffold | `requirements.txt`, `.env.example`, `.gitignore`, all folders |
| 1.2 quality.py | Audit tables, NBA tables, `get_run_id`, `log_audit_run`, `log_dq_result`, `quarantine` |
| 1.3 Bronze | `ingest.py` (AV + FEDFUNDS + GS10, B1–B4), `register_bronze.py` (3 views) |
| 1.4 Silver | `transform_silver.py` (S1–S5, UTC join, quarantine) |
| 1.5 Gold + Validate | `transform_gold.py` (VWAP / RSI / EMA / SMA / Sharpe / MDD / Vol), `validate.py` 12/12 PASS, 25 tests all PASS |

### Gate Status

- `python pipeline/validate.py` exits `0`
- Ready to tag `v1-pipeline`
- Ready to move to Epic 2


## Epic 2 Complete

| Story | Status |
|---|---|
| 2.1 Shell | `app.py` with `VALIDATION_CONFIG`, checkpoint error handling, metadata footer |
| 2.2 SEE column | Sticky header, 4 stacked charts (Price+VWAP / Volume / RSI / EMA-SMA) with correct heights and colours |
| 2.3 JUDGE column | RAG card, AI explanation auto-loaded via `session_state`, triggered rules, custom rule CRUD |
| 2.4 ACT column + PDF | NBA cards with 4 action buttons, `REF-{uuid8}` audit logging, ReportLab PDF, session action log |
| 2.5 Observability | `observability.py` — health banner, issues panel, hop cards, row flow chart, quarantine log, run history sparkline, governance expander |
| 2.6 Market Pulse Bar | Inline equity + macro row, yield spread with colour coding and ▲/▼ trend |

### Gate Status

- Both apps respond with HTTP 200
- `validate.py` still exits `0`
- Ready to tag `v2-dashboard`
- Ready to move to Epic 3

## Epic 3 Complete

| Story | Status |
|---|---|
| 3.1 Business KPIs | Fixed MDD formula (rolling peak with `min_periods=1`), verified all 4 KPIs in `gold_metrics`, added `test_sharpe_mdd.py` (10 benchmark tests, all pass) |
| 3.2 NBA Rule Engine | 12 pre-configured rules (4 technical + 4 KPI + 4 macro), user CRUD in JUDGE expander, ranked `HIGH → MEDIUM → LOW → USER`, `audit_nba_evaluations` logged on every page load |
| 3.3 LLM Rationale | Kimi `moonshot-v1-8k` with context including all KPIs + signals; `401 →` specific message; any other failure → rule-based summary; never raw error |
| 3.4 Compliance Audit | `audit_nba_evaluations` stores triggered rule IDs, highest severity, full recommendations JSON, LLM rationale, data snapshot JSON; `audit_nba_actions` stores REF IDs; PDF disclaimer present; NBA tables visible in observability |

### Gate Status

- `validate.py` exits `0`
- `35/35` tests pass
- Ready to tag `v3-intelligence`


All 5 sub-fixes applied successfully — **12/12 PASS**

| Fix | Change |
|------|--------|
| **11.1** | Title updated from `font-size:15px / weight:500` → `22px / 700` |
| **11.2** | Added **MARKET OVERVIEW** label above equity row; added **MACRO / YIELD** label with separator before macro row |
| **11.3** | Added **RISK ANALYTICS** section label before KPI tiles; PDF updated to match |
| **11.4** | Updated all 3 column headers → `13px / 600` weight with bottom border divider, themed with `_P` |
| **11.5** | `observability.py` updates: page CSS + styled title bar; `_obs_section()` helper replaces all `st.subheader`; health banner uses `✓/⚠` styled cards; issues use chip styling; hop cards now match KPI tile pattern |

**Result:** All sub-fixes validated successfully (`12/12 PASS`)


All 4 sub-fixes applied successfully

| Sub-fix | Change |
|----------|--------|
| **12.1** | Renamed labels: `"Ticker"` → `"Index / instrument"` and `"Macro Series"` → `"Benchmark series"` |
| **12.2** | Added `1M / 3M / 6M / Max` preset buttons wired to `session_state["selected_days"]`; added fine-tune slider with `label_visibility="collapsed"` and minimum step of `7` days |
| **12.3** | Added compact chip CSS scoped to `div[data-testid="column"]`; styling now uses `_P` palette for full dark mode compatibility |
| **12.4** | Added uppercase **VIEW CONTROLS** label above sidebar; renamed expander to `"Filter & period selection"` |

Additional update:
- `lookback_min` changed from `30` → `21` trading days to align with the true `1M` preset behavior.