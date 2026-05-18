"""
Silver transformation: clean, join, UTC-normalise AV + FRED data.
DQ rules S1–S5 implemented.
Creates DuckDB view: silver_market
"""

import logging
import os
from datetime import datetime, timezone

import duckdb
import pandas as pd
from dotenv import load_dotenv

from pipeline.quality import get_run_id, log_audit_run, log_dq_result, quarantine

load_dotenv()

logger = logging.getLogger(__name__)

DB_PATH = "data/market.duckdb"
SYMBOL = os.environ["SYMBOL"]
FRED_SERIES = os.environ["FRED_SERIES"]
FRED_SERIES_2 = os.getenv("FRED_SERIES_2", "GS10")

S2_MIN_ROWS = 60


def transform_silver() -> None:
    run_id = get_run_id()
    started = datetime.now(timezone.utc)
    logger.info("silver transform started run_id=%s", run_id)

    con = duckdb.connect(DB_PATH, read_only=False)
    try:
        # Load bronze views
        av_df = con.execute("SELECT * FROM bronze_av").df()
        fred_df = con.execute("SELECT * FROM bronze_fred").df()
        gs10_df = con.execute("SELECT * FROM bronze_fred_gs10").df()

        rows_in = len(av_df)
        logger.info("bronze_av: %d rows, bronze_fred: %d rows, bronze_fred_gs10: %d rows",
                    rows_in, len(fred_df), len(gs10_df))

        # S5 — ensure UTC
        for col in ("date",):
            if av_df[col].dt.tz is None:
                av_df[col] = av_df[col].dt.tz_localize("UTC")
            else:
                av_df[col] = av_df[col].dt.tz_convert("UTC")
            if fred_df[col].dt.tz is None:
                fred_df[col] = fred_df[col].dt.tz_localize("UTC")
            else:
                fred_df[col] = fred_df[col].dt.tz_convert("UTC")
            if gs10_df[col].dt.tz is None:
                gs10_df[col] = gs10_df[col].dt.tz_localize("UTC")
            else:
                gs10_df[col] = gs10_df[col].dt.tz_convert("UTC")

        log_dq_result(run_id, "silver", "S5", "PASS", 0, "All dates UTC-normalised")

        # S3 — no future dates
        now_utc = pd.Timestamp.now(tz="UTC")
        future_av = av_df[av_df["date"] > now_utc]
        if not future_av.empty:
            logger.warning("S3: %d future-dated AV rows quarantined", len(future_av))
            quarantine(run_id, "S3", future_av.to_dict("records"), "future date", rows_in)
            log_dq_result(run_id, "silver", "S3", "FAIL", len(future_av),
                          f"{len(future_av)} future-dated rows quarantined")
            av_df = av_df[av_df["date"] <= now_utc]
        else:
            log_dq_result(run_id, "silver", "S3", "PASS", 0, "No future dates")

        # S1 — null close or volume → quarantine
        null_mask = av_df["close"].isna() | av_df["volume"].isna()
        null_rows = av_df[null_mask]
        if not null_rows.empty:
            logger.warning("S1: %d rows with null close/volume quarantined", len(null_rows))
            quarantine(run_id, "S1", null_rows.to_dict("records"), "null close or volume", rows_in)
            log_dq_result(run_id, "silver", "S1", "FAIL", len(null_rows),
                          f"{len(null_rows)} null rows quarantined")
            av_df = av_df[~null_mask]
        else:
            log_dq_result(run_id, "silver", "S1", "PASS", 0, "No null close/volume")

        # S2 — completeness check
        if len(av_df) < S2_MIN_ROWS:
            logger.warning("S2: only %d rows after cleaning (min %d)", len(av_df), S2_MIN_ROWS)
            log_dq_result(run_id, "silver", "S2", "WARN", len(av_df),
                          f"Only {len(av_df)} rows, expected >= {S2_MIN_ROWS}")
        else:
            log_dq_result(run_id, "silver", "S2", "PASS", len(av_df),
                          f"{len(av_df)} rows >= {S2_MIN_ROWS}")

        # Add month key for joining
        av_df["month"] = av_df["date"].dt.to_period("M").dt.to_timestamp().dt.tz_localize("UTC")

        # Prepare FEDFUNDS monthly (take last value per month)
        fred_monthly = (
            fred_df.dropna(subset=["value"])
            .assign(month=lambda d: d["date"].dt.to_period("M").dt.to_timestamp().dt.tz_localize("UTC"))
            .groupby("month")["value"]
            .last()
            .reset_index()
            .rename(columns={"value": "macro_value"})
        )
        fred_monthly["macro_series"] = FRED_SERIES

        # Prepare GS10 monthly
        gs10_monthly = (
            gs10_df.dropna(subset=["value"])
            .assign(month=lambda d: d["date"].dt.to_period("M").dt.to_timestamp().dt.tz_localize("UTC"))
            .groupby("month")["value"]
            .last()
            .reset_index()
            .rename(columns={"value": "gs10_value"})
        )

        # S4 — join must produce >= 3 shared months
        shared_months = set(av_df["month"].unique()) & set(fred_monthly["month"].unique())
        if len(shared_months) < 3:
            msg = f"S4: only {len(shared_months)} shared months between AV and FRED (min 3)"
            logger.error(msg)
            log_dq_result(run_id, "silver", "S4", "FAIL", len(shared_months), msg)
            log_audit_run(run_id, "transform_silver", "silver", "FAIL",
                          rows_in=rows_in, detail=msg, started_at=started)
            raise RuntimeError(msg)

        log_dq_result(run_id, "silver", "S4", "PASS", len(shared_months),
                      f"{len(shared_months)} shared months")

        # Join
        silver_df = av_df.merge(fred_monthly, on="month", how="left")
        silver_df = silver_df.merge(gs10_monthly, on="month", how="left")

        silver_df["loaded_at"] = datetime.now(timezone.utc)
        silver_df["symbol"] = SYMBOL

        # Select and order output columns per spec
        output_cols = [
            "date", "month", "symbol", "close", "high", "low", "volume",
            "macro_value", "macro_series", "gs10_value", "loaded_at",
        ]
        silver_df = silver_df[output_cols].sort_values("date").reset_index(drop=True)

        # Write as DuckDB table then expose as view (not parquet — views only per rules)
        # Drop both object types in case a prior failed run left a table named silver_market
        con.execute("DROP TABLE IF EXISTS silver_market")
        con.execute("DROP VIEW IF EXISTS silver_market")
        con.execute("DROP TABLE IF EXISTS _silver_market_data")
        con.execute("CREATE TABLE _silver_market_data AS SELECT * FROM silver_df")
        con.execute("CREATE VIEW silver_market AS SELECT * FROM _silver_market_data")

        rows_out = len(silver_df)
        logger.info("silver_market: %d rows written", rows_out)
        log_audit_run(run_id, "transform_silver", "silver", "PASS",
                      rows_in=rows_in, rows_out=rows_out, started_at=started)

    except RuntimeError:
        raise
    except Exception as e:
        logger.error("transform_silver failed run_id=%s: %s", run_id, e, exc_info=True)
        log_audit_run(run_id, "transform_silver", "silver", "FAIL",
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
    transform_silver()
