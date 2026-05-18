"""
Benchmark test: Bronze parquet files have required schema columns.
Values are structural — NOT derived from pipeline code.
"""

import glob
import os

import pandas as pd
import pytest

BRONZE_DIR = "data/bronze"

AV_REQUIRED_COLS = {"date", "open", "high", "low", "close", "volume", "symbol", "loaded_at"}
FRED_REQUIRED_COLS = {"date", "value", "series_id", "loaded_at"}


def _latest_parquet(pattern: str) -> str | None:
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def test_av_bronze_exists():
    path = _latest_parquet(f"{BRONZE_DIR}/av_*.parquet")
    assert path is not None, "No AV bronze parquet found"


def test_av_bronze_schema():
    path = _latest_parquet(f"{BRONZE_DIR}/av_*.parquet")
    assert path, "No AV bronze file"
    df = pd.read_parquet(path)
    missing = AV_REQUIRED_COLS - set(df.columns)
    assert not missing, f"AV bronze missing columns: {missing}"


def test_av_bronze_date_is_utc():
    path = _latest_parquet(f"{BRONZE_DIR}/av_*.parquet")
    assert path, "No AV bronze file"
    df = pd.read_parquet(path)
    assert df["date"].dt.tz is not None, "AV date column has no timezone"
    assert str(df["date"].dt.tz) in ("UTC", "UTC+00:00"), f"AV date tz={df['date'].dt.tz}"


def test_fred_bronze_exists():
    path = _latest_parquet(f"{BRONZE_DIR}/fred_FEDFUNDS_*.parquet")
    assert path is not None, "No FRED FEDFUNDS bronze parquet found"


def test_fred_bronze_schema():
    path = _latest_parquet(f"{BRONZE_DIR}/fred_FEDFUNDS_*.parquet")
    assert path, "No FRED bronze file"
    df = pd.read_parquet(path)
    missing = FRED_REQUIRED_COLS - set(df.columns)
    assert not missing, f"FRED bronze missing columns: {missing}"


def test_fred_gs10_bronze_exists():
    path = _latest_parquet(f"{BRONZE_DIR}/fred_GS10_*.parquet")
    assert path is not None, "No FRED GS10 bronze parquet found"
