# ADL — Architecture Decision Log

### ADL-001 — DuckDB over PostgreSQL

**Decision:** Use DuckDB as the analytical store.

**Why for MVP:** Zero infrastructure setup, native parquet querying, and sufficient SQL support for analytical workloads.

**Trade-off:** Not suitable for concurrent multi-user writes.

**Production path:** Replace with an AWS-managed warehouse without changing transformation logic.

---

### ADL-002 — Medallion Architecture

**Decision:** Use Bronze / Silver / Gold data layers.

**Why for MVP:** Separates raw ingestion, validated transformations, and business-ready outputs while keeping lineage traceable.

**Trade-off:** Additional pipeline steps and storage overhead.

**Production path:** Maps directly to dbt + lakehouse patterns used in enterprise analytics platforms.

---

### ADL-003 — schedule Library over Airflow

**Decision:** Use Python `schedule` for orchestration.

**Why for MVP:** Lightweight daily scheduling without introducing orchestration infrastructure.

**Trade-off:** No retries, monitoring, or DAG management.

**Production path:** Existing jobs can be migrated into Airflow tasks with minimal refactoring.

---

### ADL-004 — Streamlit for Delivery Layer

**Decision:** Use Streamlit for dashboard delivery.

**Why for MVP:** Fastest path to an interactive analytics interface for stakeholder review and iteration.

**Trade-off:** Limited scalability and frontend flexibility compared to production UI frameworks.

**Production path:** Dashboard concepts can transition into Looker, Tableau, or a custom frontend.

---

### ADL-005 — Quarantine over Silent Record Drops

**Decision:** Invalid records are quarantined instead of removed silently.

**Why for MVP:** Preserves auditability and makes data quality failures observable during pipeline execution.

**Trade-off:** Additional pipeline complexity and storage.

**Production path:** Extend into monitored DQ workflows with alerting and governance controls.

---

### ADL-006 — Human-Governed AI Development

**Decision:** Use AI-assisted development with human-written benchmark validation.

**Why for MVP:** Accelerates delivery while ensuring critical calculations are independently verified.

**Trade-off:** Requires manual benchmark creation and review effort.

**Observed outcome:** Human validation identified incorrect RSI implementation and unsafe DQ threshold changes during development.

---

### ADL-007 — Separate Business and Operational Dashboards

**Decision:** Split market analytics and observability into separate applications.

**Why for MVP:** Business users and engineers require different workflows and operational context.

**Trade-off:** Two deployment entry points instead of one unified app.

**Production path:** Consolidate behind shared authentication and routed endpoints.