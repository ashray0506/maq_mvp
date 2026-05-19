# Fix 23 — Button Sizing: View Controls, Regenerate, Print
**File: dashboard/app.py**
**CSS and layout fixes only. No logic changes.**

---

## Fix 23.1 — Period preset buttons (1M 3M 6M YTD Max)

The buttons are too narrow — text is wrapping vertically.
Two fixes needed: more columns AND render as HTML not st.button.

Replace the current preset button columns with HTML buttons
using st.markdown + JS to update session state:

```python
# Replace the p1,p2,p3,p4,p5 = st.columns(5) preset block with:

if "selected_days" not in st.session_state:
    st.session_state["selected_days"] = 90
max_days = VALIDATION_CONFIG["lookback_days"]

presets = [("1M", 21), ("3M", 63), ("6M", 126), ("YTD", 252), ("Max", max_days)]
active = st.session_state["selected_days"]

# Render as a single inline row — no columns needed
preset_html = '<div style="display:flex;gap:4px;margin-bottom:6px;">'
for label, days in presets:
    days_capped = min(days, max_days)
    is_active = (active == days_capped)
    bg = "#E6F1FB" if is_active else "transparent"
    border = "#378ADD" if is_active else "#e8eaed"
    color = "#0C447C" if is_active else "#5f6368"
    weight = "500" if is_active else "400"
    preset_html += (
        f'<button onclick="setPeriod({days_capped})" '
        f'style="padding:4px 10px;border:0.5px solid {border};'
        f'border-radius:4px;background:{bg};color:{color};'
        f'font-size:11px;font-weight:{weight};cursor:pointer;'
        f'white-space:nowrap;font-family:system-ui,sans-serif;">'
        f'{label}</button>'
    )
preset_html += '</div>'

st.markdown(preset_html, unsafe_allow_html=True)

# Hidden number input to receive JS value
# Use a unique key so it triggers rerun
period_val = st.number_input(
    "period_hidden",
    min_value=21,
    max_value=max_days,
    value=st.session_state["selected_days"],
    step=1,
    label_visibility="collapsed",
    key="period_input"
)
if period_val != st.session_state["selected_days"]:
    st.session_state["selected_days"] = period_val
    st.rerun()
```

Add the JS function to the global CSS block at the top of app.py:

```python
st.markdown("""
<script>
function setPeriod(days) {
    // Find the number input and set its value
    const inputs = window.parent.document.querySelectorAll('input[type="number"]');
    for (const inp of inputs) {
        if (inp.min == 21) {
            inp.value = days;
            inp.dispatchEvent(new Event('input', {bubbles:true}));
            inp.dispatchEvent(new Event('change', {bubbles:true}));
            break;
        }
    }
}
</script>
""", unsafe_allow_html=True)
```

**Simpler alternative** if JS approach causes issues — use a
selectbox instead of buttons:

```python
period_map = {"1 month": 21, "3 months": 63, "6 months": 126,
              "Year to date": 252, "Max available": max_days}
selected_label = st.selectbox(
    "Analysis period",
    list(period_map.keys()),
    index=2,  # default 6 months
    label_visibility="visible"
)
lookback = period_map[selected_label]
st.session_state["selected_days"] = lookback
```

The selectbox is less visual but guaranteed to work and
affect the slider correctly. Use this if the JS approach
doesn't fire reliably.

Then the fine-tune slider:

```python
lookback = st.slider(
    "Fine-tune",
    min_value=21,
    max_value=max_days,
    value=st.session_state["selected_days"],
    step=7,
    label_visibility="collapsed"
)
st.session_state["selected_days"] = lookback
```

---

## Fix 23.2 — View controls layout: tighter row

The Index and Macro series dropdowns are too wide and the
preset area is too narrow. Fix the column proportions:

```python
# Replace current column split with:
f1, f2, f3 = st.columns([0.8, 0.8, 2.4])

with f1:
    # Index dropdown
    ...

with f2:
    # Macro series dropdown
    ...

with f3:
    # Period presets + slider
    ...
```

This gives 25% / 25% / 50% — dropdowns compact, period area wide.

---

## Fix 23.3 — Regenerate button: small, inline

The regenerate button is rendering as a full-width primary button.
It should be a small inline icon button next to the AI label.

```python
# Replace:
regen_col, _ = st.columns([1, 3])
with regen_col:
    if st.button("↺ Regenerate", key="regen"):
        ...

# With — render button inline with the section label:
label_col, btn_col = st.columns([4, 1])
with label_col:
    st.markdown(f"""
    <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
                letter-spacing:.05em;margin-bottom:5px;">
        AI interpretation
    </div>
    """, unsafe_allow_html=True)
with btn_col:
    if st.button("↺", key="regen",
                 help="Regenerate AI interpretation",
                 use_container_width=True):
        if "auto_explanation" in st.session_state:
            del st.session_state["auto_explanation"]
        if "market_pulse" in st.session_state:
            del st.session_state["market_pulse"]
        st.rerun()
```

Also add to global CSS to shrink the button height:

```python
# Inside existing <style> block:
"""
/* Small icon buttons */
button[kind="secondary"] {
    min-height: 28px !important;
    padding: 2px 8px !important;
    font-size: 12px !important;
}
"""
```

---

## Fix 23.4 — Print button: small, right-aligned in topbar

The print button is too large. It should match the dark mode
toggle — same size, same style, right side of topbar.

```python
def render_topbar(title, subtitle="Post-trade operations"):
    col_title, col_btns = st.columns([4, 1])

    with col_title:
        st.markdown(f"""
        <div style="padding:10px 0 8px 0;">
            <span style="font-size:20px;font-weight:500;
                         color:var(--color-text-primary);">
                {title}
            </span>
            <span style="font-size:11px;color:var(--color-text-tertiary);
                         margin-left:12px;">
                {subtitle}
            </span>
        </div>
        """, unsafe_allow_html=True)

    with col_btns:
        # Two small buttons side by side
        b1, b2 = st.columns(2)
        with b1:
            if st.button(
                "Print",
                key="print_btn",
                use_container_width=True,
                help="Print or save as PDF"
            ):
                st.markdown(
                    "<script>window.print();</script>",
                    unsafe_allow_html=True
                )
        with b2:
            dark_label = "Light" if st.session_state.get("dark_mode") else "Dark"
            if st.button(
                dark_label,
                key="dark_toggle",
                use_container_width=True,
                help="Toggle dark mode"
            ):
                st.session_state["dark_mode"] = not st.session_state.get("dark_mode", False)
                st.rerun()
```

Add to global CSS:

```python
"""
/* Topbar buttons — match size */
div[data-testid="stHorizontalBlock"] button {
    min-height: 32px !important;
    font-size: 11px !important;
    padding: 4px 8px !important;
}
"""
```

---

## Fix 23.5 — Global button size normalisation

Add this to the global CSS block to prevent any button from
becoming oversized:

```python
st.markdown(f"""
<style>
/* Normalise all button heights */
.stButton > button {{
    min-height: 32px !important;
    max-height: 40px !important;
    font-size: 11px !important;
    padding: 4px 10px !important;
    border: 0.5px solid var(--color-border-secondary) !important;
    background: var(--color-background-primary) !important;
    color: var(--color-text-secondary) !important;
    border-radius: 4px !important;
    line-height: 1.2 !important;
}}
.stButton > button:hover {{
    background: var(--color-background-secondary) !important;
    border-color: var(--color-border-primary) !important;
    color: var(--color-text-primary) !important;
}}
/* Prevent column buttons from wrapping */
div[data-testid="stHorizontalBlock"] .stButton > button {{
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
}}
</style>
""", unsafe_allow_html=True)
```

---

## Summary

| Issue | Fix |
|---|---|
| Period buttons text wrapping | 23.1 — HTML buttons or selectbox, wider column |
| View controls cramped | 23.2 — 25/25/50 column split |
| Regenerate button too large | 23.3 — inline icon button next to label |
| Print button too large | 23.4 — small topbar button matching dark toggle |
| All buttons inconsistent size | 23.5 — global CSS normalisation |

## Run order

```bash
streamlit run dashboard/app.py
```

## What NOT to do

- Do not use type="primary" on any button except "Run scenario"
  in the what-if tab
- Do not set button width to 100% on icon-only buttons
- Do not put the regenerate button below the AI text block
- Do not batch — 23.5 global CSS first, confirm size normalises,
  then individual fixes
