"""
Pipeline Observability Dashboard.
Port 8502: streamlit run dashboard/observability.py
Never touch app.py when editing this file.
"""

import duckdb
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DB_PATH = "data/market.duckdb"


@st.cache_resource
def get_connection():
    return duckdb.connect(DB_PATH, read_only=False)


@st.cache_data(ttl=60)
def load_audit_runs() -> pd.DataFrame:
    con = get_connection()
    return con.execute(
        "SELECT * FROM audit_pipeline_runs ORDER BY finished_at DESC"
    ).df()


@st.cache_data(ttl=60)
def load_dq_results() -> pd.DataFrame:
    con = get_connection()
    return con.execute(
        "SELECT * FROM audit_dq_results ORDER BY evaluated_at DESC"
    ).df()


@st.cache_data(ttl=60)
def load_quarantine() -> pd.DataFrame:
    con = get_connection()
    return con.execute(
        "SELECT * FROM quarantine_records ORDER BY quarantine_timestamp DESC LIMIT 50"
    ).df()


@st.cache_data(ttl=60)
def load_nba_evaluations() -> pd.DataFrame:
    con = get_connection()
    return con.execute(
        "SELECT * FROM audit_nba_evaluations ORDER BY evaluated_at DESC LIMIT 50"
    ).df()


@st.cache_data(ttl=60)
def load_nba_actions() -> pd.DataFrame:
    con = get_connection()
    return con.execute(
        "SELECT * FROM audit_nba_actions ORDER BY timestamp DESC LIMIT 50"
    ).df()


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Pipeline Observability",
    page_icon="🔬",
    layout="wide",
)

st.title("Pipeline Observability")

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
CHECKPOINT = "load_audit_data"
try:
    runs_df = load_audit_runs()
    dq_df = load_dq_results()
    quarantine_df = load_quarantine()
except Exception as e:
    st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
    st.stop()

# ---------------------------------------------------------------------------
# Health banner
# ---------------------------------------------------------------------------
CHECKPOINT = "health_banner"
try:
    if runs_df.empty:
        st.warning("No pipeline runs found. Run the pipeline first.")
        st.stop()

    last_run = runs_df.iloc[0]
    last_status = last_run.get("status", "UNKNOWN")

    if last_status == "PASS":
        st.success(f"HEALTHY — Last run: {last_run.get('step')} at {last_run.get('finished_at')}")
    else:
        st.error(f"DEGRADED — Last run: {last_run.get('step')} status={last_status} at {last_run.get('finished_at')}")
except Exception as e:
    st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
    st.stop()

# ---------------------------------------------------------------------------
# Issues panel
# ---------------------------------------------------------------------------
CHECKPOINT = "issues_panel"
try:
    st.subheader("Issues")
    if not dq_df.empty:
        issues = dq_df[dq_df["status"].isin(["FAIL", "WARN"])]
        if issues.empty:
            st.success("No DQ issues found — all checks clean.")
        else:
            for _, row in issues.iterrows():
                icon = "🔴" if row["status"] == "FAIL" else "🟡"
                st.markdown(
                    f"{icon} **[{row['layer'].upper()}] {row['rule_id']}** — "
                    f"{row['detail']} ({row['rows_affected']} rows)"
                )
    else:
        st.info("No DQ results recorded yet.")
except Exception as e:
    st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
    st.stop()

st.divider()

# ---------------------------------------------------------------------------
# Hop cards: Bronze / Silver / Gold
# ---------------------------------------------------------------------------
CHECKPOINT = "hop_cards"
try:
    st.subheader("Pipeline Hops")
    layers = ["bronze", "silver", "gold"]
    hop_cols = st.columns(3)

    for col, layer in zip(hop_cols, layers):
        layer_runs = runs_df[runs_df["layer"] == layer]
        layer_dq = dq_df[dq_df["layer"] == layer]

        if layer_runs.empty:
            col.metric(layer.capitalize(), "No runs")
            continue

        last = layer_runs.iloc[0]
        status = last.get("status", "UNKNOWN")
        rows_in = int(last.get("rows_in") or 0)
        rows_out = int(last.get("rows_out") or 0)
        rows_q = int(last.get("rows_quarantined") or 0)
        dq_pass = int((layer_dq["status"] == "PASS").sum())
        dq_fail = int((layer_dq["status"] == "FAIL").sum())

        colour = "normal" if status == "PASS" else "inverse"
        col.metric(layer.capitalize(), status, f"{rows_in}→{rows_out} rows")
        col.caption(f"DQ: {dq_pass} PASS / {dq_fail} FAIL | Quarantined: {rows_q}")
except Exception as e:
    st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
    st.stop()

st.divider()

# ---------------------------------------------------------------------------
# Row flow chart
# ---------------------------------------------------------------------------
CHECKPOINT = "row_flow_chart"
try:
    st.subheader("Row Flow")
    flow_data = []
    for layer in ["bronze", "silver", "gold"]:
        layer_runs = runs_df[runs_df["layer"] == layer]
        if not layer_runs.empty:
            last = layer_runs.iloc[0]
            flow_data.append({
                "layer": layer.capitalize(),
                "rows_in": int(last.get("rows_in") or 0),
                "rows_out": int(last.get("rows_out") or 0),
            })

    if flow_data:
        flow_df = pd.DataFrame(flow_data)
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Rows In", x=flow_df["layer"], y=flow_df["rows_in"],
                             marker_color="#64b5f6"))
        fig.add_trace(go.Bar(name="Rows Out", x=flow_df["layer"], y=flow_df["rows_out"],
                             marker_color="#81c784"))
        fig.update_layout(barmode="group", height=280,
                          margin=dict(l=0, r=0, t=20, b=0),
                          legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True)
except Exception as e:
    st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
    st.stop()

st.divider()

# ---------------------------------------------------------------------------
# Quarantine log
# ---------------------------------------------------------------------------
CHECKPOINT = "quarantine_log"
try:
    st.subheader("Quarantine Log")
    if quarantine_df.empty:
        st.success("No quarantined records — data quality clean.")
    else:
        st.dataframe(
            quarantine_df[["quarantine_timestamp", "run_id", "rule_id", "reason"]],
            use_container_width=True,
        )
except Exception as e:
    st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
    st.stop()

st.divider()

# ---------------------------------------------------------------------------
# Run history sparkline (last 7 runs)
# ---------------------------------------------------------------------------
CHECKPOINT = "run_history_sparkline"
try:
    st.subheader("Run History (last 7)")
    recent = runs_df.head(7).copy()
    if not recent.empty:
        recent["status_num"] = recent["status"].apply(lambda s: 1 if s == "PASS" else 0)
        recent = recent.iloc[::-1]  # oldest first
        fig_spark = go.Figure()
        fig_spark.add_trace(go.Scatter(
            x=recent["finished_at"].astype(str),
            y=recent["rows_out"],
            mode="lines+markers",
            line=dict(color="#42a5f5"),
            marker=dict(
                color=recent["status_num"].apply(lambda v: "#4caf50" if v else "#f44336"),
                size=10,
            ),
            name="Rows Out",
        ))
        fig_spark.update_layout(height=180, margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
        st.plotly_chart(fig_spark, use_container_width=True)
        st.caption("Green dot = PASS, Red dot = FAIL")
except Exception as e:
    st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
    st.stop()

st.divider()

# ---------------------------------------------------------------------------
# NBA audit data
# ---------------------------------------------------------------------------
CHECKPOINT = "nba_audit"
try:
    st.subheader("NBA Audit")
    nba_eval_df = load_nba_evaluations()
    nba_act_df = load_nba_actions()

    nba_left, nba_right = st.columns(2)
    with nba_left:
        st.markdown("**Evaluations**")
        if nba_eval_df.empty:
            st.info("No evaluations logged yet.")
        else:
            st.dataframe(
                nba_eval_df[["evaluated_at", "highest_severity", "triggered_rule_ids"]],
                use_container_width=True,
            )
    with nba_right:
        st.markdown("**Actions Taken**")
        if nba_act_df.empty:
            st.info("No actions logged yet.")
        else:
            st.dataframe(
                nba_act_df[["timestamp", "reference_id", "action_type", "rule_ids"]],
                use_container_width=True,
            )
except Exception as e:
    st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
    st.stop()

st.divider()

# ---------------------------------------------------------------------------
# Governance expander
# ---------------------------------------------------------------------------
with st.expander("Governance & Data Lineage"):
    st.markdown("""
### Metric Definitions
| Metric | Formula |
|---|---|
| VWAP 20d | `SUM((H+L+C)/3 × V) / SUM(V)` rolling 20 days |
| RSI-14 | Wilder's EMA, alpha=1/14, 14-period |
| EMA 3m | Exponential moving average of FEDFUNDS over 3 months |
| SMA 3m | Simple moving average of FEDFUNDS over 3 months |
| Sharpe 20d | `MEAN(excess_return) / STDDEV(excess_return) × √252`, rf = FEDFUNDS/252 |
| Max Drawdown 90d | Peak-to-trough % over 90-day rolling window |
| Volatility 20d | `STDDEV(daily_return) × √252 × 100` |
| VWAP Efficiency | `100 − AVG(|close−VWAP|/VWAP×100, 20d)` |
| Yield Spread | GS10 − FEDFUNDS |

### DQ Standards
- **Bronze:** Never edited after write. B1 (retry), B2 (rate limit), B3 (schema), B4 (dot→null)
- **Silver:** S1 (null quarantine), S2 (completeness), S3 (future dates), S4 (join depth), S5 (UTC)
- **Gold:** G1 (RSI warmup), G2 (zero volume), G3 (macro depth), G4 (KPI warmup), G5 (Sharpe rf)

### Data Lineage
```
Alpha Vantage → bronze_av → silver_market → gold_metrics → Dashboard
FRED FEDFUNDS → bronze_fred ↗
FRED GS10     → bronze_fred_gs10 ↗
```

### Governance Principles
1. Bronze is immutable — never edited after write
2. Gold is the only permitted dashboard data source
3. No silent failures — every exception logged with context
4. Quarantine not drop — failed records always accounted for
""")
