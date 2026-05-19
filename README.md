# Market Intelligence Platform
Case study for Really Big Bank — post-trade operations analytics.

Management needs external market benchmarks to contextualise bank performance against industry conditions. This platform automates that: ingest public market and macro data, enforce quality at every hop, surface what conditions mean and what to do about them.

Built to the standard you'd apply from day one in a post-trade environment — medallion architecture, DQ enforcement, full audit trail, AI-native workflow. Assessment scope met: 2 sources, 3 metrics, 1 dashboard. Platform demonstrates the engineering foundation for a broader post-trade intelligence layer.

---

## Quick Start

```bash
git clone git@github.com:ashray0506/MAQ_MVP.git
cd MAQ_MVP

python -m venv .venv
source .venv/bin/activate       # windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env            # add API keys — see .env.example
```

Get free API keys:
- Alpha Vantage: alphavantage.co/support/#api-key
- FRED: fred.stlouisfed.org/docs/api/api_key.html
- Kimi: platform.moonshot.cn

---

## Run

```bash
python pipeline/ingest.py
python pipeline/register_bronze.py
PYTHONPATH=. python pipeline/transform_silver.py
PYTHONPATH=. python pipeline/transform_gold.py
python pipeline/validate.py                      # must exit 0

streamlit run dashboard/app.py                   # :8501 — market dashboard
streamlit run dashboard/observability.py         # :8502 — pipeline health
```

---

## Architecture

```
Alpha Vantage (SPY) ──┐
                       ├──▶ Bronze ──▶ Silver ──▶ Gold ──▶ See · Judge · Act
FRED (FEDFUNDS)     ──┘     raw       cleaned    metrics
                             parquet   DuckDB     DuckDB
```

**Bronze** — raw parquet, immutable, one file per source per run  
**Silver** — cleaned, joined, UTC-normalised, dimensional  
**Gold** — VWAP · RSI-14 · EMA/SMA · Sharpe · MDD · Volatility · VWAP Efficiency  

FRED's Fed Funds Rate is the risk-free rate for Sharpe Ratio — not just macro context.

---

## Tests

```bash
pytest tests/ -v
```

Human-written benchmarks with independently computed expected values:
- RSI-14 against known 15-day sequence
- VWAP against hand-calculated 5-row fixture
- Bronze schema validation
- Silver join on fixture data
- DQ null logging and quarantine

---

## Tech Stack

| Component | Choice | Why |
|---|---|---|
| Storage | Parquet + DuckDB | Zero infra, SQL window functions, parquet reads natively |
| Schedule | `schedule` library | No daemon, readable, Airflow-replaceable |
| Dashboard | Streamlit | One command, no JS |
| Charts | Plotly | First-class Streamlit support |
| PDF | ReportLab | Lightweight, no browser |
| LLM | Kimi API (moonshot-v1-8k) | Cost-effective, OpenAI-compatible format |
| Secrets | python-dotenv | Standard local dev practice |

---

## Docs

- `PRD.md` — requirements, epics, user stories, acceptance criteria
- `RUNBOOK.md` — operations, DQ rules, troubleshooting, handoff
- `ADL.md` — architecture decision log (why, not just what)
- `CLAUDE.md` — Claude Code build instructions

---

## Limitations (MVP / Free Tier)

- Alpha Vantage free tier: ~100 days data, `outputsize=compact`
- Symbol: SPY (AXJO unavailable on free tier)
- DQ thresholds adjusted: S2 ≥ 60 rows, S4 ≥ 3 months
- Production upgrade: premium API key + 4 constant changes, no architecture change

---

## AI Usage

Built with Claude Code assistance. Human corrections applied:
- Threshold lowering caught by validate.py (AI lowered to pass its own checks)
- AXJO API limitation not flagged until runtime
- Benchmark tests written by human with independently computed values

Governance: validate.py gates every merge. Human-written tests provide ground truth AI can't self-validate against.

---

## Data product delivery

How this platform was built mirrors how any data product should be built.

### Concept → requirements

Work with the data product owner to define the question the product must answer — not the metrics, not the schema, the *question*. For this platform: "How has market activity trended over 90 days, and is there anything we should be watching?"

Translate that into a PRD with epics, user stories, and acceptance criteria before writing any code. The acceptance criteria are the contract between engineering and the product owner.

### Build standard

Write the build instructions (CLAUDE.md) before writing the code. The spec governs the implementation — including AI-generated code. Every layer has a defined contract:
- Bronze is immutable — the audit trail
- Silver is trusted — the source of truth
- Gold is consumption-ready — the only dashboard source

Violations of these contracts are detectable and fixable because the contract exists.

### Maintainability and evolution

Each layer can evolve independently:
- Add a new metric → add a column to transform_gold.py
- Add a new source → add an ingest function and a bronze view
- Change the dashboard → app.py only, no pipeline changes

The medallion model separates concerns so the product can be handed to a junior engineer without risk of them breaking upstream data.

### Influencing with data

Build observability before arguing for investment. The observability dashboard shows pipeline health, DQ outcomes, quarantine rates, and run history. If stakeholders push back on data quality investment, show them the quarantine log — not a slide about why data quality matters.

Self-service adoption is measured through the action log: audit_nba_actions shows which recommendations were acted on, by whom, and how quickly. That's the adoption metric. If the platform is being used, the data proves it.

### Handoff to a team member

1. Walk them through the layer model — the why, not the how
2. Run the pipeline together end-to-end on their machine
3. Show them the DQ rules table in RUNBOOK.md
4. Show them a log file — make sure they know ERROR vs WARNING
5. Enforce the human-written test rule — especially if they use AI

The README is the entry point. The RUNBOOK is for when something breaks. The ADL is for when someone asks why a decision was made. If something isn't in one of these three files, it isn't done.
