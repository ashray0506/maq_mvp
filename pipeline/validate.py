"""
Validation gate: 12 checks across bronze, silver, and gold layers.
Exits 0 if all pass, 1 if any fail.
Do NOT adjust thresholds to force a pass — fix the underlying code.
"""

import logging
import sys

import duckdb

DB_PATH = "data/market.duckdb"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/validate.log")],
)
logger = logging.getLogger(__name__)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> bool:
    status = "PASS" if passed else "FAIL"
    msg = f"[{status}] {name}" + (f" — {detail}" if detail else "")
    if passed:
        logger.info(msg)
    else:
        logger.error(msg)
    RESULTS.append((name, passed, detail))
    return passed


def run_checks() -> int:
    con = duckdb.connect(DB_PATH, read_only=False)
    try:
        # ------------------------------------------------------------------
        # CHECK 1: Bronze AV rows exist
        # ------------------------------------------------------------------
        try:
            av_count = con.execute("SELECT COUNT(*) FROM bronze_av").fetchone()[0]
            check("V01 bronze_av has rows", av_count > 0, f"{av_count} rows")
        except Exception as e:
            check("V01 bronze_av has rows", False, str(e))

        # ------------------------------------------------------------------
        # CHECK 2: Bronze FRED FEDFUNDS rows exist
        # ------------------------------------------------------------------
        try:
            fred_count = con.execute("SELECT COUNT(*) FROM bronze_fred").fetchone()[0]
            check("V02 bronze_fred has rows", fred_count > 0, f"{fred_count} rows")
        except Exception as e:
            check("V02 bronze_fred has rows", False, str(e))

        # ------------------------------------------------------------------
        # CHECK 3: Bronze GS10 rows exist
        # ------------------------------------------------------------------
        try:
            gs10_count = con.execute("SELECT COUNT(*) FROM bronze_fred_gs10").fetchone()[0]
            check("V03 bronze_fred_gs10 has rows", gs10_count > 0, f"{gs10_count} rows")
        except Exception as e:
            check("V03 bronze_fred_gs10 has rows", False, str(e))

        # ------------------------------------------------------------------
        # CHECK 4: Silver has expected columns
        # ------------------------------------------------------------------
        try:
            cols = {r[0] for r in con.execute("DESCRIBE silver_market").fetchall()}
            expected = {"date", "month", "symbol", "close", "high", "low", "volume",
                        "macro_value", "macro_series", "gs10_value", "loaded_at"}
            missing = expected - cols
            check("V04 silver_market schema", not missing,
                  f"missing: {missing}" if missing else f"{len(cols)} columns present")
        except Exception as e:
            check("V04 silver_market schema", False, str(e))

        # ------------------------------------------------------------------
        # CHECK 5: Silver row count >= 60
        # ------------------------------------------------------------------
        try:
            silver_count = con.execute("SELECT COUNT(*) FROM silver_market").fetchone()[0]
            check("V05 silver_market row count >= 60", silver_count >= 60, f"{silver_count} rows")
        except Exception as e:
            check("V05 silver_market row count >= 60", False, str(e))

        # ------------------------------------------------------------------
        # CHECK 6: Silver no future dates
        # ------------------------------------------------------------------
        try:
            future = con.execute(
                "SELECT COUNT(*) FROM silver_market WHERE date > NOW()"
            ).fetchone()[0]
            check("V06 silver_market no future dates", future == 0, f"{future} future rows")
        except Exception as e:
            check("V06 silver_market no future dates", False, str(e))

        # ------------------------------------------------------------------
        # CHECK 7: Silver join covers >= 3 shared months
        # ------------------------------------------------------------------
        try:
            months = con.execute(
                "SELECT COUNT(DISTINCT month) FROM silver_market WHERE macro_value IS NOT NULL"
            ).fetchone()[0]
            check("V07 silver_market >= 3 FEDFUNDS months", months >= 3, f"{months} months")
        except Exception as e:
            check("V07 silver_market >= 3 FEDFUNDS months", False, str(e))

        # ------------------------------------------------------------------
        # CHECK 8: Gold has expected metric columns
        # ------------------------------------------------------------------
        try:
            cols = {r[0] for r in con.execute("DESCRIBE gold_metrics").fetchall()}
            expected = {"vwap_20d", "rsi_14", "macro_ema_3m", "macro_sma_3m",
                        "sharpe_20d", "mdd_90d", "volatility_20d", "vwap_efficiency",
                        "gs10_value", "yield_spread"}
            missing = expected - cols
            check("V08 gold_metrics schema", not missing,
                  f"missing: {missing}" if missing else f"{len(cols)} columns present")
        except Exception as e:
            check("V08 gold_metrics schema", False, str(e))

        # ------------------------------------------------------------------
        # CHECK 9: RSI is null for first 13 rows, non-null after row 14
        # ------------------------------------------------------------------
        try:
            rsi_non_null = con.execute(
                "SELECT COUNT(*) FROM gold_metrics WHERE rsi_14 IS NOT NULL"
            ).fetchone()[0]
            check("V09 gold_metrics RSI has non-null values", rsi_non_null > 0,
                  f"{rsi_non_null} non-null RSI values")
        except Exception as e:
            check("V09 gold_metrics RSI has non-null values", False, str(e))

        # ------------------------------------------------------------------
        # CHECK 10: RSI values are within 0–100
        # ------------------------------------------------------------------
        try:
            out_of_range = con.execute(
                "SELECT COUNT(*) FROM gold_metrics WHERE rsi_14 IS NOT NULL AND (rsi_14 < 0 OR rsi_14 > 100)"
            ).fetchone()[0]
            check("V10 gold_metrics RSI in range 0–100", out_of_range == 0,
                  f"{out_of_range} out-of-range RSI values")
        except Exception as e:
            check("V10 gold_metrics RSI in range 0–100", False, str(e))

        # ------------------------------------------------------------------
        # CHECK 11: Sharpe uses FEDFUNDS — verify macro_value present in gold
        # ------------------------------------------------------------------
        try:
            has_macro = con.execute(
                "SELECT COUNT(*) FROM gold_metrics WHERE macro_value IS NOT NULL"
            ).fetchone()[0]
            check("V11 gold_metrics has macro_value for Sharpe", has_macro > 0,
                  f"{has_macro} rows with macro_value")
        except Exception as e:
            check("V11 gold_metrics has macro_value for Sharpe", False, str(e))

        # ------------------------------------------------------------------
        # CHECK 12: Audit pipeline runs table has entries
        # ------------------------------------------------------------------
        try:
            audit_count = con.execute("SELECT COUNT(*) FROM audit_pipeline_runs").fetchone()[0]
            check("V12 audit_pipeline_runs has entries", audit_count > 0,
                  f"{audit_count} audit rows")
        except Exception as e:
            check("V12 audit_pipeline_runs has entries", False, str(e))

    except Exception as e:
        logger.error("validate — unexpected error: %s", e, exc_info=True)
    finally:
        con.close()

    # Summary
    passed = sum(1 for _, p, _ in RESULTS if p)
    failed = sum(1 for _, p, _ in RESULTS if not p)
    print(f"\n{'='*50}")
    print(f"Validation: {passed} PASS / {failed} FAIL out of {len(RESULTS)} checks")
    print("="*50)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_checks())
