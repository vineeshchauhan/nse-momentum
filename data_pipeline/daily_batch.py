"""
Daily batch job — runs at 6 PM IST.
1. Fetches today's OHLCV for all Nifty 500 stocks and upserts into postgres.
2. Updates btst_signals.result_next_day for signals from yesterday.
"""
import logging
import time
from datetime import date, timedelta

from data_pipeline.angel_client import AngelClient
from data_pipeline.nse_universe import build_universe
from db.connection import get_cursor

logger = logging.getLogger(__name__)
RATE_LIMIT_SLEEP = 0.35  # seconds between Angel API calls


def replace_ohlcv(rows: list, target_date: date, symbol: str = None):
    """
    Delete existing rows for target_date (optionally filtered to one symbol),
    then insert fresh data. Ensures a clean re-run produces no stale rows.
    """
    with get_cursor(commit=True) as cur:
        if symbol:
            cur.execute("DELETE FROM ohlcv WHERE date = %s AND symbol = %s", (target_date, symbol))
        else:
            cur.execute("DELETE FROM ohlcv WHERE date = %s", (target_date,))
        deleted = cur.rowcount
        if deleted:
            logger.info(f"Deleted {deleted} existing OHLCV rows for {target_date}.")

        cur.executemany(
            """INSERT INTO ohlcv (symbol, date, open, high, low, close, volume)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            rows,
        )


def fetch_ohlcv_for_date(client: AngelClient, token: str, symbol: str, target_date: date) -> tuple | None:
    # Fetch a 3-day window around target_date — Angel One's ONE_DAY candles are
    # not returned reliably when from_date == to_date (same-day range).
    from_dt = (target_date - timedelta(days=1)).strftime("%Y-%m-%d") + " 09:00"
    to_dt   = (target_date + timedelta(days=1)).strftime("%Y-%m-%d") + " 15:35"
    target_str = target_date.strftime("%Y-%m-%d")
    try:
        candles = client.get_candle_data(token, "NSE", "ONE_DAY", from_dt, to_dt)
        for c in candles:
            if str(c[0])[:10] == target_str:
                return (symbol, target_date, float(c[1]), float(c[2]), float(c[3]), float(c[4]), int(c[5]))
        return None
    except Exception as e:
        logger.warning(f"Failed OHLCV fetch for {symbol}: {e}")
        return None


def update_btst_results(result_date: date, signal_date: date):
    """
    For btst_signals where date = signal_date and result_next_day IS NULL,
    fill result_next_day with result_date's actual return vs signal close_price.
    """
    sql_fetch = """
        SELECT bs.symbol, bs.close_price
        FROM btst_signals bs
        WHERE bs.date = %s AND bs.result_next_day IS NULL
    """
    with get_cursor() as cur:
        cur.execute(sql_fetch, (signal_date,))
        signals = cur.fetchall()

    if not signals:
        logger.info("No pending BTST results to update.")
        return

    updates = []
    with get_cursor() as cur:
        for sig in signals:
            cur.execute(
                "SELECT close FROM ohlcv WHERE symbol=%s AND date=%s",
                (sig["symbol"], result_date),
            )
            row = cur.fetchone()
            if row and sig["close_price"]:
                ret = (float(row["close"]) - float(sig["close_price"])) / float(sig["close_price"]) * 100
                updates.append((round(ret, 2), signal_date, sig["symbol"]))

    if updates:
        with get_cursor(commit=True) as cur:
            cur.executemany(
                "UPDATE btst_signals SET result_next_day=%s WHERE date=%s AND symbol=%s",
                updates,
            )
        logger.info(f"Updated result_next_day for {len(updates)} BTST signals.")


def run(target_date: date = None, symbol: str = None):
    target_date = target_date or date.today()
    signal_date = target_date - timedelta(days=1)

    logger.info(f"=== Daily batch started (target: {target_date}{f', symbol: {symbol}' if symbol else ''}) ===")
    client = AngelClient()
    client.login()

    universe = build_universe()
    universe = universe.dropna(subset=["token"])
    if symbol:
        universe = universe[universe["symbol"] == symbol.upper()]
        if universe.empty:
            logger.error(f"Symbol {symbol!r} not found in Nifty 500 universe.")
            return

    rows = []
    empty_count = 0
    for _, row in universe.iterrows():
        result = fetch_ohlcv_for_date(client, str(row["token"]), row["symbol"], target_date)
        if result:
            rows.append(result)
        else:
            empty_count += 1
        time.sleep(RATE_LIMIT_SLEEP)

    if rows:
        replace_ohlcv(rows, target_date, symbol=symbol)
        logger.info(f"Stored OHLCV for {len(rows)} stocks ({empty_count} returned no data).")
    else:
        logger.warning(
            f"No OHLCV rows to store — all {empty_count} stocks returned empty. "
            "Likely a market holiday or weekend."
        )

    update_btst_results(result_date=target_date, signal_date=signal_date)
    logger.info("=== Daily batch completed ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
