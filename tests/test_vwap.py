"""
Benchmark test: VWAP 20d rolling = SUM((H+L+C)/3 * V) / SUM(V).
Expected values computed independently — NOT derived from pipeline code.

For a 5-row full-window VWAP (window=5):
  closes = [100, 102, 101, 103, 105]
  highs  = [101, 103, 102, 104, 106]
  lows   = [ 99, 101, 100, 102, 104]
  vols   = [1000, 1500, 1200, 1100, 1300]

  Typical prices: [100, 102, 101, 103, 105]
  TP*V:           100000, 153000, 121200, 113300, 136500 → sum = 624000
  Total V:        1000+1500+1200+1100+1300 = 6100
  VWAP = 624000 / 6100 = 102.295082...
"""

import pandas as pd
import pytest

CLOSES = [100.0, 102.0, 101.0, 103.0, 105.0]
HIGHS  = [101.0, 103.0, 102.0, 104.0, 106.0]
LOWS   = [ 99.0, 101.0, 100.0, 102.0, 104.0]
VOLS   = [1000.0, 1500.0, 1200.0, 1100.0, 1300.0]

EXPECTED_VWAP_5 = 102.295082


def compute_vwap(closes, highs, lows, vols, window: int) -> pd.Series:
    df = pd.DataFrame({"close": closes, "high": highs, "low": lows, "volume": vols})
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].where(df["volume"] > 0, other=0)
    tp_vol = typical * vol
    vwap = (
        tp_vol.rolling(window, min_periods=window).sum()
        / vol.rolling(window, min_periods=window).sum()
    )
    return vwap


def test_vwap_first_rows_null_before_window():
    vwap = compute_vwap(CLOSES, HIGHS, LOWS, VOLS, window=5)
    for i in range(4):
        assert pd.isna(vwap.iloc[i]), f"Expected NaN at index {i}"


def test_vwap_full_window_value():
    vwap = compute_vwap(CLOSES, HIGHS, LOWS, VOLS, window=5)
    assert abs(vwap.iloc[4] - EXPECTED_VWAP_5) < 0.001, f"VWAP={vwap.iloc[4]:.6f}"


def test_vwap_zero_volume_excluded():
    closes = [100.0, 102.0, 0.0, 103.0, 105.0]
    highs  = [101.0, 103.0, 0.0, 104.0, 106.0]
    lows   = [ 99.0, 101.0, 0.0, 102.0, 104.0]
    vols   = [1000.0, 1500.0, 0.0, 1100.0, 1300.0]
    # VWAP should not be NaN because zero-volume rows contribute 0 to numerator and denominator
    vwap = compute_vwap(closes, highs, lows, vols, window=5)
    assert not pd.isna(vwap.iloc[4]), "VWAP should not be NaN with zero-volume rows"


def test_vwap_is_positive():
    vwap = compute_vwap(CLOSES, HIGHS, LOWS, VOLS, window=5)
    non_null = vwap.dropna()
    assert (non_null > 0).all(), "All VWAP values should be positive"
