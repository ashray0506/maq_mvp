"""
Bronze ingestion: Alpha Vantage TIME_SERIES_DAILY + FRED series/observations.
DQ rules B1–B4 implemented.
Run once: python pipeline/ingest.py
Scheduled: python pipeline/ingest.py --schedule  (daily 07:00)
"""

import argparse
import logging
import os
import time
from datetime import datetime, timezone

import pandas as pd
import requests
import schedule
from dotenv import load_dotenv

from pipeline.quality import get_run_id, log_audit_run, log_dq_result

load_dotenv()

logger = logging.getLogger(__name__)

AV_API_KEY = os.environ["ALPHA_VANTAGE_API_KEY"]
FRED_API_KEY = os.environ["FRED_API_KEY"]
SYMBOL = os.environ["SYMBOL"]
FRED_SERIES = os.environ["FRED_SERIES"]
FRED_SERIES_2 = os.getenv("FRED_SERIES_2", "GS10")

BRONZE_DIR = "data/bronze"
AV_BASE_URL = "https://www.alphavantage.co/query"
FRED_BASE_URL = "https://api.stlouisfed.org/fred"

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_S = 5

AV_EXPECTED_COLUMNS = {"date", "open", "high", "low", "close", "volume"}
FRED_EXPECTED_COLUMNS = {"date", "value"}


# ---------------------------------------------------------------------------
# B1 — retry helper
# ---------------------------------------------------------------------------

def _get_with_retry(url: str, params: dict) -> dict:
    """B1: retry 3x with 5s backoff. Raises on all failures."""
    last_exc = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_exc = e
            logger.error("HTTP attempt %d/%d failed url=%s: %s", attempt, RETRY_ATTEMPTS, url, e)
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_S)
    raise RuntimeError(f"B1: all {RETRY_ATTEMPTS} attempts failed for {url}") from last_exc


# ---------------------------------------------------------------------------
# Alpha Vantage ingestion
# ---------------------------------------------------------------------------

def ingest_alpha_vantage(run_id: str) -> str | None:
    """Fetch TIME_SERIES_DAILY for SYMBOL, write bronze parquet. Returns file path or None."""
    started = datetime.now(timezone.utc)
    step = "ingest_av"
    layer = "bronze"

    try:
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": SYMBOL,
            "outputsize": "compact",
            "apikey": AV_API_KEY,
        }
        data = _get_with_retry(AV_BASE_URL, params)

        # B2 — rate limit detection
        if "Note" in data or "Information" in data:
            msg = data.get("Note") or data.get("Information", "unknown rate limit message")
            logger.error("B2: AV rate limit detected — %s", msg)
            log_dq_result(run_id, layer, "B2", "FAIL", 0, f"Rate limit: {msg[:200]}")
            log_audit_run(run_id, step, layer, "FAIL", detail="B2 rate limit", started_at=started)
            return None

        log_dq_result(run_id, layer, "B2", "PASS", 0, "No rate limit signal")

        raw_ts = data.get("Time Series (Daily)", {})
        if not raw_ts:
            logger.error("B3: AV response missing 'Time Series (Daily)' key")
            log_dq_result(run_id, layer, "B3", "FAIL", 0, "Missing time series key")
            log_audit_run(run_id, step, layer, "FAIL", detail="B3 schema", started_at=started)
            return None

        rows = []
        for date_str, ohlcv in raw_ts.items():
            rows.append({
                "date": date_str,
                "open": float(ohlcv.get("1. open", 0)),
                "high": float(ohlcv.get("2. high", 0)),
                "low": float(ohlcv.get("3. low", 0)),
                "close": float(ohlcv.get("4. close", 0)),
                "volume": float(ohlcv.get("5. volume", 0)),
            })

        df = pd.DataFrame(rows)

        # B3 — schema validation
        missing = AV_EXPECTED_COLUMNS - set(df.columns)
        if missing:
            logger.error("B3: AV schema missing columns: %s", missing)
            log_dq_result(run_id, layer, "B3", "FAIL", 0, f"Missing cols: {missing}")
            log_audit_run(run_id, step, layer, "FAIL", detail="B3 schema", started_at=started)
            return None

        log_dq_result(run_id, layer, "B3", "PASS", len(df), "AV schema valid")

        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize("UTC")
        df["symbol"] = SYMBOL
        df["loaded_at"] = datetime.now(timezone.utc)

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = f"{BRONZE_DIR}/av_{SYMBOL}_{date_str}.parquet"
        df.to_parquet(path, index=False)

        logger.info("AV bronze written: %s (%d rows)", path, len(df))
        log_audit_run(run_id, step, layer, "PASS", rows_in=len(df), rows_out=len(df),
                      detail=path, started_at=started)
        return path

    except Exception as e:
        logger.error("ingest_av failed run_id=%s: %s", run_id, e, exc_info=True)
        log_audit_run(run_id, step, layer, "FAIL", detail=str(e)[:500], started_at=started)
        return None


# ---------------------------------------------------------------------------
# FRED ingestion (shared pattern for FEDFUNDS + GS10)
# ---------------------------------------------------------------------------

def ingest_fred(run_id: str, series_id: str) -> str | None:
    """Fetch FRED series observations, write bronze parquet. Returns file path or None."""
    started = datetime.now(timezone.utc)
    step = f"ingest_fred_{series_id}"
    layer = "bronze"

    try:
        params = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "observation_start": "2000-01-01",
        }
        data = _get_with_retry(f"{FRED_BASE_URL}/series/observations", params)

        observations = data.get("observations", [])
        if not observations:
            logger.error("B3: FRED %s response has no observations", series_id)
            log_dq_result(run_id, layer, "B3", "FAIL", 0, f"No observations for {series_id}")
            log_audit_run(run_id, step, layer, "FAIL", detail="B3 empty", started_at=started)
            return None

        rows = []
        dot_count = 0
        for obs in observations:
            raw_val = obs.get("value", ".")
            # B4 — FRED "." → null coercion
            if raw_val == ".":
                dot_count += 1
                value = None
            else:
                try:
                    value = float(raw_val)
                except ValueError:
                    dot_count += 1
                    value = None
            rows.append({"date": obs["date"], "value": value})

        if dot_count > 0:
            logger.warning("B4: FRED %s coerced %d '.' values to null", series_id, dot_count)
            log_dq_result(run_id, layer, "B4", "WARN", dot_count,
                          f"FRED {series_id}: {dot_count} dots coerced to null")
        else:
            log_dq_result(run_id, layer, "B4", "PASS", 0, f"No dot values in {series_id}")

        df = pd.DataFrame(rows)

        # B3 — schema validation
        missing = FRED_EXPECTED_COLUMNS - set(df.columns)
        if missing:
            logger.error("B3: FRED %s schema missing columns: %s", series_id, missing)
            log_dq_result(run_id, layer, "B3", "FAIL", 0, f"Missing cols: {missing}")
            log_audit_run(run_id, step, layer, "FAIL", detail="B3 schema", started_at=started)
            return None

        log_dq_result(run_id, layer, "B3", "PASS", len(df), f"FRED {series_id} schema valid")

        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize("UTC")
        df["series_id"] = series_id
        df["loaded_at"] = datetime.now(timezone.utc)

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = f"{BRONZE_DIR}/fred_{series_id}_{date_str}.parquet"
        df.to_parquet(path, index=False)

        logger.info("FRED bronze written: %s (%d rows)", path, len(df))
        log_audit_run(run_id, step, layer, "PASS", rows_in=len(df), rows_out=len(df),
                      detail=path, started_at=started)
        return path

    except Exception as e:
        logger.error("ingest_fred %s failed run_id=%s: %s", series_id, run_id, e, exc_info=True)
        log_audit_run(run_id, step, layer, "FAIL", detail=str(e)[:500], started_at=started)
        return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_ingest() -> None:
    run_id = get_run_id()
    logger.info("ingest started run_id=%s", run_id)
    ingest_alpha_vantage(run_id)
    ingest_fred(run_id, FRED_SERIES)
    ingest_fred(run_id, FRED_SERIES_2)
    logger.info("ingest complete run_id=%s", run_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule", action="store_true", help="Run daily at 07:00")
    args = parser.parse_args()

    if args.schedule:
        schedule.every().day.at("07:00").do(run_ingest)
        logger.info("Scheduler started — will run daily at 07:00")
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        run_ingest()
