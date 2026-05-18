"""
DQ helpers and audit tables. Import this module before any pipeline code.
All audit tables and NBA tables are created here on first import.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import duckdb

DB_PATH = "data/market.duckdb"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/pipeline.log"),
    ],
)
logger = logging.getLogger(__name__)

QUARANTINE_THRESHOLD = 0.10  # halt if >10% of rows quarantined in a run


def _get_connection() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(DB_PATH, read_only=False)


def _bootstrap_tables() -> None:
    con = _get_connection()
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS audit_pipeline_runs (
                run_id        VARCHAR NOT NULL,
                step          VARCHAR NOT NULL,
                layer         VARCHAR NOT NULL,
                status        VARCHAR NOT NULL,
                rows_in       INTEGER,
                rows_out      INTEGER,
                rows_quarantined INTEGER,
                detail        VARCHAR,
                started_at    TIMESTAMPTZ NOT NULL,
                finished_at   TIMESTAMPTZ
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS audit_dq_results (
                run_id        VARCHAR NOT NULL,
                layer         VARCHAR NOT NULL,
                rule_id       VARCHAR NOT NULL,
                status        VARCHAR NOT NULL,
                rows_affected INTEGER,
                detail        VARCHAR,
                evaluated_at  TIMESTAMPTZ NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS quarantine_records (
                quarantine_id        VARCHAR NOT NULL,
                run_id               VARCHAR NOT NULL,
                rule_id              VARCHAR NOT NULL,
                raw_record           VARCHAR,
                reason               VARCHAR,
                quarantine_timestamp TIMESTAMPTZ NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS user_nba_rules (
                rule_id     VARCHAR NOT NULL,
                name        VARCHAR NOT NULL,
                description VARCHAR,
                condition   VARCHAR NOT NULL,
                severity    VARCHAR NOT NULL,
                active      BOOLEAN NOT NULL DEFAULT TRUE,
                created_at  TIMESTAMPTZ NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS audit_nba_actions (
                action_id    VARCHAR NOT NULL,
                reference_id VARCHAR NOT NULL,
                session_id   VARCHAR NOT NULL,
                action_type  VARCHAR NOT NULL,
                rule_ids     VARCHAR,
                timestamp    TIMESTAMPTZ NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS audit_nba_evaluations (
                evaluation_id       VARCHAR NOT NULL,
                run_id              VARCHAR NOT NULL,
                triggered_rule_ids  VARCHAR,
                highest_severity    VARCHAR,
                recommendations     VARCHAR,
                llm_rationale       VARCHAR,
                data_snapshot       VARCHAR,
                evaluated_at        TIMESTAMPTZ NOT NULL
            )
        """)
        create_governance_tables(con)
        seed_governance_data(con)
        logger.info("quality — audit tables bootstrapped")
    except Exception as e:
        logger.error("quality — failed to bootstrap tables: %s", e, exc_info=True)
        raise
    finally:
        con.close()


def create_governance_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Create governance tables — idempotent, safe to call repeatedly."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS governance_definitions (
            definition_id    VARCHAR PRIMARY KEY,
            category         VARCHAR,
            name             VARCHAR,
            display_name     VARCHAR,
            definition       VARCHAR,
            formula          VARCHAR,
            source           VARCHAR,
            owner            VARCHAR,
            sensitivity      VARCHAR,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS governance_lineage (
            lineage_id       VARCHAR PRIMARY KEY,
            source_name      VARCHAR,
            source_layer     VARCHAR,
            target_name      VARCHAR,
            target_layer     VARCHAR,
            transform        VARCHAR,
            dq_rules         VARCHAR,
            schedule         VARCHAR,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def seed_governance_data(con: duckdb.DuckDBPyConnection) -> None:
    """Seed metric definitions and lineage. Safe to run multiple times."""
    definitions = [
        ("def_vwap", "metric", "vwap_20d", "VWAP 20d",
         "Volume-Weighted Average Price over a 20-day rolling window. "
         "Shows where the market actually traded weighted by activity — "
         "the institutional fair value reference price.",
         "SUM((H+L+C)/3 × Volume) / SUM(Volume) rolling 20d",
         "Alpha Vantage (OHLCV)", "Analytics Engineering", "internal"),

        ("def_rsi", "metric", "rsi_14", "RSI-14",
         "Relative Strength Index over 14 days using Wilder's smoothed moving average. "
         "Measures momentum: >70 = overbought (extended, review exposure), "
         "<30 = oversold (potential entry), 40–60 = neutral.",
         "100 - (100 / (1 + RS)) where RS = Wilder EMA(gains,14) / Wilder EMA(losses,14)",
         "Alpha Vantage (close price)", "Analytics Engineering", "internal"),

        ("def_ema_sma", "metric", "macro_ema_sma", "EMA vs SMA 3m",
         "3-month Exponential Moving Average vs Simple Moving Average of the Fed Funds Rate. "
         "EMA responds faster to recent rate moves. "
         "EMA above SMA = rate accelerating (tightening regime). "
         "EMA below SMA = rate decelerating (easing regime).",
         "EMA: α=2/(3+1) applied to monthly FEDFUNDS. SMA: 3-month simple average.",
         "FRED (FEDFUNDS)", "Analytics Engineering", "internal"),

        ("def_sharpe", "metric", "sharpe_20d", "Sharpe Ratio 20d",
         "Risk-adjusted return over a 20-day rolling window, annualised. "
         "Measures excess return above the risk-free rate per unit of volatility. "
         ">1 = good risk-adjusted return. 0–1 = acceptable. <0 = risk not compensated.",
         "MEAN(daily_return - FEDFUNDS/252) / STDDEV(excess_return) × √252",
         "Alpha Vantage (close) + FRED (FEDFUNDS as risk-free rate)",
         "Analytics Engineering", "internal"),

        ("def_mdd", "metric", "mdd_90d", "Max Drawdown 90d",
         "Worst peak-to-trough percentage loss over a 90-day rolling window. "
         "Standard downside risk measure used in portfolio risk management. "
         ">-10% = controlled. -10% to -20% = elevated — review position sizing. "
         "<-20% = critical — immediate review required.",
         "(close - rolling_peak_90d) / rolling_peak_90d × 100, minimum over window",
         "Alpha Vantage (close price)", "Analytics Engineering", "internal"),

        ("def_vol", "metric", "volatility_20d", "Volatility 20d",
         "Annualised standard deviation of daily returns over 20 days. "
         "Measures market risk level. "
         "<12% = low volatility regime. 12–20% = normal. >20% = elevated. >30% = crisis.",
         "STDDEV(daily_return, 20d) × √252 × 100",
         "Alpha Vantage (close price)", "Analytics Engineering", "internal"),

        ("def_vwap_eff", "metric", "vwap_efficiency", "VWAP Efficiency",
         "How consistently price stays near its volume-weighted fair value over 20 days. "
         "100 = price always at VWAP (perfect efficiency). "
         ">97 = orderly market. 94–97 = normal. <94 = persistent deviation "
         "(momentum or mean-reversion signal depending on RSI direction).",
         "100 - AVG(ABS(close - vwap_20d) / vwap_20d × 100, 20d)",
         "Alpha Vantage (close + OHLCV)", "Analytics Engineering", "internal"),

        ("def_spread", "metric", "yield_spread", "Yield Curve Spread",
         "10-Year Treasury yield (GS10) minus Fed Funds Rate (FEDFUNDS). "
         "Positive and widening = bond market pricing future rate cuts — historically "
         "supportive for equities. Negative (inverted) = yield curve inversion — "
         "historically precedes US recession. Standard macro risk indicator.",
         "GS10 - FEDFUNDS (both monthly, joined on month)",
         "FRED (GS10 + FEDFUNDS)", "Analytics Engineering", "internal"),

        ("def_close", "field", "close", "Close Price",
         "Daily adjusted closing price of the index or ETF.",
         None, "Alpha Vantage (TIME_SERIES_DAILY)", "Analytics Engineering", "internal"),

        ("def_volume", "field", "volume", "Volume",
         "Daily trading volume — number of shares/units traded.",
         None, "Alpha Vantage (TIME_SERIES_DAILY)", "Analytics Engineering", "internal"),

        ("def_fedfunds", "field", "macro_value", "Fed Funds Rate",
         "US Federal Funds Effective Rate — the overnight interbank lending rate "
         "set by the Federal Reserve. Used as the risk-free rate in Sharpe Ratio "
         "calculations (FEDFUNDS / 252 = daily risk-free rate).",
         None, "FRED series: FEDFUNDS (monthly)", "Analytics Engineering", "internal"),

        ("def_gs10", "field", "gs10_value", "10Y Treasury Yield (GS10)",
         "US 10-Year Treasury Constant Maturity Rate. "
         "Used to compute yield curve spread against Fed Funds Rate.",
         None, "FRED series: GS10 (monthly)", "Analytics Engineering", "internal"),

        ("def_bronze", "layer", "bronze", "Bronze Layer",
         "Raw data exactly as received from the API. Immutable — never edited after write. "
         "One parquet file per source per run, named with date. The audit trail.",
         None, "data/bronze/*.parquet", "Analytics Engineering", "internal"),

        ("def_silver", "layer", "silver", "Silver Layer",
         "Cleaned, joined, and timezone-normalised data. "
         "Single source of truth for all downstream consumers. "
         "No direct bronze reads permitted in dashboard or gold layer.",
         None, "DuckDB views over bronze parquet", "Analytics Engineering", "internal"),

        ("def_gold", "layer", "gold", "Gold Layer",
         "Computed metrics and business KPIs, dashboard-ready. "
         "The only permitted data source for the Streamlit dashboard.",
         None, "DuckDB views over silver", "Analytics Engineering", "internal"),
    ]

    for row in definitions:
        con.execute("""
            INSERT OR IGNORE INTO governance_definitions
            (definition_id, category, name, display_name, definition,
             formula, source, owner, sensitivity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, list(row))

    lineage = [
        ("lin_001", "Alpha Vantage API", "external", "bronze_av", "bronze",
         "Fetch TIME_SERIES_DAILY for SYMBOL. Retry 3x. Schema validate. Write parquet.",
         "B1, B2, B3", "daily 07:00"),

        ("lin_002", "FRED API (FEDFUNDS)", "external", "bronze_fred", "bronze",
         "Fetch series/observations for FEDFUNDS. Coerce '.' to null. Write parquet.",
         "B1, B3, B4", "daily 07:00"),

        ("lin_003", "FRED API (GS10)", "external", "bronze_fred_gs10", "bronze",
         "Fetch series/observations for GS10. Same pattern as FEDFUNDS.",
         "B1, B3, B4", "daily 07:00"),

        ("lin_004", "bronze_av", "bronze", "silver_market", "silver",
         "Null check close/volume. Date integrity. Join AV daily to FRED monthly "
         "on DATE_TRUNC('month', date). UTC normalise. Dimensional output.",
         "S1, S2, S3, S4, S5", "on pipeline run"),

        ("lin_005", "bronze_fred + bronze_fred_gs10", "bronze", "silver_market", "silver",
         "Join macro series to AV on month. Forward-fill for daily alignment.",
         "S4, S5", "on pipeline run"),

        ("lin_006", "silver_market", "silver", "gold_metrics", "gold",
         "Compute VWAP 20d, RSI-14 (Wilder), EMA 3m, SMA 3m, "
         "Sharpe 20d, MDD 90d, Volatility 20d, VWAP Efficiency, Yield Spread.",
         "G1, G2, G3, G4, G5", "on pipeline run"),

        ("lin_007", "gold_metrics", "gold", "dashboard/app.py", "dashboard",
         "Read-only. All charts, KPI scorecard, NBA rules evaluated against gold only.",
         None, "on dashboard load"),
    ]

    for row in lineage:
        con.execute("""
            INSERT OR IGNORE INTO governance_lineage
            (lineage_id, source_name, source_layer, target_name,
             target_layer, transform, dq_rules, schedule)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, list(row))


def get_run_id() -> str:
    return str(uuid.uuid4())


def log_audit_run(
    run_id: str,
    step: str,
    layer: str,
    status: str,
    rows_in: int = 0,
    rows_out: int = 0,
    rows_quarantined: int = 0,
    detail: str = "",
    started_at: datetime = None,
    finished_at: datetime = None,
) -> None:
    if started_at is None:
        started_at = datetime.now(timezone.utc)
    con = _get_connection()
    try:
        con.execute(
            """
            INSERT INTO audit_pipeline_runs
              (run_id, step, layer, status, rows_in, rows_out, rows_quarantined,
               detail, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                run_id, step, layer, status, rows_in, rows_out, rows_quarantined,
                detail, started_at, finished_at or datetime.now(timezone.utc),
            ],
        )
    except Exception as e:
        logger.error(
            "quality — log_audit_run failed run_id=%s step=%s: %s", run_id, step, e, exc_info=True
        )
        raise
    finally:
        con.close()


def log_dq_result(
    run_id: str,
    layer: str,
    rule_id: str,
    status: str,
    rows_affected: int = 0,
    detail: str = "",
) -> None:
    con = _get_connection()
    try:
        rows_affected = int(rows_affected)
        con.execute(
            """
            INSERT INTO audit_dq_results
              (run_id, layer, rule_id, status, rows_affected, detail, evaluated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [run_id, layer, rule_id, status, rows_affected, detail,
             datetime.now(timezone.utc)],
        )
        level = logging.WARNING if status == "FAIL" else logging.INFO
        logger.log(level, "DQ %s layer=%s rule=%s rows_affected=%d %s",
                   status, layer, rule_id, rows_affected, detail)
    except Exception as e:
        logger.error(
            "quality — log_dq_result failed run_id=%s rule=%s: %s", run_id, rule_id, e, exc_info=True
        )
        raise
    finally:
        con.close()


def quarantine(
    run_id: str,
    rule_id: str,
    records: list[dict],
    reason: str,
    total_rows_in_run: int,
) -> None:
    """Write failed records to quarantine_records. Halt if >10% of run rows are quarantined."""
    if not records:
        return

    con = _get_connection()
    try:
        for record in records:
            con.execute(
                """
                INSERT INTO quarantine_records
                  (quarantine_id, run_id, rule_id, raw_record, reason, quarantine_timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    str(uuid.uuid4()), run_id, rule_id,
                    json.dumps(record, default=str),
                    reason,
                    datetime.now(timezone.utc),
                ],
            )

        quarantined_count = con.execute(
            "SELECT COUNT(*) FROM quarantine_records WHERE run_id = ?", [run_id]
        ).fetchone()[0]

        logger.warning(
            "quarantine — run_id=%s rule=%s quarantined=%d reason=%s",
            run_id, rule_id, len(records), reason,
        )

        if total_rows_in_run > 0:
            ratio = quarantined_count / total_rows_in_run
            if ratio > QUARANTINE_THRESHOLD:
                msg = (
                    f"HALT: quarantine ratio {ratio:.1%} exceeds {QUARANTINE_THRESHOLD:.0%} "
                    f"threshold (run_id={run_id}, quarantined={quarantined_count}, "
                    f"total={total_rows_in_run})"
                )
                logger.error(msg)
                raise RuntimeError(msg)
    except RuntimeError:
        raise
    except Exception as e:
        logger.error(
            "quality — quarantine write failed run_id=%s rule=%s: %s", run_id, rule_id, e, exc_info=True
        )
        raise
    finally:
        con.close()


# Bootstrap on import
_bootstrap_tables()
