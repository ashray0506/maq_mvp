"""
Benchmark test: DQ null logging — quarantine writes records and raises on >10% threshold.
Expected behaviour is structural — NOT derived from pipeline code.
"""

import os
import tempfile

import duckdb
import pytest

from pipeline.quality import log_dq_result, quarantine, _bootstrap_tables

# Use a temp DB for all tests so they don't pollute the real DB
@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_file = str(tmp_path / "test.duckdb")
    monkeypatch.setattr("pipeline.quality.DB_PATH", db_file)
    _bootstrap_tables()
    return db_file


def _count_quarantine(db_path: str, run_id: str) -> int:
    con = duckdb.connect(db_path, read_only=False)
    count = con.execute(
        "SELECT COUNT(*) FROM quarantine_records WHERE run_id = ?", [run_id]
    ).fetchone()[0]
    con.close()
    return count


def test_quarantine_writes_records(tmp_db):
    records = [{"date": "2024-01-01", "close": None, "volume": 1000}]
    quarantine("run-001", "S1", records, "null close", total_rows_in_run=100)
    assert _count_quarantine(tmp_db, "run-001") == 1


def test_quarantine_writes_multiple_records(tmp_db):
    records = [
        {"date": "2024-01-01", "close": None},
        {"date": "2024-01-02", "close": None},
        {"date": "2024-01-03", "close": None},
    ]
    quarantine("run-002", "S1", records, "null close", total_rows_in_run=100)
    assert _count_quarantine(tmp_db, "run-002") == 3


def test_quarantine_halts_above_10_percent(tmp_db):
    """11 records out of 100 = 11% — should raise RuntimeError."""
    records = [{"date": f"2024-01-{i:02d}", "close": None} for i in range(1, 12)]
    with pytest.raises(RuntimeError, match="HALT"):
        quarantine("run-003", "S1", records, "null close", total_rows_in_run=100)


def test_quarantine_does_not_halt_at_10_percent(tmp_db):
    """10 records out of 100 = exactly 10% — should NOT raise."""
    records = [{"date": f"2024-01-{i:02d}", "close": None} for i in range(1, 11)]
    quarantine("run-004", "S1", records, "null close", total_rows_in_run=100)
    assert _count_quarantine(tmp_db, "run-004") == 10


def test_log_dq_result_writes_pass_and_fail(tmp_db):
    log_dq_result("run-005", "silver", "S1", "PASS", 0, "no nulls")
    log_dq_result("run-005", "silver", "S2", "FAIL", 5, "5 rows failed")
    con = duckdb.connect(tmp_db, read_only=False)
    rows = con.execute(
        "SELECT rule_id, status FROM audit_dq_results WHERE run_id = 'run-005' ORDER BY rule_id"
    ).fetchall()
    con.close()
    assert rows == [("S1", "PASS"), ("S2", "FAIL")]
