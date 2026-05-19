# PRD Phase 2 — What-if Portfolio Impact Simulator
**Version:** 1.0  
**Phase:** 2  
**Owner:** Analytics Engineering Lead  
**Status:** Draft  
**Builds on:** Phase 1 (v1-pipeline, v2-dashboard, v3-intelligence)  
**Reference:** Charles River IMS What-if Modelling, MSCI Stress Testing

---

## Context

Phase 1 delivered:
- Market data pipeline (Bronze → Silver → Gold)
- See → Judge → Act dashboard with live market signals
- NBA rule engine — 12 rules triggering on current metric values
- AI analyst grounded in current gold_metrics snapshot

**The gap Phase 1 doesn't answer:**

Management can see current conditions and get a recommendation. What they can't do is ask *"what happens to us if conditions change?"*

That's the what-if problem. Charles River calls it **What-if Modelling**. MSCI calls it **Stress Testing**. Both describe the same thing: given a scenario assumption, what is the projected impact on portfolio value and risk metrics — and what should we do about it?

Phase 2 adds this capability to the platform.

---

## What We Are Building

**A What-if Portfolio Impact Simulator** — an interactive tool that:

1. Takes a user-defined scenario (vol shock, drawdown, rate shock)
2. Projects the impact on all four risk KPIs (Sharpe, MDD, Vol, VWAP Efficiency)
3. Translates that into a dollar impact on an illustrative balanced portfolio
4. Re-evaluates NBA rules against projected values
5. Surfaces a forward-looking recommendation
6. Allows the output to be sent — back office, review, Slack, PDF

**Key word throughout: illustrative.** This is decision support, not financial advice. Same disclaimer as Phase 1 NBA.

---

## The Illustrative Portfolio Model

User inputs a notional portfolio value. Platform applies a simple 60/40 split:

| Leg | Allocation | Proxy |
|---|---|---|
| Equity | 60% | SPY (already in gold_metrics) |
| Fixed income | 40% | GS10 duration approximation (already in gold_metrics) |

**Why 60/40?**
- Standard balanced portfolio benchmark used across institutional platforms
- Charles River uses it as default stress test base
- Simple enough to be fully transparent — no black box
- Both components already in our data pipeline

**Why "illustrative"?**
- We don't have actual portfolio holdings — we're using index proxies
- Platform is for market benchmarking, not portfolio management
- Keeps it compliant — no regulated financial advice

User can adjust the notional value. The 60/40 split is fixed and labelled clearly as illustrative.

---

## Three Scenario Types

Each scenario maps directly to metrics already computed in gold_metrics.
No new data sources required.

---

### Scenario 1 — Volatility Shock

**Question:** If market volatility rises, what happens to risk-adjusted returns and portfolio value?

**User input:** Target volatility level (slider: current vol to 40%)

**Computation:**

```python
def scenario_vol_shock(current_metrics, target_vol_pct, notional):
    """
    Projects impact of volatility shock on Sharpe and equity leg value.
    
    Assumptions:
    - Expected return held constant (conservative — vol shock without return change)
    - Sharpe denominator (volatility) increases proportionally
    - Equity leg value impact estimated via vol-return relationship:
      implied_drawdown = (target_vol / current_vol - 1) * current_mdd * sensitivity_factor
    - sensitivity_factor = 0.6 (empirical — vol doubling implies ~60% of MDD increase)
    - Bond leg: short duration approximation, minor vol impact
    """
    current_vol = current_metrics['volatility_20d'] / 100
    current_sharpe = current_metrics['sharpe_20d']
    current_mdd = current_metrics['max_drawdown_90d']
    
    target_vol = target_vol_pct / 100
    vol_ratio = target_vol / current_vol
    
    # Projected Sharpe — denominator increases
    projected_sharpe = current_sharpe / vol_ratio if vol_ratio > 0 else 0
    
    # Projected MDD — vol shock implies drawdown risk increases
    projected_mdd = current_mdd * vol_ratio * 0.6
    projected_mdd = max(projected_mdd, -50)  # cap at -50%
    
    # Dollar impact
    equity_leg = notional * 0.60
    bond_leg = notional * 0.40
    equity_impact = equity_leg * (projected_mdd / 100 - current_mdd / 100)
    bond_impact = 0  # vol shock — minimal direct bond impact
    total_impact = equity_impact + bond_impact
    
    return {
        "scenario": "Volatility Shock",
        "input_label": f"Vol rises to {target_vol_pct:.1f}%",
        "current": {
            "sharpe": current_sharpe,
            "mdd": current_mdd,
            "vol": current_metrics['volatility_20d'],
        },
        "projected": {
            "sharpe": round(projected_sharpe, 2),
            "mdd": round(projected_mdd, 1),
            "vol": target_vol_pct,
        },
        "dollar_impact": {
            "equity_leg": round(equity_impact, 0),
            "bond_leg": round(bond_impact, 0),
            "total": round(total_impact, 0),
            "equity_allocation": equity_leg,
            "bond_allocation": bond_leg,
            "notional": notional,
        },
        "assumption": (
            "Illustrative only. Assumes constant expected return, "
            "proportional Sharpe compression, and vol-MDD sensitivity of 0.6. "
            "Not financial advice."
        )
    }
```

**Output displayed:**
```
Volatility Shock: 10.7% → 25.0%
─────────────────────────────────────────────────────────
                    Current         Projected       Change
Sharpe Ratio        0.87            0.37            ▼ -57%
Max Drawdown        -4.1%           -9.8%           ▼ worse
Volatility          10.7%           25.0%           ← scenario
─────────────────────────────────────────────────────────
Illustrative portfolio impact ($1,000,000 · 60/40)
  Equity leg ($600,000)             -$33,600
  Bond leg ($400,000)               —
  Total illustrative impact         -$33,600
─────────────────────────────────────────────────────────
NBA signal (projected):  🔴 Sharpe below 0.5 — review risk exposure
```

---

### Scenario 2 — Market Drawdown

**Question:** If the index falls by X%, what is the direct portfolio impact and does it breach risk thresholds?

**User input:** Drawdown percentage (slider: -5% to -30%)

**Computation:**

```python
def scenario_market_drawdown(current_metrics, drawdown_pct, notional):
    """
    Projects direct price impact on equity leg and MDD threshold breach.
    
    Assumptions:
    - Equity leg moves 1:1 with index (beta = 1, SPY as proxy)
    - Bond leg: flight-to-quality — modest positive offset (+0.3 * drawdown magnitude)
    - MDD updates to max of current MDD and scenario drawdown
    - Sharpe: return falls, vol rises (assumes vol-return relationship)
    """
    equity_leg = notional * 0.60
    bond_leg = notional * 0.40
    
    equity_impact = equity_leg * (drawdown_pct / 100)
    bond_offset = bond_leg * abs(drawdown_pct / 100) * 0.3  # flight to quality
    total_impact = equity_impact + bond_offset
    
    projected_mdd = min(current_metrics['max_drawdown_90d'], drawdown_pct)
    
    # Sharpe impact: return falls proportionally, vol rises by half the drawdown
    implied_vol_increase = abs(drawdown_pct) * 0.5
    projected_vol = current_metrics['volatility_20d'] + implied_vol_increase
    return_impact = drawdown_pct / 20  # rough annualisation
    projected_sharpe = current_metrics['sharpe_20d'] + return_impact

    return {
        "scenario": "Market Drawdown",
        "input_label": f"Index falls {abs(drawdown_pct):.0f}%",
        "current": {
            "sharpe": current_metrics['sharpe_20d'],
            "mdd": current_metrics['max_drawdown_90d'],
            "vol": current_metrics['volatility_20d'],
        },
        "projected": {
            "sharpe": round(projected_sharpe, 2),
            "mdd": round(projected_mdd, 1),
            "vol": round(projected_vol, 1),
        },
        "dollar_impact": {
            "equity_leg": round(equity_impact, 0),
            "bond_leg": round(bond_offset, 0),
            "total": round(total_impact, 0),
            "equity_allocation": equity_leg,
            "bond_allocation": bond_leg,
            "notional": notional,
        },
        "mdd_breach": projected_mdd < -20,
        "assumption": (
            "Illustrative only. Assumes beta=1 equity, flight-to-quality bond offset of 0.3x. "
            "Not financial advice."
        )
    }
```

---

### Scenario 3 — Rate Shock

**Question:** If the Fed Funds Rate rises by X basis points, what happens to the yield spread, bond leg, and Sharpe risk-free rate?

**User input:** Rate change in basis points (slider: +25bps to +200bps)

**Computation:**

```python
def scenario_rate_shock(current_metrics, rate_change_bps, notional):
    """
    Projects impact of Fed Funds rate rise on yield spread, bond leg, and Sharpe.
    
    Assumptions:
    - Bond duration approximation: modified duration = 7 years (10Y Treasury proxy)
    - Bond price impact = -duration × rate_change (in decimal)
    - Yield spread narrows by the full rate change (assumes GS10 stays constant)
    - Sharpe risk-free rate rises → excess return falls → Sharpe compresses
    - Equity leg: modest negative (higher rates = lower equity valuations, -0.5x rate change)
    """
    rate_change_decimal = rate_change_bps / 10000
    bond_duration = 7  # approximate modified duration for 10Y proxy
    
    equity_leg = notional * 0.60
    bond_leg = notional * 0.40
    
    # Bond leg: price falls as rates rise
    bond_impact = bond_leg * (-bond_duration * rate_change_decimal)
    
    # Equity leg: higher rates compress valuations
    equity_impact = equity_leg * (-rate_change_decimal * 0.5)
    
    total_impact = equity_impact + bond_impact
    
    # Yield spread: narrows (Fed Funds rises, GS10 assumed constant)
    projected_spread = (
        current_metrics.get('yield_spread', 0.57) - rate_change_bps / 100
    )
    
    # Sharpe: higher risk-free rate → lower excess return → lower Sharpe
    new_rf_daily = (current_metrics['macro_value'] + rate_change_bps / 100) / 252
    sharpe_compression = rate_change_decimal * 2  # rough factor
    projected_sharpe = current_metrics['sharpe_20d'] - sharpe_compression

    return {
        "scenario": "Rate Shock",
        "input_label": f"Fed Funds +{rate_change_bps}bps",
        "current": {
            "sharpe": current_metrics['sharpe_20d'],
            "yield_spread": current_metrics.get('yield_spread', 0.57),
            "fed_funds": current_metrics['macro_value'],
        },
        "projected": {
            "sharpe": round(projected_sharpe, 2),
            "yield_spread": round(projected_spread, 2),
            "fed_funds": round(
                current_metrics['macro_value'] + rate_change_bps / 100, 2
            ),
        },
        "dollar_impact": {
            "equity_leg": round(equity_impact, 0),
            "bond_leg": round(bond_impact, 0),
            "total": round(total_impact, 0),
            "equity_allocation": equity_leg,
            "bond_allocation": bond_leg,
            "notional": notional,
        },
        "inversion": projected_spread < 0,
        "assumption": (
            "Illustrative only. Assumes modified duration of 7 years (10Y proxy), "
            "GS10 constant, equity valuation compression of 0.5x rate change. "
            "Not financial advice."
        )
    }
```

---

## NBA Integration — Forward-looking Rules

After computing a scenario, re-evaluate NBA rules against **projected** values.
Same rule engine, different input values.

```python
def evaluate_nba_on_projected(projected_metrics, con):
    """
    Re-run NBA rule evaluation on projected metric values from what-if scenario.
    Returns same structure as evaluate_nba_rules() — compatible with existing
    NBA display and action components.
    Labels all recommendations as PROJECTED to distinguish from current.
    """
    # Uses same evaluate_nba_rules() function
    # Pass projected_metrics dict instead of latest gold row
    recommendations = evaluate_nba_rules_dict(projected_metrics, con)
    
    # Tag as projected
    for rec in recommendations:
        rec['rule_name'] = f"[PROJECTED] {rec['rule_name']}"
    
    return recommendations
```

**New NBA rule for yield curve inversion** (add to evaluate_nba_rules):

```python
{
    "rule_id": "YIELD_INVERSION",
    "rule_name": "Yield curve inverted",
    "condition": latest.get("yield_spread", 1) < 0,
    "metric_value": round(latest.get("yield_spread", 0), 2),
    "metric_label": "Yield spread (GS10 - FEDFUNDS)",
    "nba_category": "Macro Warning — Inversion historically precedes recession",
    "severity": "HIGH",
},
{
    "rule_id": "YIELD_COMPRESSING",
    "rule_name": "Yield spread compressing",
    "condition": 0 <= latest.get("yield_spread", 1) < 0.3,
    "metric_value": round(latest.get("yield_spread", 0), 2),
    "metric_label": "Yield spread (GS10 - FEDFUNDS)",
    "nba_category": "Macro Caution — Spread narrowing toward inversion",
    "severity": "MEDIUM",
},
```

---

## Dashboard — What-if Tab

Add as a fourth tab alongside Market Intelligence · Governance · Observability:

```
tab_market, tab_governance, tab_obs, tab_whatif = st.tabs([
    "Market Analytics",
    "Governance", 
    "Observability",
    "What-if"
])
```

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│  WHAT-IF SCENARIO ANALYSIS                                   │
│  Illustrative portfolio impact · 60/40 balanced allocation  │
├──────────────────┬──────────────────────────────────────────┤
│  SCENARIO        │  RESULTS                                  │
│                  │                                           │
│  Portfolio value │  Current → Projected KPIs                │
│  $1,000,000      │  ┌──────┬──────┬──────┬──────┐          │
│                  │  │Sharpe│ MDD  │ Vol  │Spread│          │
│  Scenario type:  │  │ 0.87 │-4.1% │10.7% │+0.57%│ current  │
│  ○ Vol shock     │  │ 0.37 │-9.8% │25.0% │+0.57%│ projected│
│  ○ Drawdown      │  └──────┴──────┴──────┴──────┘          │
│  ○ Rate shock    │                                           │
│                  │  DOLLAR IMPACT ($1M · 60/40)             │
│  [Scenario       │  Equity leg ($600K)      -$33,600        │
│   parameters]    │  Bond leg ($400K)             —          │
│                  │  Total illustrative      -$33,600 ▼      │
│  [Run scenario]  │                                           │
│                  │  PROJECTED NBA SIGNAL                     │
│                  │  🔴 Sharpe below 0.5 — review exposure   │
│                  │                                           │
│                  │  [Send to back office] [PDF export]       │
├──────────────────┴──────────────────────────────────────────┤
│  ⚠ Illustrative only. 60/40 proxy. Not financial advice.    │
└─────────────────────────────────────────────────────────────┘
```

### UI components

```python
with tab_whatif:
    st.markdown("""
    <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
                letter-spacing:.1em;padding:12px 0 4px 0;">
        What-if scenario analysis
    </div>
    <div style="font-size:12px;color:#5f6368;margin-bottom:16px;">
        Illustrative portfolio impact · 60/40 balanced allocation proxy ·
        Not financial advice
    </div>
    """, unsafe_allow_html=True)

    col_input, col_output = st.columns([1, 1.6])

    with col_input:
        # Portfolio value
        notional = st.number_input(
            "Illustrative portfolio value ($)",
            min_value=100_000,
            max_value=100_000_000,
            value=1_000_000,
            step=100_000,
            format="%d"
        )

        # Scenario selector
        scenario_type = st.radio(
            "Scenario type",
            ["Volatility shock", "Market drawdown", "Rate shock"],
            label_visibility="visible"
        )

        # Scenario parameters
        if scenario_type == "Volatility shock":
            current_vol = latest.get('volatility_20d', 15)
            target_vol = st.slider(
                "Target volatility (%)",
                min_value=float(current_vol),
                max_value=40.0,
                value=float(min(current_vol * 2, 40)),
                step=0.5,
                format="%.1f%%"
            )
            st.caption(f"Current: {current_vol:.1f}%")

        elif scenario_type == "Market drawdown":
            drawdown = st.slider(
                "Index decline (%)",
                min_value=-30,
                max_value=-5,
                value=-15,
                step=1,
                format="%d%%"
            )

        else:  # Rate shock
            rate_change = st.slider(
                "Rate increase (bps)",
                min_value=25,
                max_value=200,
                value=100,
                step=25,
                format="%dbps"
            )

        run_btn = st.button(
            "Run scenario",
            use_container_width=True,
            type="primary"
        )

    with col_output:
        if run_btn or "whatif_result" in st.session_state:

            # Compute scenario
            if run_btn:
                current_metrics = latest.to_dict()
                if scenario_type == "Volatility shock":
                    result = scenario_vol_shock(
                        current_metrics, target_vol, notional
                    )
                elif scenario_type == "Market drawdown":
                    result = scenario_market_drawdown(
                        current_metrics, drawdown, notional
                    )
                else:
                    result = scenario_rate_shock(
                        current_metrics, rate_change, notional
                    )
                st.session_state["whatif_result"] = result
            else:
                result = st.session_state["whatif_result"]

            # Current vs projected KPI table
            curr = result["current"]
            proj = result["projected"]

            st.markdown(f"""
            <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
                        letter-spacing:.06em;margin-bottom:8px;">
                {result['input_label']} — projected impact
            </div>
            """, unsafe_allow_html=True)

            # KPI comparison grid
            kpi_cols = st.columns(len(curr))
            for i, (key, curr_val) in enumerate(curr.items()):
                proj_val = proj.get(key)
                if proj_val is None:
                    continue
                label = {
                    "sharpe": "Sharpe",
                    "mdd": "Max DD",
                    "vol": "Volatility",
                    "yield_spread": "Yield spread",
                    "fed_funds": "Fed Funds",
                }.get(key, key)

                change = proj_val - curr_val if isinstance(proj_val, (int, float)) else 0
                worse = (
                    (key == "sharpe" and change < 0) or
                    (key == "mdd" and change < 0) or
                    (key == "vol" and change > 0)
                )
                arrow = "▼" if worse else "▲" if change > 0 else "→"
                color = "#d93025" if worse else "#0f9d58"

                kpi_cols[i].markdown(f"""
                <div style="border:1px solid #e8eaed;border-radius:6px;
                            padding:10px;text-align:center;">
                    <div style="font-size:10px;color:#9aa0a6;margin-bottom:4px;">
                        {label}
                    </div>
                    <div style="font-size:12px;color:#9aa0a6;">{curr_val}</div>
                    <div style="font-size:16px;font-weight:500;color:{color};">
                        {proj_val} {arrow}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            # Dollar impact
            di = result["dollar_impact"]
            total = di["total"]
            total_color = "#d93025" if total < 0 else "#0f9d58"
            total_sign = "" if total >= 0 else ""

            st.markdown(f"""
            <div style="border:1px solid #e8eaed;border-radius:6px;
                        padding:12px;margin-top:12px;background:#f8f9fa;">
                <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
                            letter-spacing:.06em;margin-bottom:8px;">
                    Illustrative portfolio impact
                    (${di['notional']:,.0f} · 60/40)
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;
                            gap:4px;font-size:12px;">
                    <div style="color:#5f6368;">
                        Equity leg (${di['equity_allocation']:,.0f})
                    </div>
                    <div style="color:{total_color};text-align:right;font-weight:500;">
                        ${di['equity_leg']:+,.0f}
                    </div>
                    <div style="color:#5f6368;">
                        Bond leg (${di['bond_allocation']:,.0f})
                    </div>
                    <div style="color:#5f6368;text-align:right;">
                        ${di['bond_leg']:+,.0f}
                    </div>
                    <div style="color:#1a1a2e;font-weight:500;
                                border-top:1px solid #e8eaed;padding-top:6px;">
                        Total illustrative impact
                    </div>
                    <div style="color:{total_color};font-weight:700;font-size:16px;
                                text-align:right;border-top:1px solid #e8eaed;
                                padding-top:6px;">
                        ${total:+,.0f}
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Projected NBA signal
            st.markdown("""
            <div style="font-size:10px;color:#9aa0a6;text-transform:uppercase;
                        letter-spacing:.06em;margin-top:12px;margin-bottom:6px;">
                Projected NBA signal
            </div>
            """, unsafe_allow_html=True)

            proj_recs = evaluate_nba_on_projected(proj, con)
            for rec in proj_recs[:3]:  # top 3 only
                icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(
                    rec["severity"], "⚪"
                )
                st.markdown(
                    f"{icon} **{rec['rule_name']}** — {rec['nba_category']}"
                )

            # Action buttons
            st.divider()
            a1, a2 = st.columns(2)
            with a1:
                if st.button("📨 Send to back office",
                             key="wi_backoffice", use_container_width=True):
                    ref = handle_action(
                        "whatif_back_office",
                        [r["rule_id"] for r in proj_recs],
                        con, session_id
                    )
                    st.success(f"Logged · {ref}")
            with a2:
                if st.button("📄 Export scenario PDF",
                             key="wi_pdf", use_container_width=True):
                    pdf = generate_whatif_pdf(result, proj_recs)
                    st.download_button(
                        "⬇ Download",
                        data=pdf,
                        file_name=f"whatif_{datetime.today().date()}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )

            # Assumption disclaimer
            st.markdown(f"""
            <div style="font-size:10px;color:#9aa0a6;margin-top:10px;
                        padding:8px;border:1px solid #e8eaed;border-radius:4px;">
                ⚠ {result['assumption']}
            </div>
            """, unsafe_allow_html=True)

        else:
            st.markdown("""
            <div style="color:#9aa0a6;font-size:13px;padding:40px;text-align:center;">
                Select a scenario and click Run scenario to see projected impact.
            </div>
            """, unsafe_allow_html=True)
```

---

## PDF Export — What-if Report

```python
def generate_whatif_pdf(result, projected_recs):
    """Generate a what-if scenario PDF report."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Market Analytics Platform", styles["Title"]))
    story.append(Paragraph(
        f"What-if Scenario Report · {datetime.today().strftime('%Y-%m-%d %H:%M')}",
        styles["Normal"]
    ))
    story.append(Spacer(1, 12))

    # Scenario summary
    story.append(Paragraph("Scenario", styles["Heading2"]))
    story.append(Paragraph(result["input_label"], styles["Normal"]))
    story.append(Spacer(1, 8))

    # Current vs projected
    story.append(Paragraph("Current vs Projected KPIs", styles["Heading2"]))
    kpi_rows = [["Metric", "Current", "Projected", "Change"]]
    for key in result["current"]:
        curr_val = result["current"][key]
        proj_val = result["projected"].get(key, "—")
        change = (
            f"{proj_val - curr_val:+.2f}"
            if isinstance(proj_val, (int, float)) and isinstance(curr_val, (int, float))
            else "—"
        )
        kpi_rows.append([key, str(curr_val), str(proj_val), change])
    
    t = Table(kpi_rows, colWidths=[120, 100, 100, 80])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))

    # Dollar impact
    di = result["dollar_impact"]
    story.append(Paragraph("Illustrative Portfolio Impact", styles["Heading2"]))
    impact_rows = [
        ["Component", "Allocation", "Impact"],
        ["Equity leg", f"${di['equity_allocation']:,.0f}", f"${di['equity_leg']:+,.0f}"],
        ["Bond leg", f"${di['bond_allocation']:,.0f}", f"${di['bond_leg']:+,.0f}"],
        ["Total", f"${di['notional']:,.0f}", f"${di['total']:+,.0f}"],
    ]
    it = Table(impact_rows, colWidths=[150, 120, 120])
    it.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(it)
    story.append(Spacer(1, 12))

    # Projected NBA
    story.append(Paragraph("Projected NBA Signals", styles["Heading2"]))
    for rec in projected_recs[:3]:
        story.append(Paragraph(
            f"• {rec['rule_name']} — {rec['nba_category']}",
            styles["Normal"]
        ))
    story.append(Spacer(1, 12))

    # Disclaimer
    story.append(Paragraph(result["assumption"], styles["Italic"]))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()
```

---

## Audit Trail

Log every what-if scenario run to `audit_nba_actions`:

```python
handle_action(
    action_type="whatif_scenario",
    rule_ids=[result["scenario"]],
    con=con,
    session_id=session_id,
    notes=f"Scenario: {result['input_label']} | "
          f"Notional: ${notional:,.0f} | "
          f"Total impact: ${result['dollar_impact']['total']:+,.0f}"
)
```

---

## Metric Coherency — Full Map

Every metric in the platform is used in at least one NBA rule and at least one what-if scenario.

| Metric | Current NBA rules | What-if scenario | Coherent |
|---|---|---|---|
| VWAP 20d | VWAP_PREMIUM, VWAP_DISCOUNT, VWAP_MOMENTUM, VWAP_REVERSION | Vol shock (VWAP Efficiency impact) | ✅ |
| RSI-14 | RSI_OB, RSI_OS, RSI_AMBER_UP, RSI_AMBER_DOWN | All scenarios (RSI directional context) | ✅ |
| EMA vs SMA | EMA_CROSS_UP, EMA_CROSS_DOWN | Rate shock (macro regime shift) | ✅ |
| Sharpe 20d | SHARPE_NEG, SHARPE_LOW | Vol shock, drawdown, rate shock | ✅ |
| MDD 90d | MDD_CRITICAL, MDD_ELEVATED | Drawdown scenario (direct) | ✅ |
| Volatility 20d | VOL_CRISIS, VOL_ELEVATED | Vol shock (direct input) | ✅ |
| VWAP Efficiency | VWAP_MOMENTUM, VWAP_REVERSION | Vol shock (derived) | ✅ |
| Yield spread | YIELD_INVERSION (new), YIELD_COMPRESSING (new) | Rate shock (direct output) | ✅ |

**Gap closed in Phase 2:** Yield spread now has two NBA rules (YIELD_INVERSION, YIELD_COMPRESSING) and is the primary output of the rate shock scenario. Full coherency across all metrics.

---

## Acceptance Criteria

- [ ] Three scenario functions implemented and tested against known inputs
- [ ] 60/40 split clearly labelled as illustrative throughout
- [ ] Disclaimer visible on every scenario result
- [ ] NBA rules re-evaluated against projected values
- [ ] YIELD_INVERSION and YIELD_COMPRESSING rules added to evaluate_nba_rules()
- [ ] Dollar impact displayed with equity/bond split
- [ ] Action buttons log to audit_nba_actions with scenario context
- [ ] PDF export includes scenario, KPI table, dollar impact, projected NBA, disclaimer
- [ ] All scenario runs logged to audit trail
- [ ] validate.py still exits 0

---

## Claude Code Instructions

> *"Read PRD_PHASE2_whatif.md. Implement in this order:*
> *1. Add YIELD_INVERSION and YIELD_COMPRESSING rules to evaluate_nba_rules() in app.py*
> *2. Add evaluate_nba_on_projected() function*
> *3. Implement scenario_vol_shock(), scenario_market_drawdown(), scenario_rate_shock() — in a new file: dashboard/scenarios.py*
> *4. Add What-if tab to app.py — tab layout first, confirm it renders*
> *5. Build the two-column layout inside the tab*
> *6. Wire scenario functions to UI*
> *7. Add generate_whatif_pdf() to app.py*
> *8. Run validate.py — must exit 0*
>
> *Do not batch. One step at a time. The word 'illustrative' must appear in every scenario output and in the PDF. Do not remove the disclaimer.*"

---

## Presentation Line

> *"Phase 2 adds what-if modelling — the same capability Charles River calls scenario analysis. You pick a scenario: volatility shock, market drawdown, or rate shock. The platform projects the impact on all four risk KPIs and translates it into a dollar impact on an illustrative 60/40 balanced portfolio. If those projected conditions breach a threshold, the NBA engine fires on the projected values — not just current values. So you're not just seeing what is happening. You're seeing what might happen and what you should do about it before it does.*
>
> *The key word throughout is illustrative — we're using index proxies, not actual holdings. Same framing Charles River uses for their what-if sandbox."*
