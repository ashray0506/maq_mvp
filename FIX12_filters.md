# Fix 12 — Charles River Style Filters
**File: dashboard/app.py — SEE column filters section only.**
**One change at a time. Confirm before moving on.**

---

## Context

Charles River IMS uses: dynamic filtering, drill-down, slice and dice,
period presets, benchmark selectors, and instrument selectors.

Your dashboard already has a lookback slider and dropdowns — correct instinct.
This fix renames them to industry-standard labels and adds period preset
buttons (1M / 3M / 6M / Max) above the slider.

---

## Fix 12.1 — Rename filter labels

Find the three filter inputs in the SEE column expander and update labels:

```python
# BEFORE:
st.selectbox("Ticker", symbols)
st.selectbox("Macro Series", macros)
st.slider("Lookback (days)", ...)

# AFTER:
st.selectbox("Index / instrument", symbols)
st.selectbox("Benchmark series", macros)
# slider label updated in Fix 12.2 below
```

Confirm: dropdowns show "Index / instrument" and "Benchmark series". Then continue.

---

## Fix 12.2 — Add period presets + rename slider

Replace the existing lookback slider with preset buttons + slider combination.
The presets set the slider value. The slider allows fine-tuning.

```python
# Period preset buttons
st.markdown("""
<div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
            letter-spacing:.06em;margin-bottom:6px;margin-top:8px;">
    Analysis period
</div>
""", unsafe_allow_html=True)

# Initialise session state for selected period
if "selected_days" not in st.session_state:
    st.session_state["selected_days"] = 90

# Preset buttons — 1M=21 trading days, 3M=63, 6M=126, Max=all available
p1, p2, p3, p4 = st.columns(4)
max_days = VALIDATION_CONFIG["lookback_days"]

if p1.button("1M", use_container_width=True):
    st.session_state["selected_days"] = min(21, max_days)
if p2.button("3M", use_container_width=True):
    st.session_state["selected_days"] = min(63, max_days)
if p3.button("6M", use_container_width=True):
    st.session_state["selected_days"] = min(126, max_days)
if p4.button("Max", use_container_width=True):
    st.session_state["selected_days"] = max_days

# Fine-tune slider — hidden label, value driven by presets
lookback = st.slider(
    "Fine-tune period",
    min_value=21,
    max_value=max_days,
    value=st.session_state["selected_days"],
    step=7,
    label_visibility="collapsed"
)

# Keep session state in sync with manual slider move
st.session_state["selected_days"] = lookback
```

Then use `lookback` instead of `date_range` everywhere the chart data is filtered:

```python
df = df_full[df_full["symbol"] == selected_symbol].head(lookback)
```

Confirm: 1M / 3M / 6M / Max buttons appear above slider. Clicking a preset
updates the slider and refilters charts. Then continue.

---

## Fix 12.3 — Style the preset buttons

The default Streamlit button style is too prominent for filter controls.
Add this to the global CSS block (Fix 9 Step 1) to make preset buttons
look like compact toggle chips:

```python
# Add inside the existing st.markdown("""<style>...""") block:
"""
/* Period preset buttons — compact chip style */
div[data-testid="column"] .stButton > button {
    border: 1px solid #e8eaed !important;
    background: #fff !important;
    color: #5f6368 !important;
    font-size: 11px !important;
    padding: 4px 0 !important;
    border-radius: 4px !important;
    font-weight: 400 !important;
}
div[data-testid="column"] .stButton > button:hover {
    background: #f1f3f4 !important;
    border-color: #9aa0a6 !important;
    color: #1a1a2e !important;
}
"""
```

Confirm: preset buttons look like compact labeled chips, not full-width
primary buttons.

---

## Fix 12.4 — Filter bar label

Add a section label above the whole filters expander consistent with the
rest of the dashboard (same pattern as "MARKET OVERVIEW" and "RISK ANALYTICS"):

```python
# Replace the current expander:
# with st.expander("⚙️ Filters", expanded=True):

# With:
st.markdown("""
<div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
            letter-spacing:.1em;padding:0 0 8px 0;">
    View controls
</div>
""", unsafe_allow_html=True)

with st.expander("Filter & period selection", expanded=True):
    # ... filter content ...
```

"View controls" as the section label matches Charles River's terminology
for the filter/selector area of a dashboard panel.

Confirm: section label "VIEW CONTROLS" appears above the filter expander.

---

## Summary of changes

| Element | Before | After |
|---|---|---|
| Symbol dropdown label | "Ticker" | "Index / instrument" |
| Macro dropdown label | "Macro Series" | "Benchmark series" |
| Slider label | "Lookback (days)" | Hidden — driven by presets |
| Period presets | None | 1M · 3M · 6M · Max |
| Section label | "⚙️ Filters" | "VIEW CONTROLS" |
| Expander title | "⚙️ Filters" | "Filter & period selection" |

---

## Presentation note

When showing the filters, say:

> "Period presets and benchmark selectors — same controls you'd find in
> Charles River IMS or Bloomberg PORT. 1M, 3M, 6M or the full available
> window. The benchmark series selector lets you switch between FEDFUNDS
> and GS10 as the macro reference — same data, different analytical lens."

---

## What NOT to do

- Do not add date pickers — slider is cleaner and avoids timezone issues
- Do not add an asset class filter — we only have one asset class (equity index)
- Do not change VALIDATION_CONFIG lookback_days value
- Do not add filters to the JUDGE or ACT columns — filters belong in SEE only
- Do not batch — 12.1 first, confirm, then 12.2 etc.
