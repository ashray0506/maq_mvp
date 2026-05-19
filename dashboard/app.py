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

SCENARIO_EXPLANATIONS = {
    "Volatility shock": {
        "what": "Models what happens if market volatility rises sharply — for example during a risk-off event, earnings shock, or geopolitical uncertainty.",
        "how": "Volatility is the denominator in the Sharpe Ratio. As vol rises, risk-adjusted returns compress even if raw returns stay the same. Higher vol also implies greater drawdown risk on the equity leg.",
        "assumes": "Expected return held constant (conservative). Bond leg unaffected by equity vol shock. Expected loss = equity × annual vol × √(20/252). 60/40 illustrative allocation.",
        "watch_for": "Sharpe dropping below 0.5 or MDD crossing -10%.",
    },
    "Market drawdown": {
        "what": "Models a direct fall in the index — for example a correction, bear market entry, or macro shock causing broad equity selling.",
        "how": "The equity leg (60%) moves 1:1 with the index decline. The bond leg (40%) receives a partial flight-to-quality offset — bonds typically rally when equities sell off. MDD updates to the scenario level if it exceeds current.",
        "assumes": "Beta of 1 for equity leg (SPY as proxy). Flight-to-quality bond offset of 0.3× drawdown magnitude. 60/40 illustrative allocation.",
        "watch_for": "MDD crossing -15% (elevated) or -20% (critical).",
    },
    "Rate shock": {
        "what": "Models a sudden rise in the Federal Funds Rate — for example an emergency hike or hawkish surprise from the Federal Reserve.",
        "how": "Higher rates compress the yield spread (GS10 - FEDFUNDS). The bond leg loses value — approximated using modified duration. The risk-free rate in Sharpe rises, compressing excess return. Equity sees modest pressure as higher rates reduce valuations.",
        "assumes": "Modified duration of 7 years for bond leg (10Y proxy). GS10 yield held constant — Fed Funds moves only. Equity compression of 0.5× rate change. 60/40 illustrative allocation.",
        "watch_for": "Yield spread going negative — curve inversion historically precedes recession.",
    },
}

SCENARIO_RELEVANT_METRICS = {
    "Volatility shock": ["volatility_20d", "sharpe_20d", "mdd_90d"],
    "Market drawdown":  ["mdd_90d", "sharpe_20d", "volatility_20d"],
    "Rate shock":       ["yield_spread", "sharpe_20d", "macro_value"],
}

RULE_METRIC_MAP = {
    "T1": "rsi_14",  "T2": "rsi_14",  "T3": "vwap_20d",  "T4": "vwap_efficiency",
    "K1": "sharpe_20d", "K2": "mdd_90d", "K3": "volatility_20d", "K4": "volatility_20d",
    "M1": "macro_ema_3m", "M2": "macro_ema_3m", "M3": "yield_spread", "M4": "macro_value",
    "YIELD_INVERSION": "yield_spread", "YIELD_COMPRESSING": "yield_spread",
}

METRIC_DISPLAY = {
    "rsi_14": "RSI-14", "vwap_20d": "VWAP (20d)", "close": "Index close ($)",
    "macro_ema_3m": "Macro EMA (3m)", "macro_sma_3m": "Macro SMA (3m)",
    "macro_value": "Fed Funds rate (%)", "volatility_20d": "Volatility 20d (%)",
    "sharpe_20d": "Sharpe ratio (20d)", "mdd_90d": "Max drawdown 90d (%)",
    "gs10_value": "10Y Treasury yield (%)", "yield_spread": "Yield spread (%)",
}

OP_TEXT = {
    ">": "rises above", "<": "falls below",
    ">=": "reaches or exceeds", "<=": "falls to or below", "between": "is between",
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
def safe_float(row, col: str, default: float = 0.0) -> float:
    """Safe float from a Series row by column name."""
    try:
        v = float(row[col])
        return default if (v != v) else v  # NaN check
    except (TypeError, ValueError, KeyError):
        return default


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

    def sf(key, default=0.0):
        val = latest.get(key)
        try:
            f = float(val)
            return default if (f != f) else f  # NaN check
        except (TypeError, ValueError):
            return default

    rsi    = sf("rsi_14",         50.0)
    vwap   = sf("vwap_20d",       0.0)
    close  = sf("close",          0.0)
    sharpe = sf("sharpe_20d",     1.0)
    mdd    = sf("mdd_90d",        0.0)
    vol    = sf("volatility_20d", 15.0)
    ema    = sf("macro_ema_3m",   0.0)
    sma    = sf("macro_sma_3m",   0.0)
    spread = sf("yield_spread",   0.5)
    macro  = sf("macro_value",    0.0)

    system_rules = [
        {"rule_id": "RSI_OB", "condition": rsi > 70,
         "rule_name": "RSI Overbought", "severity": "HIGH",
         "nba_category": "Review / consider reducing exposure",
         "action": "Consider reducing equity exposure — momentum extended",
         "detail": f"RSI at {rsi:.1f} has crossed the overbought threshold of 70. Momentum is extended. Consider reviewing long exposure."},
        {"rule_id": "RSI_AMBER_UP", "condition": 60 <= rsi < 70,
         "rule_name": "RSI Approaching Overbought", "severity": "MEDIUM",
         "nba_category": "Monitor closely",
         "action": "RSI in 60–70 amber zone — watch for threshold breach",
         "detail": f"RSI at {rsi:.1f} is in the 60–70 amber zone. Not yet overbought but momentum is building. Watch for a cross above 70."},
        {"rule_id": "RSI_OS", "condition": rsi < 30,
         "rule_name": "RSI Oversold", "severity": "HIGH",
         "nba_category": "Review / consider adding exposure",
         "action": "Potential entry opportunity — monitor for reversal",
         "detail": f"RSI at {rsi:.1f} signals oversold conditions. Potential mean-reversion entry point."},
        {"rule_id": "RSI_AMBER_DOWN", "condition": 30 < rsi <= 40,
         "rule_name": "RSI Approaching Oversold", "severity": "MEDIUM",
         "nba_category": "Monitor closely",
         "action": "RSI in 30–40 amber zone — watch for further weakness",
         "detail": f"RSI at {rsi:.1f} is approaching oversold territory. Monitor for a break below 30."},
        {"rule_id": "VWAP_PREMIUM", "condition": close > vwap * 1.02 if vwap > 0 else False,
         "rule_name": "Price Extended Above VWAP", "severity": "LOW",
         "nba_category": "Momentum extended — caution",
         "action": "Price stretched above VWAP fair value",
         "detail": f"Close ${close:.2f} is {((close/vwap-1)*100):.1f}% above VWAP ${vwap:.2f}. Price extended above institutional fair value." if vwap > 0 else "VWAP unavailable."},
        {"rule_id": "VWAP_DISCOUNT", "condition": close < vwap * 0.98 if vwap > 0 else False,
         "rule_name": "Price Below VWAP", "severity": "LOW",
         "nba_category": "Potential value — review entry",
         "action": "Price trading below VWAP — selling pressure present",
         "detail": f"Close ${close:.2f} is below VWAP ${vwap:.2f}. Price below institutional fair value — potential support level."},
        {"rule_id": "EMA_CROSS_UP", "condition": ema > sma,
         "rule_name": "EMA Above SMA — Macro Accelerating", "severity": "LOW",
         "nba_category": "Macro tightening — review fixed income exposure",
         "action": "Rate accelerating above trend — tightening macro regime",
         "detail": f"3-month EMA ({ema:.3f}) is above SMA ({sma:.3f}) on Fed Funds. Rate is accelerating — historically precedes further tightening."},
        {"rule_id": "EMA_CROSS_DOWN", "condition": ema < sma,
         "rule_name": "EMA Below SMA — Macro Decelerating", "severity": "LOW",
         "nba_category": "Macro easing signal — review exposure",
         "action": "Rate decelerating below trend — easing macro regime",
         "detail": f"3-month EMA ({ema:.3f}) is below SMA ({sma:.3f}) on Fed Funds. Rate is decelerating — easing macro conditions may follow."},
        {"rule_id": "SHARPE_NEG", "condition": sharpe < 0,
         "rule_name": "Negative Risk-Adjusted Return", "severity": "HIGH",
         "nba_category": "Review position — risk not compensated",
         "action": "Risk-adjusted returns negative — review position sizing",
         "detail": f"Sharpe ratio of {sharpe:.2f} — returns are not compensating for risk. Immediate review warranted."},
        {"rule_id": "SHARPE_LOW", "condition": 0 <= sharpe < 0.5,
         "rule_name": "Below-Benchmark Risk-Adjusted Return", "severity": "MEDIUM",
         "nba_category": "Monitor — returns below risk threshold",
         "action": "Sharpe below 0.5 — risk-adjusted returns weak",
         "detail": f"Sharpe of {sharpe:.2f} is below the 0.5 threshold. Risk-adjusted returns are weak relative to vol taken."},
        {"rule_id": "MDD_CRITICAL", "condition": mdd < -20,
         "rule_name": "Critical Drawdown", "severity": "HIGH",
         "nba_category": "Immediate review — drawdown exceeds 20%",
         "action": "Drawdown exceeds 20% — activate drawdown risk protocol",
         "detail": f"90-day max drawdown of {mdd:.1f}% is critical. Review position sizing immediately."},
        {"rule_id": "MDD_ELEVATED", "condition": -20 <= mdd < -10,
         "rule_name": "Elevated Drawdown", "severity": "MEDIUM",
         "nba_category": "Review position sizing",
         "action": "Drawdown elevated — review position sizing",
         "detail": f"90-day max drawdown of {mdd:.1f}% is elevated. Consider whether position sizing remains appropriate."},
        {"rule_id": "VOL_CRISIS", "condition": vol > 30,
         "rule_name": "Crisis-Level Volatility", "severity": "HIGH",
         "nba_category": "Immediate risk review — vol > 30%",
         "action": "Annualised volatility above 30% — reduce leverage",
         "detail": f"Annualised volatility of {vol:.1f}% is at crisis level. Leverage should be reduced immediately."},
        {"rule_id": "VOL_ELEVATED", "condition": 20 < vol <= 30,
         "rule_name": "Elevated Volatility", "severity": "MEDIUM",
         "nba_category": "Reduce position size — elevated vol",
         "action": "Volatility elevated (20–30%) — monitor risk parameters",
         "detail": f"Annualised volatility of {vol:.1f}% is elevated. Consider reducing position size."},
        {"rule_id": "YIELD_INVERSION", "condition": spread < 0,
         "rule_name": "Yield Curve Inverted", "severity": "HIGH",
         "nba_category": "Macro warning — inversion precedes recession",
         "action": "Yield curve inverted — historically precedes recession",
         "detail": f"Yield spread negative at {spread:.2f}%. Inverted yield curve historically precedes recession."},
        {"rule_id": "YIELD_COMPRESSING", "condition": 0 <= spread < 0.3,
         "rule_name": "Yield Spread Compressing", "severity": "MEDIUM",
         "nba_category": "Macro caution — spread narrowing",
         "action": "Yield spread narrowing toward inversion — watch closely",
         "detail": f"Yield spread at {spread:.2f}% is narrowing toward zero. Watch for full inversion."},
        {"rule_id": "M4_HIGH_RATES", "condition": macro > 4.0,
         "rule_name": "High Fed Funds Rate", "severity": "MEDIUM",
         "nba_category": "Restrictive monetary policy environment",
         "action": "Fed Funds above 4% — restrictive monetary policy",
         "detail": f"Fed Funds at {macro:.2f}% — restrictive policy. Higher borrowing costs weigh on equity valuations. Monitor for policy pivot."},
    ]

    triggered = [
        {"id": r["rule_id"], "name": r["rule_name"], "severity": r["severity"],
         "action": r["action"], "detail": r["detail"],
         "nba_category": r["nba_category"], "is_user_rule": False}
        for r in system_rules if r.pop("condition")
    ]

    rules = triggered

    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return sorted(rules, key=lambda r: order.get(r["severity"], 9))


def chart_layout(dark_mode: bool, title: str = "", height: int = 220) -> dict:
    """Consistent Plotly layout dict for the current theme."""
    bg         = "#1a1d27" if dark_mode else "#ffffff"
    grid       = "#2d3142" if dark_mode else "#f1f3f4"
    font_color = "#9aa0a6" if dark_mode else "#5f6368"
    line_color = "#2d3142" if dark_mode else "#e8eaed"
    return dict(
        title=dict(text=title, font=dict(size=11, color=font_color)),
        height=height,
        plot_bgcolor=bg,
        paper_bgcolor=bg,
        font=dict(family="system-ui, -apple-system, sans-serif", size=11, color=font_color),
        margin=dict(t=32, b=24, l=8, r=8),
        legend=dict(orientation="h", y=-0.3, font=dict(size=10, color=font_color)),
        xaxis=dict(gridcolor=grid, linecolor=line_color, tickfont=dict(size=10, color=font_color)),
        yaxis=dict(gridcolor=grid, linecolor=line_color, tickfont=dict(size=10, color=font_color)),
    )


def evaluate_nba_on_projected(projected: dict) -> list[dict]:
    """Re-run NBA rules against projected metric values. Tags each rule name."""
    rules = evaluate_nba_rules(pd.DataFrame([projected]))
    for r in rules:
        r["name"] = f"[PROJECTED] {r['name']}"
    return rules


def filter_projected_rules(rules: list[dict], scenario_type: str) -> list[dict]:
    """Keep only rules whose metric is relevant to the given scenario type."""
    relevant = SCENARIO_RELEVANT_METRICS.get(scenario_type, [])
    filtered = [r for r in rules if RULE_METRIC_MAP.get(r["id"]) in relevant]
    for r in filtered:
        r["name"] = r["name"].replace("[PROJECTED] ", "")
    return filtered


def render_kpi_comparison(col, label: str, current_val: str, projected_val: str, better_when: str) -> None:
    try:
        curr_num = float(str(current_val).replace("%", ""))
        proj_num = float(str(projected_val).replace("%", ""))
        change = proj_num - curr_num
        is_worse = change < 0 if better_when == "higher" else change > 0
        arrow = "▼" if change < 0 else "▲"
        color = "#d93025" if is_worse else "#0f9d58"
        worse_label = "(worse)" if is_worse else "(better)"
        change_str = f"{change:+.2f}"
    except Exception:
        color = "#9aa0a6"; arrow = "→"; worse_label = ""; change_str = "—"

    col.markdown(f"""
<div style="background:{_P['card_bg']};border:1px solid {_P['border']};border-radius:6px;
            padding:12px;text-align:center;">
  <div style="font-size:10px;color:{_P['text_sec']};text-transform:uppercase;
              letter-spacing:.05em;margin-bottom:10px;">{label}</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px;">
    <div style="background:{_P['hover_bg']};border-radius:4px;padding:6px;">
      <div style="font-size:9px;color:{_P['text_sec']};margin-bottom:2px;">CURRENT</div>
      <div style="font-size:16px;font-weight:500;color:{_P['text_pri']};">{current_val}</div>
    </div>
    <div style="background:{_P['hover_bg']};border-radius:4px;padding:6px;
                border:1px solid {color}44;">
      <div style="font-size:9px;color:{_P['text_sec']};margin-bottom:2px;">PROJECTED</div>
      <div style="font-size:16px;font-weight:500;color:{color};">{projected_val}</div>
    </div>
  </div>
  <div style="font-size:11px;color:{color};font-weight:500;">
    {arrow} {change_str} {worse_label}
  </div>
</div>
""", unsafe_allow_html=True)


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
        f"Triggered rules: {triggered}\n\n"
        "SCOPE BOUNDARY: Only answer questions about the market data above. "
        "If asked about specific securities to buy or sell, trading recommendations, "
        "or anything not in this snapshot, respond: "
        "'That is outside the scope of this platform data. I can only answer questions "
        "about the current market snapshot shown here.'"
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


MARKET_PULSE_PROMPT = (
    "You are a senior equity trader. "
    "Write ONE sentence — maximum 25 words — about current market conditions. "
    "Use trader voice: direct, specific, no hedging. "
    "Reference at least two of: price level, RSI, yield spread, VWAP. "
    "Do NOT use: 'indicating', 'suggesting', 'appears', 'seems'. "
    "Example tone: 'SPY at $739 with RSI 68 — momentum stretched above VWAP. "
    "Yield spread positive at +0.68% provides macro support. Watch 70.'"
)


def get_market_pulse(context: str) -> str:
    """LLM-generated one-line market summary. Cached per session."""
    if "market_pulse" in st.session_state:
        return st.session_state["market_pulse"]

    result = None
    if KIMI_API_KEY:
        result, _ = _kimi_post([
            {"role": "system", "content": MARKET_PULSE_PROMPT},
            {"role": "user", "content": context},
        ], max_tokens=60)

    _is_fallback = (
        not result
        or "offline" in result.lower()
        or "unavailable" in result.lower()
        or "api key" in result.lower()
        or len(result) < 10
    )

    if _is_fallback:
        try:
            _close  = float(context.split("Close: $")[1].split("\n")[0])
            _rsi    = float(context.split("RSI-14: ")[1].split("\n")[0].strip().split()[0])
            _raw_sp = context.split("Yield Spread")[1].split("%")[0].strip().replace("+", "")
            _spread = float(_raw_sp.split()[-1])
            _momentum = (
                "momentum extended" if _rsi > 65 else
                "momentum building" if _rsi > 55 else
                "momentum fading" if _rsi < 40 else "momentum neutral"
            )
            _macro = (
                "macro supportive" if _spread > 0.3 else
                "macro compressing" if _spread > 0 else
                "yield curve inverted — caution"
            )
            result = (
                f"SPY at ${_close:.0f} — {_momentum} with RSI {_rsi:.0f}. "
                f"Yield spread {'+' if _spread >= 0 else ''}{_spread:.2f}% — {_macro}."
                f"{' Watch the 70 line.' if _rsi > 65 else ''}"
            ).strip()
        except Exception:
            result = "Market data loaded. Review RSI and yield spread in the signals panel."

    st.session_state["market_pulse"] = result
    return result


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
# Dark / Light mode state — light is default
# ---------------------------------------------------------------------------
_params = st.query_params
if "dark" in _params:
    st.session_state["dark_mode"] = _params["dark"] == "1"
elif "dark_mode" not in st.session_state:
    st.session_state["dark_mode"] = False  # light is default

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
    border: 0.5px solid {_P['border']} !important;
    background: {_P['card_bg']} !important;
    color: {_P['text_body']} !important;
    font-size: 11px !important;
    padding: 4px 10px !important;
    border-radius: 4px !important;
    min-height: 32px !important;
    max-height: 40px !important;
    line-height: 1.2 !important;
}}
.stButton > button:hover {{
    background: {_P['hover_bg']} !important;
    border-color: {_P['text_sec']} !important;
    color: {_P['text_pri']} !important;
}}
/* Prevent column buttons from wrapping */
div[data-testid="stHorizontalBlock"] .stButton > button {{
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
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

/* Global dark-mode text so all Streamlit-native text inherits _P colours */
.stApp, .stApp * {{ color: {_P['text_body']}; }}
.stApp h1, .stApp h2, .stApp h3 {{ color: {_P['text_pri']} !important; }}
label, .stSelectbox label, .stSlider label, .stRadio label,
.stNumberInput label, .stTextInput label {{
    color: {_P['text_sec']} !important;
}}
/* Tab panel backgrounds */
[data-baseweb="tab-panel"] {{
    background: {_P['page_bg']} !important;
}}
/* Select / radio / input native backgrounds */
[data-baseweb="select"] > div {{
    background: {_P['input_bg']} !important;
    border-color: {_P['border']} !important;
    color: {_P['text_pri']} !important;
}}
[data-baseweb="select"] span {{ color: {_P['text_pri']} !important; }}
.stRadio div[role="radiogroup"] label {{ color: {_P['text_body']} !important; }}
[data-testid="stNumberInput"] input {{
    background: {_P['input_bg']} !important;
    color: {_P['text_pri']} !important;
    border-color: {_P['border']} !important;
}}
/* Sidebar */
[data-testid="stSidebar"] {{
    background: {_P['card_bg']} !important;
    border-right: 1px solid {_P['border']} !important;
}}
[data-testid="stSidebar"] * {{ color: {_P['text_body']}; }}

/* All tabs — dark base */
[data-baseweb="tab-list"] {{
    background: {_P['page_bg']} !important;
    border-bottom: 1px solid {_P['border']} !important;
}}
[data-baseweb="tab-list"] button {{
    color: {_P['text_sec']} !important;
    background: transparent !important;
    font-size: 12px !important;
    padding: 10px 16px !important;
    border-bottom: 3px solid transparent !important;
}}
[data-baseweb="tab-list"] button:hover {{
    color: {_P['text_pri']} !important;
    background: {_P['hover_bg']} !important;
}}
/* Market Analytics + What-if — white active underline */
[data-baseweb="tab-list"] button:nth-child(1)[aria-selected="true"],
[data-baseweb="tab-list"] button:nth-child(2)[aria-selected="true"] {{
    color: {_P['text_pri']} !important;
    border-bottom: 3px solid {_P['text_pri']} !important;
    font-weight: 600 !important;
}}
/* Governance (3rd) — indigo */
[data-baseweb="tab-list"] button:nth-child(3) {{ color: #818cf8 !important; }}
[data-baseweb="tab-list"] button:nth-child(3)[aria-selected="true"] {{
    color: #a5b4fc !important;
    border-bottom: 3px solid #818cf8 !important;
    font-weight: 600 !important;
}}
/* Observability (4th) — teal */
[data-baseweb="tab-list"] button:nth-child(4) {{ color: #34d399 !important; }}
[data-baseweb="tab-list"] button:nth-child(4)[aria-selected="true"] {{
    color: #6ee7b7 !important;
    border-bottom: 3px solid #34d399 !important;
    font-weight: 600 !important;
}}

/* Small icon buttons — regenerate, topbar toggles */
button[kind="secondary"] {{
    min-height: 28px !important;
    padding: 2px 8px !important;
    font-size: 12px !important;
}}
/* Topbar buttons — match dark toggle size */
div[data-testid="stHorizontalBlock"] button {{
    min-height: 32px !important;
    font-size: 11px !important;
    padding: 4px 8px !important;
}}

@media print {{
    .stButton, .stSlider, .stSelectbox, .stRadio,
    .stTextInput, .stNumberInput,
    [data-testid="stExpander"] button,
    [data-testid="stSidebar"], header, footer,
    .screen-only {{ display: none !important; }}
    .block-container {{ max-width: 100% !important; padding: 0 !important; }}
    [data-testid="column"] {{ background: #ffffff !important; border: none !important; padding: 8px !important; }}
    .stApp, .block-container {{
        background: #ffffff !important; color: #000000 !important;
    }}
    .stPlotlyChart {{ page-break-inside: avoid; }}
    .print-header, .print-only {{ display: block !important; }}
}}
.print-header, .print-only {{ display: none; }}
.screen-only {{ display: block; }}
</style>
<script>
function setPeriod(days) {{
    const inputs = window.parent.document.querySelectorAll('input[type="number"]');
    for (const inp of inputs) {{
        if (parseInt(inp.min) === 21) {{
            inp.value = days;
            inp.dispatchEvent(new Event('input', {{bubbles:true}}));
            inp.dispatchEvent(new Event('change', {{bubbles:true}}));
            break;
        }}
    }}
}}
</script>
""", unsafe_allow_html=True)

# Print-only header (hidden on screen, shown when printing)
st.markdown(f"""
<div class="print-header" style="padding:16px 0 8px 0;border-bottom:2px solid #000;margin-bottom:16px;">
  <div style="font-size:18px;font-weight:700;">Market Analytics Platform</div>
  <div style="font-size:11px;color:#5f6368;">
    Really Big Bank · Post-trade operations · Printed: {datetime.now().strftime('%Y-%m-%d %H:%M')}
  </div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Top-level tabs — market content renders into tab_market by default;
# governance content is explicitly wrapped at the bottom of this file.
# ---------------------------------------------------------------------------
tab_market, tab_whatif, tab_governance, tab_observability, tab_arch = st.tabs([
    "📈 Market Analytics", "🔮 What-if", "📋 Governance", "🔬 Observability", "Architecture"
])

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
    # Load filter options (sidebar hidden — persistent bar used instead)
    # ---------------------------------------------------------------------------
    if "selected_days" not in st.session_state:
        st.session_state["selected_days"] = VALIDATION_CONFIG["lookback_default"]
    _max_days = VALIDATION_CONFIG["lookback_days"]

    # Filter bar rendered inline after Risk Analytics (below)

    # Defaults — overridden by filter bar after first render
    selected_symbol = st.session_state.get("filter_symbol", symbols[0] if symbols else SYMBOL)
    selected_macro  = st.session_state.get("filter_macro", macro_series_list[0] if macro_series_list else FRED_SERIES)
    lookback        = st.session_state["selected_days"]

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
        _tb_left, _tb_right = st.columns([8, 2])
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
            _btn1, _btn2 = st.columns(2)
            with _btn1:
                if st.button("🖨 Print", key="print_btn", use_container_width=True, help="Print or save as PDF"):
                    st.markdown("<script>window.print();</script>", unsafe_allow_html=True)
            with _btn2:
                _toggle_label = "☀️ Light" if _dark else "🌙 Dark"
                if st.button(_toggle_label, key="dark_mode_toggle", use_container_width=True):
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

        # Fix 14.2 — solid filled RAG colours
        _rag_solid = {
            "over":    ("#b91c1c", "#ffffff"),
            "under":   ("#166534", "#ffffff"),
            "neutral": ("#b45309", "#ffffff"),
        }
        _bg_solid, _fg_solid = _rag_solid[rag_class]
        # Keep legacy vars for JUDGE card rag_styles references
        _bg, _fg, _border = (
            "fef2f2", "b91c1c", "fecaca") if rag_class == "over" else (
            "f0fdf4", "166534", "bbf7d0") if rag_class == "under" else (
            "fef9e7", "b45309", "fde68a")

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

    # Fix 21.2 — Amber pulse tile
    CHECKPOINT = "market_pulse"
    try:
        _pulse_context = _build_market_context(latest, [])
        _pulse = get_market_pulse(_pulse_context)

        # Theme-aware amber colours
        _pbg    = "#412402" if _dark else "#FAEEDA"
        _pbdr   = "#BA7517" if _dark else "#EF9F27"
        _ptxt   = "#FAC775" if _dark else "#633806"
        _plbl   = "#EF9F27" if _dark else "#854F0B"

        _pulse_col, _pulse_btn_col = st.columns([8, 1])
        with _pulse_col:
            st.markdown(f"""
<div style="background:{_pbg};border:1px solid {_pbdr};border-radius:6px;
            padding:10px 16px;display:flex;align-items:center;
            justify-content:space-between;gap:16px;margin-top:4px;">
  <span style="font-size:13px;color:{_ptxt};font-style:italic;line-height:1.5;flex:1;">
    {_pulse}
  </span>
  <span style="font-size:10px;color:{_plbl};white-space:nowrap;flex-shrink:0;">
    AI · auto-generated
  </span>
</div>
""", unsafe_allow_html=True)
        with _pulse_btn_col:
            if st.button("↺", key="refresh_pulse", help="Regenerate market pulse"):
                st.session_state.pop("market_pulse", None)
                st.rerun()
    except Exception:
        pass

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

    # Filter bar — full width above three columns
    CHECKPOINT = "filter_bar"
    try:
        st.markdown(f"""
<div style="background:{_P['card_bg']};border:1px solid {_P['border']};
            border-radius:6px;padding:8px 14px;margin-bottom:12px;">
  <div style="font-size:9px;color:{_P['text_sec']};text-transform:uppercase;
              letter-spacing:.1em;margin-bottom:6px;">View controls</div>
""", unsafe_allow_html=True)
        _fb1, _fb2, _fb3 = st.columns([0.8, 0.8, 2.4])
        with _fb1:
            _sel_sym = st.selectbox("Index", symbols, index=0, key="filter_symbol")
        with _fb2:
            _sel_mac = st.selectbox("Macro series", macro_series_list, index=0, key="filter_macro",
                help="FEDFUNDS = Federal Funds Rate. GS10 = 10Y Treasury yield.")
        with _fb3:
            _fpresets = [("1M", 21), ("3M", 63), ("6M", 126), ("YTD", 252), ("Max", _max_days)]
            _active = st.session_state["selected_days"]
            _preset_html = '<div style="display:flex;gap:4px;margin-bottom:6px;">'
            for _lbl, _days in _fpresets:
                _dc = min(_days, _max_days)
                _is_on = (_active == _dc)
                _pbg = "#E6F1FB" if _is_on else "transparent"
                _pbdr = "#378ADD" if _is_on else "#5f6368"
                _pcol = "#0C447C" if _is_on else "#9aa0a6"
                _pw = "600" if _is_on else "400"
                _preset_html += (
                    f'<button onclick="setPeriod({_dc})" '
                    f'style="padding:4px 10px;border:0.5px solid {_pbdr};'
                    f'border-radius:4px;background:{_pbg};color:{_pcol};'
                    f'font-size:11px;font-weight:{_pw};cursor:pointer;'
                    f'white-space:nowrap;font-family:system-ui,sans-serif;">'
                    f'{_lbl}</button>'
                )
            _preset_html += '</div>'
            st.markdown(_preset_html, unsafe_allow_html=True)
            _period_val = st.number_input(
                "period_hidden", min_value=21, max_value=_max_days,
                value=st.session_state["selected_days"], step=1,
                label_visibility="collapsed", key="period_input",
            )
            if _period_val != st.session_state["selected_days"]:
                st.session_state["selected_days"] = _period_val
                st.rerun()
            lookback = st.slider("Fine-tune", min_value=21, max_value=_max_days,
                                 value=st.session_state["selected_days"], step=7,
                                 label_visibility="collapsed")
            st.session_state["selected_days"] = lookback
        st.markdown("</div>", unsafe_allow_html=True)

        selected_symbol = _sel_sym
        selected_macro  = _sel_mac
        if _sel_sym != st.session_state.get("_last_sym") or lookback != st.session_state.get("_last_lkb"):
            st.session_state["_last_sym"] = _sel_sym
            st.session_state["_last_lkb"] = lookback
            load_gold.clear()
        df = load_gold(lookback, selected_symbol)
        if not df.empty:
            latest = df.iloc[-1]

        st.markdown(f"""
<div class="print-only" style="font-size:11px;color:#5f6368;padding:6px 0;
    border-bottom:1px solid #e8eaed;margin-bottom:12px;">
  Index: {selected_symbol} · Macro: {selected_macro} ·
  Period: {lookback} days · Printed: {datetime.now().strftime('%Y-%m-%d %H:%M')}
</div>
""", unsafe_allow_html=True)
    except Exception as e:
        st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
        st.stop()

    # Three columns: SEE / JUDGE / ACT

    # ---------------------------------------------------------------------------
    # Three columns: SEE / JUDGE / ACT
    # ---------------------------------------------------------------------------
    see_col, judge_col, act_col = st.columns([1.3, 1.2, 1.0])

    # ============================= SEE =============================
    with see_col:
        st.markdown(f'<div style="font-size:13px;font-weight:600;color:{_P["text_pri"]};padding-bottom:10px;border-bottom:1px solid {_P["border"]};margin-bottom:14px;">Market conditions<span style="color:{_P["text_sec"]};font-weight:400;"> →</span></div>', unsafe_allow_html=True)
        CHECKPOINT = "see_column"
        try:
            import plotly.graph_objects as _sgo

            CHART_COLORS = {
                "close": "#1a1a2e" if not _dark else "#e8eaed",
                "vwap": "#EF9F27", "rsi": "#7c3aed",
                "ema": "#378ADD", "sma": "#EF9F27",
                "vol_up": "#0f9d58", "vol_down": "#d93025",
            }

            # Chart 1 — Price + VWAP
            _sc1 = _sgo.Figure()
            _sc1.add_trace(_sgo.Scatter(x=df["date"], y=df["close"], name="Close",
                line=dict(color=CHART_COLORS["close"], width=1.5)))
            _sc1.add_trace(_sgo.Scatter(x=df["date"], y=df["vwap_20d"], name="VWAP 20d",
                line=dict(color=CHART_COLORS["vwap"], width=1.5, dash="dot")))
            _sc1.update_layout(**chart_layout(_dark, height=180))
            st.plotly_chart(_sc1, use_container_width=True)

            # Chart 2 — Volume
            _scols = [CHART_COLORS["vol_up"] if c >= o else CHART_COLORS["vol_down"]
                      for c, o in zip(df["close"], df["close"].shift(1).fillna(df["close"]))]
            _sc2 = _sgo.Figure()
            _sc2.add_trace(_sgo.Bar(x=df["date"], y=df["volume"], marker_color=_scols))
            _sc2.update_layout(**{**chart_layout(_dark, height=110), "showlegend": False})
            st.plotly_chart(_sc2, use_container_width=True)

            # Chart 3 — RSI
            _sc3 = _sgo.Figure()
            _sc3.add_trace(_sgo.Scatter(x=df["date"], y=df["rsi_14"], name="RSI-14",
                line=dict(color=CHART_COLORS["rsi"], width=1.5)))
            _sc3.add_hline(y=VALIDATION_CONFIG["rsi_overbought"], line_dash="dash",
                line_color="#ef4444", line_width=0.8, annotation_text="70", annotation_font_size=9)
            _sc3.add_hline(y=VALIDATION_CONFIG["rsi_oversold"], line_dash="dash",
                line_color="#10b981", line_width=0.8, annotation_text="30", annotation_font_size=9)
            _sc3.update_yaxes(range=[0, 100], tickvals=[0, 30, 70, 100])
            _sc3.update_layout(**{**chart_layout(_dark, height=150), "showlegend": False})
            st.plotly_chart(_sc3, use_container_width=True)

            # Chart 4 — EMA vs SMA
            _macro_df = (df[["month","macro_ema_3m","macro_sma_3m"]]
                .drop_duplicates("month").sort_values("month")
                .dropna(subset=["macro_ema_3m","macro_sma_3m"]))
            _sc4 = _sgo.Figure()
            _sc4.add_trace(_sgo.Scatter(x=_macro_df["month"], y=_macro_df["macro_ema_3m"],
                name="EMA 3m", line=dict(color=CHART_COLORS["ema"], width=2)))
            _sc4.add_trace(_sgo.Scatter(x=_macro_df["month"], y=_macro_df["macro_sma_3m"],
                name="SMA 3m", line=dict(color=CHART_COLORS["sma"], width=2, dash="dash")))
            _sc4.update_layout(**chart_layout(_dark, height=150))
            st.plotly_chart(_sc4, use_container_width=True)
            st.caption("Blue solid = EMA (accelerating). Amber dashed = SMA (lagging). EMA > SMA = tightening macro.")

            # Divider before Risk Analytics
            st.markdown(f'<hr style="border:none;border-top:0.5px solid {_P["border"]};margin:12px 0;"/>', unsafe_allow_html=True)

            # Risk Analytics
            st.markdown(f"""
<div style="font-size:10px;color:{_P['text_sec']};text-transform:uppercase;
            letter-spacing:.1em;margin-bottom:4px;">Risk analytics</div>
<div style="font-size:11px;color:{_P['text_body']};margin-bottom:8px;line-height:1.4;">
  Risk-adjusted performance context.
</div>
""", unsafe_allow_html=True)

            _tile_colors = {"good": "#0f9d58", "warn": "#b45309", "bad": "#d93025", "na": "#9aa0a6"}

            def kpi_tile(col, label, value, color, sublabel):
                col.markdown(f"""
<div style="border:1px solid {_P['border']};border-radius:6px;
            padding:8px 12px;background:{_P['card_bg']};">
  <div style="font-size:9px;color:{_P['text_sec']};text-transform:uppercase;letter-spacing:.06em;">{label}</div>
  <div style="font-size:18px;font-weight:500;color:{_tile_colors[color]};line-height:1.2;">{value}</div>
  <div style="font-size:10px;color:{_P['text_sec']};">{sublabel}</div>
</div>
""", unsafe_allow_html=True)

            # Use safe_float(latest, col) — always from filtered df
            _sv  = safe_float(latest, "sharpe_20d")
            _mv  = safe_float(latest, "mdd_90d")
            _vv  = safe_float(latest, "volatility_20d")
            _ev  = safe_float(latest, "vwap_efficiency")
            _spv = safe_float(latest, "yield_spread")

            _sk1, _sk2 = st.columns(2)
            kpi_tile(_sk1, "Sharpe 20d",
                f"{_sv:.2f}" if _sv else "—",
                "good" if _sv > 1 else "warn" if _sv >= 0 else "bad" if _sv else "na",
                "risk-adjusted return" if _sv else "warmup period")
            kpi_tile(_sk2, "Max drawdown 90d",
                f"{_mv:.1f}%" if _mv else "—",
                "good" if _mv > -10 else "warn" if _mv > -20 else "bad" if _mv else "na",
                "controlled" if _mv > -10 else "elevated" if _mv else "warmup period")

            _sk3, _sk4 = st.columns(2)
            kpi_tile(_sk3, "Volatility 20d",
                f"{_vv:.1f}%" if _vv else "—",
                "good" if _vv < 12 else "warn" if _vv < 20 else "bad" if _vv else "na",
                "low regime" if _vv < 12 else "elevated" if _vv >= 20 else "normal")
            kpi_tile(_sk4, "VWAP efficiency",
                f"{_ev:.1f}" if _ev else "—",
                "good" if _ev > 97 else "warn" if _ev > 94 else "bad" if _ev else "na",
                "orderly" if _ev > 97 else "deviation signal" if _ev else "normal")

            _sk5, _ = st.columns([1, 1])
            kpi_tile(_sk5, "Yield spread",
                f"+{_spv:.2f}%" if _spv > 0 else f"{_spv:.2f}%" if _spv else "—",
                "good" if _spv > 0.5 else "warn" if _spv >= 0 else "bad" if _spv else "na",
                "normal curve" if _spv > 0.5 else "compressing" if _spv >= 0 else "inverted — caution")

        except Exception as e:
            st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")
            st.stop()

    # ============================= JUDGE =============================
    with judge_col:
        st.markdown(f'<div style="font-size:13px;font-weight:600;color:{_P["text_pri"]};padding-bottom:10px;border-bottom:1px solid {_P["border"]};margin-bottom:14px;">Signal analysis<span style="color:{_P["text_sec"]};font-weight:400;"> →</span></div>', unsafe_allow_html=True)
        CHECKPOINT = "judge_rag"
        try:
            # Fix 18.2 — compact one-line RAG bar
            st.markdown(f"""
<div style="background:{_bg_solid};border-radius:6px;padding:10px 14px;
            display:flex;align-items:center;justify-content:space-between;
            margin-bottom:12px;">
  <span style="font-size:14px;font-weight:600;color:{_fg_solid};">
    RSI {rsi_display} — {rag_text}
  </span>
  <span style="font-size:10px;color:{_fg_solid};opacity:.75;">
    OB: {VALIDATION_CONFIG['rsi_overbought']} · OS: {VALIDATION_CONFIG['rsi_oversold']} · Wilder 14d
  </span>
</div>
""", unsafe_allow_html=True)

            # Fix 16.5 — CORRECT ORDER: Signals → AI → Ask → My alerts (collapsed)

            # Fix 18.3 — CORRECT ORDER: AI first (overview) → signals (specifics) → Ask (collapsed)

            # 1. AI interpretation FIRST — label + icon button inline
            _ai_label_col, _ai_btn_col = st.columns([4, 1])
            with _ai_label_col:
                st.markdown(f"<div style='font-size:10px;color:{_P['text_sec']};text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;'>AI interpretation</div>", unsafe_allow_html=True)
            with _ai_btn_col:
                if st.button("↺", key="regen", help="Regenerate AI interpretation", use_container_width=True):
                    st.session_state.pop("llm_explanation", None)
                    st.session_state["llm_explanation"] = call_llm(triggered_rules, latest)
                    st.rerun()
            explanation = st.session_state.get("llm_explanation", "")
            st.markdown(
                f'<div style="background:{_P["card_bg"]};border:1px solid {_P["border"]};'
                f'border-radius:6px;padding:10px 12px;font-size:12px;color:{_P["text_body"]};'
                f'line-height:1.6;word-wrap:break-word;overflow-wrap:break-word;margin-bottom:6px;">'
                f'{explanation}</div>',
                unsafe_allow_html=True,
            )

            # 2. Triggered signals AFTER AI
            st.markdown(f"<div style='font-size:10px;color:{_P['text_sec']};text-transform:uppercase;letter-spacing:.05em;margin:10px 0 6px 0;'>Triggered signals</div>", unsafe_allow_html=True)
            _rule_dot_colors = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#10b981", "USER": "#378add"}
            if triggered_rules:
                for rule in triggered_rules:
                    _is_user = rule.get("is_user_rule", False)
                    _user_tag = f'<span style="font-size:9px;background:#1e3a5f;color:#93c5fd;border-radius:3px;padding:1px 5px;margin-left:6px;">MY ALERT</span>' if _is_user else ""
                    dot = _rule_dot_colors.get(rule["severity"], "#9aa0a6")
                    st.markdown(f"""
<div style="display:flex;align-items:flex-start;gap:8px;padding:7px 10px;
            border:1px solid {_P['border']};border-radius:6px;margin-bottom:4px;background:{_P['card_bg']};">
  <div style="width:8px;height:8px;border-radius:50%;background:{dot};flex-shrink:0;margin-top:3px;"></div>
  <div>
    <div style="font-size:11px;font-weight:500;color:{_P['text_pri']};">{rule['name']}{_user_tag}</div>
    <div style="font-size:10px;color:{_P['text_sec']};">{rule['severity']} · {rule.get('nba_category', rule['action'])[:60]}</div>
  </div>
</div>
""", unsafe_allow_html=True)
            else:
                st.markdown(f"""
<div style="padding:8px 12px;border:1px solid {_P['border']};border-radius:6px;
            background:{_P['card_bg']};font-size:11px;color:#6ee7b7;margin-bottom:6px;">
  ✓ All signals within normal range
</div>
""", unsafe_allow_html=True)

            # 3. Ask about this data — collapsed
            if "chat_history" not in st.session_state:
                st.session_state["chat_history"] = []
            with st.expander("Ask about this data", expanded=False):
                st.caption("Answers grounded in current market snapshot only. Not financial advice.")
                _eq1, _eq2 = st.columns(2)
                for _ei, _eq in enumerate([
                    "Why is RSI approaching overbought?", "What does the yield spread signal?",
                    "Has volatility been rising or falling?", "What would trigger a red signal?",
                ]):
                    (_eq1 if _ei % 2 == 0 else _eq2).button(_eq, key=f"eq_{_ei}",
                        use_container_width=True,
                        on_click=lambda q=_eq: st.session_state.update({"analyst_prefill": q}))

                for msg in st.session_state["chat_history"]:
                    _bubble_bg = _P["chip_bg"] if msg["role"] == "user" else _P["card_bg"]
                    _bubble_bdr = "" if msg["role"] == "user" else f'border:1px solid {_P["border"]};'
                    _speaker = "You" if msg["role"] == "user" else "Analyst"
                    st.markdown(
                        f'<div style="background:{_bubble_bg};{_bubble_bdr}border-radius:6px;'
                        f'padding:8px 10px;margin-bottom:4px;font-size:12px;color:{_P["text_body"]};">'
                        f'<strong>{_speaker}:</strong> {msg["content"]}</div>',
                        unsafe_allow_html=True,
                    )
                with st.form("chat_form", clear_on_submit=True):
                    user_q = st.text_input("Question",
                        value=st.session_state.pop("analyst_prefill", ""),
                        placeholder="Ask about the current market data...",
                        label_visibility="collapsed")
                    if st.form_submit_button("Ask", use_container_width=True) and user_q.strip():
                        with st.spinner("Reading the data…"):
                            answer = call_llm_chat(user_q.strip(), latest, triggered_rules,
                                                   st.session_state["chat_history"])
                        st.session_state["chat_history"].append({"role": "user", "content": user_q.strip()})
                        st.session_state["chat_history"].append({"role": "assistant", "content": answer})
                        st.session_state["chat_history"] = st.session_state["chat_history"][-10:]
                        st.rerun()
                if st.session_state["chat_history"]:
                    if st.button("Clear chat", key="clear_chat"):
                        st.session_state["chat_history"] = []
                        st.rerun()

            # Fix 16.8 — My alerts: collapsed at bottom of JUDGE
            with st.expander("⚙ My alerts", expanded=False):
                st.caption("Define your own alert conditions. Rules are evaluated alongside the pre-configured signals above.")
                _acon = get_connection()
                _user_rules = _acon.execute(
                    "SELECT rule_id, name, severity, active FROM user_nba_rules ORDER BY created_at DESC"
                ).df()
                if not _user_rules.empty:
                    st.dataframe(_user_rules, use_container_width=True, hide_index=True)
                else:
                    st.info("No alerts configured yet.")

                with st.form("add_rule_form"):
                    r_name   = st.text_input("Alert name")
                    r_metric = st.selectbox("Metric", list(METRIC_DISPLAY.keys()),
                                            format_func=lambda k: METRIC_DISPLAY[k])
                    r_op     = st.selectbox("Condition", list(OP_TEXT.keys()),
                                            format_func=lambda k: OP_TEXT[k])
                    r_thresh = st.number_input("Threshold", value=0.0, step=0.1, format="%.2f")
                    r_sev    = st.selectbox("Severity", ["LOW", "MEDIUM", "HIGH"])

                    # Plain English preview
                    if r_name and r_metric and r_op:
                        st.markdown(f"""
<div style="padding:10px 12px;background:{_P['hover_bg']};border:1px solid #378ADD;
            border-radius:6px;font-size:12px;color:{_P['text_body']};margin-top:6px;">
  <strong style="color:{_P['text_pri']};">Alert preview:</strong><br/>
  Alert me when <strong>{METRIC_DISPLAY[r_metric]}</strong> {OP_TEXT[r_op]}
  <strong>{r_thresh}</strong> — severity: <strong>{r_sev}</strong>
</div>""", unsafe_allow_html=True)

                    submitted = st.form_submit_button("Add alert")
                    if submitted and r_name:
                        new_id = f"U{str(uuid.uuid4())[:8].upper()}"
                        _acon.execute(
                            "INSERT INTO user_nba_rules VALUES (?, ?, ?, ?, ?, TRUE, ?)",
                            [new_id, r_name, f"{METRIC_DISPLAY[r_metric]} {OP_TEXT[r_op]} {r_thresh}",
                             f"{r_metric} {r_op} {r_thresh}", r_sev, datetime.now(timezone.utc)],
                        )
                        st.success(f"Alert {new_id} added.")
                        st.rerun()

                # History test
                if st.button("Test against last 90 days", key="test_rule"):
                    try:
                        _op_sql = {">":">","<":"<",">=":">=","<=":"<="}
                        if r_op in _op_sql:
                            _hcount = _acon.execute(f"""
                                SELECT COUNT(*) FROM gold_metrics
                                WHERE {r_metric} {_op_sql[r_op]} {r_thresh}
                                AND date >= CURRENT_DATE - INTERVAL 90 DAYS
                            """).fetchone()[0]
                        else:
                            _hcount = 0
                        _hnote = (
                            "frequent — consider tightening the threshold" if _hcount > 20
                            else "infrequent — threshold looks appropriate" if _hcount > 0
                            else "never fired — threshold may be too extreme"
                        )
                        st.markdown(f"""
<div style="font-size:12px;color:{_P['text_body']};padding:8px 10px;
            background:{_P['hover_bg']};border-radius:4px;margin-top:6px;">
  This alert would have fired <strong>{_hcount} times</strong> in the last 90 days — {_hnote}
</div>""", unsafe_allow_html=True)
                    except Exception as _he:
                        st.caption(f"Could not test rule: {_he}")

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

            # Fix 18.4 — severity summary bar
            _high_n = sum(1 for r in triggered_rules if r.get("severity") == "HIGH")
            _med_n  = sum(1 for r in triggered_rules if r.get("severity") == "MEDIUM")
            _low_n  = sum(1 for r in triggered_rules if r.get("severity") == "LOW")
            _usr_n  = sum(1 for r in triggered_rules if r.get("is_user_rule"))
            if _high_n == 0 and _med_n == 0:
                st.markdown(f"""
<div style="padding:8px 12px;border:1px solid {_P['border']};border-radius:6px;
            background:{_P['card_bg']};font-size:12px;color:#6ee7b7;margin-bottom:12px;">
  ✓ No urgent actions — {_low_n} monitoring signal{'s' if _low_n != 1 else ''}
  {f'· {_usr_n} custom alert' if _usr_n else ''}
</div>
""", unsafe_allow_html=True)
            else:
                _sb = " ".join(filter(None, [
                    f"🔴 {_high_n} HIGH" if _high_n else "",
                    f"🟡 {_med_n} MEDIUM" if _med_n else "",
                    f"🟢 {_low_n} LOW" if _low_n else "",
                ]))
                st.markdown(f"""
<div style="padding:8px 12px;border:1px solid #b45309;border-radius:6px;
            background:{_P['hover_bg']};font-size:12px;color:#EF9F27;margin-bottom:12px;">
  {_sb}
</div>
""", unsafe_allow_html=True)

            if triggered_rules:
                for rule in triggered_rules:
                    _sev_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢", "USER": "🔵"}.get(rule["severity"], "⚪")
                    _rule_detail = rule.get("detail", rule.get("action", ""))
                    st.markdown(f"""
<div style="border:1px solid {_P['border']};border-radius:6px;padding:10px 12px;margin-bottom:8px;background:{_P['card_bg']};">
  <div style="font-size:12px;font-weight:500;color:{_P['text_pri']};margin-bottom:2px;">
    {_sev_icon} {rule['name']}
  </div>
  <div style="font-size:10px;color:{_P['text_sec']};margin-bottom:6px;">{rule['severity']}</div>
  <div style="font-size:11px;color:{_P['text_body']};line-height:1.5;margin-bottom:8px;
              padding:6px 8px;background:{_P['hover_bg']};border-radius:4px;">
    {_rule_detail}
  </div>
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
                st.markdown(f"""
<div style="padding:12px;border:1px solid {_P['border']};border-radius:6px;
            background:{_P['card_bg']};text-align:center;font-size:12px;color:#6ee7b7;">
  ✓ No actions required — all signals within normal range
</div>
""", unsafe_allow_html=True)

            # PDF export
            if st.button("Export PDF Report", use_container_width=True):
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

        st.markdown(f"""
<div style="font-size:12px;color:{_P['text_body']};margin-bottom:14px;line-height:1.6;">
  <strong style="color:{_P['text_pri']};">Market Analytics</strong>
  — post-trade market benchmark platform ·
  Alpha Vantage (SPY) + FRED (FEDFUNDS, GS10) ·
  Definitions and lineage in DuckDB governance tables ·
  Production path: Alation or Collibra ·
  <a href="https://github.com/ashray0506/MAQ_MVP" target="_blank"
     style="color:#378ADD;text-decoration:none;">GitHub ↗</a>
</div>
""", unsafe_allow_html=True)

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

        _obs_chart_layout = chart_layout(_dark)

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
                    **{**chart_layout(_dark, height=260),
                       "barmode": "group",
                       "legend": dict(orientation="h", y=1.15, font=dict(size=10))},
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
                _fig_spark.update_layout(**{**chart_layout(_dark, height=180), "showlegend": False})
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

# ---------------------------------------------------------------------------
# What-if tab (Phase 2)
# ---------------------------------------------------------------------------
with tab_whatif:
    CHECKPOINT = "whatif_tab"
    try:
        import importlib.util as _ilu, pathlib as _pl, io as _io
        _sc_path = _pl.Path(__file__).parent / "scenarios.py"
        _sc_spec = _ilu.spec_from_file_location("scenarios", _sc_path)
        _sc_mod  = _ilu.module_from_spec(_sc_spec)
        _sc_spec.loader.exec_module(_sc_mod)
        scenario_vol_shock       = _sc_mod.scenario_vol_shock
        scenario_market_drawdown = _sc_mod.scenario_market_drawdown
        scenario_rate_shock      = _sc_mod.scenario_rate_shock

        _wi_con = get_connection()
        _wi_session = st.session_state.get("session_id", "pre-session")

        st.markdown(f"""
<div style="font-size:10px;color:{_P['text_sec']};text-transform:uppercase;
            letter-spacing:.1em;padding:12px 0 4px 0;">What-if scenario analysis</div>
<div style="font-size:12px;color:{_P['text_body']};margin-bottom:16px;">
  Illustrative portfolio impact · 60/40 balanced allocation proxy · Not financial advice
</div>
""", unsafe_allow_html=True)

        _wi_left, _wi_right = st.columns([1, 1.6])

        with _wi_left:
            st.markdown(f'<div style="font-size:13px;font-weight:600;color:{_P["text_pri"]};padding-bottom:10px;border-bottom:1px solid {_P["border"]};margin-bottom:14px;">Scenario inputs</div>', unsafe_allow_html=True)

            _notional = st.number_input(
                "Illustrative portfolio value ($)",
                min_value=100_000, max_value=100_000_000,
                value=1_000_000, step=100_000, format="%d",
            )

            _scenario_type = st.radio(
                "Scenario type",
                ["Volatility shock", "Market drawdown", "Rate shock"],
            )

            # Fix 13.1 — scenario explanation card
            _expl = SCENARIO_EXPLANATIONS[_scenario_type]
            with st.expander("What does this scenario model?", expanded=True):
                st.markdown(f"""
<div style="font-size:12px;color:{_P['text_body']};line-height:1.7;">
  <div style="margin-bottom:8px;">{_expl['what']}</div>
  <div style="font-size:11px;color:{_P['text_sec']};margin-bottom:6px;">
    <strong style="color:{_P['text_pri']};">How it works:</strong> {_expl['how']}
  </div>
  <div style="font-size:11px;color:{_P['text_sec']};margin-bottom:6px;">
    <strong style="color:{_P['text_pri']};">Assumptions:</strong> {_expl['assumes']}
  </div>
  <div style="font-size:11px;background:{_P['hover_bg']};border:1px solid #b45309;
              border-radius:4px;padding:6px 10px;color:#EF9F27;">
    <strong>Watch for:</strong> {_expl['watch_for']}
  </div>
</div>
""", unsafe_allow_html=True)

            _wi_latest = df.iloc[-1] if not df.empty else pd.Series({})
            _cur_vol = float(_wi_latest.get("volatility_20d") or 15.0)

            if _scenario_type == "Volatility shock":
                st.caption(f"Current volatility: {_cur_vol:.1f}%")
                _target_vol = st.slider("Target volatility (%)",
                    min_value=float(max(_cur_vol, 10.0)), max_value=40.0,
                    value=float(min(_cur_vol * 2, 40.0)), step=0.5, format="%.1f%%")
            elif _scenario_type == "Market drawdown":
                _drawdown = st.slider("Index decline (%)",
                    min_value=-30, max_value=-5, value=-15, step=1, format="%d%%")
            else:
                _rate_change = st.slider("Rate increase (bps)",
                    min_value=25, max_value=200, value=100, step=25, format="%dbps")

            _run_btn = st.button("Run scenario", use_container_width=True, type="primary")

        with _wi_right:
            st.markdown(f'<div style="font-size:13px;font-weight:600;color:{_P["text_pri"]};padding-bottom:10px;border-bottom:1px solid {_P["border"]};margin-bottom:14px;">Projected impact</div>', unsafe_allow_html=True)

            if _run_btn or "whatif_result" in st.session_state:
                if _run_btn:
                    _cm = _wi_latest.to_dict() if not _wi_latest.empty else {}
                    if _scenario_type == "Volatility shock":
                        _result = scenario_vol_shock(_cm, _target_vol, _notional)
                    elif _scenario_type == "Market drawdown":
                        _result = scenario_market_drawdown(_cm, _drawdown, _notional)
                    else:
                        _result = scenario_rate_shock(_cm, _rate_change, _notional)
                    st.session_state["whatif_result"] = _result
                    _wi_con.execute(
                        "INSERT INTO audit_nba_actions VALUES (?, ?, ?, ?, ?, ?)",
                        [str(uuid.uuid4()), f"REF-{str(uuid.uuid4())[:8].upper()}",
                         _wi_session, "whatif_scenario", _result["scenario"],
                         datetime.now(timezone.utc)],
                    )
                else:
                    _result = st.session_state["whatif_result"]

                _curr = _result["current"]
                _proj = _result["projected"]
                _di   = _result["dollar_impact"]

                st.markdown(f"""
<div style="font-size:10px;color:{_P['text_sec']};text-transform:uppercase;
            letter-spacing:.06em;margin-bottom:10px;">
  {_result['input_label']} — projected vs current
</div>""", unsafe_allow_html=True)

                # Fix 13.2 — explicit CURRENT / PROJECTED tiles
                _ks = list(_curr.keys())
                _kpi_cols = st.columns(len(_ks))
                _bw_map = {"sharpe":"higher","mdd":"higher","vol":"lower",
                           "yield_spread":"higher","fed_funds":"lower"}
                _lbl_map = {"sharpe":"Sharpe ratio","mdd":"Max drawdown",
                            "vol":"Volatility","yield_spread":"Yield spread","fed_funds":"Fed Funds"}
                for _i, _key in enumerate(_ks):
                    _cv = _curr[_key]; _pv = _proj.get(_key)
                    if _pv is None: continue
                    render_kpi_comparison(
                        _kpi_cols[_i],
                        _lbl_map.get(_key, _key),
                        f"{_cv:.2f}" if isinstance(_cv, float) else str(_cv),
                        f"{_pv:.2f}" if isinstance(_pv, float) else str(_pv),
                        better_when=_bw_map.get(_key, "higher"),
                    )

                _total = _di["total"]
                _tc = "#d93025" if _total < 0 else "#0f9d58"
                st.markdown(f"""
<div style="background:{_P['card_bg']};border:1px solid {_P['border']};border-radius:6px;
            padding:14px;margin-top:12px;">
  <div style="font-size:10px;color:{_P['text_sec']};text-transform:uppercase;
              letter-spacing:.06em;margin-bottom:10px;">
    Illustrative portfolio impact (${_di['notional']:,.0f} · 60/40)
  </div>
  <div style="display:grid;grid-template-columns:1fr auto;gap:6px 16px;font-size:12px;">
    <div style="color:{_P['text_body']};">Equity leg (${_di['equity_allocation']:,.0f})</div>
    <div style="color:{_tc};font-weight:500;text-align:right;">${_di['equity_leg']:+,.0f}</div>
    <div style="color:{_P['text_body']};">Bond leg (${_di['bond_allocation']:,.0f})</div>
    <div style="color:{_P['text_body']};text-align:right;">${_di['bond_leg']:+,.0f}</div>
    <div style="color:{_P['text_pri']};font-weight:600;border-top:1px solid {_P['border']};padding-top:6px;">Total illustrative impact</div>
    <div style="color:{_tc};font-weight:700;font-size:16px;text-align:right;
                border-top:1px solid {_P['border']};padding-top:6px;">${_total:+,.0f}</div>
  </div>
</div>""", unsafe_allow_html=True)

                # Fix 13.3 — calculation expander
                if _di.get("method"):
                    with st.expander("How was this calculated?"):
                        st.caption(_di["method"])
                        st.caption(_result["assumption"])

                # Fix 13.4 — filtered + labelled projected NBA signals
                st.markdown(f"""
<div style="font-size:10px;color:{_P['text_sec']};text-transform:uppercase;
            letter-spacing:.06em;margin-top:14px;margin-bottom:6px;">Under this scenario, these conditions would be triggered</div>
""", unsafe_allow_html=True)

                _proj_metrics = dict(_wi_latest.to_dict())
                _proj_metrics.update(_proj)
                _all_proj_rules = evaluate_nba_on_projected(_proj_metrics)
                _proj_rules = filter_projected_rules(_all_proj_rules, _scenario_type)

                if _proj_rules:
                    for _pr in _proj_rules:
                        _pdot = {"HIGH":"#ef4444","MEDIUM":"#f59e0b","LOW":"#10b981"}.get(_pr["severity"],"#9aa0a6")
                        st.markdown(f"""
<div style="display:flex;align-items:flex-start;gap:8px;padding:8px 10px;
            border:1px solid {_P['border']};border-radius:6px;margin-bottom:4px;background:{_P['card_bg']};">
  <div style="width:8px;height:8px;border-radius:50%;background:{_pdot};flex-shrink:0;margin-top:3px;"></div>
  <div>
    <div style="font-size:11px;font-weight:500;color:{_P['text_pri']};">{_pr['name']}</div>
    <div style="font-size:10px;color:{_P['text_sec']};">{_pr['action'][:80]}{'…' if len(_pr['action'])>80 else ''}</div>
  </div>
</div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""
<div style="display:flex;align-items:center;gap:8px;padding:8px 10px;
            border:1px solid {_P['border']};border-radius:6px;background:{_P['card_bg']};">
  <div style="width:8px;height:8px;border-radius:50%;background:#0f9d58;flex-shrink:0;"></div>
  <div style="font-size:11px;color:#6ee7b7;font-weight:500;">No threshold breaches under this scenario</div>
</div>""", unsafe_allow_html=True)

                st.divider()
                _wa1, _wa2 = st.columns(2)
                with _wa1:
                    if st.button("📨 Send to back office", key="wi_backoffice", use_container_width=True):
                        _wref = f"REF-{str(uuid.uuid4())[:8].upper()}"
                        _wi_con.execute(
                            "INSERT INTO audit_nba_actions VALUES (?, ?, ?, ?, ?, ?)",
                            [str(uuid.uuid4()), _wref, _wi_session, "whatif_back_office",
                             _result["scenario"], datetime.now(timezone.utc)],
                        )
                        st.success(f"Logged · {_wref}")
                with _wa2:
                    if st.button("📄 Export scenario PDF", key="wi_pdf", use_container_width=True):
                        try:
                            from reportlab.lib import colors as _rl_colors
                            from reportlab.lib.pagesizes import A4
                            from reportlab.lib.styles import getSampleStyleSheet
                            from reportlab.lib.units import cm
                            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
                            _buf = _io.BytesIO()
                            _doc = SimpleDocTemplate(_buf, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
                            _sty = getSampleStyleSheet(); _story = []
                            _story.append(Paragraph("Market Analytics Platform", _sty["Title"]))
                            _story.append(Paragraph(f"What-if Scenario Report · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", _sty["Normal"]))
                            _story.append(Spacer(1, 0.3*cm))
                            _story.append(Paragraph("Scenario", _sty["Heading2"]))
                            _story.append(Paragraph(_result["input_label"], _sty["Normal"]))
                            _story.append(Spacer(1, 0.3*cm))
                            _story.append(Paragraph("Current vs Projected KPIs", _sty["Heading2"]))
                            _kpi_rows = [["Metric","Current","Projected","Change"]]
                            for _k in _curr:
                                _cv2=_curr[_k]; _pv2=_proj.get(_k,"—")
                                _chg2 = (f"{_pv2-_cv2:+.2f}" if isinstance(_pv2,(int,float)) and isinstance(_cv2,(int,float)) else "—")
                                _kpi_rows.append([_label_map.get(_k,_k),str(_cv2),str(_pv2),_chg2])
                            _kt = Table(_kpi_rows, colWidths=[4*cm,3*cm,3*cm,3*cm])
                            _kt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),_rl_colors.darkblue),("TEXTCOLOR",(0,0),(-1,0),_rl_colors.whitesmoke),("GRID",(0,0),(-1,-1),0.5,_rl_colors.lightgrey),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("ROWBACKGROUNDS",(0,1),(-1,-1),[_rl_colors.whitesmoke,_rl_colors.white])]))
                            _story.append(_kt); _story.append(Spacer(1,0.3*cm))
                            _story.append(Paragraph("Illustrative Portfolio Impact", _sty["Heading2"]))
                            _imp_rows = [["Component","Allocation","Impact"],["Equity leg",f"${_di['equity_allocation']:,.0f}",f"${_di['equity_leg']:+,.0f}"],["Bond leg",f"${_di['bond_allocation']:,.0f}",f"${_di['bond_leg']:+,.0f}"],["Total",f"${_di['notional']:,.0f}",f"${_di['total']:+,.0f}"]]
                            _it = Table(_imp_rows, colWidths=[5*cm,4*cm,4*cm])
                            _it.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),_rl_colors.grey),("TEXTCOLOR",(0,0),(-1,0),_rl_colors.whitesmoke),("GRID",(0,0),(-1,-1),0.5,_rl_colors.lightgrey),("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold")]))
                            _story.append(_it); _story.append(Spacer(1,0.3*cm))
                            _story.append(Paragraph("Projected NBA Signals", _sty["Heading2"]))
                            for _pr2 in _proj_rules[:3]:
                                _story.append(Paragraph(f"• {_pr2['name']} — {_pr2['action']}", _sty["Normal"]))
                            _story.append(Spacer(1,0.4*cm))
                            _story.append(Paragraph(_result["assumption"], _sty["Italic"]))
                            _story.append(Paragraph("DISCLAIMER: Decision support only. Not financial advice. Illustrative 60/40 proxy. Not based on actual holdings.", _sty["Italic"]))
                            _doc.build(_story); _buf.seek(0)
                            st.download_button("⬇ Download PDF", data=_buf.read(),
                                file_name=f"whatif_{_result['scenario'].replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                                mime="application/pdf", use_container_width=True)
                        except Exception as _pdf_err:
                            st.error(f"PDF failed: {_pdf_err}")

                st.markdown(f"""
<div style="font-size:10px;color:{_P['text_sec']};margin-top:10px;padding:8px 10px;
            border:1px solid {_P['border']};border-radius:4px;background:{_P['card_bg']};">
  ⚠ {_result['assumption']}
</div>""", unsafe_allow_html=True)

            else:
                st.markdown(f"""
<div style="color:{_P['text_sec']};font-size:13px;padding:60px 0;text-align:center;">
  Select a scenario and click <strong style="color:{_P['text_pri']};">Run scenario</strong> to see projected impact.
</div>""", unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Checkpoint [{CHECKPOINT}] failed: {e}")

# ---------------------------------------------------------------------------
# Architecture tab (PRD Change 3)
# ---------------------------------------------------------------------------
with tab_arch:
    import streamlit.components.v1 as _components

    # Remove all Streamlit padding above the iframe so it sits flush under the tab bar
    st.markdown("""
<style>
[data-testid="stTabsContent"] { padding-top: 0 !important; }
</style>
""", unsafe_allow_html=True)

    try:
        with open("dashboard/architecture.html", "r") as _f:
            _arch_html = _f.read()

        # Inject a resize script so the iframe expands to its full content height
        _resize_script = """
<script>
(function() {
  function _sendHeight() {
    var h = document.documentElement.scrollHeight || document.body.scrollHeight;
    window.parent.postMessage({type: 'streamlit:setFrameHeight', height: h}, '*');
  }
  window.addEventListener('load', function() { _sendHeight(); setTimeout(_sendHeight, 300); });
  new MutationObserver(_sendHeight).observe(document.body, {childList:true, subtree:true, attributes:true});
})();
</script>
"""
        # Inject before </body> if present, else append
        if "</body>" in _arch_html:
            _arch_html = _arch_html.replace("</body>", _resize_script + "</body>")
        else:
            _arch_html = _arch_html + _resize_script

        # Use a large initial height; the injected script will correct it on load
        _components.html(_arch_html, height=900, scrolling=False)

    except FileNotFoundError:
        st.info(
            "architecture.html not found in dashboard/. "
            "Save the architecture diagram HTML to dashboard/architecture.html."
        )
    except Exception as _ae:
        st.error(f"Architecture tab failed: {_ae}")
