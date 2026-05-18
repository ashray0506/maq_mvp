"""
Register DuckDB views over bronze parquet files.
Views: bronze_av, bronze_fred, bronze_fred_gs10
Run after ingest.py.
"""

import logging
import os

import duckdb
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DB_PATH = "data/market.duckdb"
BRONZE_DIR = "data/bronze"
SYMBOL = os.environ["SYMBOL"]
FRED_SERIES = os.environ["FRED_SERIES"]
FRED_SERIES_2 = os.getenv("FRED_SERIES_2", "GS10")


def register_views() -> None:
    con = duckdb.connect(DB_PATH, read_only=False)
    try:
        av_glob = f"{BRONZE_DIR}/av_{SYMBOL}_*.parquet"
        fred_glob = f"{BRONZE_DIR}/fred_{FRED_SERIES}_*.parquet"
        fred_gs10_glob = f"{BRONZE_DIR}/fred_{FRED_SERIES_2}_*.parquet"

        con.execute(f"""
            CREATE OR REPLACE VIEW bronze_av AS
            SELECT * FROM read_parquet('{av_glob}')
        """)
        logger.info("registered view bronze_av → %s", av_glob)

        con.execute(f"""
            CREATE OR REPLACE VIEW bronze_fred AS
            SELECT * FROM read_parquet('{fred_glob}')
        """)
        logger.info("registered view bronze_fred → %s", fred_glob)

        con.execute(f"""
            CREATE OR REPLACE VIEW bronze_fred_gs10 AS
            SELECT * FROM read_parquet('{fred_gs10_glob}')
        """)
        logger.info("registered view bronze_fred_gs10 → %s", fred_gs10_glob)

        for view in ("bronze_av", "bronze_fred", "bronze_fred_gs10"):
            count = con.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
            logger.info("view %s: %d rows", view, count)

    except Exception as e:
        logger.error("register_bronze failed: %s", e, exc_info=True)
        raise
    finally:
        con.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler("logs/pipeline.log")],
    )
    register_views()
