"""
One-time script: backfill 1 year of daily OHLCV for all Nifty 500 stocks.
Also seeds the stocks table.

Usage:
    python scripts/seed_historical.py
"""
import sys
import logging
import time
from datetime import date, timedelta

sys.path.insert(0, ".")  # run from repo root

from data_pipeline.angel_client import AngelClient
from data_pipeline.nse_universe import build_universe
from db.connection import get_cursor
from db.models import create_tables

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
)
logger = logging.getLogger(__name__)

RATE_LIMIT_SLEEP = 0.35  # seconds between API calls to stay within limits


def seed_stocks(universe):
    sql = """
        INSERT INTO stocks (symbol, name, isin, sector, token, is_fo, is_nifty500)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol) DO UPDATE SET
            name        = EXCLUDED.name,
            isin        = EXCLUDED.isin,
            sector      = EXCLUDED.sector,
            token       = EXCLUDED.token,
            is_fo       = EXCLUDED.is_fo,
            is_nifty500 = EXCLUDED.is_nifty500
    """
    rows = [
        (
            r["symbol"], r.get("name"), r.get("isin"),
            r.get("sector"), str(r["token"]) if r.get("token") else None,
            bool(r.get("is_fo")), True,
        )
        for _, r in universe.iterrows()
    ]
    with get_cursor(commit=True) as cur:
        cur.executemany(sql, rows)
    logger.info(f"Seeded {len(rows)} stocks into stocks table.")


def seed_ohlcv(client: AngelClient, universe):
    today = date.today()
    one_year_ago = today - timedelta(days=365)
    from_dt = one_year_ago.strftime("%Y-%m-%d") + " 09:00"
    to_dt   = today.strftime("%Y-%m-%d") + " 15:35"

    upsert_sql = """
        INSERT INTO ohlcv (symbol, date, open, high, low, close, volume)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, date) DO NOTHING
    """

    total = len(universe)
    for idx, (_, row) in enumerate(universe.iterrows(), 1):
        symbol = row["symbol"]
        token  = str(row["token"])
        logger.info(f"[{idx}/{total}] Fetching {symbol}...")
        try:
            candles = client.get_candle_data(token, "NSE", "ONE_DAY", from_dt, to_dt)
            if not candles:
                logger.warning(f"  No data returned for {symbol}")
                continue
            rows = []
            for c in candles:
                # c = [timestamp_str, open, high, low, close, volume]
                day = c[0][:10]  # "YYYY-MM-DD"
                rows.append((symbol, day, float(c[1]), float(c[2]),
                              float(c[3]), float(c[4]), int(c[5])))
            with get_cursor(commit=True) as cur:
                cur.executemany(upsert_sql, rows)
            logger.info(f"  Inserted {len(rows)} candles for {symbol}")
        except Exception as e:
            logger.error(f"  Error for {symbol}: {e}")
        time.sleep(RATE_LIMIT_SLEEP)


def main():
    create_tables()

    logger.info("Building universe (Nifty 500 + Angel tokens)...")
    universe = build_universe()
    universe = universe.dropna(subset=["token"])
    logger.info(f"Universe size after token filter: {len(universe)}")

    seed_stocks(universe)

    client = AngelClient()
    client.login()
    seed_ohlcv(client, universe)
    logger.info("Historical seed complete.")


if __name__ == "__main__":
    main()
