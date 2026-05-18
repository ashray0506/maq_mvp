# Fix 11 — Header Labels, Title, KPI Section, Observability Alignment
**Read app.py and observability.py before making changes.**
**One section at a time. Confirm before moving on.**

---

## Context — what the screenshots show

Looking at the current dashboard:
- Title "Market Intelligence Platform" is too small / same weight as everything else
- The INDEX CLOSE / VWAP / RSI row has no section label — floats without context
- The 10Y Treasury / Yield spread row has no label either
- KPI scorecard has no label or just "KPI Scorecard" — not industry standard
- Observability formatting doesn't match the market dashboard style
- 4 KPI tiles instead of 3 — fine, explained below

---

## Why 4 KPI tiles (not 3)

The original brief said 2–3 metrics. We have 3 technical metrics (VWAP, RSI, EMA/SMA) which satisfy the brief. The 4 KPI tiles (Sharpe, MDD, Vol, VWAP Efficiency) are business KPIs added beyond scope to show depth. Fine to keep — just don't call them "metrics" in the dashboard, call them "Risk Analytics" to distinguish from the technical metrics.

---

## Fix 11.1 — Platform title (bolder, larger)

Find the title `st.markdown` in app.py and update:

```python
# Replace the current title span with:
st.markdown("""
<div style="background:#fff;border-bottom:1px solid #e8eaed;padding:14px 0 12px 0;
            display:flex;align-items:center;justify-content:space-between;">
    <span style="font-size:22px;font-weight:700;color:#1a1a2e;letter-spacing:-0.4px;">
        Market Intelligence Platform
    </span>
    <span style="font-size:11px;color:#9aa0a6;">
        Really Big Bank · Post-trade operations
    </span>
</div>
""", unsafe_allow_html=True)
```

Key change: `font-weight:500` → `font-weight:700`, `font-size:15px` → `font-size:22px`.

Confirm: title is visibly bolder and larger. Then continue.

---

## Fix 11.2 — Label the header rows

The two header rows need section labels so they read as a coherent unit.
Charles River calls this section **"Market Overview"**.

Update the combined header HTML — add small uppercase labels above each row:

```python
st.markdown(f"""
<div style="background:#fff;border-bottom:1px solid #e8eaed;padding:12px 0 10px 0;">

  <!-- Row label -->
  <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
              letter-spacing:.1em;margin-bottom:10px;">
    Market overview
  </div>

  <!-- Row 1: equity metrics -->
  <div style="display:flex;align-items:baseline;gap:28px;margin-bottom:10px;flex-wrap:wrap;">
    <div>
      <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
                  letter-spacing:.05em;">Index close</div>
      <div style="font-size:22px;font-weight:500;color:#1a1a2e;">${close_val:.2f}</div>
      <div style="font-size:11px;color:{change_color};">{change_arrow} {abs(day_change):.2f}%</div>
    </div>
    <div style="width:1px;height:36px;background:#e8eaed;align-self:center;"></div>
    <div>
      <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
                  letter-spacing:.05em;">VWAP 20d</div>
      <div style="font-size:22px;font-weight:500;color:#1a1a2e;">{vwap_display}</div>
      <div style="font-size:11px;color:#9aa0a6;">fair value</div>
    </div>
    <div style="width:1px;height:36px;background:#e8eaed;align-self:center;"></div>
    <div>
      <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
                  letter-spacing:.05em;">RSI-14</div>
      <div style="font-size:22px;font-weight:500;color:#1a1a2e;">{rsi_display}</div>
      <div style="font-size:11px;color:#b45309;">{rag_text.lower()}</div>
    </div>
    <div style="width:1px;height:36px;background:#e8eaed;align-self:center;"></div>
    <div>
      <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
                  letter-spacing:.05em;">Fed funds</div>
      <div style="font-size:22px;font-weight:500;color:#1a1a2e;">{macro_display}</div>
      <div style="font-size:11px;color:#9aa0a6;">risk-free rate</div>
    </div>
    <div style="width:1px;height:36px;background:#e8eaed;align-self:center;"></div>
    <div style="padding:5px 14px;border-radius:20px;font-size:12px;font-weight:500;
                background:#{bg};color:#{fg};border:1px solid #{border};align-self:center;">
      {rag_text}
    </div>
  </div>

  <!-- Row 2: macro/yield — labelled -->
  <div style="display:flex;align-items:center;gap:20px;font-size:11px;
              color:#5f6368;flex-wrap:wrap;padding-top:8px;
              border-top:1px solid #f1f3f4;">
    <span style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
                 letter-spacing:.08em;margin-right:4px;">Macro / yield</span>
    <span>10Y Treasury <strong>{gs10_display}</strong></span>
    <span style="color:#e8eaed;">|</span>
    <span>Yield spread <strong style="color:{spread_color}">{spread_display}</strong></span>
    <span style="color:#e8eaed;">|</span>
    <span>Vol <strong>{vol_display}</strong></span>
    <span style="color:#e8eaed;">|</span>
    <span>MDD <strong>{mdd_display}</strong></span>
    <span style="margin-left:auto;font-size:10px;color:#9aa0a6;">
      Run: {run_id} · {last_run}
    </span>
  </div>

</div>
""", unsafe_allow_html=True)
```

Confirm: "MARKET OVERVIEW" label visible above the metrics row. "MACRO / YIELD" label visible before the second row. Then continue.

---

## Fix 11.3 — Rename KPI scorecard section

Find the KPI scorecard section label and update from "KPI Scorecard" to "Risk Analytics":

```python
# Replace any st.markdown("### KPI Scorecard") or similar with:
st.markdown("""
<div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
            letter-spacing:.1em;padding:12px 0 8px 0;">
    Risk analytics
</div>
""", unsafe_allow_html=True)
```

Charles River calls this section "Risk Analytics" — it covers the same KPIs (Sharpe, MDD, Vol). The sub-labels under each tile ("risk-adjusted return", "controlled", "low regime") stay as they are.

Confirm: section label reads "RISK ANALYTICS" not "KPI Scorecard".

---

## Fix 11.4 — Column section headers (Market conditions / Signal analysis / Recommended actions)

These are currently `st.markdown("**Market conditions**")` etc. Make them consistent weight and style:

```python
# Apply this pattern to all three column headers:
def section_header(text):
    return st.markdown(f"""
    <div style="font-size:13px;font-weight:600;color:#1a1a2e;
                padding-bottom:10px;border-bottom:1px solid #f1f3f4;
                margin-bottom:14px;">
        {text}
    </div>
    """, unsafe_allow_html=True)

# Use as:
section_header("Market conditions")
section_header("Signal analysis")
section_header("Recommended actions")
```

Confirm: all three column headers same style and weight.

---

## Fix 11.5 — Observability formatting alignment

The observability dashboard needs to match the market dashboard style. Open `observability.py` and apply these changes:

**Title — match market dashboard:**
```python
st.markdown("""
<div style="background:#fff;border-bottom:1px solid #e8eaed;padding:14px 0 12px 0;
            display:flex;align-items:center;justify-content:space-between;">
    <span style="font-size:22px;font-weight:700;color:#1a1a2e;letter-spacing:-0.4px;">
        Pipeline Observability
    </span>
    <span style="font-size:11px;color:#9aa0a6;">
        Really Big Bank · Post-trade operations
    </span>
</div>
""", unsafe_allow_html=True)
```

**Health banner — tighter, same card style:**
```python
status_bg = "#f0fdf4" if is_healthy else "#fef2f2"
status_border = "#bbf7d0" if is_healthy else "#fecaca"
status_color = "#166534" if is_healthy else "#b91c1c"
status_label = "HEALTHY" if is_healthy else "DEGRADED"
status_icon = "✓" if is_healthy else "⚠"

st.markdown(f"""
<div style="background:{status_bg};border:1px solid {status_border};
            border-radius:6px;padding:10px 16px;margin-bottom:16px;
            display:flex;align-items:center;gap:10px;">
    <span style="font-size:14px;font-weight:700;color:{status_color};">
        {status_icon} {status_label}
    </span>
    <span style="font-size:11px;color:{status_color};opacity:.8;">
        Last run: {last_run_label}
    </span>
</div>
""", unsafe_allow_html=True)
```

**Section labels — same pattern as market dashboard:**
```python
def obs_section(text):
    return st.markdown(f"""
    <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
                letter-spacing:.1em;padding:12px 0 8px 0;">
        {text}
    </div>
    """, unsafe_allow_html=True)

# Use for: ISSUES, PIPELINE HOPS, ROW FLOW, QUARANTINE LOG, RUN HISTORY, NBA AUDIT
obs_section("Issues")
obs_section("Pipeline hops")
obs_section("Row flow")
obs_section("Quarantine log")
obs_section("Run history")
obs_section("NBA audit")
```

**Hop cards — match the KPI tile style:**
```python
def hop_card(col, layer_name, emoji, status, rows_in, rows_out, dq_pass, dq_fail, quarantined):
    bg = "#f0fdf4" if status == "PASS" else "#fef2f2"
    border = "#bbf7d0" if status == "PASS" else "#fecaca"
    status_color = "#166534" if status == "PASS" else "#b91c1c"
    col.markdown(f"""
    <div style="background:#fff;border:1px solid #e8eaed;border-radius:6px;padding:14px;">
        <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
                    letter-spacing:.05em;margin-bottom:6px;">{emoji} {layer_name}</div>
        <div style="display:inline-block;padding:2px 8px;border-radius:10px;
                    background:{bg};border:1px solid {border};
                    font-size:11px;font-weight:500;color:{status_color};
                    margin-bottom:10px;">{status}</div>
        <div style="font-size:12px;color:#1a1a2e;margin-bottom:2px;">
            {rows_in} → {rows_out} rows
        </div>
        <div style="font-size:11px;color:#9aa0a6;">
            DQ {dq_pass} PASS / {dq_fail} FAIL · quarantined {quarantined}
        </div>
    </div>
    """, unsafe_allow_html=True)
```

**Issues panel — same chip style as triggered rules in market dashboard:**
```python
# For each issue:
st.markdown(f"""
<div style="display:flex;align-items:flex-start;gap:8px;padding:8px 10px;
            border:1px solid #fecaca;border-radius:6px;margin-bottom:5px;
            background:#fef2f2;">
    <div style="width:8px;height:8px;border-radius:50%;background:#ef4444;
                flex-shrink:0;margin-top:3px;"></div>
    <div style="font-size:11px;color:#1a1a2e;line-height:1.5;">{issue_text}</div>
</div>
""", unsafe_allow_html=True)

# When clean:
st.markdown("""
<div style="padding:10px 14px;border:1px solid #bbf7d0;border-radius:6px;
            background:#f0fdf4;font-size:12px;color:#166534;">
    ✓ No issues — all DQ rules passing
</div>
""", unsafe_allow_html=True)
```

**Page background — same as market dashboard:**
Make sure the same global CSS block from Fix 9 Step 1 is at the top of `observability.py`:
```python
st.markdown("""
<style>
.stApp { background: #f8f9fa; }
.block-container { padding-top: 0 !important; max-width: 100% !important; }
header[data-testid="stHeader"] { display: none; }
</style>
""", unsafe_allow_html=True)
```

Confirm: observability dashboard has same title weight, background, card style, and section label pattern as market dashboard.

---

## Summary of label changes

| Was | Now | Why |
|---|---|---|
| "Market Intelligence Platform" (small) | **Market Intelligence Platform** (bold, 22px) | Platform name needs to be the anchor |
| No label on metrics row | `MARKET OVERVIEW` | Charles River standard, gives context |
| No label on macro row | `MACRO / YIELD` | Distinguishes equity from macro |
| "KPI Scorecard" | `RISK ANALYTICS` | Industry standard — Charles River, Bloomberg |
| "Market conditions" (plain) | **Market conditions** (600 weight, with divider) | Consistent heading weight across columns |
| Observability has different style | Matches market dashboard | Same platform, same visual language |

---

## Run order

No pipeline changes needed — all frontend only.

```bash
streamlit run dashboard/app.py       # check market dashboard
streamlit run dashboard/observability.py --server.port 8502   # check observability
```

## What NOT to do

- Do not rename the tab labels ("Market Intelligence", "Governance", "Observability") — those are fine
- Do not change VALIDATION_CONFIG
- Do not add any new sections — this fix is labels and formatting only
- Do not batch — fix 11.1 first, confirm, then 11.2 etc.
