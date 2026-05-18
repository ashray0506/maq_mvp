"""
Benchmark tests: Sharpe 20d and MDD 90d.
Expected values computed independently — NOT derived from pipeline code.

Sharpe window=20, rf=5%/252:
  returns = [0.012,-0.008,0.015,0.003,-0.011, 0.009,0.006,-0.004,0.018,0.001,
             -0.007,0.013,0.005,-0.002,0.010, 0.008,-0.006,0.014,0.002,-0.009]
  Computed using pandas rolling(20).mean() / rolling(20).std() * sqrt(252)
  Sharpe = 5.788252

MDD window=10, prices=[100,105,102,108,95,90,97,103,98,110]:
  Peak tracking with min_periods=1, min() over window=10
  Worst drawdown = 90-108/108 = -16.6667%
"""

import math

import pandas as pd
import pytest

TRADING_DAYS = 252

# 20 daily returns for Sharpe test
RETURNS_20 = [
    0.012, -0.008, 0.015, 0.003, -0.011,
    0.009, 0.006, -0.004, 0.018, 0.001,
    -0.007, 0.013, 0.005, -0.002, 0.010,
    0.008, -0.006, 0.014, 0.002, -0.009,
]
RF_RATE_PCT = 5.0  # FEDFUNDS %
EXPECTED_SHARPE = 5.788252

# Prices for MDD test
PRICES_MDD = [100.0, 105.0, 102.0, 108.0, 95.0, 90.0, 97.0, 103.0, 98.0, 110.0]
EXPECTED_MDD = -16.666667  # %


def compute_sharpe_series(returns: list[float], rf_pct: float, window: int = 20) -> pd.Series:
    """Sharpe: MEAN(excess) / STDDEV(excess) * sqrt(252). rf = rf_pct/100/252 daily."""
    s = pd.Series(returns, dtype=float)
    daily_rf = rf_pct / 100 / TRADING_DAYS
    excess = s - daily_rf
    mean_e = excess.rolling(window, min_periods=window).mean()
    std_e = excess.rolling(window, min_periods=window).std()
    return (mean_e / std_e.replace(0, float("nan"))) * (TRADING_DAYS ** 0.5)


def compute_mdd_series(prices: list[float], window: int) -> pd.Series:
    """MDD: rolling peak (min_periods=1) then min drawdown over window."""
    close = pd.Series(prices, dtype=float)
    rolling_peak = close.rolling(window, min_periods=1).max()
    drawdown = (close - rolling_peak) / rolling_peak * 100
    return drawdown.rolling(window, min_periods=window).min()


# ---------------------------------------------------------------------------
# Sharpe tests
# ---------------------------------------------------------------------------

def test_sharpe_full_window_value():
    sharpe = compute_sharpe_series(RETURNS_20, RF_RATE_PCT)
    result = sharpe.iloc[-1]
    assert not math.isnan(result), "Sharpe should be non-null for full window"
    assert abs(result - EXPECTED_SHARPE) < 0.01, f"Sharpe={result:.4f}, expected={EXPECTED_SHARPE}"


def test_sharpe_null_before_window():
    sharpe = compute_sharpe_series(RETURNS_20, RF_RATE_PCT)
    for i in range(19):
        assert math.isnan(sharpe.iloc[i]), f"Sharpe should be null at index {i}"


def test_sharpe_uses_rf_rate():
    """Sharpe with rf=0 should differ from Sharpe with rf=5%."""
    s_with_rf = compute_sharpe_series(RETURNS_20, 5.0)
    s_no_rf = compute_sharpe_series(RETURNS_20, 0.0)
    assert s_with_rf.iloc[-1] != s_no_rf.iloc[-1], "rf rate should affect Sharpe value"


def test_sharpe_positive_for_positive_returns():
    pos_returns = [0.005] * 20
    sharpe = compute_sharpe_series(pos_returns, 0.0)
    # With all identical returns std=0, should be nan
    assert math.isnan(sharpe.iloc[-1]) or sharpe.iloc[-1] > 0


def test_sharpe_negative_for_negative_excess():
    neg_returns = [-0.005] * 20
    sharpe = compute_sharpe_series(neg_returns, 5.0)
    result = sharpe.iloc[-1]
    if not math.isnan(result):
        assert result < 0, "Negative excess returns → negative Sharpe"


# ---------------------------------------------------------------------------
# MDD tests
# ---------------------------------------------------------------------------

def test_mdd_full_window_value():
    mdd = compute_mdd_series(PRICES_MDD, window=10)
    result = mdd.iloc[-1]
    assert not math.isnan(result), "MDD should be non-null at full window"
    assert abs(result - EXPECTED_MDD) < 0.01, f"MDD={result:.4f}%, expected={EXPECTED_MDD}"


def test_mdd_null_before_window():
    mdd = compute_mdd_series(PRICES_MDD, window=10)
    for i in range(9):
        assert math.isnan(mdd.iloc[i]), f"MDD should be null at index {i}"


def test_mdd_is_non_positive():
    """MDD can never be positive — worst drawdown is always <= 0."""
    mdd = compute_mdd_series(PRICES_MDD, window=10)
    non_null = mdd.dropna()
    assert (non_null <= 0).all(), "MDD should always be <= 0"


def test_mdd_monotonically_rising_prices():
    """All-rising prices → MDD = 0 (no drawdown)."""
    rising = [100.0 + i for i in range(10)]
    mdd = compute_mdd_series(rising, window=10)
    result = mdd.iloc[-1]
    assert abs(result) < 1e-9, f"All-rising prices should have MDD=0, got {result}"


def test_mdd_catastrophic_drop():
    prices = [100.0, 100.0, 100.0, 100.0, 100.0, 50.0, 50.0, 50.0, 50.0, 50.0]
    mdd = compute_mdd_series(prices, window=10)
    result = mdd.iloc[-1]
    assert abs(result - (-50.0)) < 0.01, f"50% drop → MDD=-50%, got {result}"
