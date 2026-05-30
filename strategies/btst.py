"""
BTST Screener — runs weekdays at 3:00 PM IST.

Filters F&O stocks with:
  - Price change >= 5% vs previous close
  - Volume >= 1.5x 20-day average volume
  - Skips entirely if Nifty is down > 1% on the day
  - Close near high : Close >= 97% of day's high (no upper-wick rejection)
  - Prior trend     : 5-day net move between -3% and +3% (quiet before breakout)
  - Prior ADR       : Average daily range over last 5 days < 2% (stock was tight)


Saves results to btst_signals and triggers email.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import pytz

from data_pipeline.angel_client import AngelClient
from db.connection import get_cursor
from config import (
    BTST_MIN_PRICE_CHANGE_PCT, BTST_MIN_VOLUME_RATIO, BTST_NIFTY_DOWN_THRESHOLD,
    BTST_CLOSE_NEAR_HIGH_PCT, BTST_PRIOR_TREND_MIN_PCT, BTST_PRIOR_TREND_MAX_PCT,
    BTST_PRIOR_ADR_MAX_PCT,
)

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

NIFTY_TOKEN = "99926000"  # Angel One token for NIFTY 50 index

_MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def _last_thursday_of_month(year: int, month: int) -> date:
    first_next = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last_day = first_next - timedelta(days=1)
    return last_day - timedelta(days=(last_day.weekday() - 3) % 7)


def get_monthly_expiries(ref_date: date = None) -> tuple:
    """Returns (cur_expiry_str, next_expiry_str) as "DDMonYYYY" for Angel One API."""
    ref_date = ref_date or date.today()
    cur = _last_thursday_of_month(ref_date.year, ref_date.month)
    if ref_date > cur:
        m = ref_date.month % 12 + 1
        y = ref_date.year + (1 if ref_date.month == 12 else 0)
        cur = _last_thursday_of_month(y, m)
    m2 = cur.month % 12 + 1
    y2 = cur.year + (1 if cur.month == 12 else 0)
    nxt = _last_thursday_of_month(y2, m2)
    fmt = lambda d: f"{d.day:02d}{_MON[d.month - 1]}{d.year}"
    return fmt(cur), fmt(nxt)


def _atm_iv(greeks: list, atm_strike: float) -> Optional[float]:
    """Return IV of the ATM CE option from an option greeks list."""
    ce = [g for g in greeks if str(g.get("optionType", "")).upper() == "CE"]
    if not ce:
        return None
    closest = min(ce, key=lambda g: abs(float(g.get("strikePrice") or 0) - atm_strike))
    iv = closest.get("impliedVolatility")
    if iv is None:
        return None
    v = float(iv)
    return round(v, 2) if v > 0 else None


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
    Returns {symbol: (close, volume, high)} for target_date.
    Past dates are read from the OHLCV table; today uses the live Angel API.
    """
    target_date = target_date or date.today()

    if target_date < date.today():
        with get_cursor() as cur:
            cur.execute(
                "SELECT symbol, close, volume, high FROM ohlcv WHERE symbol = ANY(%s) AND date = %s",
                (symbols, target_date),
            )
            return {
                r["symbol"]: (float(r["close"]), int(r["volume"]), float(r["high"]))
                for r in cur.fetchall()
            }

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
                c = candles[-1]  # [timestamp, open, high, low, close, volume]
                results[symbol] = (float(c[4]), int(c[5]), float(c[2]))
        except Exception as e:
            logger.debug(f"Price fetch failed for {symbol}: {e}")
    return results


def get_prior_5d_stats(symbol: str, as_of: date = None) -> Optional[dict]:
    """Returns 5-day net move % and avg daily range % for the 5 days before as_of."""
    as_of = as_of or date.today()
    with get_cursor() as cur:
        cur.execute(
            "SELECT close, high, low FROM ohlcv WHERE symbol=%s AND date < %s ORDER BY date DESC LIMIT 5",
            (symbol, as_of),
        )
        rows = cur.fetchall()
    if len(rows) < 5:
        return None
    closes = [float(r["close"]) for r in rows]
    highs  = [float(r["high"])  for r in rows]
    lows   = [float(r["low"])   for r in rows]
    # rows[0] = most recent, rows[4] = 5 days ago
    net_move_pct = (closes[0] - closes[4]) / closes[4] * 100
    adr_pct      = sum((h - l) / c * 100 for h, l, c in zip(highs, lows, closes)) / 5
    return {"net_move_pct": net_move_pct, "adr_pct": adr_pct}


def _save_filter_stats(funnel: dict, target_date: date = None):
    target_date = target_date or date.today()
    sql = """
        INSERT INTO btst_filter_stats
            (date, scanned, no_price, missing_data, failed_price_chg,
             failed_volume, failed_near_high, failed_trend, failed_adr, passed)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (date) DO UPDATE SET
            scanned          = EXCLUDED.scanned,
            no_price         = EXCLUDED.no_price,
            missing_data     = EXCLUDED.missing_data,
            failed_price_chg = EXCLUDED.failed_price_chg,
            failed_volume    = EXCLUDED.failed_volume,
            failed_near_high = EXCLUDED.failed_near_high,
            failed_trend     = EXCLUDED.failed_trend,
            failed_adr       = EXCLUDED.failed_adr,
            passed           = EXCLUDED.passed
    """
    with get_cursor(commit=True) as cur:
        cur.execute(sql, (
            target_date,
            funnel["scanned"], funnel["no_price"], funnel["missing_data"],
            funnel["failed_price_chg"], funnel["failed_volume"], funnel["failed_near_high"],
            funnel["failed_trend"], funnel["failed_adr"], funnel["passed"],
        ))


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
        return [], {"nifty_gate": True, "scanned": 0, "no_price": 0, "missing_data": 0,
                    "failed_price_chg": 0, "failed_volume": 0, "failed_near_high": 0,
                    "failed_trend": 0, "failed_adr": 0, "passed": 0}

    fo_stocks = get_fo_stocks()
    logger.info(f"Scanning {len(fo_stocks)} F&O stocks...")

    current_prices = get_current_prices(client, fo_stocks, target_date)

    signals = []
    f_no_price = f_missing = f_price = f_volume = f_near_high = f_trend = f_adr = 0
    s_no_price: list = []
    s_missing:  list = []
    s_price:    list = []
    s_volume:   list = []
    s_near_high: list = []
    s_trend:    list = []
    s_adr:      list = []

    for symbol in fo_stocks:
        if symbol not in current_prices:
            f_no_price += 1
            s_no_price.append(symbol)
            continue
        close, volume, high = current_prices[symbol]
        prev_close = get_previous_close(symbol, as_of=target_date)
        avg_vol    = get_20d_avg_volume(symbol, as_of=target_date)

        if prev_close is None or avg_vol is None or avg_vol == 0:
            f_missing += 1
            s_missing.append(symbol)
            continue

        price_chg_pct = (close - prev_close) / prev_close * 100
        vol_ratio     = volume / avg_vol

        if price_chg_pct < BTST_MIN_PRICE_CHANGE_PCT:
            f_price += 1
            s_price.append({"symbol": symbol, "value": round(price_chg_pct, 2)})
            continue
        if vol_ratio < BTST_MIN_VOLUME_RATIO:
            f_volume += 1
            s_volume.append({"symbol": symbol, "value": round(vol_ratio, 2)})
            continue
        if high > 0 and close < BTST_CLOSE_NEAR_HIGH_PCT * high:
            f_near_high += 1
            s_near_high.append({"symbol": symbol, "value": round(close / high * 100, 1)})
            continue

        prior = get_prior_5d_stats(symbol, as_of=target_date)
        if prior is None:
            f_missing += 1
            s_missing.append(symbol)
            continue
        if not (BTST_PRIOR_TREND_MIN_PCT <= prior["net_move_pct"] <= BTST_PRIOR_TREND_MAX_PCT):
            f_trend += 1
            s_trend.append({"symbol": symbol, "value": round(prior["net_move_pct"], 2)})
            continue
        if prior["adr_pct"] >= BTST_PRIOR_ADR_MAX_PCT:
            f_adr += 1
            s_adr.append({"symbol": symbol, "value": round(prior["adr_pct"], 2)})
            continue

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

    funnel = {
        "scanned":          len(fo_stocks),
        "no_price":         f_no_price,
        "missing_data":     f_missing,
        "failed_price_chg": f_price,
        "failed_volume":    f_volume,
        "failed_near_high": f_near_high,
        "failed_trend":     f_trend,
        "failed_adr":       f_adr,
        "passed":           len(signals),
        # per-stock detail (not persisted to DB)
        "detail": {
            "no_price":         s_no_price,
            "missing_data":     s_missing,
            "failed_price_chg": s_price,
            "failed_volume":    s_volume,
            "failed_near_high": s_near_high,
            "failed_trend":     s_trend,
            "failed_adr":       s_adr,
        },
    }
    logger.info(
        "BTST funnel: scanned=%d no_price=%d missing=%d price=%d vol=%d near_high=%d trend=%d adr=%d passed=%d",
        funnel["scanned"], funnel["no_price"], funnel["missing_data"],
        funnel["failed_price_chg"], funnel["failed_volume"], funnel["failed_near_high"],
        funnel["failed_trend"], funnel["failed_adr"], funnel["passed"],
    )
    _save_filter_stats(funnel, target_date)

    if signals:
        save_signals(signals, target_date)
        logger.info(f"Saved {len(signals)} BTST signals.")
    else:
        logger.info("No BTST signals.")

    # Enrich with stock names (single query)
    if signals:
        syms = [s["symbol"] for s in signals]
        with get_cursor() as cur:
            cur.execute("SELECT symbol, name FROM stocks WHERE symbol = ANY(%s)", (syms,))
            name_map = {r["symbol"]: r["name"] for r in cur.fetchall()}
        for sig in signals:
            sig["name"] = name_map.get(sig["symbol"]) or sig["symbol"]

    # Enrich with IV for current-month and next-month expiry (not saved to DB)
    if signals:
        expiry_cur, expiry_nxt = get_monthly_expiries(target_date)
        logger.info("Fetching IV for expiries %s / %s", expiry_cur, expiry_nxt)
        for sig in signals:
            sym, strike = sig["symbol"], sig["suggested_strike"]
            try:
                sig["iv_current_month"] = _atm_iv(client.get_option_greeks(sym, expiry_cur), strike)
            except Exception as e:
                logger.debug("IV cur failed %s: %s", sym, e)
                sig["iv_current_month"] = None
            try:
                sig["iv_next_month"] = _atm_iv(client.get_option_greeks(sym, expiry_nxt), strike)
            except Exception as e:
                logger.debug("IV nxt failed %s: %s", sym, e)
                sig["iv_next_month"] = None

    logger.info("=== BTST Screener completed ===")
    return signals, funnel


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from emailer.sender import send_btst_email
    sigs, _ = run()
    if sigs:
        send_btst_email(sigs)
