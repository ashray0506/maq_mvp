# Market Analytics Platform
Case study for Really Big Bank — post-trade operations analytics.

Management needs external market benchmarks to contextualise bank
performance against industry conditions. This platform automates
that: ingest public market and macro data, enforce quality at every
hop, and surface what conditions mean and what to do about them.

Built to the standard you'd apply from day one in a post-trade
environment — medallion architecture, DQ enforcement, full audit
trail, AI-native workflow.

**Assessment scope:** 2 sources · 3 metrics · 1 dashboard.
Platform demonstrates the engineering foundation for a broader
post-trade intelligence layer.

---

## Quick start

```bash
git clone git@github.com:ashray0506/MAQ_MVP.git
cd MAQ_MVP

python -m venv .venv
source .venv/bin/activate       # windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env            # add your API keys
```

Free API keys:
- Alpha Vantage: alphavantage.co/support/#api-key
- FRED: fred.stlouisfed.org/docs/api/api_key.html
- Kimi: platform.moonshot.cn (for AI analyst feature)

---

## Run the pipeline

```bash
python pipeline/ingest.py
python pipeline/register_bronze.py
PYTHONPATH=. python pipeline/transform_silver.py
PYTHONPATH=. python pipeline/transform_gold.py
python pipeline/validate.py                    # must exit 0

streamlit run dashboard/app.py                 # platform on :8501
streamlit run dashboard/observability.py       # pipeline health on :8502
```

---

## Platform structure

```
Home (landing page)
├── Market Analytics — 90-day trend, RSI, macro, risk KPIs, NBA
├── What-if — volatility shock, drawdown, rate change simulator
├── Governance — metric definitions, lineage, DQ catalogue
├── Observability — pipeline health, DQ outcomes, run history
├── Architecture — strategic diagram, MVP vs production
└── Runbook — ops guide, troubleshooting, handoff
```

---

## Architecture

```
Alpha Vantage (SPY) ──┐
                       ├──▶ Bronze ──▶ Silver ──▶ Gold ──▶ Dashboard
FRED (FEDFUNDS+GS10) ──┘     DQ         DQ         DQ
```

**Bronze** — raw parquet, immutable, one file per source per run
**Silver** — cleaned, joined, UTC-normalised, dimensional model
**Gold** — VWAP · RSI-14 · EMA/SMA · Sharpe · MDD · Volatility ·
           VWAP Efficiency · Yield Spread

FRED's Fed Funds Rate / 252 = daily risk-free rate for Sharpe.
The macro join built in Sprint 1 is the input to risk-adjusted
return calculations, not just a chart overlay.

---

## Metrics

| Metric | Formula | Signal |
|---|---|---|
| VWAP 20d | SUM((H+L+C)/3 × V) / SUM(V) | Price vs volume benchmark |
| RSI-14 | Wilder's EMA α=1/14 | >70 overbought · <30 oversold |
| EMA vs SMA 3m | On FEDFUNDS | Macro regime direction |
| Sharpe 20d | MEAN(excess) / STDDEV × √252 | Risk-adjusted return |
| Max Drawdown 90d | Peak-to-trough % | Downside risk |
| Volatility 20d | STDDEV × √252 | Market risk level |
| Yield Spread | GS10 − FEDFUNDS | Curve inversion signal |

---

## Data quality

14 rules across Bronze (B1-B4), Silver (S1-S5), Gold (G1-G5).
Every failure logged. Every record accounted for — quarantine not drop.

Audit tables: `audit_pipeline_runs` · `audit_dq_results` ·
`quarantine_records` · `governance_definitions` · `governance_lineage`

---

## Tests

```bash
pytest tests/ -v
```

Human-written benchmark tests with independently computed expected
values — RSI-14, VWAP, bronze schema, silver join, DQ null logging.

---

## Data product delivery

**Concept → requirements:** Define the question before the schema.
For this platform: *"How has market activity trended over 90 days,
and is there anything to watch?"* Translate into PRD with epics,
stories, and acceptance criteria before writing code.

**Build standard:** CLAUDE.md governs the implementation — including
AI-generated code. Each layer has a defined contract: Bronze is
immutable, Silver is trusted, Gold is the only dashboard source.

**Maintainability:** Each layer evolves independently. Add a metric
→ one function in transform_gold.py. Add a source → one ingest
function + bronze view. Change the dashboard → app.py only.

**Influencing with data:** Build observability before arguing for
investment. The observability dashboard shows DQ outcomes and
quarantine rates. The action log in audit_nba_actions shows whether
recommendations are being acted on — that is the adoption metric.

**Handoff:** Walk them through the layer model (the why, not the how).
Run the pipeline together. Show them a log file. Show them the
observability dashboard. Enforce the human-written test rule.

---

## Agent log

Built with Claude Code assistance.

**AI wrote:** Pipeline scripts, transforms, dashboard shell,
audit tables, DQ framework, NBA engine, what-if scenarios.

**Humans wrote:** Benchmark tests with independently computed
expected values. Architecture decisions. Metric selection and
justification. Governance definitions.

**Corrections applied:**
- Threshold lowering caught by validate.py
- RSI formula (SMA → Wilder EMA) caught by benchmark test
- AXJO API limitation → SPY substitution (human decision)
- Module path errors (PYTHONPATH) — environment assumption

**Key principle:** Governance applies to AI-generated code the
same as any other code. validate.py gates every merge.

---

## MVP limitations

- Alpha Vantage free tier: ~100 days (compact mode)
- Symbol: SPY (AXJO unavailable on free tier)
- Thresholds adjusted: S2 ≥60 rows, S4 ≥3 months
- Production upgrade: premium API + 4 constant changes

**Production path:** S3 + Redshift/Athena · Airflow · Alation ·
Looker or custom frontend. Architecture unchanged.
