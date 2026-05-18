# Fix 9 — Dashboard Visual Redesign
**Read app.py fully before making any changes.**
**Apply the CSS first, then update each component. Confirm after each section.**

---

## Design principles

- Background: `#f8f9fa` (light gray page) — not white
- Cards and panels: `#ffffff` with `1px solid #e8eaed` borders
- No default Streamlit purple. No gradient backgrounds.
- Typography: tight, small labels in uppercase, large values
- Colours encode meaning only: green = good, amber = watch, red = alert, gray = neutral
- Dividers between columns via `gap:1px; background:#e8eaed` grid trick
- Footer: always visible, shows run metadata and DQ status

---

## Step 1 — Global CSS injection

Add this at the very top of `app.py` immediately after imports, before any `st.` calls:

```python
st.markdown("""
<style>
/* Page background */
.stApp { background: #f8f9fa; }

/* Remove default Streamlit padding */
.block-container { padding-top: 0 !important; padding-bottom: 0 !important; max-width: 100% !important; }

/* Hide Streamlit default header */
header[data-testid="stHeader"] { display: none; }

/* Column dividers */
[data-testid="column"] {
    background: #ffffff;
    padding: 20px 20px !important;
    border-right: 1px solid #e8eaed;
}
[data-testid="column"]:last-child { border-right: none; }

/* Metric overrides */
[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #e8eaed;
    border-radius: 6px;
    padding: 10px 14px;
}
[data-testid="stMetricLabel"] { font-size: 10px !important; color: #9aa0a6 !important; text-transform: uppercase; letter-spacing: .05em; }
[data-testid="stMetricValue"] { font-size: 20px !important; font-weight: 500 !important; }

/* Button overrides */
.stButton > button {
    border: 1px solid #e8eaed !important;
    background: #ffffff !important;
    color: #5f6368 !important;
    font-size: 11px !important;
    padding: 5px 10px !important;
    border-radius: 4px !important;
    width: 100%;
}
.stButton > button:hover {
    background: #f8f9fa !important;
    border-color: #9aa0a6 !important;
}

/* Info boxes */
[data-testid="stInfo"] {
    background: #f8f9fa !important;
    border: 1px solid #e8eaed !important;
    border-radius: 6px !important;
    font-size: 12px !important;
    color: #5f6368 !important;
}

/* Expander */
[data-testid="stExpander"] {
    border: 1px solid #e8eaed !important;
    border-radius: 6px !important;
    background: #ffffff !important;
}

/* Divider */
hr { border-color: #e8eaed !important; margin: 12px 0 !important; }

/* Caption */
.stCaption { font-size: 10px !important; color: #9aa0a6 !important; }
</style>
""", unsafe_allow_html=True)
```

Confirm: page background changes to light gray. Then continue.

---

## Step 2 — Topbar (replaces st.title)

Replace any `st.title(...)` or `st.header(...)` at the top with:

```python
st.markdown("""
<div style="background:#fff;border-bottom:1px solid #e8eaed;padding:12px 0 12px 0;
            display:flex;align-items:center;justify-content:space-between;margin-bottom:0;">
    <span style="font-size:15px;font-weight:500;color:#1a1a2e;letter-spacing:-0.2px;">
        Market Intelligence Platform
    </span>
    <span style="font-size:11px;color:#9aa0a6;">
        Really Big Bank · Post-trade operations
    </span>
</div>
""", unsafe_allow_html=True)
```

---

## Step 3 — Combined header (replaces all three header rows)

Replace the sticky header, pulse bar, and any separate equity/macro sections with one combined block.
Build the values in Python first, then render:

```python
# Build values safely
close_val = df['close'].iloc[0] if not df.empty else 0
vwap_val = df['vwap_20d'].ffill().dropna().iloc[0] if df['vwap_20d'].notna().any() else None
rsi_val = df['rsi_14'].dropna().iloc[0] if df['rsi_14'].notna().any() else None
macro_val = df['macro_value'].ffill().dropna().iloc[0] if df['macro_value'].notna().any() else None
gs10_val = df['gs10_value'].ffill().dropna().iloc[0] if 'gs10_value' in df.columns and df['gs10_value'].notna().any() else None
vol_val = df['volatility_20d'].dropna().iloc[0] if df['volatility_20d'].notna().any() else None
mdd_val = df['max_drawdown_90d'].dropna().iloc[0] if df['max_drawdown_90d'].notna().any() else None
spread = round(gs10_val - macro_val, 2) if gs10_val and macro_val else None

# RSI signal
cfg = VALIDATION_CONFIG
if rsi_val and rsi_val > cfg['overbought_threshold']:
    rag_class, rag_text = "over", "Overbought — review"
elif rsi_val and rsi_val < cfg['oversold_threshold']:
    rag_class, rag_text = "under", "Oversold — opportunity"
elif rsi_val and rsi_val >= cfg['amber_upper']:
    rag_class, rag_text = "neutral", "Approaching overbought"
elif rsi_val and rsi_val <= cfg['amber_lower']:
    rag_class, rag_text = "neutral", "Approaching oversold"
else:
    rag_class, rag_text = "neutral", "Neutral — monitor"

rag_colors = {
    "over":    ("fef2f2", "b91c1c", "fecaca"),
    "under":   ("f0fdf4", "166534", "bbf7d0"),
    "neutral": ("fef9e7", "b45309", "fde68a"),
}
bg, fg, border = rag_colors[rag_class]

rsi_display = f"{rsi_val:.1f}" if rsi_val else "—"
macro_display = f"{macro_val:.2f}%" if macro_val else "—"
vwap_display = f"${vwap_val:.2f}" if vwap_val else "—"
gs10_display = f"{gs10_val:.2f}%" if gs10_val else "—"
spread_display = f"{'+' if spread and spread > 0 else ''}{spread:.2f}% {'▲' if spread and spread > 0 else '▼'}" if spread else "—"
spread_color = "#0f9d58" if spread and spread > 0 else "#d93025"
vol_display = f"{vol_val:.1f}%" if vol_val else "—"
mdd_display = f"{mdd_val:.1f}%" if mdd_val else "—"

day_change = ((close_val / df['close'].iloc[1]) - 1) * 100 if len(df) > 1 else 0
change_color = "#0f9d58" if day_change >= 0 else "#d93025"
change_arrow = "▲" if day_change >= 0 else "▼"

run_id = meta['metadata'].get('last_run_id', 'N/A') if meta['success'] else 'N/A'
last_run = str(meta['metadata'].get('last_run_timestamp', ''))[:10] if meta['success'] else 'N/A'

st.markdown(f"""
<div style="background:#fff;border-bottom:1px solid #e8eaed;padding:14px 0 10px 0;margin-bottom:0;">
  <div style="display:flex;align-items:baseline;gap:24px;margin-bottom:10px;flex-wrap:wrap;">
    <div>
      <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;letter-spacing:.05em;">Index close</div>
      <div style="font-size:22px;font-weight:500;color:#1a1a2e;line-height:1;">${close_val:.2f}</div>
      <div style="font-size:11px;color:{change_color}">{change_arrow} {abs(day_change):.2f}%</div>
    </div>
    <div style="width:1px;height:36px;background:#e8eaed;align-self:center;"></div>
    <div>
      <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;letter-spacing:.05em;">VWAP 20d</div>
      <div style="font-size:22px;font-weight:500;color:#1a1a2e;line-height:1;">{vwap_display}</div>
      <div style="font-size:11px;color:#9aa0a6;">fair value</div>
    </div>
    <div style="width:1px;height:36px;background:#e8eaed;align-self:center;"></div>
    <div>
      <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;letter-spacing:.05em;">RSI-14</div>
      <div style="font-size:22px;font-weight:500;color:#1a1a2e;line-height:1;">{rsi_display}</div>
      <div style="font-size:11px;color:#b45309;">{rag_text.lower()}</div>
    </div>
    <div style="width:1px;height:36px;background:#e8eaed;align-self:center;"></div>
    <div>
      <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;letter-spacing:.05em;">Fed funds</div>
      <div style="font-size:22px;font-weight:500;color:#1a1a2e;line-height:1;">{macro_display}</div>
      <div style="font-size:11px;color:#9aa0a6;">risk-free rate</div>
    </div>
    <div style="width:1px;height:36px;background:#e8eaed;align-self:center;"></div>
    <div style="padding:5px 12px;border-radius:20px;font-size:12px;font-weight:500;
                background:#{bg};color:#{fg};border:1px solid #{border};align-self:center;">
      {rag_text}
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:16px;font-size:11px;color:#5f6368;flex-wrap:wrap;">
    <span>10Y Treasury <strong>{gs10_display}</strong></span>
    <span>Yield spread <strong style="color:{spread_color}">{spread_display}</strong></span>
    <span>Vol <strong>{vol_display}</strong></span>
    <span>MDD <strong>{mdd_display}</strong></span>
    <span style="margin-left:auto;background:#f1f3f4;padding:2px 8px;border-radius:10px;">
      Run: {run_id} · {last_run}
    </span>
  </div>
</div>
""", unsafe_allow_html=True)
```

Confirm: single clean header, two lines, no redundancy. Then continue.

---

## Step 4 — KPI scorecard (compact, borderless tiles)

Replace the existing KPI scorecard section. Use `st.columns(4)` with custom metric rendering.
Add a sub-label under each value describing what the number means:

```python
k1, k2, k3, k4 = st.columns(4)

def kpi_tile(col, label, value, sublabel, color):
    """color: 'good'=#0f9d58, 'warn'=#b45309, 'bad'=#d93025, 'na'=#9aa0a6"""
    colors = {"good": "#0f9d58", "warn": "#b45309", "bad": "#d93025", "na": "#9aa0a6"}
    col.markdown(f"""
    <div style="background:#fff;border:1px solid #e8eaed;border-radius:6px;
                padding:10px 14px;height:72px;">
      <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
                  letter-spacing:.05em;margin-bottom:4px;">{label}</div>
      <div style="font-size:18px;font-weight:500;color:{colors[color]};
                  line-height:1;">{value}</div>
      <div style="font-size:10px;color:#9aa0a6;margin-top:3px;">{sublabel}</div>
    </div>
    """, unsafe_allow_html=True)

sharpe = df['sharpe_20d'].dropna().iloc[0] if df['sharpe_20d'].notna().any() else None
mdd = df['max_drawdown_90d'].dropna().iloc[0] if df['max_drawdown_90d'].notna().any() else None
vol = df['volatility_20d'].dropna().iloc[0] if df['volatility_20d'].notna().any() else None
eff = df['vwap_efficiency'].dropna().iloc[0] if df['vwap_efficiency'].notna().any() else None

kpi_tile(k1, "Sharpe 20d",
    f"{sharpe:.2f}" if sharpe else "—",
    "good" if sharpe and sharpe > 1 else "warn" if sharpe and sharpe >= 0 else "bad" if sharpe else "na",
    "risk-adjusted return" if sharpe else "warmup period")

kpi_tile(k2, "Max drawdown 90d",
    f"{mdd:.1f}%" if mdd else "—",
    "good" if mdd and mdd > -10 else "warn" if mdd and mdd > -20 else "bad" if mdd else "na",
    "controlled" if mdd and mdd > -10 else "elevated" if mdd else "—")

kpi_tile(k3, "Volatility 20d",
    f"{vol:.1f}%" if vol else "—",
    "good" if vol and vol < 12 else "warn" if vol and vol < 20 else "bad" if vol else "na",
    "low regime" if vol and vol < 12 else "elevated" if vol and vol >= 20 else "normal")

kpi_tile(k4, "VWAP efficiency",
    f"{eff:.1f}" if eff else "—",
    "good" if eff and eff > 97 else "warn" if eff and eff > 94 else "bad" if eff else "na",
    "orderly" if eff and eff > 97 else "deviation signal" if eff and eff <= 94 else "normal")
```

Note: the `kpi_tile` function takes `label, value, color, sublabel` — fix the argument order in the calls above to match.

Confirm: four compact tiles in a row with coloured values and sub-labels. Then continue.

---

## Step 5 — RAG card (JUDGE column)

Replace the existing RAG card with:

```python
rag_styles = {
    "over":    {"bg": "#fef2f2", "border": "#fecaca", "val_color": "#b91c1c"},
    "under":   {"bg": "#f0fdf4", "border": "#bbf7d0", "val_color": "#166534"},
    "neutral": {"bg": "#fef9e7", "border": "#fde68a", "val_color": "#b45309"},
}
s = rag_styles[rag_class]

st.markdown(f"""
<div style="background:{s['bg']};border:1px solid {s['border']};border-radius:8px;
            padding:16px;text-align:center;margin-bottom:14px;">
  <div style="font-size:24px;font-weight:500;color:{s['val_color']};">
    RSI {rsi_display}
  </div>
  <div style="font-size:11px;color:{s['val_color']};opacity:.85;margin-top:4px;">
    {rag_text}
  </div>
</div>
""", unsafe_allow_html=True)
```

---

## Step 6 — Triggered rules (JUDGE column)

Replace the list of triggered rules with styled chips:

```python
rule_colors = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#10b981",
               "USER": "#378ADD", "NONE": "#9aa0a6"}

for rec in recommendations:
    if rec["rule_id"] == "NONE":
        st.markdown("""
        <div style="display:flex;align-items:center;gap:8px;padding:8px 10px;
                    border:1px solid #e8eaed;border-radius:6px;background:#fff;">
          <div style="width:8px;height:8px;border-radius:50%;background:#10b981;flex-shrink:0;"></div>
          <div style="font-size:11px;color:#166534;font-weight:500;">All signals within normal range</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        dot_color = rule_colors.get(rec['severity'], '#9aa0a6')
        val_text = f" · {rec['metric_value']} {rec['metric_label']}" if rec.get('metric_value') else ""
        st.markdown(f"""
        <div style="display:flex;align-items:flex-start;gap:8px;padding:8px 10px;
                    border:1px solid #e8eaed;border-radius:6px;margin-bottom:5px;background:#fff;">
          <div style="width:8px;height:8px;border-radius:50%;background:{dot_color};
                      flex-shrink:0;margin-top:3px;"></div>
          <div>
            <div style="font-size:11px;font-weight:500;color:#1a1a2e;">{rec['rule_name']}</div>
            <div style="font-size:10px;color:#9aa0a6;">{rec['nba_category']}{val_text}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)
```

---

## Step 7 — Action buttons (ACT column)

Replace action buttons with compact styled cards:

```python
for rec in recommendations:
    if rec["rule_id"] == "NONE":
        st.markdown("""
        <div style="padding:12px;border:1px solid #e8eaed;border-radius:6px;
                    background:#f0fdf4;text-align:center;font-size:12px;color:#166534;">
          No actions required
        </div>
        """, unsafe_allow_html=True)
        continue

    st.markdown(f"""
    <div style="border:1px solid #e8eaed;border-radius:6px;padding:10px 12px;margin-bottom:8px;background:#fff;">
      <div style="font-size:12px;font-weight:500;color:#1a1a2e;margin-bottom:2px;">{rec['rule_name']}</div>
      <div style="font-size:10px;color:#9aa0a6;margin-bottom:8px;">{rec['nba_category']}</div>
    </div>
    """, unsafe_allow_html=True)

    b1, b2 = st.columns(2)
    with b1:
        if st.button("📨 Back office", key=f"bo_{rec['rule_id']}"):
            ref = handle_action("back_office", [rec["rule_id"]], con, session_id)
            st.success(f"Logged · {ref}")
        if st.button("💬 Slack alert", key=f"sl_{rec['rule_id']}"):
            ref = handle_action("slack_alert", [rec["rule_id"]], con, session_id)
            st.success(f"Logged · {ref}")
    with b2:
        if st.button("👁 For review", key=f"rv_{rec['rule_id']}"):
            ref = handle_action("review", [rec["rule_id"]], con, session_id)
            st.success(f"Logged · {ref}")
        if st.button("📋 Add to report", key=f"rp_{rec['rule_id']}"):
            ref = handle_action("report", [rec["rule_id"]], con, session_id)
            st.success(f"Logged · {ref}")
```

---

## Step 8 — Footer

Replace metadata caption with a clean footer bar:

```python
dq_pass = meta['metadata'].get('dq_rules_passed', '—') if meta['success'] else '—'
q_count = meta['metadata'].get('quarantine_count_today', 0) if meta['success'] else '—'
rows = meta['metadata'].get('rows_in_gold', '—') if meta['success'] else '—'
last_ts = str(meta['metadata'].get('last_run_timestamp', ''))[:19] if meta['success'] else '—'

st.markdown(f"""
<div style="background:#fff;border-top:1px solid #e8eaed;padding:8px 0;margin-top:16px;
            display:flex;align-items:center;gap:20px;font-size:10px;color:#9aa0a6;flex-wrap:wrap;">
  <span>Last run: {last_ts} UTC</span>
  <span>Rows: {rows}</span>
  <span style="color:#0f9d58;font-weight:500;">DQ: {dq_pass}/12 PASS</span>
  <span>Quarantined: {q_count}</span>
  <span style="margin-left:auto;">Data: Alpha Vantage · FRED</span>
</div>
""", unsafe_allow_html=True)
```

---

## Step 9 — Plotly chart colour palette

Apply consistent colours to all Plotly charts:

```python
CHART_COLORS = {
    "close":    "#1a1a2e",   # dark navy — primary series
    "vwap":     "#EF9F27",   # amber dashed — secondary
    "rsi":      "#7c3aed",   # purple — oscillator
    "ema":      "#378ADD",   # blue solid — EMA
    "sma":      "#EF9F27",   # amber dashed — SMA
    "vol_up":   "#0f9d58",   # green — up days
    "vol_down": "#d93025",   # red — down days
    "grid":     "#f1f3f4",   # subtle grid lines
    "zero":     "#e8eaed",   # zero/threshold lines
}

# Apply to all charts via update_layout:
fig.update_layout(
    plot_bgcolor="#ffffff",
    paper_bgcolor="#ffffff",
    font=dict(family="system-ui, -apple-system, sans-serif", size=11, color="#5f6368"),
    margin=dict(t=32, b=24, l=8, r=8),
    legend=dict(orientation="h", y=-0.25, font=dict(size=10)),
    xaxis=dict(gridcolor="#f1f3f4", linecolor="#e8eaed", tickfont=dict(size=10)),
    yaxis=dict(gridcolor="#f1f3f4", linecolor="#e8eaed", tickfont=dict(size=10)),
)

# RSI specific — always force y-axis 0-100
fig_rsi.update_yaxes(range=[0, 100], tickvals=[0, 30, 70, 100])
fig_rsi.add_hline(y=70, line_dash="dash", line_color="#ef4444", line_width=0.8,
                  annotation_text="70", annotation_font_size=9)
fig_rsi.add_hline(y=30, line_dash="dash", line_color="#10b981", line_width=0.8,
                  annotation_text="30", annotation_font_size=9)
```

---

## Run order

```bash
streamlit run dashboard/app.py
```

No pipeline re-run needed — this is all frontend changes.

---

## What NOT to do

- Do not add gradients, shadows, or coloured section backgrounds
- Do not use Streamlit's default `st.success()` green boxes for KPI cards — use custom HTML
- Do not use emoji as the primary visual element in headers — keep them only in buttons
- Do not change VALIDATION_CONFIG thresholds
- Do not batch steps — apply CSS first, confirm, then each component
