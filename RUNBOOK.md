# RUNBOOK — Market Intelligence Platform
**Audience:** Engineers operating or onboarding to this platform.

---

## Run the Pipeline

```bash
source .venv/bin/activate

python pipeline/ingest.py                        # fetch bronze
python pipeline/register_bronze.py               # register DuckDB views
PYTHONPATH=. python pipeline/transform_silver.py # clean + join
PYTHONPATH=. python pipeline/transform_gold.py   # metrics + KPIs
python pipeline/validate.py                      # confirm all 12 checks pass

streamlit run dashboard/app.py                   # market dashboard :8501
streamlit run dashboard/observability.py         # pipeline health :8502
```

Scheduled mode (daily 07:00):
```bash
python pipeline/ingest.py --schedule
```

---

## Layer Rules

| Layer | Rule |
|---|---|
| Bronze | Never edit after write. Fix ingest logic, re-run. |
| Silver | No direct reads in dashboard or gold. |
| Gold | Only permitted source for dashboard. |
| Quarantine | Failed records written here, never silently dropped. |

---

## DQ Rules Reference

### Bronze
| ID | Check | On Failure |
|---|---|---|
| B1 | Retry 3x, 5s backoff | Log ERROR, skip run |
| B2 | AV `Note`/`Information` key = rate limit | Log ERROR, skip run |
| B3 | Expected columns present | Log ERROR, do not write |
| B4 | FRED `"."` → null | Log WARNING with count |

### Silver
| ID | Check | On Failure |
|---|---|---|
| S1 | close, volume not null | Quarantine rows |
| S2 | ≥ 60 rows | Log WARNING |
| S3 | No future dates | Quarantine rows |
| S4 | Join ≥ 3 shared months | Log ERROR, halt |
| S5 | Timezone normalisation | AV daily → UTC. FRED monthly → joined on
|    |                        | DATE_TRUNC('month') then forward-filled   |
|    |                        | across daily rows. Explicit, not assumed. |

### Gold
| ID | Check | On Failure |
|---|---|---|
| G1 | RSI null first 14 rows | Expected |
| G2 | VWAP excludes zero-volume | Log count |
| G3 | ≥ 3 months macro for EMA/SMA | Log ERROR, halt |
| G4 | Sharpe/Vol null first 20 rows | Expected |
| G5 | Sharpe uses FEDFUNDS/252 | Verify on run |

---

## Audit Tables

| Table | What it stores |
|---|---|
| `audit_pipeline_runs` | One row per step per run — rows in/out/quarantined, status |
| `audit_dq_results` | One row per DQ rule per run — PASS/FAIL, rows affected |
| `quarantine_records` | Failed records — rule ID, raw record JSON, reason |
| `audit_nba_evaluations` | NBA rule evaluation — triggered rules, rationale, data snapshot |
| `audit_nba_actions` | Actions taken — type, reference ID, session, timestamp |

Query quarantine:
```sql
SELECT * FROM quarantine_records
ORDER BY quarantine_timestamp DESC LIMIT 20;
```

Query last run DQ summary:
```sql
SELECT rule_id, status, rows_affected, detail
FROM audit_dq_results
WHERE run_id = (SELECT MAX(run_id) FROM audit_pipeline_runs)
ORDER BY layer, rule_id;
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `KeyError: ALPHA_VANTAGE_API_KEY` | `.env` not created or venv not active |
| AV returns `Note` in JSON | Rate limit (25/day) — wait or use second key |
| `DuckDB: Table not found` | Run `register_bronze.py` first |
| RSI all nulls | Less than 14 rows in bronze — check `outputsize` param |
| Silver join < 3 months | Date type mismatch — check both bronze views |
| Dashboard blank | Run full pipeline in order, then launch |
| validate.py exits 1 | Read FAIL lines — do not adjust thresholds to force pass |

---

## AI Code Guardrails

This pipeline uses Claude Code. Before accepting any AI-generated transform:

- [ ] Window function uses correct lookback period?
- [ ] Nulls handled explicitly — not implicitly dropped?
- [ ] Timezone handling explicit?
- [ ] DQ log lines present for every failure path?
- [ ] Benchmark tests pass with independently computed values?

**Never:** adjust a validate.py threshold to make a failing check pass. Fix the code.

---

## Adding a New Metric

1. Define it in PRD before writing code
2. Add DQ rule to this runbook
3. Write human benchmark test first
4. Implement in `transform_gold.py`
5. Add to `VALIDATION_CONFIG` in `app.py`
6. Update `build_market_context()` so LLM has the value

## Adding a New Data Source

1. Add ingest function to `ingest.py` (retry + schema check + DQ logging)
2. Register bronze view in `register_bronze.py`
3. Add silver join logic to `transform_silver.py`
4. Add DQ rules to this runbook
5. Update `.env.example`

---

## Handing Off

Walk them through: bronze is immutable → silver is trusted → gold is the only dashboard source → quarantine means nothing disappears silently. Then show them a log file. Then show them the observability dashboard. Then run the tests together.
