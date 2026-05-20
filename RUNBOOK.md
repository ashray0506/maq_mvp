# RUNBOOK — Market Analytics Platform
**Audience:** Engineers onboarding to or operating the platform.

---

## Platform Structure

| Layer | Rule |
|---|---|
| Bronze | Raw, immutable source data |
| Silver | Cleaned and validated transformation layer |
| Gold | Only approved dashboard source |
| Quarantine | Failed records retained for review, never silently dropped |

---

## Delivery Priorities

The MVP prioritised:

1. Data correctness over UI polish  
2. Auditability over feature breadth  
3. Operational visibility over orchestration complexity  
4. Deterministic fallback behaviour over AI-only workflows  
5. Clear business workflows before frontend optimisation  

Infrastructure concerns such as Airflow, authentication, and distributed compute were deferred for scope control.

---

## Dashboard Design Principles

- SEE → JUDGE → ACT structure used to guide analytical flow
- Business analytics separated from operational observability
- Macro context displayed alongside technical indicators
- Governance definitions embedded directly in-platform
- Visual hierarchy focused on actionable signals

---

## Pipeline Execution

```bash
python pipeline/ingest.py
python pipeline/register_bronze.py
PYTHONPATH=. python pipeline/transform_silver.py
PYTHONPATH=. python pipeline/transform_gold.py
python pipeline/validate.py

streamlit run dashboard/app.py
streamlit run dashboard/observability.py