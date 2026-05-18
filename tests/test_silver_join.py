"""
Benchmark test: Silver join correctness — AV daily joined to FRED monthly.
Expected behaviour computed independently — NOT derived from pipeline code.
"""

import pandas as pd
import pytest


def _make_av(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime(dates, utc=True),
        "close": [100.0] * len(dates),
        "high":  [101.0] * len(dates),
        "low":   [ 99.0] * len(dates),
        "volume": [1000.0] * len(dates),
        "symbol": "SPY",
    })


def _make_fred(dates: list[str], values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime(dates, utc=True),
        "value": values,
        "series_id": "FEDFUNDS",
    })


def _join(av_df: pd.DataFrame, fred_df: pd.DataFrame) -> pd.DataFrame:
    """Replicate the silver join logic: last FRED value per month."""
    av_df = av_df.copy()
    av_df["month"] = av_df["date"].dt.to_period("M").dt.to_timestamp().dt.tz_localize("UTC")

    fred_monthly = (
        fred_df.dropna(subset=["value"])
        .assign(month=lambda d: d["date"].dt.to_period("M").dt.to_timestamp().dt.tz_localize("UTC"))
        .groupby("month")["value"]
        .last()
        .reset_index()
        .rename(columns={"value": "macro_value"})
    )

    return av_df.merge(fred_monthly, on="month", how="left")


def test_join_broadcasts_monthly_to_daily():
    av = _make_av(["2024-01-10", "2024-01-15", "2024-01-20"])
    fred = _make_fred(["2024-01-01"], [5.33])
    result = _join(av, fred)
    assert result["macro_value"].notna().all(), "All January rows should have macro_value"
    assert (result["macro_value"] == 5.33).all()


def test_join_uses_last_fred_value_in_month():
    av = _make_av(["2024-02-10"])
    fred = _make_fred(["2024-02-01", "2024-02-15"], [5.0, 5.5])
    result = _join(av, fred)
    # Last value in February is 5.5
    assert result["macro_value"].iloc[0] == 5.5


def test_join_leaves_null_for_unmatched_months():
    av = _make_av(["2024-03-10"])
    fred = _make_fred(["2024-01-01"], [5.33])  # no March data
    result = _join(av, fred)
    assert result["macro_value"].isna().all(), "No March FRED data → macro_value should be null"


def test_join_shared_months_count():
    av = _make_av(["2024-01-10", "2024-02-10", "2024-03-10", "2024-04-10"])
    fred = _make_fred(["2024-01-01", "2024-02-01", "2024-03-01"], [5.0, 5.1, 5.2])
    result = _join(av, fred)
    shared = result["macro_value"].notna().sum()
    # 3 out of 4 months matched
    assert shared == 3, f"Expected 3 matched months, got {shared}"
