"""
Market Intelligence Dashboard — See. Judge. Act.
Port 8501: streamlit run dashboard/app.py
"""

import os
import uuid
from datetime import datetime, timezone

import duckdb
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# VALIDATION_CONFIG — all thresholds here, nowhere else
# ---------------------------------------------------------------------------
VALIDATION_CONFIG = {
    # RSI thresholds
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    # Sharpe RAG
    "sharpe_green": 1.0,
    "sharpe_amber": 0.0,
    # MDD RAG (values are negative %)
    "mdd_amber": -10.0,
    "mdd_red": -20.0,
    # Volatility RAG (annualised %)
    "vol_amber": 20.0,
    "vol_red": 30.0,
    # VWAP Efficiency
    "vwap_eff_signal": 94.0,
    # Yield spread colour (%)
    "spread_green": 0.5,
    "spread_red": -0.5,
    # Lookback slider
    "lookback_min": 30,
    "lookback_max": 90,
    "lookback_default": 60,
}

DB_PATH = "data/market.duckdb"
SYMBOL = os.getenv("SYMBOL", "SPY")
FRED_SERIES = os.getenv("FRED_SERIES", "FEDFUNDS")
KIMI_API_KEY = os.getenv("KIMI_API_KEY", "")


# ---------------------------------------------------------------------------
# DB connection helper
# ---------------------------------------------------------------------------
@st.cache_resource
def get_connection():
    return duckdb.connect(DB_PATH, read_only=False)


# ---------------------------------------------------------------------------
# Data loaders — gold layer only
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300)
def load_gold(days: int, symbol: str) -> pd.DataFrame:
    con = get_connection()
    df = con.execute(
        f"""
        SELECT * FROM gold_metrics
        WHERE symbol = ?
        ORDER BY date DESC
        LIMIT {days}
        """,
        [symbol],
    ).df()
    return df.sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=300)
def load_last_run_meta() -> dict:
    con = get_connection()
    row = con.execute(
        """
        SELECT step, status, rows_out, finished_at
        FROM audit_pipeline_runs
        ORDER BY finished_at DESC
        LIMIT 1
        """
    ).fetchone()
    if row:
        return {"step": row[0], "status": row[1], "rows_out": row[2], "finished_at": row[3]}
    return {}


@st.cache_data(ttl=300)
def load_symbols() -> list[str]:
    con = get_connection()
    rows = con.execute("SELECT DISTINCT symbol FROM gold_metrics ORDER BY symbol").fetchall()
    return [r[0] for r in rows] if rows else [SYMBOL]


@st.cache_data(ttl=300)
def load_macro_series() -> list[str]:
    con = get_connection()
    rows = con.execute(
        "SELECT DISTINCT macro_series FROM gold_metrics WHERE macro_series IS NOT NULL ORDER BY macro_series"
    ).fetchall()
    return [r[0] for r in rows] if rows else [FRED_SERIES]


# ---------------------------------------------------------------------------
# RAG helpers
# ---------------------------------------------------------------------------
def rsi_rag(rsi: float | None) -> tuple[str, str]:
    if rsi is None or pd.isna(rsi):
        return "grey", "N/A"
    if rsi >= VALIDATION_CONFIG["rsi_overbought"]:
        return "red", "Overbought"
    if rsi <= VALIDATION_CONFIG["rsi_oversold"]:
        return "green", "Oversold"
    return "amber", "Neutral"


def sharpe_rag(v: float | None) -> str:
    if v is None or pd.isna(v):
        return "grey"
    if v >= VALIDATION_CONFIG["sharpe_green"]:
        return "green"
    if v >= VALIDATION_CONFIG["sharpe_amber"]:
        return "amber"
    return "red"


def mdd_rag(v: float | None) -> str:
    if v is None or pd.isna(v):
        return "grey"
    if v >= VALIDATION_CONFIG["mdd_amber"]:
        return "green"
    if v >= VALIDATION_CONFIG["mdd_red"]:
        return "amber"
    return "red"


def vol_rag(v: float | None) -> str:
    if v is None or pd.isna(v):
        return "grey"
    if v <= VALIDATION_CONFIG["vol_amber"]:
        return "green"
    if v <= VALIDATION_CONFIG["vol_red"]:
        return "amber"
    return "red"


def spread_colour(spread: float | None) -> str:
    if spread is None or pd.isna(spread):
        return "grey"
    if spread > VALIDATION_CONFIG["spread_green"]:
        return "green"
    if spread < VALIDATION_CONFIG["spread_red"]:
        return "red"
    return "amber"


RAG_CSS = {
    "green": "#1a7a3a",
    "amber": "#b8860b",
    "red": "#b02020",
    "grey": "#555555",
}

RAG_BG = {
    "green": "#d4edda",
    "amber": "#fff3cd",
    "red": "#f8d7da",
    "grey": "#e2e3e5",
}


# ---------------------------------------------------------------------------
# NBA helpers
# ---------------------------------------------------------------------------
def evaluate_nba_rules(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    latest = df.iloc[-1]
    rules = []

    def _rule(rid, name, severity, condition, action):
        if condition:
            rules.append({"id": rid, "name": name, "severity": severity, "action": action})

    rsi = latest.get("rsi_14")
    vwap = latest.get("vwap_20d")
    close = latest.get("close")
    sharpe = latest.get("sharpe_20d")
    mdd = latest.get("mdd_90d")
    vol = latest.get("volatility_20d")
    vwap_eff = latest.get("vwap_efficiency")
    ema = latest.get("macro_ema_3m")
    sma = latest.get("macro_sma_3m")
    macro = latest.get("macro_value")
    spread = latest.get("yield_spread")

    # Technical rules
    _rule("T1", "RSI Overbought", "HIGH",
          rsi is not None and not pd.isna(rsi) and rsi >= VALIDATION_CONFIG["rsi_overbought"],
          "Consider reducing equity exposure — momentum extended")
    _rule("T2", "RSI Oversold", "MEDIUM",
          rsi is not None and not pd.isna(rsi) and rsi <= VALIDATION_CONFIG["rsi_oversold"],
          "Potential entry opportunity — monitor for reversal")
    _rule("T3", "Price Below VWAP", "MEDIUM",
          close is not None and vwap is not None and not pd.isna(close) and not pd.isna(vwap) and close < vwap,
          "Price trading below VWAP — selling pressure present")
    _rule("T4", "VWAP Efficiency Low", "LOW",
          vwap_eff is not None and not pd.isna(vwap_eff) and vwap_eff < VALIDATION_CONFIG["vwap_eff_signal"],
          "High deviation from VWAP — increased execution cost risk")

    # KPI rules
    _rule("K1", "Negative Sharpe", "HIGH",
          sharpe is not None and not pd.isna(sharpe) and sharpe < VALIDATION_CONFIG["sharpe_amber"],
          "Risk-adjusted returns negative — review position sizing")
    _rule("K2", "Max Drawdown Alert", "HIGH",
          mdd is not None and not pd.isna(mdd) and mdd < VALIDATION_CONFIG["mdd_red"],
          "Drawdown exceeds 20% — activate drawdown risk protocol")
    _rule("K3", "High Volatility", "MEDIUM",
          vol is not None and not pd.isna(vol) and vol > VALIDATION_CONFIG["vol_red"],
          "Annualised volatility above 30% — reduce leverage")
    _rule("K4", "Elevated Volatility", "LOW",
          vol is not None and not pd.isna(vol) and VALIDATION_CONFIG["vol_amber"] < vol <= VALIDATION_CONFIG["vol_red"],
          "Volatility elevated (20–30%) — monitor risk parameters")

    # Macro rules
    _rule("M1", "EMA Above SMA", "LOW",
          ema is not None and sma is not None and not pd.isna(ema) and not pd.isna(sma) and ema > sma,
          "Rate accelerating above trend — tightening macro regime")
    _rule("M2", "EMA Below SMA", "LOW",
          ema is not None and sma is not None and not pd.isna(ema) and not pd.isna(sma) and ema < sma,
          "Rate decelerating below trend — easing macro regime")
    _rule("M3", "Inverted Yield Curve", "HIGH",
          spread is not None and not pd.isna(spread) and spread < VALIDATION_CONFIG["spread_red"],
          "Yield curve inverted — historically precedes recession, exercise caution")
    _rule("M4", "High Fed Funds Rate", "MEDIUM",
          macro is not None and not pd.isna(macro) and macro > 4.0,
          "Fed Funds above 4% — restrictive monetary policy environment")

    # Sort: HIGH → MEDIUM → LOW
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return sorted(rules, key=lambda r: order.get(r["severity"], 9))


def call_llm(rules: list[dict], latest_row: pd.Series) -> str:
    import requests as req

    if not KIMI_API_KEY:
        return _rule_based_summary(rules, latest_row)

    rsi = latest_row.get("rsi_14")
    close = latest_row.get("close")
    sharpe = latest_row.get("sharpe_20d")
    mdd = latest_row.get("mdd_90d")
    vol = latest_row.get("volatility_20d")
    macro = latest_row.get("macro_value")
    spread = latest_row.get("yield_spread")

    triggered = ", ".join(r["name"] for r in rules) if rules else "none"
    context = (
        f"Symbol: {SYMBOL}\n"
        f"Close: {close:.2f}\n"
        f"RSI-14: {rsi:.1f}\n"
        f"Sharpe 20d: {sharpe:.2f}\n"
        f"Max Drawdown 90d: {mdd:.1f}%\n"
        f"Volatility 20d: {vol:.1f}%\n"
        f"Fed Funds Rate: {macro:.2f}%\n"
        f"Yield Spread (GS10-FEDFUNDS): {spread:.2f}%\n"
        f"Triggered rules: {triggered}"
    )

    try:
        resp = req.post(
            "https://api.moonshot.cn/v1/chat/completions",
            headers={"Authorization": f"Bearer {KIMI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "moonshot-v1-8k",
                "messages": [
                    {"role": "system", "content": (
                        "You are a senior portfolio analyst. Provide a concise 3–4 sentence "
                        "market assessment for a portfolio manager. Be factual, reference the "
                        "data, and note any key risks. Do not give specific buy/sell instructions."
                    )},
                    {"role": "user", "content": f"Current market data:\n{context}"},
                ],
                "max_tokens": 300,
                "temperature": 0.3,
            },
            timeout=15,
        )
        if resp.status_code == 401:
            return "LLM unavailable: API key invalid or expired. Showing rule-based summary.\n\n" + _rule_based_summary(rules, latest_row)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return _rule_based_summary(rules, latest_row)


def _rule_based_summary(rules: list[dict], latest_row: pd.Series) -> str:
    if not rules:
        return (
            f"{SYMBOL} signals are within normal ranges. No rules triggered. "
            "Monitor for changes in RSI, volatility, or macro conditions."
        )
    high = [r for r in rules if r["severity"] == "HIGH"]
    med = [r for r in rules if r["severity"] == "MEDIUM"]
    parts = []
    if high:
        parts.append(f"HIGH severity alerts: {', '.join(r['name'] for r in high)}.")
    if med:
        parts.append(f"Medium alerts: {', '.join(r['name'] for r in med)}.")
    parts.append("Review triggered rules and consider appropriate risk actions.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Market Intelligence",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
.rag-card {
    padding: 16px 20px;
    border-radius: 8px;
    margin-bottom: 12px;
    font-weight: 600;
}
.metric-pill {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 0.85em;
    font-weight: 600;
    margin-right: 6px;
}
.sticky-header {
    position: sticky;
    top: 0;
    z-index: 100;
    background: white;
    padding-bottom: 8px;
    border-bottom: 1px solid #eee;
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# CHECKPOINT: Load data
# ---------------------------------------------------------------------------
CHECKPOINT = "load_gold_data"
try:
    symbols = load_symbols()
    macro_series_list = load_macro_series()
except Exception as e:
    st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Filters")
    selected_symbol = st.selectbox("Ticker", symbols, index=0)
    selected_macro = st.selectbox("Macro Series", macro_series_list, index=0)
    lookback = st.slider(
        "Lookback (days)",
        VALIDATION_CONFIG["lookback_min"],
        VALIDATION_CONFIG["lookback_max"],
        VALIDATION_CONFIG["lookback_default"],
    )

# ---------------------------------------------------------------------------
# CHECKPOINT: Load gold
# ---------------------------------------------------------------------------
CHECKPOINT = "load_gold_metrics"
try:
    df = load_gold(lookback, selected_symbol)
    if df.empty:
        st.warning("No data found. Run the pipeline first.")
        st.stop()
    latest = df.iloc[-1]
except Exception as e:
    st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
    st.stop()

# ---------------------------------------------------------------------------
# Sticky header
# ---------------------------------------------------------------------------
close_val = latest.get("close", float("nan"))
vwap_val = latest.get("vwap_20d", float("nan"))
rsi_val = latest.get("rsi_14", float("nan"))
macro_val = latest.get("macro_value", float("nan"))
rsi_colour, rsi_label = rsi_rag(rsi_val)

st.markdown("### Market Intelligence Platform")

h_col1, h_col2, h_col3, h_col4, h_col5 = st.columns([2, 2, 2, 2, 1])
with h_col1:
    st.metric("Close", f"${close_val:,.2f}" if not pd.isna(close_val) else "—")
with h_col2:
    st.metric("VWAP 20d", f"${vwap_val:,.2f}" if not pd.isna(vwap_val) else "—")
with h_col3:
    st.metric("RSI-14", f"{rsi_val:.1f}" if not pd.isna(rsi_val) else "—")
with h_col4:
    st.metric(f"{selected_macro} (%)", f"{macro_val:.2f}" if not pd.isna(macro_val) else "—")
with h_col5:
    colour_hex = RAG_CSS.get(rsi_colour, "#555")
    bg_hex = RAG_BG.get(rsi_colour, "#eee")
    st.markdown(
        f'<div class="rag-card" style="background:{bg_hex};color:{colour_hex};text-align:center;">'
        f'{rsi_label}</div>',
        unsafe_allow_html=True,
    )

st.divider()

# ---------------------------------------------------------------------------
# Market Pulse Bar (Story 2.6)
# ---------------------------------------------------------------------------
CHECKPOINT = "market_pulse_bar"
try:
    gs10_val = latest.get("gs10_value", float("nan"))
    spread_val = latest.get("yield_spread", float("nan"))
    vol_val = latest.get("volatility_20d", float("nan"))

    # Spread trend: compare current spread vs 30d average
    if len(df) >= 30:
        avg_spread_30d = df["yield_spread"].tail(30).mean()
        spread_trend = "▲" if (not pd.isna(spread_val) and not pd.isna(avg_spread_30d) and spread_val > avg_spread_30d) else "▼"
    else:
        spread_trend = "—"

    sc = spread_colour(spread_val)
    sc_hex = RAG_CSS.get(sc, "#555")
    sc_bg = RAG_BG.get(sc, "#eee")

    pb_left, pb_right = st.columns(2)
    with pb_left:
        st.markdown("**Equity**")
        prev_close = df.iloc[-2]["close"] if len(df) >= 2 else close_val
        day_chg = (close_val - prev_close) / prev_close * 100 if prev_close else 0
        chg_sign = "+" if day_chg >= 0 else ""
        st.markdown(
            f'<span class="metric-pill" style="background:#e8f5e9;color:#1a7a3a;">'
            f'{selected_symbol} ${close_val:,.2f} ({chg_sign}{day_chg:.2f}%)</span>'
            f'<span class="metric-pill" style="background:{RAG_BG.get(rsi_colour,"#eee")};color:{RAG_CSS.get(rsi_colour,"#555")};">'
            f'RSI {rsi_val:.1f}</span>'
            f'<span class="metric-pill" style="background:#e3f2fd;color:#0d47a1;">'
            f'Vol {vol_val:.1f}%</span>' if not pd.isna(vol_val) else "",
            unsafe_allow_html=True,
        )
    with pb_right:
        st.markdown("**Macro / Yield**")
        st.markdown(
            f'<span class="metric-pill" style="background:#f3e5f5;color:#6a1b9a;">'
            f'Fed Funds {macro_val:.2f}%</span>'
            f'<span class="metric-pill" style="background:#e8eaf6;color:#283593;">'
            f'GS10 {gs10_val:.2f}%</span>'
            f'<span class="metric-pill" style="background:{sc_bg};color:{sc_hex};">'
            f'Spread {spread_val:+.2f}% {spread_trend}</span>'
            if not (pd.isna(macro_val) or pd.isna(gs10_val) or pd.isna(spread_val)) else
            '<span style="color:grey;">Macro data loading…</span>',
            unsafe_allow_html=True,
        )
except Exception as e:
    st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
    st.stop()

st.divider()

# ---------------------------------------------------------------------------
# KPI Scorecard
# ---------------------------------------------------------------------------
CHECKPOINT = "kpi_scorecard"
try:
    sharpe_val = latest.get("sharpe_20d", float("nan"))
    mdd_val = latest.get("mdd_90d", float("nan"))

    st.markdown("#### KPI Scorecard")
    k1, k2, k3, k4 = st.columns(4)

    def _kpi_card(col, label, value, fmt, rag_fn):
        colour = rag_fn(value)
        ch = RAG_CSS.get(colour, "#555")
        bg = RAG_BG.get(colour, "#eee")
        display = fmt.format(value) if not pd.isna(value) else "—"
        col.markdown(
            f'<div class="rag-card" style="background:{bg};color:{ch};">'
            f'<div style="font-size:0.8em;font-weight:400;">{label}</div>'
            f'<div style="font-size:1.4em;">{display}</div></div>',
            unsafe_allow_html=True,
        )

    _kpi_card(k1, "Sharpe 20d", sharpe_val, "{:.2f}", sharpe_rag)
    _kpi_card(k2, "Max Drawdown 90d", mdd_val, "{:.1f}%", mdd_rag)
    _kpi_card(k3, "Volatility 20d", vol_val, "{:.1f}%", vol_rag)
    vwap_eff_val = latest.get("vwap_efficiency", float("nan"))

    def _vwap_eff_rag(v):
        if v is None or pd.isna(v):
            return "grey"
        return "green" if v >= VALIDATION_CONFIG["vwap_eff_signal"] else "amber"

    _kpi_card(k4, "VWAP Efficiency", vwap_eff_val, "{:.1f}", _vwap_eff_rag)

except Exception as e:
    st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
    st.stop()

st.divider()

# ---------------------------------------------------------------------------
# NBA evaluation + compliance audit logging
# ---------------------------------------------------------------------------
CHECKPOINT = "nba_evaluation"
try:
    import json as _json

    triggered_rules = evaluate_nba_rules(df)

    # Append user-defined active rules for display (they don't auto-trigger, just listed)
    _con = get_connection()
    _user_rules_df = _con.execute(
        "SELECT rule_id, name, condition, severity FROM user_nba_rules WHERE active = TRUE"
    ).df()
    for _, ur in _user_rules_df.iterrows():
        triggered_rules.append({
            "id": ur["rule_id"],
            "name": ur["name"],
            "severity": "USER",
            "action": ur["condition"],
        })

    if "nba_rules" not in st.session_state:
        st.session_state["nba_rules"] = triggered_rules
    if "llm_explanation" not in st.session_state:
        st.session_state["llm_explanation"] = call_llm(triggered_rules, latest)
    if "action_log" not in st.session_state:
        st.session_state["action_log"] = []

    # Story 3.4 — log evaluation to audit_nba_evaluations on every page load
    _triggered_ids = [r["id"] for r in triggered_rules]
    _severities = [r["severity"] for r in triggered_rules]
    _sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "USER": 3}
    _highest = min(_severities, key=lambda s: _sev_order.get(s, 9)) if _severities else "NONE"
    _data_snapshot = latest.to_dict()

    _con.execute(
        "INSERT INTO audit_nba_evaluations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            str(uuid.uuid4()),
            st.session_state.get("session_id", "pre-session"),
            _json.dumps(_triggered_ids),
            _highest,
            _json.dumps([{"id": r["id"], "name": r["name"], "action": r["action"]} for r in triggered_rules]),
            st.session_state.get("llm_explanation", ""),
            _json.dumps(_data_snapshot, default=str),
            datetime.now(timezone.utc),
        ],
    )

except Exception as e:
    st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
    st.stop()

# ---------------------------------------------------------------------------
# Three columns: SEE / JUDGE / ACT
# ---------------------------------------------------------------------------
see_col, judge_col, act_col = st.columns([2, 1.5, 1.5])

# ============================= SEE =============================
with see_col:
    st.markdown("#### See")
    CHECKPOINT = "see_charts"
    try:
        import plotly.graph_objects as go

        # Chart 1 — Price + VWAP (220px)
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=df["date"], y=df["close"], name="Close",
                                   line=dict(color="#1f77b4", width=1.5)))
        fig1.add_trace(go.Scatter(x=df["date"], y=df["vwap_20d"], name="VWAP 20d",
                                   line=dict(color="#ff7f0e", width=1.5, dash="dot")))
        fig1.update_layout(height=220, margin=dict(l=0, r=0, t=20, b=0),
                           legend=dict(orientation="h", y=1.1), showlegend=True)
        st.plotly_chart(fig1, use_container_width=True)

        # Chart 2 — Volume bars green/red (150px)
        colours = ["#2ca02c" if c >= o else "#d62728"
                   for c, o in zip(df["close"], df["close"].shift(1).fillna(df["close"]))]
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(x=df["date"], y=df["volume"], marker_color=colours, name="Volume"))
        fig2.update_layout(height=150, margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

        # Chart 3 — RSI y-axis 0–100 (180px)
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=df["date"], y=df["rsi_14"], name="RSI-14",
                                   line=dict(color="#9467bd", width=1.5)))
        fig3.add_hline(y=VALIDATION_CONFIG["rsi_overbought"], line_dash="dash", line_color="red", line_width=1)
        fig3.add_hline(y=VALIDATION_CONFIG["rsi_oversold"], line_dash="dash", line_color="green", line_width=1)
        fig3.update_yaxes(range=[0, 100])
        fig3.update_layout(height=180, margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
        st.plotly_chart(fig3, use_container_width=True)

        # Chart 4 — EMA vs SMA (180px)
        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(x=df["date"], y=df["macro_ema_3m"], name="EMA 3m",
                                   line=dict(color="#1f77b4", width=2)))
        fig4.add_trace(go.Scatter(x=df["date"], y=df["macro_sma_3m"], name="SMA 3m",
                                   line=dict(color="#ff7f0e", width=2, dash="dash")))
        fig4.update_layout(height=180, margin=dict(l=0, r=0, t=10, b=0),
                           legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig4, use_container_width=True)
        st.caption("Blue solid = EMA (accelerating rate). Orange dashed = SMA (lagging rate). "
                   "EMA above SMA signals tightening macro regime.")

    except Exception as e:
        st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
        st.stop()

# ============================= JUDGE =============================
with judge_col:
    st.markdown("#### Judge")
    CHECKPOINT = "judge_rag"
    try:
        # RAG card
        rc = rsi_colour
        rc_hex = RAG_CSS.get(rc, "#555")
        rc_bg = RAG_BG.get(rc, "#eee")
        rsi_display = f"{rsi_val:.1f}" if not pd.isna(rsi_val) else "—"
        st.markdown(
            f'<div class="rag-card" style="background:{rc_bg};color:{rc_hex};'
            f'font-size:1.3em;text-align:center;padding:24px;">'
            f'RSI {rsi_display}<br><span style="font-size:0.7em;">{rsi_label}</span></div>',
            unsafe_allow_html=True,
        )

        # AI explanation (auto-loaded on open)
        st.markdown("**AI Analysis**")
        explanation = st.session_state.get("llm_explanation", "")
        st.markdown(explanation)

        if st.button("Regenerate"):
            st.session_state.pop("llm_explanation", None)
            st.session_state["llm_explanation"] = call_llm(triggered_rules, latest)
            st.rerun()

        # Triggered rules
        st.markdown("**Triggered Rules**")
        if triggered_rules:
            for rule in triggered_rules:
                sev = rule["severity"]
                icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🔵"}.get(sev, "⚪")
                st.markdown(f"{icon} **{rule['name']}** ({sev})")
        else:
            st.success("No rules triggered.")

        # Custom rule manager
        with st.expander("Custom Rule Manager"):
            st.markdown("_Add, view, or deactivate your own rules._")
            con = get_connection()
            user_rules = con.execute(
                "SELECT rule_id, name, severity, active FROM user_nba_rules ORDER BY created_at DESC"
            ).df()
            if not user_rules.empty:
                st.dataframe(user_rules, use_container_width=True)
            else:
                st.info("No custom rules yet.")

            with st.form("add_rule_form"):
                r_name = st.text_input("Rule name")
                r_desc = st.text_input("Description")
                r_cond = st.text_input("Condition (text description)")
                r_sev = st.selectbox("Severity", ["LOW", "MEDIUM", "HIGH"])
                submitted = st.form_submit_button("Add Rule")
                if submitted and r_name:
                    new_id = f"U{str(uuid.uuid4())[:8].upper()}"
                    con.execute(
                        "INSERT INTO user_nba_rules VALUES (?, ?, ?, ?, ?, TRUE, ?)",
                        [new_id, r_name, r_desc, r_cond, r_sev, datetime.now(timezone.utc)],
                    )
                    st.success(f"Rule {new_id} added.")
                    st.rerun()

    except Exception as e:
        st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
        st.stop()

# ============================= ACT =============================
with act_col:
    st.markdown("#### Act")
    CHECKPOINT = "act_nba"
    try:
        con = get_connection()
        session_id = st.session_state.get("session_id") or str(uuid.uuid4())
        st.session_state["session_id"] = session_id

        ACTION_TYPES = [
            "Send to Trader",
            "Send for Analysis",
            "Add to Report",
            "Flag for Review",
        ]
        sev_icons = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🔵", "USER": "🔵"}

        if triggered_rules:
            for rule in triggered_rules:
                icon = sev_icons.get(rule["severity"], "⚪")
                with st.container():
                    st.markdown(f"**{icon} {rule['name']}**")
                    st.caption(rule["action"])
                    action_cols = st.columns(2)
                    for i, action_type in enumerate(ACTION_TYPES):
                        btn_col = action_cols[i % 2]
                        btn_key = f"btn_{rule['id']}_{action_type.replace(' ','_')}"
                        if btn_col.button(action_type, key=btn_key):
                            ref_id = f"REF-{str(uuid.uuid4())[:8].upper()}"
                            con.execute(
                                "INSERT INTO audit_nba_actions VALUES (?, ?, ?, ?, ?, ?)",
                                [
                                    str(uuid.uuid4()), ref_id, session_id,
                                    action_type, rule["id"],
                                    datetime.now(timezone.utc),
                                ],
                            )
                            log_entry = {
                                "ref_id": ref_id,
                                "action": action_type,
                                "rule": rule["name"],
                                "at": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                            }
                            st.session_state["action_log"].insert(0, log_entry)
                            st.session_state["action_log"] = st.session_state["action_log"][:10]
                            st.success(f"Logged {ref_id}")
                st.markdown("---")
        else:
            st.info("No actions required.")

        # PDF export
        if st.button("Export PDF Report"):
            CHECKPOINT = "pdf_export"
            try:
                from io import BytesIO

                from reportlab.lib import colors
                from reportlab.lib.pagesizes import A4
                from reportlab.lib.styles import getSampleStyleSheet
                from reportlab.lib.units import cm
                from reportlab.platypus import (
                    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
                )

                buf = BytesIO()
                doc = SimpleDocTemplate(buf, pagesize=A4,
                                        rightMargin=2*cm, leftMargin=2*cm,
                                        topMargin=2*cm, bottomMargin=2*cm)
                styles = getSampleStyleSheet()
                story = []

                story.append(Paragraph(f"Market Intelligence Report — {selected_symbol}", styles["Title"]))
                story.append(Paragraph(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", styles["Normal"]))
                story.append(Spacer(1, 0.4*cm))

                story.append(Paragraph("Snapshot", styles["Heading2"]))
                snap_data = [
                    ["Metric", "Value"],
                    ["Close", f"${close_val:,.2f}"],
                    ["VWAP 20d", f"${vwap_val:,.2f}" if not pd.isna(vwap_val) else "—"],
                    ["RSI-14", f"{rsi_val:.1f}" if not pd.isna(rsi_val) else "—"],
                    [f"{selected_macro}", f"{macro_val:.2f}%"],
                ]
                snap_table = Table(snap_data, colWidths=[7*cm, 7*cm])
                snap_table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
                ]))
                story.append(snap_table)
                story.append(Spacer(1, 0.4*cm))

                story.append(Paragraph("KPI Scorecard", styles["Heading2"]))
                kpi_data = [
                    ["KPI", "Value"],
                    ["Sharpe 20d", f"{sharpe_val:.2f}" if not pd.isna(sharpe_val) else "—"],
                    ["Max Drawdown 90d", f"{mdd_val:.1f}%" if not pd.isna(mdd_val) else "—"],
                    ["Volatility 20d", f"{vol_val:.1f}%" if not pd.isna(vol_val) else "—"],
                    ["VWAP Efficiency", f"{vwap_eff_val:.1f}" if not pd.isna(vwap_eff_val) else "—"],
                ]
                kpi_table = Table(kpi_data, colWidths=[7*cm, 7*cm])
                kpi_table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
                ]))
                story.append(kpi_table)
                story.append(Spacer(1, 0.4*cm))

                story.append(Paragraph("Triggered Rules", styles["Heading2"]))
                if triggered_rules:
                    for r in triggered_rules:
                        story.append(Paragraph(f"• [{r['severity']}] {r['name']}: {r['action']}", styles["Normal"]))
                else:
                    story.append(Paragraph("No rules triggered.", styles["Normal"]))
                story.append(Spacer(1, 0.4*cm))

                story.append(Paragraph("AI Rationale", styles["Heading2"]))
                story.append(Paragraph(st.session_state.get("llm_explanation", "—"), styles["Normal"]))
                story.append(Spacer(1, 0.6*cm))

                story.append(Paragraph(
                    "DISCLAIMER: Decision support only. Not financial advice. "
                    "This report is generated for informational purposes only and does not "
                    "constitute investment advice or a recommendation to buy or sell any security.",
                    styles["Italic"],
                ))

                doc.build(story)
                buf.seek(0)
                st.download_button(
                    "Download PDF",
                    data=buf,
                    file_name=f"market_report_{selected_symbol}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime="application/pdf",
                )
            except Exception as pdf_err:
                st.error(f"Checkpoint [{CHECKPOINT}] failed: {pdf_err}")

        # Action log
        if st.session_state["action_log"]:
            st.markdown("**Session Action Log**")
            for entry in st.session_state["action_log"]:
                st.markdown(
                    f'<small style="color:grey;">{entry["at"]}</small> '
                    f'**{entry["ref_id"]}** — {entry["action"]} ({entry["rule"]})',
                    unsafe_allow_html=True,
                )

    except Exception as e:
        st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
        st.stop()

# ---------------------------------------------------------------------------
# Metadata footer
# ---------------------------------------------------------------------------
st.divider()
CHECKPOINT = "metadata_footer"
try:
    meta = load_last_run_meta()
    if meta:
        ft = meta.get("finished_at")
        ft_str = ft.strftime("%Y-%m-%d %H:%M UTC") if hasattr(ft, "strftime") else str(ft)
        st.caption(
            f"Last pipeline run: **{meta.get('step')}** | "
            f"Status: **{meta.get('status')}** | "
            f"Rows: **{meta.get('rows_out')}** | "
            f"Finished: {ft_str}"
        )
except Exception as e:
    st.caption(f"Metadata unavailable: {e}")
