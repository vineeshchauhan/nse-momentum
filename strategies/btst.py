"""
BTST Screener — runs weekdays at 3:00 PM IST.

Filters F&O stocks with:
  - Price change >= 5% vs previous close
  - Volume >= 1.5x 20-day average volume
  - Skips entirely if Nifty is down > 1% on the day

Saves results to btst_signals and triggers email.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import pytz

from data_pipeline.angel_client import AngelClient
from db.connection import get_cursor
from config import BTST_MIN_PRICE_CHANGE_PCT, BTST_MIN_VOLUME_RATIO, BTST_NIFTY_DOWN_THRESHOLD

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

NIFTY_TOKEN = "99926000"  # Angel One token for NIFTY 50 index


def get_nifty_change(client: AngelClient, target_date: date = None) -> float:
    """Returns Nifty 50 % change from previous close for target_date."""
    target_date = target_date or date.today()
    try:
        yesterday = target_date - timedelta(days=1)
        from_dt = yesterday.strftime("%Y-%m-%d") + " 09:00"
        to_dt   = target_date.strftime("%Y-%m-%d") + " 15:00"
        candles = client.get_candle_data(NIFTY_TOKEN, "NSE", "ONE_DAY", from_dt, to_dt)
        if len(candles) < 2:
            return 0.0
        prev_close = float(candles[-2][4])
        curr_close = float(candles[-1][4])
        return (curr_close - prev_close) / prev_close * 100
    except Exception as e:
        logger.warning(f"Could not fetch Nifty level: {e}")
        return 0.0


def get_fo_stocks() -> list:
    with get_cursor() as cur:
        cur.execute("SELECT symbol FROM stocks WHERE is_fo = TRUE AND is_nifty500 = TRUE")
        return [r["symbol"] for r in cur.fetchall()]


def get_previous_close(symbol: str, as_of: date = None) -> Optional[float]:
    as_of = as_of or date.today()
    with get_cursor() as cur:
        cur.execute(
            "SELECT close FROM ohlcv WHERE symbol=%s AND date < %s ORDER BY date DESC LIMIT 1",
            (symbol, as_of),
        )
        row = cur.fetchone()
        return float(row["close"]) if row else None


def get_20d_avg_volume(symbol: str, as_of: date = None) -> Optional[float]:
    as_of = as_of or date.today()
    with get_cursor() as cur:
        cur.execute(
            """SELECT AVG(volume) as avg_vol FROM (
                SELECT volume FROM ohlcv
                WHERE symbol=%s AND date < %s
                ORDER BY date DESC LIMIT 20
            ) sub""",
            (symbol, as_of),
        )
        row = cur.fetchone()
        return float(row["avg_vol"]) if row and row["avg_vol"] else None


def suggest_atm_call_strike(close_price: float) -> float:
    """Round to nearest 50 for index stocks, 10 otherwise."""
    step = 50 if close_price > 5000 else 10
    return round(close_price / step) * step


def get_current_prices(client: AngelClient, symbols: list, target_date: date = None) -> dict:
    """
    Returns {symbol: (close, volume)} for target_date.
    Past dates are read from the OHLCV table; today uses the live Angel API.
    """
    target_date = target_date or date.today()

    if target_date < date.today():
        with get_cursor() as cur:
            cur.execute(
                "SELECT symbol, close, volume FROM ohlcv WHERE symbol = ANY(%s) AND date = %s",
                (symbols, target_date),
            )
            return {r["symbol"]: (float(r["close"]), int(r["volume"])) for r in cur.fetchall()}

    from_dt = target_date.strftime("%Y-%m-%d") + " 09:00"
    to_dt   = target_date.strftime("%Y-%m-%d") + " 15:10"

    with get_cursor() as cur:
        cur.execute(
            "SELECT symbol, token FROM stocks WHERE symbol = ANY(%s)",
            (symbols,),
        )
        token_map = {r["symbol"]: str(r["token"]) for r in cur.fetchall() if r.get("token")}

    results = {}
    for symbol in symbols:
        token = token_map.get(symbol)
        if not token:
            continue
        try:
            candles = client.get_candle_data(token, "NSE", "ONE_DAY", from_dt, to_dt)
            if candles:
                c = candles[-1]
                results[symbol] = (float(c[4]), int(c[5]))
        except Exception as e:
            logger.debug(f"Price fetch failed for {symbol}: {e}")
    return results


def save_signals(signals: list, target_date: date = None):
    target_date = target_date or date.today()
    sql = """
        INSERT INTO btst_signals
            (date, symbol, price_change_pct, volume_ratio, close_price, suggested_strike)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (date, symbol) DO UPDATE SET
            price_change_pct = EXCLUDED.price_change_pct,
            volume_ratio     = EXCLUDED.volume_ratio,
            close_price      = EXCLUDED.close_price,
            suggested_strike = EXCLUDED.suggested_strike
    """
    rows = [
        (target_date, s["symbol"], s["price_change_pct"], s["volume_ratio"],
         s["close_price"], s["suggested_strike"])
        for s in signals
    ]
    with get_cursor(commit=True) as cur:
        cur.executemany(sql, rows)


def run(target_date: date = None) -> list:
    """
    Executes BTST screen. Returns list of signal dicts (also saved to DB).
    Returns empty list if Nifty gate fails.
    Pass target_date to run for a historical date (prices read from OHLCV table).
    """
    target_date = target_date or date.today()
    logger.info(f"=== BTST Screener started (target: {target_date}) ===")
    client = AngelClient()
    client.login()

    nifty_chg = get_nifty_change(client, target_date)
    logger.info(f"Nifty change on {target_date}: {nifty_chg:.2f}%")
    if nifty_chg <= BTST_NIFTY_DOWN_THRESHOLD:
        logger.warning(f"Nifty is down {nifty_chg:.2f}% — skipping BTST screen.")
        return []

    fo_stocks = get_fo_stocks()
    logger.info(f"Scanning {len(fo_stocks)} F&O stocks...")

    current_prices = get_current_prices(client, fo_stocks, target_date)

    signals = []
    for symbol in fo_stocks:
        if symbol not in current_prices:
            continue
        close, volume = current_prices[symbol]
        prev_close = get_previous_close(symbol, as_of=target_date)
        avg_vol    = get_20d_avg_volume(symbol, as_of=target_date)

        if prev_close is None or avg_vol is None or avg_vol == 0:
            continue

        price_chg_pct = (close - prev_close) / prev_close * 100
        vol_ratio     = volume / avg_vol

        if price_chg_pct >= BTST_MIN_PRICE_CHANGE_PCT and vol_ratio >= BTST_MIN_VOLUME_RATIO:
            signals.append({
                "symbol":           symbol,
                "price_change_pct": round(price_chg_pct, 2),
                "volume_ratio":     round(vol_ratio, 2),
                "close_price":      close,
                "suggested_strike": suggest_atm_call_strike(close),
                "stop_loss":        round(close * 0.98, 2),
            })

    # Sort by volume ratio descending
    signals.sort(key=lambda x: x["volume_ratio"], reverse=True)

    if signals:
        save_signals(signals, target_date)
        logger.info(f"Saved {len(signals)} BTST signals.")
    else:
        logger.info("No BTST signals.")

    logger.info("=== BTST Screener completed ===")
    return signals


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from emailer.sender import send_btst_email
    sigs = run()
    if sigs:
        send_btst_email(sigs)
