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
    return duckdb.connect(DB_PATH, read_only=True)


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

st.markdown("""
<style>
.stApp { background: #f8f9fa; }
.block-container { padding-top: 0 !important; padding-bottom: 0 !important; max-width: 100% !important; }
header[data-testid="stHeader"] { display: none; }
hr { border-color: #e8eaed !important; margin: 12px 0 !important; }
.stCaption { font-size: 10px !important; color: #9aa0a6 !important; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div style="background:#fff;border-bottom:1px solid #e8eaed;padding:14px 0 12px 0;
            display:flex;align-items:center;justify-content:space-between;margin-bottom:0;">
    <span style="font-size:22px;font-weight:700;color:#1a1a2e;letter-spacing:-0.4px;">
        Pipeline Observability
    </span>
    <span style="font-size:11px;color:#9aa0a6;">
        Really Big Bank · Post-trade operations
    </span>
</div>
""", unsafe_allow_html=True)


def _obs_section(text: str) -> None:
    st.markdown(
        f'<div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;'
        f'letter-spacing:.1em;padding:12px 0 8px 0;">{text}</div>',
        unsafe_allow_html=True,
    )

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
    last_status = str(last_run.get("status", "UNKNOWN"))
    last_step   = str(last_run.get("step", "—"))
    last_time   = str(last_run.get("finished_at", "—"))[:19]

    is_healthy = last_status == "PASS"
    _hbg, _hbr, _hfc, _htxt = (
        ("#f0fdf4", "#bbf7d0", "#0f9d58", "#166534") if is_healthy
        else ("#fef2f2", "#fecaca", "#d93025", "#b91c1c")
    )
    _hlabel = "✓ HEALTHY" if is_healthy else "⚠ DEGRADED"
    st.markdown(f"""
<div style="background:{_hbg};border:1px solid {_hbr};border-radius:6px;
            padding:10px 16px;margin-bottom:16px;display:flex;align-items:center;gap:10px;">
    <span style="font-size:14px;font-weight:700;color:{_htxt};">{_hlabel}</span>
    <span style="font-size:11px;color:{_htxt};opacity:.8;">Last run: {last_step} · {last_time}</span>
</div>
""", unsafe_allow_html=True)
except Exception as e:
    st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
    st.stop()

# ---------------------------------------------------------------------------
# Issues panel
# ---------------------------------------------------------------------------
CHECKPOINT = "issues_panel"
try:
    _obs_section("Issues")
    if not dq_df.empty:
        issues = dq_df[dq_df["status"].isin(["FAIL", "WARN"])]
        if issues.empty:
            st.markdown("""
<div style="padding:10px 14px;border:1px solid #bbf7d0;border-radius:6px;
            background:#f0fdf4;font-size:12px;color:#166534;">
    ✓ No issues — all DQ rules passing
</div>
""", unsafe_allow_html=True)
        else:
            for _, row in issues.iterrows():
                _idot = "#ef4444" if row["status"] == "FAIL" else "#f59e0b"
                st.markdown(f"""
<div style="display:flex;align-items:flex-start;gap:8px;padding:8px 10px;
            border:1px solid #fecaca;border-radius:6px;margin-bottom:4px;background:#fef2f2;">
    <div style="width:8px;height:8px;border-radius:50%;background:{_idot};
                flex-shrink:0;margin-top:3px;"></div>
    <div style="font-size:11px;color:#1a1a2e;line-height:1.5;">
        <strong>[{row['layer'].upper()}] {row['rule_id']}</strong> — {row['detail']} ({row['rows_affected']} rows)
    </div>
</div>
""", unsafe_allow_html=True)
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
    _obs_section("Pipeline hops")
    _layer_colors = {"bronze": "#b45309", "silver": "#0f9d58", "gold": "#378ADD"}
    hop_cols = st.columns(3)

    for col, layer in zip(hop_cols, ["bronze", "silver", "gold"]):
        layer_runs = runs_df[runs_df["layer"] == layer]
        layer_dq   = dq_df[dq_df["layer"] == layer]
        _lc = _layer_colors[layer]

        if layer_runs.empty:
            col.markdown(f"""
<div style="background:#fff;border:1px solid #e8eaed;border-radius:6px;padding:12px 14px;">
  <div style="font-size:9px;color:{_lc};text-transform:uppercase;letter-spacing:.05em;">{layer}</div>
  <div style="font-size:16px;font-weight:500;color:#9aa0a6;">No runs</div>
</div>""", unsafe_allow_html=True)
            continue

        last    = layer_runs.iloc[0]
        status  = str(last.get("status", "UNKNOWN"))
        rows_in  = int(last.get("rows_in") or 0)
        rows_out = int(last.get("rows_out") or 0)
        rows_q   = int(last.get("rows_quarantined") or 0)
        dq_pass  = int((layer_dq["status"] == "PASS").sum())
        dq_fail  = int((layer_dq["status"] == "FAIL").sum())

        _sc = "#0f9d58" if status == "PASS" else "#d93025"
        _sbg, _sbr = ("#f0fdf4", "#bbf7d0") if status == "PASS" else ("#fef2f2", "#fecaca")
        col.markdown(f"""
<div style="background:#fff;border:1px solid {_lc};border-radius:6px;padding:14px;">
  <div style="font-size:10px;color:{_lc};text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">{layer}</div>
  <div style="display:inline-block;padding:2px 8px;border-radius:10px;background:{_sbg};border:1px solid {_sbr};
              font-size:11px;font-weight:500;color:{_sc};margin-bottom:10px;">{status}</div>
  <div style="font-size:12px;color:#1a1a2e;margin-bottom:2px;">{rows_in:,} → {rows_out:,} rows</div>
  <div style="font-size:11px;color:#9aa0a6;">DQ {dq_pass} PASS / {dq_fail} FAIL · quarantined {rows_q}</div>
</div>""", unsafe_allow_html=True)
except Exception as e:
    st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
    st.stop()

st.divider()

# ---------------------------------------------------------------------------
# Row flow chart
# ---------------------------------------------------------------------------
CHECKPOINT = "row_flow_chart"
try:
    _obs_section("Row flow")
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
    _obs_section("Quarantine log")
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
    _obs_section("Run history (last 7)")
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
    _obs_section("NBA audit")
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
