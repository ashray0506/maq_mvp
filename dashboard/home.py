"""
dashboard/home.py
Landing page for Market Analytics platform.
"""
import streamlit as st


def get_home_pulse(con, kimi_post_fn) -> str:
    if "market_pulse" in st.session_state:
        return st.session_state["market_pulse"]
    try:
        row = con.execute("""
            SELECT close, rsi_14, macro_value, yield_spread, vwap_20d, volatility_20d
            FROM gold_metrics ORDER BY date DESC LIMIT 1
        """).fetchone()
        if not row or not row[0]:
            return "Market data loading — run the pipeline to update."
        close, rsi, funds, spread, vwap, vol = [round(v, 2) if v else 0 for v in row]
        messages = [
            {"role": "system", "content": (
                "You are a senior equity trader. Write ONE sentence — max 25 words — "
                "in trader voice about current market conditions. Be direct. Reference "
                "price, RSI, and one macro signal. No hedging words."
            )},
            {"role": "user", "content": (
                f"Index close: ${close}, RSI-14: {rsi}, VWAP 20d: ${vwap}, "
                f"Fed Funds: {funds}%, Yield spread: +{spread}%, Volatility: {vol}%"
            )},
        ]
        result, err = kimi_post_fn(messages, max_tokens=60)
        if err or not result or len(result) < 15:
            raise ValueError("bad response")
        st.session_state["market_pulse"] = result
        return result
    except Exception:
        try:
            row = con.execute("""
                SELECT close, rsi_14, yield_spread FROM gold_metrics
                ORDER BY date DESC LIMIT 1
            """).fetchone()
            if row and row[0]:
                close, rsi, spread = [round(v, 2) if v else 0 for v in row]
                momentum = ("momentum stretched" if rsi > 65 else
                            "momentum building" if rsi > 55 else "momentum neutral")
                macro = ("yield spread supportive" if spread > 0.3
                         else "spread compressing — watch")
                result = f"SPY at ${close:.0f} — {momentum} with RSI {rsi:.0f}. {macro.capitalize()}."
                st.session_state["market_pulse"] = result
                return result
        except Exception:
            pass
        return "Market data loading — run the pipeline to update."


def render_home(con, dark: bool, kimi_post_fn=None):
    if dark:
        card_bg  = "#1a1d27"; border   = "#2d3142"; text_p = "#e8eaed"
        text_s   = "#9aa0a6"; text_t   = "#5f6368"
        blue_bg  = "#0C447C"; blue_tx  = "#B5D4F4"
        teal_bg  = "#085041"; teal_tx  = "#9FE1CB"
        gray_bg  = "#2C2C2A"; gray_tx  = "#D3D1C7"
    else:
        card_bg  = "#ffffff"; border   = "#e8eaed"; text_p = "#1a1a2e"
        text_s   = "#5f6368"; text_t   = "#9aa0a6"
        blue_bg  = "#E6F1FB"; blue_tx  = "#0C447C"
        teal_bg  = "#E1F5EE"; teal_tx  = "#0F6E56"
        gray_bg  = "#F1EFE8"; gray_tx  = "#5F5E5A"

    # ── live data ──
    try:
        latest = con.execute("""
            SELECT rsi_14 FROM gold_metrics ORDER BY date DESC LIMIT 1
        """).fetchone()
        rsi = round(latest[0], 1) if latest and latest[0] else None
    except Exception:
        rsi = None

    try:
        dq = con.execute("""
            SELECT
                SUM(CASE WHEN status='PASS' THEN 1 ELSE 0 END),
                COUNT(*)
            FROM audit_dq_results
            WHERE run_id = (SELECT MAX(run_id) FROM audit_pipeline_runs)
        """).fetchone()
        dq_pass  = int(dq[0]) if dq and dq[0] else 0
        dq_total = int(dq[1]) if dq and dq[1] else 0
    except Exception:
        dq_pass = dq_total = 0

    try:
        last_run_row = con.execute("""
            SELECT finished_at FROM audit_pipeline_runs
            ORDER BY finished_at DESC LIMIT 1
        """).fetchone()
        last_run = str(last_run_row[0])[:16] if last_run_row and last_run_row[0] else "—"
    except Exception:
        last_run = "—"

    try:
        quarantine = con.execute("""
            SELECT COUNT(*) FROM quarantine_records
            WHERE DATE(quarantine_timestamp) = CURRENT_DATE
        """).fetchone()[0]
    except Exception:
        quarantine = 0

    try:
        last_scenario = con.execute("""
            SELECT action_type FROM audit_nba_actions
            WHERE action_type LIKE 'whatif%'
            ORDER BY action_at DESC LIMIT 1
        """).fetchone()
        scenario_text = last_scenario[0].replace("whatif_", "") if last_scenario else "none run"
    except Exception:
        scenario_text = "none run"

    try:
        sig_row = con.execute("""
            SELECT rules_triggered FROM audit_nba_evaluations
            ORDER BY evaluated_at DESC LIMIT 1
        """).fetchone()
        sig_count = sig_row[0] if sig_row else 0
    except Exception:
        sig_count = 0

    rsi_label = (
        f"RSI {rsi} — overbought" if rsi and rsi > 70 else
        f"RSI {rsi} — approaching overbought" if rsi and rsi >= 60 else
        f"RSI {rsi} — neutral" if rsi else "RSI unavailable"
    )
    dq_ok = dq_pass == dq_total and dq_total > 0

    # ── CSS ──
    st.markdown(f"""
    <style>
    .home-tile {{
        background:{card_bg};border:0.5px solid {border};
        border-radius:12px;padding:18px 20px;
        position:relative;min-height:140px;
    }}
    .home-tile.blue {{ border-left:3px solid #378ADD; }}
    .home-tile.teal {{ border-left:3px solid #1D9E75; }}
    .home-tile.gray {{ border-left:3px solid #888780; }}
    .tile-title {{ font-size:15px;font-weight:500;color:{text_p};margin-bottom:5px; }}
    .tile-desc  {{ font-size:12px;color:{text_s};line-height:1.6;margin-bottom:12px; }}
    .tile-status {{ font-size:11px;color:{text_t};display:flex;align-items:center;gap:6px; }}
    .sdot {{ width:6px;height:6px;border-radius:50%;display:inline-block;flex-shrink:0; }}
    .sdot.g {{ background:#1D9E75; }} .sdot.a {{ background:#EF9F27; }}
    .sdot.r {{ background:#E24B4A; }} .sdot.x {{ background:#888780; }}
    .tile-badge {{ font-size:10px;padding:2px 8px;border-radius:10px;
                   font-weight:500;float:right;margin-top:2px; }}
    .badge-blue {{ background:{blue_bg};color:{blue_tx}; }}
    .badge-teal {{ background:{teal_bg};color:{teal_tx}; }}
    .badge-gray {{ background:{gray_bg};color:{gray_tx}; }}
    .home-section {{ font-size:10px;font-weight:500;color:{text_t};
                     text-transform:uppercase;letter-spacing:.1em;
                     margin-bottom:10px;display:flex;align-items:center;gap:8px; }}
    </style>
    """, unsafe_allow_html=True)

    # ── topbar ──
    st.markdown(f"""
    <div style="background:{card_bg};border-bottom:1px solid {border};
                padding:12px 0;display:flex;align-items:center;
                justify-content:space-between;margin-bottom:20px;">
        <span style="font-size:22px;font-weight:700;color:{text_p};letter-spacing:-0.4px;">
            Market Analytics Platform
        </span>
        <span style="font-size:11px;color:{text_s};">Navigator</span>
    </div>
    """, unsafe_allow_html=True)

    # ── ROW 1: Analytics ──
    st.markdown(f"""
    <div class="home-section">Analytics
        <span class="tile-badge badge-blue" style="float:none">Market intelligence</span>
    </div>""", unsafe_allow_html=True)

    col1, col2 = st.columns(2, gap="medium")
    with col1:
        st.markdown(f"""
        <div class="home-tile blue">
            <span class="tile-badge badge-blue">Live</span>
            <div class="tile-title">Market Analytics</div>
            <div class="tile-desc">90-day trend, RSI signal, macro overlay,
                risk analytics, and AI signal analysis.</div>
            <div class="tile-status">
                <span class="sdot {'g' if rsi and rsi < 70 else 'a'}"></span>
                {sig_count} signal{'s' if sig_count != 1 else ''} active · {rsi_label}
            </div>
        </div>""", unsafe_allow_html=True)
        if st.button("Open Market Analytics →", key="nav_market", use_container_width=True):
            st.session_state["active_page"] = "Market Analytics"
            st.rerun()

    with col2:
        st.markdown(f"""
        <div class="home-tile blue">
            <span class="tile-badge badge-blue">Simulator</span>
            <div class="tile-title">What-if analysis</div>
            <div class="tile-desc">Volatility shocks, drawdown, rate change.
                Illustrative 60/40 portfolio impact with projected NBA signals.</div>
            <div class="tile-status">
                <span class="sdot a"></span>3 scenario types · Last: {scenario_text}
            </div>
        </div>""", unsafe_allow_html=True)
        if st.button("Open What-if →", key="nav_whatif", use_container_width=True):
            st.session_state["active_page"] = "What-if"
            st.rerun()

    st.markdown(f'<hr style="border:none;border-top:0.5px solid {border};margin:20px 0;"/>',
                unsafe_allow_html=True)

    # ── ROW 2: Data Management ──
    st.markdown(f"""
    <div class="home-section">Data management
        <span class="tile-badge badge-teal" style="float:none">Pipeline &amp; governance</span>
    </div>""", unsafe_allow_html=True)

    col3, col4 = st.columns(2, gap="medium")
    with col3:
        st.markdown(f"""
        <div class="home-tile teal">
            <span class="tile-badge badge-teal">Catalogue</span>
            <div class="tile-title">Governance</div>
            <div class="tile-desc">Metric definitions, field catalogue, data lineage,
                and DQ standards. Production: Alation or Collibra.</div>
            <div class="tile-status">
                <span class="sdot g"></span>15 definitions · 7 lineage hops
            </div>
        </div>""", unsafe_allow_html=True)
        if st.button("Open Governance →", key="nav_gov", use_container_width=True):
            st.session_state["active_page"] = "Governance"
            st.rerun()

    with col4:
        dq_dot   = "g" if dq_ok else "r"
        dq_label = f"DQ {dq_pass}/{dq_total} PASS" if dq_total else "No runs yet"
        st.markdown(f"""
        <div class="home-tile teal">
            <span class="tile-badge badge-teal">Pipeline health</span>
            <div class="tile-title">Observability</div>
            <div class="tile-desc">Hop status, DQ outcomes, quarantine log,
                run history, and NBA audit trail.</div>
            <div class="tile-status">
                <span class="sdot {dq_dot}"></span>
                {dq_label} · Quarantined: {quarantine} · Last: {last_run}
            </div>
        </div>""", unsafe_allow_html=True)
        if st.button("Open Observability →", key="nav_obs", use_container_width=True):
            st.session_state["active_page"] = "Observability"
            st.rerun()

    st.markdown(f'<hr style="border:none;border-top:0.5px solid {border};margin:20px 0;"/>',
                unsafe_allow_html=True)

    # ── ROW 3: Documentation ──
    st.markdown(f"""
    <div class="home-section">Documentation
        <span class="tile-badge badge-gray" style="float:none">Reference</span>
    </div>""", unsafe_allow_html=True)

    col5, col6, col7 = st.columns(3, gap="medium")
    with col5:
        st.markdown(f"""
        <div class="home-tile gray">
            <div class="tile-title">Architecture</div>
            <div class="tile-desc">Strategic data architecture. MVP vs production.
                Click any component for detail.</div>
            <div class="tile-status"><span class="sdot x"></span>Interactive diagram</div>
        </div>""", unsafe_allow_html=True)
        if st.button("Open Architecture →", key="nav_arch", use_container_width=True):
            st.session_state["active_page"] = "Architecture"
            st.rerun()

    with col6:
        st.markdown(f"""
        <div class="home-tile gray">
            <div class="tile-title">GitHub</div>
            <div class="tile-desc">Source code, README, Architecture Decision Log, & AI Assisted Delivery Notes</div>
            <div class="tile-status"><span class="sdot x"></span>ashray0506/MAQMVP</div>
        </div>""", unsafe_allow_html=True)
        st.link_button("Open GitHub ↗", "https://github.com/ashray0506/MAQ_MVP",
                       use_container_width=True)

    with col7:
        st.markdown(f"""
        <div class="home-tile gray">
            <div class="tile-title">Runbook</div>
            <div class="tile-desc">Pipeline ops, DQ rules, troubleshooting,
                and handoff guide.</div>
            <div class="tile-status"><span class="sdot x"></span>RUNBOOK.md</div>
        </div>""", unsafe_allow_html=True)
        if st.button("Open Runbook →", key="nav_runbook", use_container_width=True):
            st.session_state["active_page"] = "Runbook"
            st.rerun()

    # ── footer ──
    st.markdown(f"""
    <div style="margin-top:24px;padding-top:12px;border-top:0.5px solid {border};
                font-size:10px;color:{text_t};
                display:flex;justify-content:space-between;">
        <span>Market Analytics ·  Trading Platform · Post-trade operations</span>
        <span>Data: Alpha Vantage · FRED · Built with Claude Code</span>
    </div>
    """, unsafe_allow_html=True)

