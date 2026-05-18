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
        logger.info("quality — audit tables bootstrapped")
    except Exception as e:
        logger.error("quality — failed to bootstrap tables: %s", e, exc_info=True)
        raise
    finally:
        con.close()


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
