"""
Gold transformation: technical metrics + business KPIs.
Metrics: VWAP 20d, RSI-14 (Wilder's), EMA 3m, SMA 3m
KPIs: Sharpe 20d, MDD 90d, Volatility 20d, VWAP Efficiency
Yield: gs10_value, yield_spread
DQ rules G1–G5 implemented.
Creates DuckDB view: gold_metrics
"""

import logging
import os
from datetime import datetime, timezone

import duckdb
import pandas as pd
from dotenv import load_dotenv

from pipeline.quality import get_run_id, log_audit_run, log_dq_result

load_dotenv()

logger = logging.getLogger(__name__)

DB_PATH = "data/market.duckdb"
FRED_SERIES = os.environ["FRED_SERIES"]

TRADING_DAYS = 252
RSI_PERIOD = 14
VWAP_WINDOW = 20
EMA_SMA_MONTHS = 3
SHARPE_WINDOW = 20
MDD_WINDOW = 90
VOL_WINDOW = 20


# ---------------------------------------------------------------------------
# Technical metric helpers
# ---------------------------------------------------------------------------

def _compute_vwap(df: pd.DataFrame, run_id: str) -> pd.Series:
    """VWAP 20d rolling: SUM((H+L+C)/3 * V) / SUM(V). G2: exclude zero-volume rows."""
    zero_vol = int((df["volume"] == 0).sum())
    if zero_vol > 0:
        logger.info("G2: excluding %d zero-volume rows from VWAP", zero_vol)
        log_dq_result(run_id, "gold", "G2", "WARN", zero_vol,
                      f"{zero_vol} zero-volume rows excluded from VWAP")
    else:
        log_dq_result(run_id, "gold", "G2", "PASS", 0, "No zero-volume rows")

    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].where(df["volume"] > 0, other=0)
    tp_vol = typical * vol

    vwap = tp_vol.rolling(VWAP_WINDOW, min_periods=VWAP_WINDOW).sum() / \
           vol.rolling(VWAP_WINDOW, min_periods=VWAP_WINDOW).sum()
    return vwap


def _compute_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """RSI-14 using Wilder's EMA (alpha = 1/period). G1: first 14 rows are null — expected."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    alpha = 1 / period
    avg_gain = gain.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    # Force first (period-1) rows to null per G1
    rsi.iloc[:period - 1] = float("nan")
    return rsi


def _compute_ema_sma_macro(df: pd.DataFrame, run_id: str) -> tuple[pd.Series, pd.Series]:
    """EMA 3m and SMA 3m on FEDFUNDS monthly values, broadcast to daily dates. G3: need >= 3 months."""
    macro_monthly = (
        df[["month", "macro_value"]].drop_duplicates("month").sort_values("month")
    )
    unique_months = macro_monthly["macro_value"].dropna()

    if len(unique_months) < EMA_SMA_MONTHS:
        msg = f"G3: only {len(unique_months)} macro months (need >= {EMA_SMA_MONTHS})"
        logger.error(msg)
        log_dq_result(run_id, "gold", "G3", "FAIL", int(len(unique_months)), msg)
        raise RuntimeError(msg)

    log_dq_result(run_id, "gold", "G3", "PASS", int(len(unique_months)),
                  f"{len(unique_months)} macro months available")

    ema_monthly = macro_monthly["macro_value"].ewm(span=EMA_SMA_MONTHS, adjust=False).mean()
    sma_monthly = macro_monthly["macro_value"].rolling(EMA_SMA_MONTHS, min_periods=EMA_SMA_MONTHS).mean()

    macro_monthly = macro_monthly.copy()
    macro_monthly["macro_ema"] = ema_monthly.values
    macro_monthly["macro_sma"] = sma_monthly.values

    # Broadcast back to daily
    daily = df[["date", "month"]].merge(
        macro_monthly[["month", "macro_ema", "macro_sma"]], on="month", how="left"
    )
    return daily["macro_ema"], daily["macro_sma"]


# ---------------------------------------------------------------------------
# Business KPI helpers
# ---------------------------------------------------------------------------

def _compute_daily_return(close: pd.Series) -> pd.Series:
    return close.pct_change()


def _compute_sharpe(close: pd.Series, macro_value: pd.Series, run_id: str) -> pd.Series:
    """Sharpe 20d. G5: risk-free = macro_value / 252. G4: null for first 20 rows."""
    daily_return = _compute_daily_return(close)
    daily_rf = macro_value / 100 / TRADING_DAYS  # FEDFUNDS is in %, convert to decimal daily
    excess = daily_return - daily_rf

    mean_excess = excess.rolling(SHARPE_WINDOW, min_periods=SHARPE_WINDOW).mean()
    std_excess = excess.rolling(SHARPE_WINDOW, min_periods=SHARPE_WINDOW).std()

    sharpe = (mean_excess / std_excess.replace(0, float("nan"))) * (TRADING_DAYS ** 0.5)
    log_dq_result(run_id, "gold", "G5", "PASS", 0, "Sharpe uses FEDFUNDS/252 as risk-free rate")
    return sharpe


def _compute_mdd(close: pd.Series, window: int = MDD_WINDOW) -> pd.Series:
    """Max Drawdown over rolling window. G4: null for first rows.
    Peak is tracked with min_periods=1 so drawdown is always defined;
    the outer min() with min_periods=window ensures we only report after a full window."""
    rolling_peak = close.rolling(window, min_periods=1).max()
    drawdown = (close - rolling_peak) / rolling_peak * 100
    mdd = drawdown.rolling(window, min_periods=window).min()
    return mdd


def _compute_volatility(close: pd.Series) -> pd.Series:
    """Annualised volatility 20d. G4: null for first 20 rows."""
    daily_return = _compute_daily_return(close)
    vol = daily_return.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std() * (TRADING_DAYS ** 0.5) * 100
    return vol


def _compute_vwap_efficiency(close: pd.Series, vwap: pd.Series) -> pd.Series:
    """VWAP Efficiency: 100 - AVG(ABS(close-vwap)/vwap*100) over 20d."""
    pct_dev = (close - vwap).abs() / vwap.replace(0, float("nan")) * 100
    efficiency = 100 - pct_dev.rolling(VWAP_WINDOW, min_periods=VWAP_WINDOW).mean()
    return efficiency


# ---------------------------------------------------------------------------
# Main transform
# ---------------------------------------------------------------------------

def transform_gold() -> None:
    run_id = get_run_id()
    started = datetime.now(timezone.utc)
    logger.info("gold transform started run_id=%s", run_id)

    con = duckdb.connect(DB_PATH, read_only=False)
    try:
        df = con.execute("SELECT * FROM silver_market ORDER BY date").df()
        rows_in = len(df)
        logger.info("silver_market: %d rows loaded", rows_in)

        # Forward-fill monthly macro columns so every daily row has a value for Sharpe/EMA/SMA
        df["macro_value"] = df["macro_value"].ffill()
        df["gs10_value"] = df["gs10_value"].ffill()

        # Compute technical metrics
        df["vwap_20d"] = _compute_vwap(df, run_id)
        df["rsi_14"] = _compute_rsi(df["close"])
        df["macro_ema_3m"], df["macro_sma_3m"] = _compute_ema_sma_macro(df, run_id)

        # G1 — RSI null first 14 rows is expected
        null_rsi = df["rsi_14"].isna().sum()
        log_dq_result(run_id, "gold", "G1", "PASS", null_rsi,
                      f"RSI null for first {null_rsi} rows (window warmup)")

        # G4 — Sharpe/Vol null first 20 rows is expected
        df["sharpe_20d"] = _compute_sharpe(df["close"], df["macro_value"], run_id)
        df["mdd_90d"] = _compute_mdd(df["close"])
        df["volatility_20d"] = _compute_volatility(df["close"])
        df["vwap_efficiency"] = _compute_vwap_efficiency(df["close"], df["vwap_20d"])

        null_sharpe = df["sharpe_20d"].isna().sum()
        log_dq_result(run_id, "gold", "G4", "PASS", null_sharpe,
                      f"Sharpe/Vol null for first {null_sharpe} rows (window warmup)")

        # Yield spread
        df["yield_spread"] = df["gs10_value"] - df["macro_value"]

        # Build gold view
        gold_cols = [
            "date", "month", "symbol",
            "close", "high", "low", "volume",
            "macro_value", "macro_series", "gs10_value", "yield_spread",
            "vwap_20d", "rsi_14", "macro_ema_3m", "macro_sma_3m",
            "sharpe_20d", "mdd_90d", "volatility_20d", "vwap_efficiency",
            "loaded_at",
        ]
        gold_df = df[gold_cols].copy()

        con.execute("DROP VIEW IF EXISTS gold_metrics")
        con.execute("DROP TABLE IF EXISTS gold_metrics")
        con.execute("DROP TABLE IF EXISTS _gold_metrics_data")
        con.execute("CREATE TABLE _gold_metrics_data AS SELECT * FROM gold_df")
        con.execute("CREATE VIEW gold_metrics AS SELECT * FROM _gold_metrics_data")

        rows_out = len(gold_df)
        logger.info("gold_metrics: %d rows written", rows_out)
        log_audit_run(run_id, "transform_gold", "gold", "PASS",
                      rows_in=rows_in, rows_out=rows_out, started_at=started)

    except RuntimeError:
        raise
    except Exception as e:
        logger.error("transform_gold failed run_id=%s: %s", run_id, e, exc_info=True)
        log_audit_run(run_id, "transform_gold", "gold", "FAIL",
                      detail=str(e)[:500], started_at=started)
        raise
    finally:
        con.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler("logs/pipeline.log")],
    )
    transform_gold()
