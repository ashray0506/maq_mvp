"""
What-if scenario functions for Phase 2.
All outputs are illustrative only — not financial advice.
"""
import math


def scenario_vol_shock(current_metrics: dict, target_vol_pct: float, notional: float) -> dict:
    """
    Projects impact of volatility shock on Sharpe and equity leg value.

    Assumptions:
    - Expected return held constant (conservative — vol shock without return change)
    - Sharpe denominator (volatility) increases proportionally
    - Equity leg impact estimated via vol-return relationship:
      implied_drawdown = (target_vol / current_vol - 1) * current_mdd * sensitivity_factor
    - sensitivity_factor = 0.6 (empirical — vol doubling implies ~60% of MDD increase)
    - Bond leg: short duration approximation, minor vol impact
    """
    current_vol    = float(current_metrics.get("volatility_20d") or 15.0)
    current_sharpe = float(current_metrics.get("sharpe_20d") or 0.0)
    current_mdd    = float(current_metrics.get("mdd_90d") or 0.0)

    vol_ratio        = target_vol_pct / current_vol if current_vol > 0 else 1.0
    projected_sharpe = round(current_sharpe / vol_ratio, 2) if vol_ratio > 0 else 0.0
    projected_mdd    = round(max(current_mdd * vol_ratio * 0.7, -50.0), 1)

    equity_leg    = notional * 0.60
    holding_days  = 20  # 1-month horizon

    current_exp_loss   = equity_leg * (current_vol / 100) * math.sqrt(holding_days / 252)
    projected_exp_loss = equity_leg * (target_vol_pct / 100) * math.sqrt(holding_days / 252)
    equity_impact      = -(projected_exp_loss - current_exp_loss)
    bond_impact        = 0.0
    total_impact       = equity_impact

    return {
        "scenario":    "Volatility Shock",
        "input_label": f"Vol rises to {target_vol_pct:.1f}%",
        "current": {
            "sharpe": round(current_sharpe, 2),
            "mdd":    round(current_mdd, 1),
            "vol":    round(current_vol, 1),
        },
        "projected": {
            "sharpe": projected_sharpe,
            "mdd":    projected_mdd,
            "vol":    round(target_vol_pct, 1),
        },
        "dollar_impact": {
            "equity_leg":        round(equity_impact, 0),
            "bond_leg":          round(bond_impact, 0),
            "total":             round(total_impact, 0),
            "equity_allocation": equity_leg,
            "bond_allocation":   notional * 0.40,
            "notional":          notional,
            "method": (
                f"Expected loss = equity × annual vol × √(20/252). "
                f"Current expected loss: ${current_exp_loss:,.0f} → "
                f"Projected: ${projected_exp_loss:,.0f}"
            ),
        },
        "assumption": (
            "Illustrative. 20-day horizon. 60/40 allocation proxy. "
            "Not financial advice."
        ),
    }


def scenario_market_drawdown(current_metrics: dict, drawdown_pct: float, notional: float) -> dict:
    """
    Projects direct price impact on equity leg and MDD threshold breach.

    Assumptions:
    - Equity leg moves 1:1 with index (beta = 1, SPY as proxy)
    - Bond leg: flight-to-quality — modest positive offset (+0.3 * drawdown magnitude)
    - MDD updates to max of current MDD and scenario drawdown
    - Sharpe: return falls, vol rises (assumes vol-return relationship)
    """
    current_sharpe = current_metrics.get("sharpe_20d") or 0.0
    current_mdd    = current_metrics.get("mdd_90d") or 0.0
    current_vol    = current_metrics.get("volatility_20d") or 15.0

    equity_leg  = notional * 0.60
    bond_leg    = notional * 0.40

    equity_impact = equity_leg * (drawdown_pct / 100)
    bond_offset   = bond_leg * abs(drawdown_pct / 100) * 0.3
    total_impact  = equity_impact + bond_offset

    projected_mdd        = min(float(current_mdd), drawdown_pct)
    implied_vol_increase = abs(drawdown_pct) * 0.5
    projected_vol        = float(current_vol) + implied_vol_increase
    return_impact        = drawdown_pct / 20.0
    projected_sharpe     = float(current_sharpe) + return_impact

    return {
        "scenario":    "Market Drawdown",
        "input_label": f"Index falls {abs(drawdown_pct):.0f}%",
        "current": {
            "sharpe": round(float(current_sharpe), 2),
            "mdd":    round(float(current_mdd), 1),
            "vol":    round(float(current_vol), 1),
        },
        "projected": {
            "sharpe": round(projected_sharpe, 2),
            "mdd":    round(projected_mdd, 1),
            "vol":    round(projected_vol, 1),
        },
        "dollar_impact": {
            "equity_leg":       round(equity_impact, 0),
            "bond_leg":         round(bond_offset, 0),
            "total":            round(total_impact, 0),
            "equity_allocation": equity_leg,
            "bond_allocation":   bond_leg,
            "notional":          notional,
        },
        "mdd_breach": projected_mdd < -20,
        "assumption": (
            "Illustrative only. Assumes beta=1 equity, "
            "flight-to-quality bond offset of 0.3x. Not financial advice."
        ),
    }


def scenario_rate_shock(current_metrics: dict, rate_change_bps: float, notional: float) -> dict:
    """
    Projects impact of Fed Funds rate rise on yield spread, bond leg, and Sharpe.

    Assumptions:
    - Bond duration approximation: modified duration = 7 years (10Y Treasury proxy)
    - Bond price impact = -duration × rate_change (in decimal)
    - Yield spread narrows by the full rate change (assumes GS10 stays constant)
    - Sharpe risk-free rate rises → excess return falls → Sharpe compresses
    - Equity leg: modest negative (higher rates = lower equity valuations, -0.5x rate change)
    """
    current_sharpe  = current_metrics.get("sharpe_20d") or 0.0
    current_spread  = current_metrics.get("yield_spread") or 0.57
    current_macro   = current_metrics.get("macro_value") or 3.64
    bond_duration   = 7.0

    rate_change_decimal = rate_change_bps / 10_000

    equity_leg = notional * 0.60
    bond_leg   = notional * 0.40

    bond_impact   = bond_leg * (-bond_duration * rate_change_decimal)
    equity_impact = equity_leg * (-rate_change_decimal * 0.5)
    total_impact  = equity_impact + bond_impact

    projected_spread = float(current_spread) - rate_change_bps / 100
    sharpe_compression = rate_change_decimal * 2.0
    projected_sharpe   = float(current_sharpe) - sharpe_compression
    projected_fed_funds = round(float(current_macro) + rate_change_bps / 100, 2)

    return {
        "scenario":    "Rate Shock",
        "input_label": f"Fed Funds +{rate_change_bps:.0f}bps",
        "current": {
            "sharpe":       round(float(current_sharpe), 2),
            "yield_spread": round(float(current_spread), 2),
            "fed_funds":    round(float(current_macro), 2),
        },
        "projected": {
            "sharpe":       round(projected_sharpe, 2),
            "yield_spread": round(projected_spread, 2),
            "fed_funds":    projected_fed_funds,
        },
        "dollar_impact": {
            "equity_leg":       round(equity_impact, 0),
            "bond_leg":         round(bond_impact, 0),
            "total":            round(total_impact, 0),
            "equity_allocation": equity_leg,
            "bond_allocation":   bond_leg,
            "notional":          notional,
        },
        "inversion": projected_spread < 0,
        "assumption": (
            "Illustrative only. Assumes modified duration of 7 years (10Y proxy), "
            "GS10 constant, equity valuation compression of 0.5x rate change. "
            "Not financial advice."
        ),
    }
