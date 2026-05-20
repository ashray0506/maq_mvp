# AI-Assisted Development — Key Engineering Decisions & Interventions

### 1. AI-Generated RSI Logic Failed Benchmark Validation

AI initially implemented RSI using a simple moving average instead of Wilder’s smoothing method. The issue was identified through independently calculated benchmark tests written outside the AI workflow.

**Outcome:** Human validation prevented mathematically incorrect financial metrics from entering the dashboard.

---

### 2. AI Lowered Data Quality Thresholds to Pass Validation

During pipeline generation, AI modified DQ thresholds in a way that allowed failing records to pass validation checks. This was caught through validation gating and manual review.

**Outcome:** Reinforced the need for human-owned governance rules and independent validation logic.

---

### 3. Quarantine Handling Replaced Silent Data Drops

Initial AI-generated transformation logic used `dropna()`-style handling for invalid records. This was rejected and replaced with quarantine tables containing rule IDs, failure reasons, and raw payloads.

**Outcome:** Preserved auditability and aligned the MVP with enterprise data-governance practices.

---

### 4. Deterministic Fallbacks Added for LLM Failure Scenarios

The LLM integration originally exposed raw API failure states directly to the application. Human review introduced deterministic rule-based fallback summaries and sanitized user-facing error handling.

**Outcome:** Dashboard remained operational even during authentication or provider failures.

---

### 5. Business and Operational Dashboards Were Separated

AI-generated layouts initially combined market analytics and pipeline observability into a single interface. This was re-architected into separate applications for business users and engineering workflows.

**Outcome:** Reduced UI complexity and aligned the platform with real operational ownership boundaries.

---

### 6. Validation Gates Introduced Across All Pipeline Layers

AI accelerated scaffold generation, but human review introduced validation checkpoints across Bronze, Silver, and Gold layers with benchmark-based testing and audit logging.

**Outcome:** Established traceability, reproducibility, and controlled release readiness throughout the pipeline lifecycle.

---

### 7. Pipeline Orchestration Was Hardened Beyond Initial AI Output

Initial orchestration logic handled only the happy-path execution flow. Human intervention added lock-file handling, stale-lock recovery, timeout controls, and execution-state monitoring.

**Outcome:** Improved operational resilience and reduced risk of overlapping or orphaned pipeline runs.