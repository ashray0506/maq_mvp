# Dashboard Fixes — Claude Code Instructions
**Read dashboard/app.py before making any changes.**
**Fix one issue at a time. Confirm it works before moving to the next.**

---

## Issue 1 — FEDFUNDS blank in header

**Problem:** `macro_value` is null on recent rows because FRED is monthly and not all daily rows have a joined macro value.

**Fix:** Wherever the header or pulse bar reads `macro_value`, replace direct access with a forward-filled lookup:

```python
# find any instance of latest['macro_value'] in the header/pulse bar
# replace with:
macro_val = df['macro_value'].ffill().dropna().iloc[0] if df['macro_value'].notna().any() else None
```

Apply this same pattern anywhere `macro_value`, `macro_ema_3m`, or `macro_sma_3m` is read from `latest` in the sticky header or pulse bar. Use `df['col'].ffill().dropna().iloc[0]` not `latest['col']` for any monthly series.

**Confirm:** FEDFUNDS % shows a value in the header after reload.

---

## Issue 2 — Sharpe 20d blank

**Problem:** Sharpe requires 20 rows of non-null returns AND non-null FEDFUNDS. If `macro_value` is null on most rows, Sharpe cannot be computed.

**Fix in `pipeline/transform_gold.py`:** After loading silver data and before computing any metrics, forward-fill the macro column:

```python
df['macro_value'] = df['macro_value'].ffill()
df['macro_ema_3m'] = df['macro_ema_3m'].ffill()
df['macro_sma_3m'] = df['macro_sma_3m'].ffill()
```

After this fix, re-run gold:
```bash
PYTHONPATH=. python pipeline/transform_gold.py
```

Then reload the dashboard. Sharpe should populate after row 20.

**Diagnose first if unsure:**
```python
import duckdb
con = duckdb.connect('market.duckdb')
print(con.execute("""
    SELECT date, macro_value, sharpe_20d, volatility_20d
    FROM gold_metrics ORDER BY date DESC LIMIT 25
""").fetchdf())
```

**Confirm:** Sharpe 20d shows a numeric value in KPI scorecard.

---

## Issue 3 — LLM showing "API key invalid or expired"

**Problem:** Kimi API key in `.env` is expired or missing.

**Diagnose first:**
```bash
python -c "
import requests, os
from dotenv import load_dotenv
load_dotenv()
key = os.getenv('KIMI_API_KEY', '')
print('Key present:', bool(key), '| First 8 chars:', key[:8] if key else 'NONE')
r = requests.post(
    'https://api.moonshot.cn/v1/chat/completions',
    headers={'Authorization': f'Bearer {key}'},
    json={'model': 'moonshot-v1-8k', 'messages': [{'role':'user','content':'hello'}]},
    timeout=10
)
print('Status:', r.status_code)
print('Response:', r.text[:300])
"
```

**If 401:** Key expired. Get a new one at platform.moonshot.cn and update `.env`.

**If key is valid but still failing:** Update `call_llm()` in `app.py` to detect 401 specifically and show a clear message instead of the generic fallback:

```python
def call_llm(prompt: str, context: str) -> str:
    full_prompt = f"{context}\n\nUser question: {prompt}"
    kimi_key = os.getenv("KIMI_API_KEY", "")
    if kimi_key:
        try:
            r = requests.post(
                "https://api.moonshot.cn/v1/chat/completions",
                headers={"Authorization": f"Bearer {kimi_key}"},
                json={
                    "model": "moonshot-v1-8k",
                    "messages": [{"role": "user", "content": full_prompt}]
                },
                timeout=15
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            elif r.status_code == 401:
                return "AI analyst offline — API key invalid or expired. Update KIMI_API_KEY in .env."
            else:
                return f"AI analyst offline — API error {r.status_code}."
        except requests.exceptions.Timeout:
            return "AI analyst offline — request timed out."
        except Exception:
            pass

    # rule-based fallback — never crashes, never shows raw error
    rsi_val = context.split("RSI-14:")[1].split("(")[0].strip() if "RSI-14:" in context else "unknown"
    return (
        f"AI analyst offline — KIMI_API_KEY not configured. "
        f"Current RSI: {rsi_val}. Review triggered rules for recommended actions."
    )
```

**Confirm:** Error message is specific and clear, not a raw traceback.

---

## Issue 4 — "No rules triggered" at RSI 68

**Problem:** RSI 68 should trigger `RSI_AMBER_UP` (60–70 range). Rule evaluation is likely failing due to null handling or column name mismatch.

**Diagnose first — add this temporarily to the top of `evaluate_nba_rules()`:**
```python
st.sidebar.write("DEBUG RSI:", latest.get("rsi_14"), type(latest.get("rsi_14")))
st.sidebar.write("DEBUG columns:", list(latest.index))
```

**Fix — update all rule conditions to handle nulls explicitly:**

```python
def safe_float(val, default=50.0):
    try:
        return float(val) if val is not None and str(val) != 'nan' else default
    except (TypeError, ValueError):
        return default
```

Add this helper at the top of `evaluate_nba_rules()` and use it for every metric read:

```python
rsi = safe_float(latest.get("rsi_14"), default=50.0)
vwap = safe_float(latest.get("vwap_20d"), default=0.0)
close = safe_float(latest.get("close"), default=0.0)
sharpe = safe_float(latest.get("sharpe_20d"), default=1.0)
mdd = safe_float(latest.get("max_drawdown_90d"), default=0.0)
vol = safe_float(latest.get("volatility_20d"), default=15.0)
eff = safe_float(latest.get("vwap_efficiency"), default=97.0)
ema = safe_float(latest.get("macro_ema_3m"), default=0.0)
sma = safe_float(latest.get("macro_sma_3m"), default=0.0)
```

Then update rule conditions to use these local variables instead of `latest.get(...)` directly.

**Remove the debug sidebar lines after confirming rules fire.**

**Confirm:** RSI 68 shows amber rule triggered in JUDGE column.

---

## Issue 5 — Remove "See / Judge / Act" explicit labels

**Problem:** Labels are too literal. The layout should imply the flow.

**Fix:** Find and remove or replace these captions:

```python
# DELETE these lines entirely:
st.caption("📊 SEE — Market Data")
st.caption("💬 JUDGE — What This Means")
st.caption("🎯 ACT — Next Best Action")

# If column headers are needed, replace with minimal labels:
# SEE column:   st.markdown("##### Market conditions")
# JUDGE column: st.markdown("##### Signal analysis")
# ACT column:   st.markdown("##### Recommended actions")
```

**Confirm:** No "See / Judge / Act" text visible on dashboard.

---

## Issue 6 — Action buttons — back office context

**Problem:** Current buttons are generic. Should reflect post-trade operations context. No integration needed — just log the action with a reference ID.

**Fix:** Replace existing action buttons with:

```python
st.markdown("**Route this signal**")
b1, b2 = st.columns(2)
with b1:
    if st.button("📨 Back office", key=f"bo_{rec['rule_id']}"):
        ref = handle_action("back_office", [rec["rule_id"]], con, session_id)
        st.success(f"Logged · {ref}")
    if st.button("💬 Slack alert", key=f"slack_{rec['rule_id']}"):
        ref = handle_action("slack_alert", [rec["rule_id"]], con, session_id)
        st.success(f"Logged · {ref}")
with b2:
    if st.button("👁 Send for review", key=f"rv_{rec['rule_id']}"):
        ref = handle_action("review", [rec["rule_id"]], con, session_id)
        st.success(f"Logged · {ref}")
    if st.button("📋 Add to report", key=f"rp_{rec['rule_id']}"):
        ref = handle_action("report", [rec["rule_id"]], con, session_id)
        st.success(f"Logged · {ref}")
```

**Confirm:** Four buttons visible per triggered rule. Each logs a REF-XXXXXXXX to `audit_nba_actions`.

---

## Issue 7 — Metric hover definitions

**Problem:** No explanations for metrics. Should show on hover.

**Fix:** Add this dict at the top of `app.py` immediately after `VALIDATION_CONFIG`:

```python
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
```

**Then use `help=` parameter on every `st.metric()` call:**

```python
# example — apply this pattern to every metric tile
st.metric(
    label="RSI-14",
    value=f"{rsi:.1f}",
    help=METRIC_DEFINITIONS["RSI-14"]
)

st.metric(
    label="Sharpe 20d",
    value=f"{sharpe:.2f}" if sharpe else "N/A",
    help=METRIC_DEFINITIONS["Sharpe 20d"]
)

st.metric(
    label="Max Drawdown 90d",
    value=f"{mdd:.1f}%" if mdd else "N/A",
    help=METRIC_DEFINITIONS["Max Drawdown 90d"]
)

st.metric(
    label="Volatility 20d",
    value=f"{vol:.1f}%" if vol else "N/A",
    help=METRIC_DEFINITIONS["Volatility 20d"]
)

st.metric(
    label="VWAP Efficiency",
    value=f"{eff:.1f}" if eff else "N/A",
    help=METRIC_DEFINITIONS["VWAP Efficiency"]
)
```

Streamlit's `help=` renders as a tooltip (?) icon on hover — no extra code needed.

**Note for presentation:** Tell the assessor that in production, these definitions would live in a data catalogue (Alation, Collibra, or DataHub) and be pulled via API rather than hardcoded. The `METRIC_DEFINITIONS` dict is the local equivalent — same pattern, different source.

**Confirm:** Hovering any metric tile shows a tooltip with the definition.

---
## Fix 8 — Consolidate header rows
In app.py find the three separate render calls and merge them:

Delete the standalone render_sticky_header() call
Delete the standalone pulse bar section
Replace both with a single combined header that has two lines: equity metrics on line 1, macro/yield on line 2
Keep KPI scorecard as a compact single row of st.columns(4) with smaller font — not a full section with a heading

The ## KPI Scorecard heading and any st.subheader() or st.markdown("### ...") above the KPI tiles should be removed. The tiles speak for themselves.
Add this to your FIXES file and give it to Claude Code as Issue 8.

------
## Run order after all fixes

```bash
# re-run gold to pick up forward-fill fix
PYTHONPATH=. python pipeline/transform_gold.py

# validate
python pipeline/validate.py

# restart dashboard (Ctrl+C first if running)
streamlit run dashboard/app.py
```

---

## What NOT to do

- Do not change `VALIDATION_CONFIG` thresholds
- Do not read from bronze or silver in the dashboard
- Do not add actual Slack/back office integrations — log the action only
- Do not remove the `handle_action()` audit logging when updating buttons
- Do not batch all fixes — one at a time, confirm each before continuing
