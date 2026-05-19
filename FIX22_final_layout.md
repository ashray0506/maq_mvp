# Fix 22 — Final Layout Per Wireframe
**File: dashboard/app.py**
**This is the definitive restructure. Read the full file before starting.**
**Follow the wireframe exactly. One section at a time.**

---

## The layout (reference throughout)

```
TOPBAR: Market Analytics | Dark toggle | Print
─────────────────────────────────────────────────
HEADER
  Market overview: Close · VWAP · RSI · Fed Funds
  Macro/yield: 10Y · Spread · Vol · MDD
  LLM pulse: amber tile

VIEW CONTROLS (full width)
  Index ▾ | Macro series ▾ | 1M 3M 6M YTD Max [slider]

─────────────────────────────────────────────────
SEE →                JUDGE →           ACT
─────                ──────            ───
Charts               RAG signal bar    Severity summary
Price + VWAP         AI interpretation NBA cards (detail)
Volume               ─── divider ───   Action buttons
RSI                  Triggered signals PDF export
EMA vs SMA           Ask (collapsed)   Action log
─── divider ───      My alerts
Risk analytics       (collapsed)
Sharpe MDD
Vol  VWAP Eff
─────────────────────────────────────────────────
FOOTER
```

---

## Fix 22.1 — Wire filters to KPI tiles (critical bug fix)

This is the root cause of filters not affecting metrics.

Find where `latest` is defined and ensure it comes from the
FILTERED dataframe, not df_full:

```python
# After render_filter_bar() or inline filter returns lookback:
df = df_full[
    df_full["symbol"] == selected_symbol
].sort_values("date").tail(lookback)   # tail = most recent N days

# THIS is the fix — latest must come from df, not df_full
latest = df.dropna(subset=["close"]).iloc[0]
```

Then pass `latest` to EVERY component that reads metric values:
- Header render
- KPI tiles
- NBA rule evaluation
- LLM context builder
- What-if scenario inputs

```python
# Correct pattern throughout:
sharpe = safe_float(latest, "sharpe_20d")
mdd    = safe_float(latest, "max_drawdown_90d")
vol    = safe_float(latest, "volatility_20d")
eff    = safe_float(latest, "vwap_efficiency")

# Wrong pattern (do not use):
sharpe = df_full["sharpe_20d"].dropna().iloc[0]  # ignores filter
```

Where `safe_float` is:
```python
def safe_float(row, col, default=0.0):
    try:
        v = float(row[col])
        return default if v != v else v  # NaN check
    except (TypeError, ValueError, KeyError):
        return default
```

Confirm: move the period slider to 1M (21 days) and verify
the Sharpe tile changes. If it doesn't change — the tile
is still reading from df_full.

---

## Fix 22.2 — SEE column: charts first, Risk Analytics below divider

```python
def render_see_column(df, latest, dark):
    section_header("Market conditions →")

    # --- CHARTS (brief requirements) ---

    # Chart 1: Price + VWAP (rolling average overlay — brief requirement)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["close"],
        name="Close",
        line=dict(color="#1a1a2e" if not dark else "#e8eaed", width=2)
    ))
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["vwap_20d"],
        name="VWAP 20d",
        line=dict(color="#EF9F27", width=1.5, dash="dash")
    ))
    fig.update_layout(**chart_layout(dark, height=180))
    st.plotly_chart(fig, use_container_width=True)

    # Chart 2: Volume
    dfc = df.copy()
    dfc["colour"] = dfc["close"].diff().apply(
        lambda x: "#0f9d58" if (x and x >= 0) else "#d93025"
    )
    fig_vol = go.Figure(go.Bar(
        x=dfc["date"], y=dfc["volume"],
        marker_color=dfc["colour"]
    ))
    fig_vol.update_layout(**chart_layout(dark, height=110))
    st.plotly_chart(fig_vol, use_container_width=True)

    # Chart 3: RSI with RAG thresholds (the signal — brief requirement)
    fig_rsi = go.Figure()
    fig_rsi.add_hline(y=70, line_dash="dash", line_color="#d93025",
                      line_width=0.8, annotation_text="70",
                      annotation_font_size=9)
    fig_rsi.add_hline(y=30, line_dash="dash", line_color="#0f9d58",
                      line_width=0.8, annotation_text="30",
                      annotation_font_size=9)
    fig_rsi.add_trace(go.Scatter(
        x=df["date"], y=df["rsi_14"],
        name="RSI-14", line=dict(color="#7c3aed", width=2)
    ))
    fig_rsi.update_yaxes(range=[0, 100])
    fig_rsi.update_layout(**chart_layout(dark, height=150))
    st.plotly_chart(fig_rsi, use_container_width=True)

    # Chart 4: EMA vs SMA macro overlay (brief requirement)
    macro_df = (
        df[["month", "macro_ema_3m", "macro_sma_3m"]]
        .drop_duplicates("month")
        .sort_values("month")
        .dropna(subset=["macro_ema_3m", "macro_sma_3m"])
    )
    fig_macro = go.Figure()
    fig_macro.add_trace(go.Scatter(
        x=macro_df["month"], y=macro_df["macro_ema_3m"],
        name="EMA 3m", line=dict(color="#378ADD", width=2)
    ))
    fig_macro.add_trace(go.Scatter(
        x=macro_df["month"], y=macro_df["macro_sma_3m"],
        name="SMA 3m", line=dict(color="#EF9F27", width=2, dash="dash")
    ))
    fig_macro.update_layout(**chart_layout(dark, height=150))
    st.plotly_chart(fig_macro, use_container_width=True)
    st.caption(
        "Blue solid = EMA (accelerating rate). "
        "Amber dashed = SMA (lagging rate). "
        "EMA above SMA = tightening macro regime."
    )

    # --- DIVIDER ---
    st.markdown(
        f'<hr style="border:none;border-top:0.5px solid '
        f'{"#2d3142" if dark else "#e8eaed"};margin:14px 0;"/>',
        unsafe_allow_html=True
    )

    # --- RISK ANALYTICS (contextualisation layer) ---
    st.markdown(f"""
    <div style="font-size:10px;color:{"#9aa0a6" if dark else "#9aa0a6"};
                text-transform:uppercase;letter-spacing:.1em;
                margin-bottom:4px;">
        Risk analytics
    </div>
    <div style="font-size:11px;color:{"#9aa0a6" if dark else "#5f6368"};
                margin-bottom:10px;line-height:1.5;">
        How much risk the index is taking to generate these returns —
        contextualises market conditions against performance benchmarks.
    </div>
    """, unsafe_allow_html=True)

    # KPI tiles — computed from filtered df via latest
    sharpe = safe_float(latest, "sharpe_20d")
    mdd    = safe_float(latest, "max_drawdown_90d")
    vol    = safe_float(latest, "volatility_20d")
    eff    = safe_float(latest, "vwap_efficiency")
    spread = safe_float(latest, "yield_spread")

    k1, k2 = st.columns(2)
    kpi_tile(k1, "Sharpe 20d",
        f"{sharpe:.2f}" if sharpe else "—",
        "good" if sharpe > 1 else "warn" if sharpe >= 0 else "bad",
        "risk-adjusted return")
    kpi_tile(k2, "Max drawdown 90d",
        f"{mdd:.1f}%" if mdd else "—",
        "good" if mdd > -10 else "warn" if mdd > -20 else "bad",
        "controlled" if mdd > -10 else "elevated")

    k3, k4 = st.columns(2)
    kpi_tile(k3, "Volatility 20d",
        f"{vol:.1f}%" if vol else "—",
        "good" if vol < 12 else "warn" if vol < 20 else "bad",
        "low regime" if vol < 12 else "elevated" if vol >= 20 else "normal")
    kpi_tile(k4, "VWAP efficiency",
        f"{eff:.1f}" if eff else "—",
        "good" if eff > 97 else "warn" if eff > 94 else "bad",
        "orderly" if eff > 97 else "deviation signal")

    k5, _ = st.columns([1, 1])
    kpi_tile(k5, "Yield spread",
        f"+{spread:.2f}%" if spread > 0 else f"{spread:.2f}%",
        "good" if spread > 0.5 else "warn" if spread >= 0 else "bad",
        "normal curve" if spread > 0.5 else
        "compressing" if spread >= 0 else "inverted — caution")
```

---

## Fix 22.3 — JUDGE column: RAG bar not billboard

```python
def render_judge_column(df, latest, recommendations, context, con, dark):
    section_header("Signal analysis →")

    rsi = safe_float(latest, "rsi_14", 50)
    cfg = VALIDATION_CONFIG

    # Determine signal state
    if rsi > cfg['overbought_threshold']:
        bg, text, label = "#b91c1c", "#ffffff", f"RSI {rsi:.1f} — overbought"
    elif rsi < cfg['oversold_threshold']:
        bg, text, label = "#166534", "#ffffff", f"RSI {rsi:.1f} — oversold"
    elif rsi >= cfg['amber_upper']:
        bg, text, label = "#b45309", "#ffffff", f"RSI {rsi:.1f} — approaching overbought"
    elif rsi <= cfg['amber_lower']:
        bg, text, label = "#b45309", "#ffffff", f"RSI {rsi:.1f} — approaching oversold"
    else:
        bg, text, label = "#e8eaed", "#5f6368", f"RSI {rsi:.1f} — neutral"

    # Compact signal bar (not billboard)
    st.markdown(f"""
    <div style="background:{bg};border-radius:6px;padding:9px 14px;
                margin-bottom:10px;display:flex;align-items:center;
                justify-content:space-between;">
        <span style="font-size:13px;font-weight:500;color:{text};">
            {label}
        </span>
        <span style="font-size:9px;color:{text};opacity:.75;">
            threshold {cfg['overbought_threshold']} / {cfg['oversold_threshold']}
            · Wilder 14d EMA
        </span>
    </div>
    """, unsafe_allow_html=True)

    # AI interpretation
    st.markdown(f"""
    <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
                letter-spacing:.05em;margin-bottom:5px;">
        AI interpretation
    </div>
    """, unsafe_allow_html=True)

    if "auto_explanation" not in st.session_state:
        with st.spinner("Reading conditions..."):
            st.session_state["auto_explanation"] = generate_nba_rationale(
                recommendations, context
            )
    st.info(st.session_state["auto_explanation"])

    regen_col, _ = st.columns([1, 3])
    with regen_col:
        if st.button("↺ Regenerate", key="regen"):
            del st.session_state["auto_explanation"]
            st.rerun()

    # Divider before NBA layer
    st.markdown(
        f'<hr style="border:none;border-top:0.5px solid '
        f'{"#2d3142" if dark else "#e8eaed"};margin:10px 0;"/>',
        unsafe_allow_html=True
    )

    # Triggered signals
    st.markdown(f"""
    <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
                letter-spacing:.05em;margin-bottom:6px;">
        Triggered signals
    </div>
    """, unsafe_allow_html=True)

    if recommendations and recommendations[0]["rule_id"] != "NONE":
        for rec in recommendations:
            dot = {"HIGH":"#ef4444","MEDIUM":"#f59e0b",
                   "LOW":"#10b981","USER":"#378ADD"}.get(rec["severity"],"#9aa0a6")
            user_tag = (
                '<span style="font-size:9px;background:#E6F1FB;color:#0C447C;'
                'border-radius:3px;padding:1px 5px;margin-left:5px;">MY ALERT</span>'
            ) if rec.get("is_user_rule") else ""
            border = "#e8eaed" if not dark else "#2d3142"
            bg_card = "#ffffff" if not dark else "#1a1d27"
            st.markdown(f"""
            <div style="display:flex;align-items:flex-start;gap:8px;
                        padding:7px 10px;border:0.5px solid {border};
                        border-radius:6px;margin-bottom:5px;
                        background:{bg_card};">
                <div style="width:8px;height:8px;border-radius:50%;
                            background:{dot};flex-shrink:0;margin-top:3px;"></div>
                <div>
                    <div style="font-size:11px;font-weight:500;
                                color:{"#1a1a2e" if not dark else "#e8eaed"};">
                        {rec['rule_name']}{user_tag}
                    </div>
                    <div style="font-size:10px;color:#9aa0a6;">
                        {rec['severity']} · {rec['nba_category']}
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="padding:8px 12px;border:0.5px solid #bbf7d0;
                    border-radius:6px;background:#f0fdf4;
                    font-size:12px;color:#166534;">
            All signals within normal range
        </div>
        """, unsafe_allow_html=True)

    # Collapsed tools
    with st.expander("Ask about this data", expanded=False):
        st.caption("Grounded in current snapshot. Not financial advice.")
        examples = [
            "Why is RSI approaching overbought?",
            "What does the yield spread signal?",
            "Has volatility been rising or falling?",
            "What would trigger a red signal?",
        ]
        eq1, eq2 = st.columns(2)
        for i, q in enumerate(examples):
            col = eq1 if i % 2 == 0 else eq2
            if col.button(q, key=f"eq_{i}", use_container_width=True):
                st.session_state["analyst_question"] = q
        question = st.text_input(
            "Question",
            value=st.session_state.get("analyst_question", ""),
            placeholder="Ask about the current market data...",
            label_visibility="collapsed"
        )
        if question:
            with st.spinner("Reading the data..."):
                st.info(call_llm(question, context))

    with st.expander("My alerts", expanded=False):
        # existing custom rule CRUD
        pass
```

---

## Fix 22.4 — Main wiring

```python
# After all function definitions, the main app flow:

con = duckdb.connect("market.duckdb", read_only=False)
create_nba_tables(con)
session_id = str(uuid.uuid4())[:8]

checkpoint = "init"
try:
    checkpoint = "loading data"
    df_full = con.execute(f"""
        SELECT * FROM {VALIDATION_CONFIG['data_source']}
        ORDER BY date DESC
        LIMIT {VALIDATION_CONFIG['lookback_days']}
    """).fetchdf()

    checkpoint = "validating columns"
    missing = [c for c in VALIDATION_CONFIG['required_columns']
               if c not in df_full.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    checkpoint = "applying filters"
    # Render filter bar and get selections
    selected_symbol, selected_macro, lookback = render_filter_bar(
        con, df_full, VALIDATION_CONFIG["lookback_days"]
    )

    # Filter — THIS propagates to all downstream components
    df = df_full[
        df_full["symbol"] == selected_symbol
    ].sort_values("date").tail(lookback)

    # Latest row from FILTERED data — not df_full
    latest = df.dropna(subset=["close"]).iloc[0]

    checkpoint = "building context"
    context = build_market_context(df, latest)
    meta = render_metadata_footer(con)

    checkpoint = "rendering header"
    render_header(latest, meta, dark)
    render_pulse_tile(context)

    checkpoint = "evaluating rules"
    recommendations = evaluate_nba_rules(df, latest, con)

    checkpoint = "rendering columns"
    col_see, col_judge, col_act = st.columns([1.3, 1.2, 1.0])

    with col_see:
        render_see_column(df, latest, dark)

    with col_judge:
        render_judge_column(df, latest, recommendations, context, con, dark)

    with col_act:
        render_act_column(recommendations, meta, df, latest, con, session_id, dark)

    checkpoint = "footer"
    render_footer(meta)

except Exception as e:
    st.error(f"Dashboard failed at: **{checkpoint}**")
    st.exception(e)
    st.stop()
```

---

## What NOT to do

- Do not use `df_full.iloc[0]` for latest — always `df.iloc[0]`
- Do not put Risk Analytics tiles above the three columns
- Do not put filter bar above the three columns as a standalone block
- Do not use a large billboard RAG card — compact bar only
- Do not put charts outside the SEE column — they live inside it
- Do not batch — 22.1 (filter fix) first, confirm tiles respond to slider, then continue
