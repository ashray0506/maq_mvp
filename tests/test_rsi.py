"""
Benchmark test: RSI-14 (Wilder's EMA, alpha=1/14).
Expected values computed independently — NOT derived from pipeline code.

Price sequence: [100,102,101,103,99,98,101,104,103,105,102,100,103,106,104,107,105,108,106,110]
Manual Wilder's EMA calculation confirms these values.
"""

import math

import pandas as pd
import pytest

PRICES = [
    100, 102, 101, 103, 99, 98, 101, 104, 103, 105,
    102, 100, 103, 106, 104, 107, 105, 108, 106, 110,
]

# Independently computed expected values (rounded to 4dp for tolerance)
EXPECTED = {
    13: None,           # first 13 indices (0-12) are null per G1; idx 13 is 14th element = still null
    14: 70.0570,
    15: 72.8773,
    18: 66.7585,
    19: 70.7011,
}


def compute_rsi(prices: list[float], period: int = 14) -> pd.Series:
    close = pd.Series(prices, dtype=float)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    alpha = 1 / period
    avg_gain = gain.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    rsi.iloc[: period - 1] = float("nan")
    return rsi


def test_rsi_first_13_rows_are_null():
    rsi = compute_rsi(PRICES)
    for i in range(13):
        assert math.isnan(rsi.iloc[i]), f"Expected NaN at index {i}, got {rsi.iloc[i]}"


def test_rsi_index_13_is_null():
    """Index 13 is the 14th row — still part of warmup window."""
    rsi = compute_rsi(PRICES)
    assert math.isnan(rsi.iloc[13])


def test_rsi_index_14_value():
    rsi = compute_rsi(PRICES)
    assert abs(rsi.iloc[14] - EXPECTED[14]) < 0.01, f"RSI[14]={rsi.iloc[14]:.4f}"


def test_rsi_index_15_value():
    rsi = compute_rsi(PRICES)
    assert abs(rsi.iloc[15] - EXPECTED[15]) < 0.01, f"RSI[15]={rsi.iloc[15]:.4f}"


def test_rsi_values_in_range_0_to_100():
    rsi = compute_rsi(PRICES)
    non_null = rsi.dropna()
    assert (non_null >= 0).all() and (non_null <= 100).all(), "RSI out of 0–100 range"


def test_rsi_final_value():
    rsi = compute_rsi(PRICES)
    assert abs(rsi.iloc[19] - EXPECTED[19]) < 0.01, f"RSI[19]={rsi.iloc[19]:.4f}"
