"""
Market Analytics Dashboard 
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
    "lookback_min": 21,
    "lookback_max": 90,
    "lookback_default": 60,
    "lookback_days": 90,  # alias used by period preset buttons
}

METRIC_DEFINITIONS = {
    "RSI-14": (
        "Relative Strength Index (14-day, Wilder's smoothed average). "
        "Measures momentum: >70 = overbought, <30 = oversold, 40–60 = neutral. "
        "Standard technical indicator used across institutional platforms."
    ),
    "VWAP 20d": (
        "Volume-Weighted Average Price over 20 days. "
        "Shows where the market traded weighted by volume — the institutional fair value reference. "
        "Price above VWAP = bullish momentum. Below = bearish."
    ),
    "Sharpe 20d": (
        "Risk-adjusted return over 20 days, annualised. "
        "Excess return above the Fed Funds rate (risk-free rate) divided by volatility. "
        ">1 = good, 0–1 = acceptable, <0 = risk is not being compensated."
    ),
    "Max Drawdown 90d": (
        "Worst peak-to-trough loss over the last 90 days. "
        "Standard downside risk measure used in portfolio risk management. "
        ">-10% = controlled, -10% to -20% = elevated, <-20% = critical."
    ),
    "Volatility 20d": (
        "Annualised standard deviation of daily returns over 20 days. "
        "Measures market risk level. "
        "<12% = low, 12–20% = normal, >20% = elevated, >30% = crisis."
    ),
    "VWAP Efficiency": (
        "How consistently price stays near its volume-weighted fair value. "
        "100 = price always at VWAP. Lower = persistent deviation. "
        ">97 = orderly market, 94–97 = normal, <94 = momentum or mean-reversion signal."
    ),
    "Yield Spread": (
        "10Y Treasury yield (GS10) minus Fed Funds rate. "
        "Positive and widening = bond market pricing future rate cuts (equities historically supportive). "
        "Negative = yield curve inverted, historically precedes recession."
    ),
    "EMA vs SMA": (
        "3-month Exponential Moving Average vs Simple Moving Average of the Fed Funds rate. "
        "EMA responds faster to recent moves. EMA above SMA = rate accelerating. "
        "EMA below SMA = rate decelerating. Signals macro regime shifts."
    ),
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
def _safe_float(val, default: float) -> float:
    try:
        f = float(val)
        return default if pd.isna(f) else f
    except (TypeError, ValueError):
        return default


def evaluate_nba_rules(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    latest = df.iloc[-1]
    rules = []

    def _rule(rid, name, severity, condition, action):
        if condition:
            rules.append({"id": rid, "name": name, "severity": severity, "action": action})

    # Use safe_float with neutral defaults so null values never silently suppress rules
    rsi = _safe_float(latest.get("rsi_14"), default=50.0)
    vwap = _safe_float(latest.get("vwap_20d"), default=0.0)
    close = _safe_float(latest.get("close"), default=0.0)
    sharpe = _safe_float(latest.get("sharpe_20d"), default=1.0)
    mdd = _safe_float(latest.get("mdd_90d"), default=0.0)
    vol = _safe_float(latest.get("volatility_20d"), default=15.0)
    vwap_eff = _safe_float(latest.get("vwap_efficiency"), default=97.0)
    ema = _safe_float(latest.get("macro_ema_3m"), default=0.0)
    sma = _safe_float(latest.get("macro_sma_3m"), default=0.0)
    macro = _safe_float(latest.get("macro_value"), default=0.0)
    spread = _safe_float(latest.get("yield_spread"), default=0.0)

    # Track which values were actually present (not defaulted) for rule gating
    has_rsi = latest.get("rsi_14") is not None and not pd.isna(latest.get("rsi_14", float("nan")))
    has_vwap = latest.get("vwap_20d") is not None and not pd.isna(latest.get("vwap_20d", float("nan")))
    has_sharpe = latest.get("sharpe_20d") is not None and not pd.isna(latest.get("sharpe_20d", float("nan")))
    has_mdd = latest.get("mdd_90d") is not None and not pd.isna(latest.get("mdd_90d", float("nan")))
    has_vol = latest.get("volatility_20d") is not None and not pd.isna(latest.get("volatility_20d", float("nan")))
    has_ema_sma = (latest.get("macro_ema_3m") is not None and not pd.isna(latest.get("macro_ema_3m", float("nan")))
                   and latest.get("macro_sma_3m") is not None and not pd.isna(latest.get("macro_sma_3m", float("nan"))))
    has_spread = latest.get("yield_spread") is not None and not pd.isna(latest.get("yield_spread", float("nan")))
    has_macro = latest.get("macro_value") is not None and not pd.isna(latest.get("macro_value", float("nan")))

    # Technical rules
    _rule("T1", "RSI Overbought", "HIGH",
          has_rsi and rsi >= VALIDATION_CONFIG["rsi_overbought"],
          "Consider reducing equity exposure — momentum extended")
    _rule("T2", "RSI Oversold", "MEDIUM",
          has_rsi and rsi <= VALIDATION_CONFIG["rsi_oversold"],
          "Potential entry opportunity — monitor for reversal")
    _rule("T3", "Price Below VWAP", "MEDIUM",
          has_vwap and close > 0 and close < vwap,
          "Price trading below VWAP — selling pressure present")
    _rule("T4", "VWAP Efficiency Low", "LOW",
          has_vwap and vwap_eff < VALIDATION_CONFIG["vwap_eff_signal"],
          "High deviation from VWAP — increased execution cost risk")

    # KPI rules
    _rule("K1", "Negative Sharpe", "HIGH",
          has_sharpe and sharpe < VALIDATION_CONFIG["sharpe_amber"],
          "Risk-adjusted returns negative — review position sizing")
    _rule("K2", "Max Drawdown Alert", "HIGH",
          has_mdd and mdd < VALIDATION_CONFIG["mdd_red"],
          "Drawdown exceeds 20% — activate drawdown risk protocol")
    _rule("K3", "High Volatility", "MEDIUM",
          has_vol and vol > VALIDATION_CONFIG["vol_red"],
          "Annualised volatility above 30% — reduce leverage")
    _rule("K4", "Elevated Volatility", "LOW",
          has_vol and VALIDATION_CONFIG["vol_amber"] < vol <= VALIDATION_CONFIG["vol_red"],
          "Volatility elevated (20–30%) — monitor risk parameters")

    # Macro rules
    _rule("M1", "EMA Above SMA", "LOW",
          has_ema_sma and ema > sma,
          "Rate accelerating above trend — tightening macro regime")
    _rule("M2", "EMA Below SMA", "LOW",
          has_ema_sma and ema < sma,
          "Rate decelerating below trend — easing macro regime")
    _rule("M3", "Inverted Yield Curve", "HIGH",
          has_spread and spread < VALIDATION_CONFIG["spread_red"],
          "Yield curve inverted — historically precedes recession, exercise caution")
    _rule("M4", "High Fed Funds Rate", "MEDIUM",
          has_macro and macro > 4.0,
          "Fed Funds above 4% — restrictive monetary policy environment")

    # Sort: HIGH → MEDIUM → LOW
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return sorted(rules, key=lambda r: order.get(r["severity"], 9))


def _fmt_val(val, fmt=".2f", suffix="") -> str:
    try:
        return f"{float(val):{fmt}}{suffix}" if val is not None and not pd.isna(val) else "N/A"
    except (TypeError, ValueError):
        return "N/A"


def _build_market_context(row: pd.Series, rules: list[dict]) -> str:
    """Build the shared market context string passed to the LLM."""
    triggered = ", ".join(r["name"] for r in rules) if rules else "none"
    return (
        f"Symbol: {SYMBOL}\n"
        f"Close: {_fmt_val(row.get('close'))}\n"
        f"RSI-14: {_fmt_val(row.get('rsi_14'), '.1f')}\n"
        f"VWAP 20d: {_fmt_val(row.get('vwap_20d'))}\n"
        f"Sharpe 20d: {_fmt_val(row.get('sharpe_20d'))}\n"
        f"Max Drawdown 90d: {_fmt_val(row.get('mdd_90d'), '.1f', '%')}\n"
        f"Volatility 20d: {_fmt_val(row.get('volatility_20d'), '.1f', '%')}\n"
        f"VWAP Efficiency: {_fmt_val(row.get('vwap_efficiency'), '.1f')}\n"
        f"Fed Funds Rate: {_fmt_val(row.get('macro_value'), '.2f', '%')}\n"
        f"GS10 10Y Treasury: {_fmt_val(row.get('gs10_value'), '.2f', '%')}\n"
        f"Yield Spread (GS10-FEDFUNDS): {_fmt_val(row.get('yield_spread'), '.2f', '%')}\n"
        f"EMA 3m: {_fmt_val(row.get('macro_ema_3m'), '.3f')}\n"
        f"SMA 3m: {_fmt_val(row.get('macro_sma_3m'), '.3f')}\n"
        f"Triggered rules: {triggered}"
    )


def _kimi_post(messages: list[dict], max_tokens: int = 400) -> tuple[str | None, str | None]:
    """
    POST to Kimi API. Returns (content, error_msg).
    error_msg is None on success, set on any failure.
    """
    import requests as req
    try:
        resp = req.post(
            "https://api.moonshot.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {KIMI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "moonshot-v1-8k", "messages": messages,
                  "max_tokens": max_tokens, "temperature": 0.3},
            timeout=15,
        )
        if resp.status_code == 401:
            return None, "AI analyst offline — API key invalid or expired. Update KIMI_API_KEY in .env."
        if resp.status_code != 200:
            return None, f"AI analyst offline — API error {resp.status_code}."
        return resp.json()["choices"][0]["message"]["content"].strip(), None
    except req.exceptions.Timeout:
        return None, "AI analyst offline — request timed out."
    except Exception as exc:
        return None, f"AI analyst offline — {exc}"


def call_llm(rules: list[dict], latest_row: pd.Series) -> str:
    if not KIMI_API_KEY:
        return _rule_based_summary(rules)

    context = _build_market_context(latest_row, rules)
    messages = [
        {"role": "system", "content": (
            "You are a senior portfolio analyst. Provide a concise 3–4 sentence "
            "market assessment for a portfolio manager. Be factual, reference the "
            "data, and note any key risks. Do not give specific buy/sell instructions."
        )},
        {"role": "user", "content": f"Current market data:\n{context}"},
    ]
    content, err = _kimi_post(messages)
    if err:
        return err + "\n\n" + _rule_based_summary(rules)
    return content


def call_llm_chat(question: str, latest_row: pd.Series, rules: list[dict],
                  history: list[dict]) -> str:
    """Answer a free-form question with full market context + conversation history."""
    if not KIMI_API_KEY:
        return "AI analyst offline — KIMI_API_KEY not configured. Update .env to enable chat."

    context = _build_market_context(latest_row, rules)
    system_msg = (
        "You are a senior portfolio analyst assistant for a post-trade operations team. "
        "You have access to the current market snapshot below. Answer questions concisely "
        "and accurately. Reference specific numbers from the data when relevant. "
        "Do not invent data not provided. Do not give specific buy/sell instructions.\n\n"
        f"Current market snapshot:\n{context}"
    )
    messages = [{"role": "system", "content": system_msg}]
    # Include up to last 6 turns of history for context
    messages.extend(history[-6:])
    messages.append({"role": "user", "content": question})

    content, err = _kimi_post(messages, max_tokens=500)
    if err:
        return err
    return content


def _rule_based_summary(rules: list[dict]) -> str:
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

# ---------------------------------------------------------------------------
# Dark / Light mode state
# ---------------------------------------------------------------------------
if "dark_mode" not in st.session_state:
    st.session_state["dark_mode"] = False

_dark = st.session_state["dark_mode"]

# Palette — swaps on toggle
_P = {
    "page_bg":    "#1a1a2e" if _dark else "#f8f9fa",
    "card_bg":    "#16213e" if _dark else "#ffffff",
    "border":     "#2a2a4a" if _dark else "#e8eaed",
    "text_pri":   "#e8eaf6" if _dark else "#1a1a2e",
    "text_sec":   "#7986cb" if _dark else "#9aa0a6",
    "text_body":  "#b0bec5" if _dark else "#5f6368",
    "hover_bg":   "#0d1b2a" if _dark else "#f8f9fa",
    "input_bg":   "#1e2a3a" if _dark else "#ffffff",
    "chip_bg":    "#1e2a3a" if _dark else "#f1f3f4",
}

st.markdown(f"""
<style>
/* Page background */
.stApp {{ background: {_P['page_bg']}; }}

/* Remove default Streamlit padding */
.block-container {{ padding-top: 0 !important; padding-bottom: 0 !important; max-width: 100% !important; }}

/* Hide Streamlit default header */
header[data-testid="stHeader"] {{ display: none; }}

/* Column dividers */
[data-testid="column"] {{
    background: {_P['card_bg']};
    padding: 20px 20px !important;
    border-right: 1px solid {_P['border']};
}}
[data-testid="column"]:last-child {{ border-right: none; }}

/* Metric overrides */
[data-testid="stMetric"] {{
    background: {_P['card_bg']};
    border: 1px solid {_P['border']};
    border-radius: 6px;
    padding: 10px 14px;
}}
[data-testid="stMetricLabel"] {{ font-size: 10px !important; color: {_P['text_sec']} !important; text-transform: uppercase; letter-spacing: .05em; }}
[data-testid="stMetricValue"] {{ font-size: 20px !important; font-weight: 500 !important; color: {_P['text_pri']} !important; }}

/* Button overrides */
.stButton > button {{
    border: 1px solid {_P['border']} !important;
    background: {_P['card_bg']} !important;
    color: {_P['text_body']} !important;
    font-size: 11px !important;
    padding: 5px 10px !important;
    border-radius: 4px !important;
    width: 100%;
}}
.stButton > button:hover {{
    background: {_P['hover_bg']} !important;
    border-color: {_P['text_sec']} !important;
}}

/* Text inputs */
[data-testid="stTextInput"] input {{
    background: {_P['input_bg']} !important;
    color: {_P['text_pri']} !important;
    border: 1px solid {_P['border']} !important;
}}

/* Info boxes */
[data-testid="stInfo"] {{
    background: {_P['hover_bg']} !important;
    border: 1px solid {_P['border']} !important;
    border-radius: 6px !important;
    font-size: 12px !important;
    color: {_P['text_body']} !important;
}}

/* Expander */
[data-testid="stExpander"] {{
    border: 1px solid {_P['border']} !important;
    border-radius: 6px !important;
    background: {_P['card_bg']} !important;
}}

/* Dataframe */
[data-testid="stDataFrame"] {{ background: {_P['card_bg']} !important; }}

/* Divider */
hr {{ border-color: {_P['border']} !important; margin: 12px 0 !important; }}

/* Caption */
.stCaption {{ font-size: 10px !important; color: {_P['text_sec']} !important; }}

/* Markdown text */
.stMarkdown p, .stMarkdown li {{ color: {_P['text_body']}; }}

/* Period preset buttons — compact chip style */
div[data-testid="column"] .stButton > button {{
    border: 1px solid {_P['border']} !important;
    background: {_P['card_bg']} !important;
    color: {_P['text_body']} !important;
    font-size: 11px !important;
    padding: 4px 0 !important;
    border-radius: 4px !important;
    font-weight: 400 !important;
}}
div[data-testid="column"] .stButton > button:hover {{
    background: {_P['hover_bg']} !important;
    border-color: {_P['text_sec']} !important;
    color: {_P['text_pri']} !important;
}}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Top-level tabs — market content renders into tab_market by default;
# governance content is explicitly wrapped at the bottom of this file.
# ---------------------------------------------------------------------------
tab_market, tab_governance, tab_observability = st.tabs(["📈 Market Analytics", "📋 Governance", "🔬 Observability"])

# Switch Streamlit's active container to tab_market for all content below
with tab_market:

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
        # Fix 12.4 — View controls label + renamed expander
        st.markdown("""
<div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
            letter-spacing:.1em;padding:0 0 8px 0;">
    View controls
</div>
""", unsafe_allow_html=True)

        with st.expander("Filter & period selection", expanded=True):
            # Fix 12.1 — industry-standard labels
            selected_symbol = st.selectbox("Index / instrument", symbols, index=0)
            selected_macro  = st.selectbox("Benchmark series", macro_series_list, index=0)

            # Fix 12.2 — period preset buttons + fine-tune slider
            st.markdown("""
<div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
            letter-spacing:.06em;margin-bottom:6px;margin-top:8px;">
    Analysis period
</div>
""", unsafe_allow_html=True)

            if "selected_days" not in st.session_state:
                st.session_state["selected_days"] = VALIDATION_CONFIG["lookback_default"]

            _max_days = VALIDATION_CONFIG["lookback_days"]
            _p1, _p2, _p3, _p4 = st.columns(4)
            if _p1.button("1M", use_container_width=True):
                st.session_state["selected_days"] = min(21, _max_days)
            if _p2.button("3M", use_container_width=True):
                st.session_state["selected_days"] = min(63, _max_days)
            if _p3.button("6M", use_container_width=True):
                st.session_state["selected_days"] = min(126, _max_days)
            if _p4.button("Max", use_container_width=True):
                st.session_state["selected_days"] = _max_days

            lookback = st.slider(
                "Fine-tune period",
                min_value=VALIDATION_CONFIG["lookback_min"],
                max_value=_max_days,
                value=st.session_state["selected_days"],
                step=7,
                label_visibility="collapsed",
            )
            st.session_state["selected_days"] = lookback

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
    # Consolidated header — line 1: equity metrics | line 2: macro/yield
    # ---------------------------------------------------------------------------
    CHECKPOINT = "consolidated_header"
    try:
        close_val = latest.get("close", float("nan"))
        vwap_val = latest.get("vwap_20d", float("nan"))
        rsi_val = latest.get("rsi_14", float("nan"))
        vol_val = latest.get("volatility_20d", float("nan"))
        macro_val = df["macro_value"].ffill().dropna().iloc[-1] if df["macro_value"].notna().any() else float("nan")
        gs10_val = df["gs10_value"].ffill().dropna().iloc[-1] if df["gs10_value"].notna().any() else float("nan")
        spread_val = gs10_val - macro_val if not (pd.isna(gs10_val) or pd.isna(macro_val)) else float("nan")
        rsi_colour, rsi_label = rsi_rag(rsi_val)

        prev_close = df.iloc[-2]["close"] if len(df) >= 2 else close_val
        day_chg = (close_val - prev_close) / prev_close * 100 if prev_close else 0
        chg_sign = "+" if day_chg >= 0 else ""

        if len(df) >= 30:
            avg_spread_30d = df["yield_spread"].tail(30).mean()
            spread_trend = "▲" if (not pd.isna(spread_val) and not pd.isna(avg_spread_30d) and spread_val > avg_spread_30d) else "▼"
        else:
            spread_trend = "—"

        sc = spread_colour(spread_val)
        sc_hex = RAG_CSS.get(sc, "#555")
        sc_bg = RAG_BG.get(sc, "#eee")
        rsi_hex = RAG_CSS.get(rsi_colour, "#555")
        rsi_bg = RAG_BG.get(rsi_colour, "#eee")

        # Topbar with dark/light toggle
        _tb_left, _tb_right = st.columns([8, 1])
        with _tb_left:
            st.markdown(f"""
    <div style="background:{_P['card_bg']};border-bottom:1px solid {_P['border']};
                padding:12px 0 12px 0;display:flex;align-items:center;
                justify-content:space-between;margin-bottom:0;">
        <span style="font-size:22px;font-weight:700;color:{_P['text_pri']};letter-spacing:-0.4px;">
            Market Analytics
        </span>
        <span style="font-size:11px;color:{_P['text_sec']};">
             Post-trade operations
        </span>
    </div>
    """, unsafe_allow_html=True)
        with _tb_right:
            _toggle_label = "☀️ Light" if _dark else "🌙 Dark"
            if st.button(_toggle_label, key="dark_mode_toggle"):
                st.session_state["dark_mode"] = not _dark
                st.rerun()

        # Determine RSI signal class
        _rsi_v = rsi_val if not pd.isna(rsi_val) else None
        if _rsi_v and _rsi_v >= VALIDATION_CONFIG["rsi_overbought"]:
            rag_class, rag_text = "over", "Overbought — review"
        elif _rsi_v and _rsi_v <= VALIDATION_CONFIG["rsi_oversold"]:
            rag_class, rag_text = "under", "Oversold — opportunity"
        elif _rsi_v and _rsi_v >= 60:
            rag_class, rag_text = "neutral", "Approaching overbought"
        elif _rsi_v and _rsi_v <= 40:
            rag_class, rag_text = "neutral", "Approaching oversold"
        else:
            rag_class, rag_text = "neutral", "Neutral — monitor"

        _rag_colors = {
            "over":    ("fef2f2", "b91c1c", "fecaca"),
            "under":   ("f0fdf4", "166534", "bbf7d0"),
            "neutral": ("fef9e7", "b45309", "fde68a"),
        }
        _bg, _fg, _border = _rag_colors[rag_class]

        rsi_display    = f"{rsi_val:.1f}" if not pd.isna(rsi_val) else "—"
        vwap_display   = f"${vwap_val:.2f}" if not pd.isna(vwap_val) else "—"
        macro_display  = f"{macro_val:.2f}%" if not pd.isna(macro_val) else "—"
        gs10_display   = f"{gs10_val:.2f}%" if not pd.isna(gs10_val) else "—"
        vol_display    = f"{vol_val:.1f}%" if not pd.isna(vol_val) else "—"
        mdd_now        = df["mdd_90d"].dropna().iloc[-1] if df["mdd_90d"].notna().any() else None
        mdd_display    = f"{mdd_now:.1f}%" if mdd_now is not None else "—"
        spread_color   = "#0f9d58" if not pd.isna(spread_val) and spread_val > 0 else "#d93025"
        spread_display = (
            f"{'+' if spread_val > 0 else ''}{spread_val:.2f}% {spread_trend}"
            if not pd.isna(spread_val) else "—"
        )
        change_color = "#0f9d58" if day_chg >= 0 else "#d93025"
        change_arrow = "▲" if day_chg >= 0 else "▼"

        meta = load_last_run_meta()
        last_run_ts = ""
        if meta:
            ft = meta.get("finished_at")
            last_run_ts = ft.strftime("%Y-%m-%d %H:%M") if hasattr(ft, "strftime") else str(ft)[:19]

        st.markdown(f"""
    <div style="background:{_P['card_bg']};border-bottom:1px solid {_P['border']};padding:14px 0 10px 0;margin-bottom:0;">

      <div style="font-size:10px;color:{_P['text_sec']};text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px;">
        Market overview
      </div>

      <div style="display:flex;align-items:baseline;gap:24px;margin-bottom:10px;flex-wrap:wrap;">
        <div>
          <div style="font-size:10px;color:{_P['text_sec']};text-transform:uppercase;letter-spacing:.05em;">Index close</div>
          <div style="font-size:22px;font-weight:500;color:{_P['text_pri']};line-height:1;">${close_val:.2f}</div>
          <div style="font-size:11px;color:{change_color}">{change_arrow} {abs(day_chg):.2f}%</div>
        </div>
        <div style="width:1px;height:36px;background:{_P['border']};align-self:center;"></div>
        <div>
          <div style="font-size:10px;color:{_P['text_sec']};text-transform:uppercase;letter-spacing:.05em;">VWAP 20d</div>
          <div style="font-size:22px;font-weight:500;color:{_P['text_pri']};line-height:1;">{vwap_display}</div>
          <div style="font-size:11px;color:{_P['text_sec']};">fair value</div>
        </div>
        <div style="width:1px;height:36px;background:{_P['border']};align-self:center;"></div>
        <div>
          <div style="font-size:10px;color:{_P['text_sec']};text-transform:uppercase;letter-spacing:.05em;">RSI-14</div>
          <div style="font-size:22px;font-weight:500;color:{_P['text_pri']};line-height:1;">{rsi_display}</div>
          <div style="font-size:11px;color:#b45309;">{rag_text.lower()}</div>
        </div>
        <div style="width:1px;height:36px;background:{_P['border']};align-self:center;"></div>
        <div>
          <div style="font-size:10px;color:{_P['text_sec']};text-transform:uppercase;letter-spacing:.05em;">Fed funds</div>
          <div style="font-size:22px;font-weight:500;color:{_P['text_pri']};line-height:1;">{macro_display}</div>
          <div style="font-size:11px;color:{_P['text_sec']};">risk-free rate</div>
        </div>
        <div style="width:1px;height:36px;background:{_P['border']};align-self:center;"></div>
        <div style="padding:5px 12px;border-radius:20px;font-size:12px;font-weight:500;
                    background:#{_bg};color:#{_fg};border:1px solid #{_border};align-self:center;">
          {rag_text}
        </div>
      </div>

      <div style="display:flex;align-items:center;gap:16px;font-size:11px;color:{_P['text_body']};
                  flex-wrap:wrap;padding-top:8px;border-top:1px solid {_P['border']};">
        <span style="font-size:10px;color:{_P['text_sec']};text-transform:uppercase;letter-spacing:.08em;margin-right:4px;">Macro / yield</span>
        <span>10Y Treasury <strong>{gs10_display}</strong></span>
        <span style="color:{_P['border']};">|</span>
        <span>Yield spread <strong style="color:{spread_color}">{spread_display}</strong></span>
        <span style="color:{_P['border']};">|</span>
        <span>Vol <strong>{vol_display}</strong></span>
        <span style="color:{_P['border']};">|</span>
        <span>MDD <strong>{mdd_display}</strong></span>
        <span style="margin-left:auto;background:{_P['chip_bg']};padding:2px 8px;border-radius:10px;color:{_P['text_sec']};">
          Run: {last_run_ts or '—'}
        </span>
      </div>

    </div>
    """, unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
        st.stop()

    st.divider()

    # ---------------------------------------------------------------------------
    # Risk Analytics
    # ---------------------------------------------------------------------------
    CHECKPOINT = "kpi_scorecard"
    try:
        sharpe_val   = df["sharpe_20d"].dropna().iloc[-1]   if df["sharpe_20d"].notna().any()   else None
        mdd_val      = df["mdd_90d"].dropna().iloc[-1]       if df["mdd_90d"].notna().any()       else None
        vol_kpi      = df["volatility_20d"].dropna().iloc[-1] if df["volatility_20d"].notna().any() else None
        vwap_eff_val = df["vwap_efficiency"].dropna().iloc[-1] if df["vwap_efficiency"].notna().any() else None

        st.markdown(f"""
    <div style="font-size:10px;color:{_P['text_sec']};text-transform:uppercase;
                letter-spacing:.1em;padding:12px 0 8px 0;">
        Risk analytics
    </div>
    """, unsafe_allow_html=True)

        k1, k2, k3, k4 = st.columns(4)

        _tile_colors = {"good": "#0f9d58", "warn": "#b45309", "bad": "#d93025", "na": "#9aa0a6"}

        def kpi_tile(col, label, value, color, sublabel):
            col.markdown(f"""
    <div style="background:{_P['card_bg']};border:1px solid {_P['border']};border-radius:6px;
                padding:10px 14px;height:72px;">
      <div style="font-size:10px;color:{_P['text_sec']};text-transform:uppercase;
                  letter-spacing:.05em;margin-bottom:4px;">{label}</div>
      <div style="font-size:18px;font-weight:500;color:{_tile_colors[color]};
                  line-height:1;">{value}</div>
      <div style="font-size:10px;color:{_P['text_sec']};margin-top:3px;">{sublabel}</div>
    </div>
    """, unsafe_allow_html=True)

        kpi_tile(k1, "Sharpe 20d",
                 f"{sharpe_val:.2f}" if sharpe_val is not None else "—",
                 "good" if sharpe_val and sharpe_val > 1 else "warn" if sharpe_val and sharpe_val >= 0 else "bad" if sharpe_val is not None else "na",
                 "risk-adjusted return" if sharpe_val is not None else "warmup period")

        kpi_tile(k2, "Max drawdown 90d",
                 f"{mdd_val:.1f}%" if mdd_val is not None else "—",
                 "good" if mdd_val and mdd_val > -10 else "warn" if mdd_val and mdd_val > -20 else "bad" if mdd_val is not None else "na",
                 "controlled" if mdd_val and mdd_val > -10 else "elevated" if mdd_val is not None else "warmup period")

        kpi_tile(k3, "Volatility 20d",
                 f"{vol_kpi:.1f}%" if vol_kpi is not None else "—",
                 "good" if vol_kpi and vol_kpi < 12 else "warn" if vol_kpi and vol_kpi < 20 else "bad" if vol_kpi is not None else "na",
                 "low regime" if vol_kpi and vol_kpi < 12 else "elevated" if vol_kpi and vol_kpi >= 20 else "normal")

        kpi_tile(k4, "VWAP efficiency",
                 f"{vwap_eff_val:.1f}" if vwap_eff_val is not None else "—",
                 "good" if vwap_eff_val and vwap_eff_val > 97 else "warn" if vwap_eff_val and vwap_eff_val > 94 else "bad" if vwap_eff_val is not None else "na",
                 "orderly" if vwap_eff_val and vwap_eff_val > 97 else "deviation signal" if vwap_eff_val and vwap_eff_val <= 94 else "normal")

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

        get_connection().execute(
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
        st.markdown(f'<div style="font-size:13px;font-weight:600;color:{_P["text_pri"]};padding-bottom:10px;border-bottom:1px solid {_P["border"]};margin-bottom:14px;">Market conditions</div>', unsafe_allow_html=True)
        CHECKPOINT = "see_charts"
        try:
            import plotly.graph_objects as go

            CHART_COLORS = {
                "close":    "#1a1a2e",
                "vwap":     "#EF9F27",
                "rsi":      "#7c3aed",
                "ema":      "#378ADD",
                "sma":      "#EF9F27",
                "vol_up":   "#0f9d58",
                "vol_down": "#d93025",
                "grid":     "#f1f3f4",
                "zero":     "#e8eaed",
            }

            _chart_layout = dict(
                plot_bgcolor="#ffffff",
                paper_bgcolor="#ffffff",
                font=dict(family="system-ui, -apple-system, sans-serif", size=11, color="#5f6368"),
                margin=dict(t=32, b=24, l=8, r=8),
                legend=dict(orientation="h", y=-0.25, font=dict(size=10)),
                xaxis=dict(gridcolor="#f1f3f4", linecolor="#e8eaed", tickfont=dict(size=10)),
                yaxis=dict(gridcolor="#f1f3f4", linecolor="#e8eaed", tickfont=dict(size=10)),
            )

            # Chart 1 — Price + VWAP (220px)
            fig1 = go.Figure()
            fig1.add_trace(go.Scatter(x=df["date"], y=df["close"], name="Close",
                                       line=dict(color=CHART_COLORS["close"], width=1.5)))
            fig1.add_trace(go.Scatter(x=df["date"], y=df["vwap_20d"], name="VWAP 20d",
                                       line=dict(color=CHART_COLORS["vwap"], width=1.5, dash="dot")))
            fig1.update_layout(height=220, **_chart_layout)
            st.plotly_chart(fig1, use_container_width=True)

            # Chart 2 — Volume bars green/red (150px)
            colours = [CHART_COLORS["vol_up"] if c >= o else CHART_COLORS["vol_down"]
                       for c, o in zip(df["close"], df["close"].shift(1).fillna(df["close"]))]
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(x=df["date"], y=df["volume"], marker_color=colours, name="Volume"))
            fig2.update_layout(height=150, showlegend=False, **{k: v for k, v in _chart_layout.items() if k != "legend"})
            st.plotly_chart(fig2, use_container_width=True)

            # Chart 3 — RSI y-axis 0–100 (180px)
            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(x=df["date"], y=df["rsi_14"], name="RSI-14",
                                       line=dict(color=CHART_COLORS["rsi"], width=1.5)))
            fig3.add_hline(y=VALIDATION_CONFIG["rsi_overbought"], line_dash="dash",
                           line_color="#ef4444", line_width=0.8,
                           annotation_text="70", annotation_font_size=9)
            fig3.add_hline(y=VALIDATION_CONFIG["rsi_oversold"], line_dash="dash",
                           line_color="#10b981", line_width=0.8,
                           annotation_text="30", annotation_font_size=9)
            fig3.update_yaxes(range=[0, 100], tickvals=[0, 30, 70, 100])
            fig3.update_layout(height=180, showlegend=False, **{k: v for k, v in _chart_layout.items() if k != "legend"})
            st.plotly_chart(fig3, use_container_width=True)

            # Chart 4 — EMA vs SMA (180px)
            fig4 = go.Figure()
            fig4.add_trace(go.Scatter(x=df["date"], y=df["macro_ema_3m"], name="EMA 3m",
                                       line=dict(color=CHART_COLORS["ema"], width=2)))
            fig4.add_trace(go.Scatter(x=df["date"], y=df["macro_sma_3m"], name="SMA 3m",
                                       line=dict(color=CHART_COLORS["sma"], width=2, dash="dash")))
            fig4.update_layout(height=180, **_chart_layout)
            st.plotly_chart(fig4, use_container_width=True)
            st.caption("Blue solid = EMA (accelerating rate). Amber dashed = SMA (lagging rate). "
                       "EMA above SMA signals tightening macro regime.")

        except Exception as e:
            st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
            st.stop()

    # ============================= JUDGE =============================
    with judge_col:
        st.markdown(f'<div style="font-size:13px;font-weight:600;color:{_P["text_pri"]};padding-bottom:10px;border-bottom:1px solid {_P["border"]};margin-bottom:14px;">Signal analysis</div>', unsafe_allow_html=True)
        CHECKPOINT = "judge_rag"
        try:
            # RAG card
            _rag_styles = {
                "over":    {"bg": "#fef2f2", "border": "#fecaca", "val_color": "#b91c1c"},
                "under":   {"bg": "#f0fdf4", "border": "#bbf7d0", "val_color": "#166534"},
                "neutral": {"bg": "#fef9e7", "border": "#fde68a", "val_color": "#b45309"},
            }
            _s = _rag_styles[rag_class]
            st.markdown(f"""
    <div style="background:{_s['bg']};border:1px solid {_s['border']};border-radius:8px;
                padding:16px;text-align:center;margin-bottom:14px;">
      <div style="font-size:24px;font-weight:500;color:{_s['val_color']};">
        RSI {rsi_display}
      </div>
      <div style="font-size:11px;color:{_s['val_color']};opacity:.85;margin-top:4px;">
        {rag_text}
      </div>
    </div>
    """, unsafe_allow_html=True)

            # AI explanation (auto-loaded on open)
            st.markdown("**AI Analysis**")
            explanation = st.session_state.get("llm_explanation", "")
            st.markdown(explanation)

            if st.button("Regenerate"):
                st.session_state.pop("llm_explanation", None)
                st.session_state["llm_explanation"] = call_llm(triggered_rules, latest)
                st.rerun()

            # Triggered rules — styled chips
            st.markdown("<div style='font-size:11px;color:#9aa0a6;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;'>Triggered signals</div>", unsafe_allow_html=True)
            _rule_dot_colors = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#10b981", "USER": "#378add"}
            if triggered_rules:
                for rule in triggered_rules:
                    dot = _rule_dot_colors.get(rule["severity"], "#9aa0a6")
                    st.markdown(f"""
    <div style="display:flex;align-items:flex-start;gap:8px;padding:8px 10px;
                border:1px solid {_P['border']};border-radius:6px;margin-bottom:5px;background:{_P['card_bg']};">
      <div style="width:8px;height:8px;border-radius:50%;background:{dot};
                  flex-shrink:0;margin-top:3px;"></div>
      <div>
        <div style="font-size:11px;font-weight:500;color:{_P['text_pri']};">{rule['name']}</div>
        <div style="font-size:10px;color:{_P['text_sec']};">{rule['severity']} · {rule['action'][:60]}{'…' if len(rule['action'])>60 else ''}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
    <div style="display:flex;align-items:center;gap:8px;padding:8px 10px;
                border:1px solid {_P['border']};border-radius:6px;background:{_P['card_bg']};">
      <div style="width:8px;height:8px;border-radius:50%;background:#10b981;flex-shrink:0;"></div>
      <div style="font-size:11px;color:#166534;font-weight:500;">All signals within normal range</div>
    </div>
    """, unsafe_allow_html=True)

            st.divider()

            # Ask a question — chat with full market context
            st.markdown("<div style='font-size:11px;color:#9aa0a6;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;'>Ask the analyst</div>", unsafe_allow_html=True)

            if "chat_history" not in st.session_state:
                st.session_state["chat_history"] = []  # list of {"role": str, "content": str}

            # Render existing chat history
            for msg in st.session_state["chat_history"]:
                if msg["role"] == "user":
                    st.markdown(
                        f'<div style="background:{_P["chip_bg"]};border-radius:6px;padding:8px 10px;'
                        f'margin-bottom:4px;font-size:12px;color:{_P["text_pri"]};">'
                        f'<strong>You:</strong> {msg["content"]}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<div style="background:{_P["card_bg"]};border:1px solid {_P["border"]};border-radius:6px;'
                        f'padding:8px 10px;margin-bottom:4px;font-size:12px;color:{_P["text_body"]};">'
                        f'<strong>Analyst:</strong> {msg["content"]}</div>',
                        unsafe_allow_html=True,
                    )

            # Chat input
            with st.form("chat_form", clear_on_submit=True):
                user_q = st.text_input(
                    "Question",
                    placeholder="e.g. What does the yield spread mean right now?",
                    label_visibility="collapsed",
                )
                send = st.form_submit_button("Ask", use_container_width=True)
                if send and user_q.strip():
                    with st.spinner("Thinking…"):
                        answer = call_llm_chat(
                            user_q.strip(), latest, triggered_rules,
                            st.session_state["chat_history"],
                        )
                    st.session_state["chat_history"].append({"role": "user", "content": user_q.strip()})
                    st.session_state["chat_history"].append({"role": "assistant", "content": answer})
                    # Keep last 10 turns
                    st.session_state["chat_history"] = st.session_state["chat_history"][-10:]
                    st.rerun()

            if st.session_state["chat_history"]:
                if st.button("Clear chat", key="clear_chat"):
                    st.session_state["chat_history"] = []
                    st.rerun()

            st.divider()

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
                        get_connection().execute(
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
        st.markdown(f'<div style="font-size:13px;font-weight:600;color:{_P["text_pri"]};padding-bottom:10px;border-bottom:1px solid {_P["border"]};margin-bottom:14px;">Recommended actions</div>', unsafe_allow_html=True)
        CHECKPOINT = "act_nba"
        try:
            session_id = st.session_state.get("session_id") or str(uuid.uuid4())
            st.session_state["session_id"] = session_id

            def handle_action(action_type: str, rule_id: str) -> str:
                ref_id = f"REF-{str(uuid.uuid4())[:8].upper()}"
                get_connection().execute(
                    "INSERT INTO audit_nba_actions VALUES (?, ?, ?, ?, ?, ?)",
                    [str(uuid.uuid4()), ref_id, session_id, action_type, rule_id,
                     datetime.now(timezone.utc)],
                )
                rule_name = next((r["name"] for r in triggered_rules if r["id"] == rule_id), rule_id)
                log_entry = {
                    "ref_id": ref_id, "action": action_type,
                    "rule": rule_name, "at": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                }
                st.session_state["action_log"].insert(0, log_entry)
                st.session_state["action_log"] = st.session_state["action_log"][:10]
                return ref_id

            if triggered_rules:
                for rule in triggered_rules:
                    st.markdown(f"""
    <div style="border:1px solid {_P['border']};border-radius:6px;padding:10px 12px;margin-bottom:8px;background:{_P['card_bg']};">
      <div style="font-size:12px;font-weight:500;color:{_P['text_pri']};margin-bottom:2px;">{rule['name']}</div>
      <div style="font-size:10px;color:{_P['text_sec']};margin-bottom:6px;">{rule['severity']} · {rule['action'][:70]}{'…' if len(rule['action'])>70 else ''}</div>
    </div>
    """, unsafe_allow_html=True)
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("📨 Back office", key=f"bo_{rule['id']}"):
                            ref = handle_action("back_office", rule["id"])
                            st.success(f"Logged · {ref}")
                        if st.button("💬 Slack alert", key=f"sl_{rule['id']}"):
                            ref = handle_action("slack_alert", rule["id"])
                            st.success(f"Logged · {ref}")
                    with b2:
                        if st.button("👁 For review", key=f"rv_{rule['id']}"):
                            ref = handle_action("review", rule["id"])
                            st.success(f"Logged · {ref}")
                        if st.button("📋 Add to report", key=f"rp_{rule['id']}"):
                            ref = handle_action("report", rule["id"])
                            st.success(f"Logged · {ref}")
            else:
                st.markdown("""
    <div style="padding:12px;border:1px solid #e8eaed;border-radius:6px;
                background:#f0fdf4;text-align:center;font-size:12px;color:#166534;">
      No actions required
    </div>
    """, unsafe_allow_html=True)

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

                    story.append(Paragraph("Risk Analytics", styles["Heading2"]))
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
    # Footer
    # ---------------------------------------------------------------------------
    CHECKPOINT = "footer"
    try:
        _meta = load_last_run_meta()
        _rows    = _meta.get("rows_out", "—") if _meta else "—"
        _status  = _meta.get("status", "—")   if _meta else "—"
        _ft      = _meta.get("finished_at")   if _meta else None
        _last_ts = _ft.strftime("%Y-%m-%d %H:%M") if hasattr(_ft, "strftime") else str(_ft)[:19] if _ft else "—"
        _dq_color = "#0f9d58" if _status == "PASS" else "#d93025"

        st.markdown(f"""
    <div style="background:{_P['card_bg']};border-top:1px solid {_P['border']};padding:8px 0;margin-top:16px;
                display:flex;align-items:center;gap:20px;font-size:10px;color:{_P['text_sec']};flex-wrap:wrap;">
      <span>Last run: {_last_ts} UTC</span>
      <span>Rows in gold: {_rows}</span>
      <span style="color:{_dq_color};font-weight:500;">Status: {_status}</span>
      <span style="margin-left:auto;">Data: Alpha Vantage · FRED</span>
    </div>
    """, unsafe_allow_html=True)
    except Exception as e:
        st.caption(f"Footer unavailable: {e}")


with tab_governance:
    CHECKPOINT = "governance_tab"
    try:
        _gcon = get_connection()

        st.markdown("### Data Governance")
        st.caption(
            "Definitions and lineage live in DuckDB governance tables — the same database the pipeline writes to. "
            "In production these would be registered in Alation, Collibra, or DataHub and pulled via API. "
            "The pattern is identical — we just swap the source."
        )

        gov_tab1, gov_tab2, gov_tab3 = st.tabs([
            "📐 Metric Definitions", "🗂 Field & Layer Definitions", "🔗 Data Lineage"
        ])

        # ── Tab 1: Metric definitions ──────────────────────────────────────
        with gov_tab1:
            try:
                _df_metrics = _gcon.execute("""
                    SELECT display_name, definition, formula, source, sensitivity
                    FROM governance_definitions
                    WHERE category = 'metric'
                    ORDER BY definition_id
                """).df()
                _df_metrics.columns = ["Name", "Definition", "Formula", "Source", "Sensitivity"]
                for _, row in _df_metrics.iterrows():
                    with st.expander(f"**{row['Name']}**"):
                        st.markdown(row["Definition"])
                        if row["Formula"] and str(row["Formula"]) not in ("None", "nan"):
                            st.markdown("**Formula**")
                            st.code(row["Formula"], language=None)
                        _mc1, _mc2 = st.columns(2)
                        _mc1.markdown(f"**Source:** {row['Source']}")
                        _mc2.markdown(f"**Sensitivity:** `{row['Sensitivity']}`")
            except Exception as _e:
                st.error(f"Metric definitions failed: {_e}")

        # ── Tab 2: Field & Layer definitions ──────────────────────────────
        with gov_tab2:
            try:
                _df_fields = _gcon.execute("""
                    SELECT display_name, category, definition, source, sensitivity
                    FROM governance_definitions
                    WHERE category IN ('field', 'layer')
                    ORDER BY category DESC, definition_id
                """).df()
                _df_fields.columns = ["Name", "Category", "Definition", "Source", "Sensitivity"]
                st.dataframe(_df_fields, use_container_width=True, hide_index=True)
            except Exception as _e:
                st.error(f"Field definitions failed: {_e}")

        # ── Tab 3: Data Lineage ────────────────────────────────────────────
        with gov_tab3:
            try:
                # Live row counts per layer from audit_pipeline_runs
                _row_counts = {}
                for _layer in ("bronze", "silver", "gold"):
                    _r = _gcon.execute(
                        "SELECT MAX(rows_out) FROM audit_pipeline_runs WHERE layer = ? AND status = 'PASS'",
                        [_layer]
                    ).fetchone()[0]
                    _row_counts[_layer] = f"{int(_r):,}" if _r else "—"

                # ── Lineage flow diagram ──────────────────────────────────
                st.markdown(f"""
<div style="overflow-x:auto;padding:16px 0;">
<div style="display:flex;align-items:stretch;gap:0;min-width:900px;">

  <!-- Raw APIs -->
  <div style="background:{_P['card_bg']};border:1px solid {_P['border']};border-radius:8px;
              padding:14px 16px;min-width:160px;flex:1;">
    <div style="font-size:9px;color:{_P['text_sec']};text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">External</div>
    <div style="font-size:13px;font-weight:600;color:{_P['text_pri']};margin-bottom:8px;">Raw APIs</div>
    <div style="font-size:10px;color:{_P['text_sec']};line-height:1.6;">
      Alpha Vantage<br>TIME_SERIES_DAILY<br><br>
      FRED FEDFUNDS<br>FRED GS10
    </div>
  </div>

  <!-- Arrow -->
  <div style="display:flex;align-items:center;padding:0 10px;color:{_P['text_sec']};font-size:20px;">→</div>

  <!-- Bronze -->
  <div style="background:{_P['card_bg']};border:1px solid #b45309;border-radius:8px;
              padding:14px 16px;min-width:160px;flex:1;">
    <div style="font-size:9px;color:#b45309;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">Bronze</div>
    <div style="font-size:13px;font-weight:600;color:{_P['text_pri']};margin-bottom:8px;">bronze_av<br>bronze_fred<br>bronze_fred_gs10</div>
    <div style="font-size:10px;color:{_P['text_sec']};line-height:1.6;">
      Raw parquet, immutable<br>
      DQ: B1 retry · B2 rate limit<br>B3 schema · B4 dot→null<br>
      <strong style="color:#b45309;">{_row_counts.get('bronze','—')} rows</strong>
    </div>
  </div>

  <!-- Arrow -->
  <div style="display:flex;align-items:center;padding:0 10px;color:{_P['text_sec']};font-size:20px;">→</div>

  <!-- Silver -->
  <div style="background:{_P['card_bg']};border:1px solid #0f9d58;border-radius:8px;
              padding:14px 16px;min-width:160px;flex:1;">
    <div style="font-size:9px;color:#0f9d58;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">Silver</div>
    <div style="font-size:13px;font-weight:600;color:{_P['text_pri']};margin-bottom:8px;">silver_market</div>
    <div style="font-size:10px;color:{_P['text_sec']};line-height:1.6;">
      Cleaned · joined · UTC<br>
      AV daily ⋈ FRED monthly<br>
      DQ: S1–S5<br>
      <strong style="color:#0f9d58;">{_row_counts.get('silver','—')} rows</strong>
    </div>
  </div>

  <!-- Arrow -->
  <div style="display:flex;align-items:center;padding:0 10px;color:{_P['text_sec']};font-size:20px;">→</div>

  <!-- Gold -->
  <div style="background:{_P['card_bg']};border:1px solid #378ADD;border-radius:8px;
              padding:14px 16px;min-width:160px;flex:1;">
    <div style="font-size:9px;color:#378ADD;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">Gold</div>
    <div style="font-size:13px;font-weight:600;color:{_P['text_pri']};margin-bottom:8px;">gold_metrics</div>
    <div style="font-size:10px;color:{_P['text_sec']};line-height:1.6;">
      VWAP · RSI · EMA/SMA<br>
      Sharpe · MDD · Vol · Efficiency<br>
      DQ: G1–G5<br>
      <strong style="color:#378ADD;">{_row_counts.get('gold','—')} rows</strong>
    </div>
  </div>

  <!-- Arrow -->
  <div style="display:flex;align-items:center;padding:0 10px;color:{_P['text_sec']};font-size:20px;">→</div>

  <!-- Dashboard -->
  <div style="background:{_P['card_bg']};border:1px solid #7c3aed;border-radius:8px;
              padding:14px 16px;min-width:160px;flex:1;">
    <div style="font-size:9px;color:#7c3aed;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">Dashboard</div>
    <div style="font-size:13px;font-weight:600;color:{_P['text_pri']};margin-bottom:8px;">app.py :8501</div>
    <div style="font-size:10px;color:{_P['text_sec']};line-height:1.6;">
      Read-only from gold<br>
      See · Judge · Act<br>
      NBA rules · LLM · PDF<br>
      <strong style="color:#7c3aed;">gold only</strong>
    </div>
  </div>

</div>
</div>
""", unsafe_allow_html=True)

                st.caption(
                    "Bronze is immutable. Silver is trusted. Gold is the only permitted dashboard source. "
                    "Each hop applies progressively stricter DQ rules."
                )

                # ── Lineage hop table ─────────────────────────────────────
                st.markdown("#### Hop detail")
                _df_lineage = _gcon.execute("""
                    SELECT
                        source_name  AS "Source",
                        target_name  AS "Target",
                        target_layer AS "Layer",
                        dq_rules     AS "DQ rules",
                        schedule     AS "Schedule",
                        transform    AS "Transform"
                    FROM governance_lineage
                    ORDER BY lineage_id
                """).df()
                st.dataframe(_df_lineage, use_container_width=True, hide_index=True)

                # ── All definitions table with filter ─────────────────────
                st.markdown("#### Definitions catalogue")
                _cat_filter = st.selectbox(
                    "Filter by category",
                    ["All", "metric", "field", "layer"],
                    key="gov_cat_filter",
                )
                _where = "" if _cat_filter == "All" else f"WHERE category = '{_cat_filter}'"
                _df_defs = _gcon.execute(f"""
                    SELECT display_name AS "Name", category AS "Category",
                           definition AS "Definition", formula AS "Formula",
                           source AS "Source", sensitivity AS "Sensitivity"
                    FROM governance_definitions
                    {_where}
                    ORDER BY category, definition_id
                """).df()
                st.dataframe(_df_defs, use_container_width=True, hide_index=True)

            except Exception as _e:
                st.error(f"Lineage failed: {_e}")

    except Exception as e:
        st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")

# ---------------------------------------------------------------------------
# Observability tab
# ---------------------------------------------------------------------------
with tab_observability:
    CHECKPOINT = "observability_tab"
    try:
        import plotly.graph_objects as _go

        _ocon = get_connection()
        _runs_df = _ocon.execute("SELECT * FROM audit_pipeline_runs ORDER BY finished_at DESC").df()
        _dq_df   = _ocon.execute("SELECT * FROM audit_dq_results ORDER BY evaluated_at DESC").df()
        _quar_df = _ocon.execute("SELECT * FROM quarantine_records ORDER BY quarantine_timestamp DESC LIMIT 50").df()
        _nba_eval_df = _ocon.execute("SELECT * FROM audit_nba_evaluations ORDER BY evaluated_at DESC LIMIT 50").df()
        _nba_act_df  = _ocon.execute("SELECT * FROM audit_nba_actions ORDER BY timestamp DESC LIMIT 50").df()

        _obs_chart_layout = dict(
            plot_bgcolor=_P["card_bg"], paper_bgcolor=_P["card_bg"],
            font=dict(family="system-ui, -apple-system, sans-serif", size=11, color=_P["text_body"]),
            margin=dict(t=28, b=20, l=8, r=8),
            xaxis=dict(gridcolor=_P["border"], linecolor=_P["border"], tickfont=dict(size=10)),
            yaxis=dict(gridcolor=_P["border"], linecolor=_P["border"], tickfont=dict(size=10)),
        )

        if _runs_df.empty:
            st.warning("No pipeline runs found. Run the pipeline first.")
        else:
            _last_run    = _runs_df.iloc[0]
            _last_status = str(_last_run.get("status", "UNKNOWN"))
            _last_step   = str(_last_run.get("step", "—"))
            _last_time   = str(_last_run.get("finished_at", "—"))[:19]

            # ── Health banner ──────────────────────────────────────────────
            if _last_status == "PASS":
                _hbg, _hbr, _hfc, _htxt = "#f0fdf4", "#bbf7d0", "#0f9d58", "#166534"
                _hlabel = "HEALTHY"
            else:
                _hbg, _hbr, _hfc, _htxt = "#fef2f2", "#fecaca", "#d93025", "#b91c1c"
                _hlabel = "DEGRADED"

            st.markdown(f"""
<div style="background:{_hbg};border:1px solid {_hbr};border-radius:8px;
            padding:12px 16px;margin-bottom:12px;display:flex;align-items:center;gap:10px;">
  <div style="width:10px;height:10px;border-radius:50%;background:{_hfc};flex-shrink:0;"></div>
  <div style="font-size:13px;font-weight:600;color:{_htxt};">{_hlabel}</div>
  <div style="font-size:11px;color:{_htxt};">Last run: {_last_step} · {_last_time}</div>
</div>
""", unsafe_allow_html=True)

            # ── Issues panel ───────────────────────────────────────────────
            if not _dq_df.empty:
                _issues = _dq_df[_dq_df["status"].isin(["FAIL", "WARN"])]
                if not _issues.empty:
                    st.markdown(f"<div style='font-size:11px;color:{_P['text_sec']};text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;'>Issues</div>", unsafe_allow_html=True)
                    for _, _irow in _issues.iterrows():
                        _idot = "#d93025" if _irow["status"] == "FAIL" else "#f59e0b"
                        st.markdown(f"""
<div style="display:flex;align-items:flex-start;gap:8px;padding:8px 10px;
            border:1px solid {_P['border']};border-radius:6px;margin-bottom:4px;background:{_P['card_bg']};">
  <div style="width:8px;height:8px;border-radius:50%;background:{_idot};flex-shrink:0;margin-top:3px;"></div>
  <div style="font-size:11px;color:{_P['text_pri']};"><strong>[{_irow['layer'].upper()}] {_irow['rule_id']}</strong> — {_irow['detail']} ({_irow['rows_affected']} rows)</div>
</div>
""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""
<div style="display:flex;align-items:center;gap:8px;padding:8px 10px;
            border:1px solid {_P['border']};border-radius:6px;background:{_P['card_bg']};margin-bottom:8px;">
  <div style="width:8px;height:8px;border-radius:50%;background:#0f9d58;flex-shrink:0;"></div>
  <div style="font-size:11px;color:#166534;font-weight:500;">All DQ checks clean</div>
</div>
""", unsafe_allow_html=True)

            st.divider()

            # ── Hop cards ─────────────────────────────────────────────────
            st.markdown(f"<div style='font-size:11px;color:{_P['text_sec']};text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;'>Pipeline hops</div>", unsafe_allow_html=True)
            _layer_colors = {"bronze": "#b45309", "silver": "#0f9d58", "gold": "#378ADD"}
            _hop1, _hop2, _hop3 = st.columns(3)
            for _col, _layer in zip([_hop1, _hop2, _hop3], ["bronze", "silver", "gold"]):
                _lr = _runs_df[_runs_df["layer"] == _layer]
                _ld = _dq_df[_dq_df["layer"] == _layer]
                _lc = _layer_colors[_layer]
                if _lr.empty:
                    _col.markdown(f"""
<div style="background:{_P['card_bg']};border:1px solid {_P['border']};border-radius:6px;padding:12px 14px;">
  <div style="font-size:9px;color:{_lc};text-transform:uppercase;letter-spacing:.05em;">{_layer}</div>
  <div style="font-size:16px;font-weight:500;color:{_P['text_sec']};">No runs</div>
</div>""", unsafe_allow_html=True)
                    continue
                _last = _lr.iloc[0]
                _hst  = str(_last.get("status", "UNKNOWN"))
                _ri   = int(_last.get("rows_in") or 0)
                _ro   = int(_last.get("rows_out") or 0)
                _rq   = int(_last.get("rows_quarantined") or 0)
                _dp   = int((_ld["status"] == "PASS").sum())
                _dfn  = int((_ld["status"] == "FAIL").sum())
                _scolor = "#0f9d58" if _hst == "PASS" else "#d93025"
                _col.markdown(f"""
<div style="background:{_P['card_bg']};border:1px solid {_lc};border-radius:6px;padding:12px 14px;">
  <div style="font-size:9px;color:{_lc};text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">{_layer}</div>
  <div style="font-size:18px;font-weight:500;color:{_scolor};line-height:1;">{_hst}</div>
  <div style="font-size:11px;color:{_P['text_sec']};margin-top:4px;">{_ri:,} → {_ro:,} rows</div>
  <div style="font-size:10px;color:{_P['text_sec']};margin-top:2px;">DQ {_dp} PASS / {_dfn} FAIL · quarantined {_rq}</div>
</div>""", unsafe_allow_html=True)

            st.divider()

            # ── Row flow chart ─────────────────────────────────────────────
            _flow_data = []
            for _layer in ["bronze", "silver", "gold"]:
                _lr = _runs_df[_runs_df["layer"] == _layer]
                if not _lr.empty:
                    _last = _lr.iloc[0]
                    _flow_data.append({
                        "layer": _layer.capitalize(),
                        "rows_in": int(_last.get("rows_in") or 0),
                        "rows_out": int(_last.get("rows_out") or 0),
                    })
            if _flow_data:
                _flow_df = pd.DataFrame(_flow_data)
                _fig_flow = _go.Figure()
                _fig_flow.add_trace(_go.Bar(name="Rows In",  x=_flow_df["layer"], y=_flow_df["rows_in"],  marker_color="#378ADD"))
                _fig_flow.add_trace(_go.Bar(name="Rows Out", x=_flow_df["layer"], y=_flow_df["rows_out"], marker_color="#0f9d58"))
                _fig_flow.update_layout(
                    barmode="group", height=260,
                    legend=dict(orientation="h", y=1.15, font=dict(size=10)),
                    **_obs_chart_layout,
                )
                st.plotly_chart(_fig_flow, use_container_width=True)

            st.divider()

            # ── Run history sparkline ──────────────────────────────────────
            st.markdown(f"<div style='font-size:11px;color:{_P['text_sec']};text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;'>Run history (last 7)</div>", unsafe_allow_html=True)
            _recent = _runs_df.head(7).copy().iloc[::-1]
            if not _recent.empty:
                _recent["status_num"] = _recent["status"].apply(lambda s: 1 if s == "PASS" else 0)
                _fig_spark = _go.Figure()
                _fig_spark.add_trace(_go.Scatter(
                    x=_recent["finished_at"].astype(str),
                    y=_recent["rows_out"],
                    mode="lines+markers",
                    line=dict(color="#378ADD", width=2),
                    marker=dict(
                        color=_recent["status_num"].apply(lambda v: "#0f9d58" if v else "#d93025"),
                        size=10,
                    ),
                ))
                _fig_spark.update_layout(
                    height=180, showlegend=False,
                    **{k: v for k, v in _obs_chart_layout.items() if k != "legend"},
                )
                st.plotly_chart(_fig_spark, use_container_width=True)
                st.caption("Green dot = PASS · Red dot = FAIL")

            st.divider()

            # ── Quarantine log ────────────────────────────────────────────
            st.markdown(f"<div style='font-size:11px;color:{_P['text_sec']};text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;'>Quarantine log</div>", unsafe_allow_html=True)
            if _quar_df.empty:
                st.markdown(f"""
<div style="display:flex;align-items:center;gap:8px;padding:8px 10px;
            border:1px solid {_P['border']};border-radius:6px;background:{_P['card_bg']};">
  <div style="width:8px;height:8px;border-radius:50%;background:#0f9d58;flex-shrink:0;"></div>
  <div style="font-size:11px;color:#166534;font-weight:500;">No quarantined records — data quality clean</div>
</div>
""", unsafe_allow_html=True)
            else:
                st.dataframe(_quar_df[["quarantine_timestamp", "run_id", "rule_id", "reason"]], use_container_width=True, hide_index=True)

            st.divider()

            # ── NBA audit ─────────────────────────────────────────────────
            st.markdown(f"<div style='font-size:11px;color:{_P['text_sec']};text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;'>NBA audit</div>", unsafe_allow_html=True)
            _na1, _na2 = st.columns(2)
            with _na1:
                st.caption("Evaluations")
                if _nba_eval_df.empty:
                    st.info("No evaluations logged yet.")
                else:
                    st.dataframe(_nba_eval_df[["evaluated_at", "highest_severity", "triggered_rule_ids"]], use_container_width=True, hide_index=True)
            with _na2:
                st.caption("Actions taken")
                if _nba_act_df.empty:
                    st.info("No actions logged yet.")
                else:
                    st.dataframe(_nba_act_df[["timestamp", "reference_id", "action_type", "rule_ids"]], use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
