"""
Weekly Momentum Portfolio — runs every Monday at 9:00 AM IST.

1. Ranks all Nifty 500 stocks by 1-month return (today vs 20 trading days ago).
2. Selects top 30.
3. Compares with previous week's portfolio → NEW ENTRY / CONTINUATION / EXIT.
4. Logs to momentum_portfolio and momentum_changes tables.
"""
import logging
from datetime import date, timedelta
from typing import Optional

from db.connection import get_cursor

logger = logging.getLogger(__name__)


def get_week_start(as_of: date = None) -> date:
    today = as_of or date.today()
    return today - timedelta(days=today.weekday())  # Monday of current week


def get_momentum_scores(as_of: date = None) -> list:
    """
    Returns list of {symbol, momentum_1m, close_price} for all Nifty500 stocks
    that have enough history. Sorted descending by momentum_1m.
    as_of defaults to today; pass a past date to replay a historical run.
    """
    as_of = as_of or date.today()
    sql = """
        WITH latest AS (
            SELECT symbol, close AS close_now, date AS date_now,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
            FROM ohlcv
            WHERE date <= %s
        ),
        twenty_days_ago AS (
            SELECT symbol, close AS close_20d,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
            FROM ohlcv
            WHERE date <= %s
              AND (symbol, date) IN (
                  SELECT symbol, date
                  FROM (
                      SELECT symbol, date,
                             ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn2
                      FROM ohlcv
                      WHERE date <= %s
                  ) sub2
                  WHERE rn2 = 21
              )
        ),
        stocks_filter AS (
            SELECT symbol FROM stocks WHERE is_nifty500 = TRUE
        )
        SELECT
            l.symbol,
            l.close_now,
            t.close_20d,
            ROUND(((l.close_now - t.close_20d) / t.close_20d * 100)::numeric, 2) AS momentum_1m
        FROM latest l
        JOIN twenty_days_ago t ON l.symbol = t.symbol AND l.rn = 1 AND t.rn = 1
        JOIN stocks_filter sf ON l.symbol = sf.symbol
        WHERE t.close_20d > 0
        ORDER BY momentum_1m DESC
    """
    with get_cursor() as cur:
        cur.execute(sql, (as_of, as_of, as_of))
        return [dict(r) for r in cur.fetchall()]


def get_previous_portfolio(week_start: date) -> dict:
    """Returns {symbol: rank} for the portfolio from the week before week_start."""
    prev_week = week_start - timedelta(weeks=1)
    with get_cursor() as cur:
        cur.execute(
            "SELECT symbol, rank FROM momentum_portfolio WHERE week_start = %s",
            (prev_week,),
        )
        return {r["symbol"]: r["rank"] for r in cur.fetchall()}


def save_portfolio(week_start: date, top30: list):
    """top30: list of {symbol, rank, momentum_1m, entry_price}"""
    sql = """
        INSERT INTO momentum_portfolio (week_start, symbol, rank, momentum_1m, entry_price)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (week_start, symbol) DO UPDATE SET
            rank        = EXCLUDED.rank,
            momentum_1m = EXCLUDED.momentum_1m,
            entry_price = EXCLUDED.entry_price
    """
    rows = [(week_start, s["symbol"], s["rank"], s["momentum_1m"], s["entry_price"]) for s in top30]
    with get_cursor(commit=True) as cur:
        cur.executemany(sql, rows)


def save_changes(week_start: date, changes: list):
    sql = """
        INSERT INTO momentum_changes
            (week_start, symbol, change_type, rank_current, rank_previous, momentum_1m)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (week_start, symbol) DO UPDATE SET
            change_type   = EXCLUDED.change_type,
            rank_current  = EXCLUDED.rank_current,
            rank_previous = EXCLUDED.rank_previous,
            momentum_1m   = EXCLUDED.momentum_1m
    """
    rows = [
        (week_start, c["symbol"], c["change_type"],
         c["rank_current"], c["rank_previous"], c["momentum_1m"])
        for c in changes
    ]
    with get_cursor(commit=True) as cur:
        cur.executemany(sql, rows)


def mark_exits(week_start: date, prev_portfolio: dict, current_symbols: set, scores: dict):
    """Insert EXIT records for stocks that left the top 30."""
    exits = []
    for symbol, prev_rank in prev_portfolio.items():
        if symbol not in current_symbols:
            exits.append({
                "symbol":       symbol,
                "change_type":  "EXIT",
                "rank_current": None,
                "rank_previous": prev_rank,
                "momentum_1m":  scores.get(symbol, {}).get("momentum_1m"),
            })
    return exits


def get_sector(symbol: str) -> Optional[str]:
    with get_cursor() as cur:
        cur.execute("SELECT sector FROM stocks WHERE symbol = %s", (symbol,))
        row = cur.fetchone()
        return row["sector"] if row else None


def run(as_of_date: date = None) -> dict:
    """
    Runs momentum strategy. Returns dict with:
      week_start, top30 (list), changes (list), exits (list)
    Pass as_of_date to replay a historical run (e.g. a missed Monday).
    """
    logger.info(f"=== Weekly Momentum started (as_of: {as_of_date or date.today()}) ===")
    week_start = get_week_start(as_of_date)

    scores = get_momentum_scores(as_of_date)
    if not scores:
        logger.error("No momentum scores — is OHLCV data loaded?")
        return {}

    top30_raw = scores[:30]
    score_map = {s["symbol"]: s for s in scores}

    prev_portfolio = get_previous_portfolio(week_start)
    prev_symbols   = set(prev_portfolio.keys())

    top30 = []
    changes = []

    for rank, s in enumerate(top30_raw, 1):
        symbol = s["symbol"]
        entry_price = float(s["close_now"])
        change_type = "NEW ENTRY" if symbol not in prev_symbols else "CONTINUATION"
        sector = get_sector(symbol)

        top30.append({
            "rank":        rank,
            "symbol":      symbol,
            "momentum_1m": float(s["momentum_1m"]),
            "entry_price": entry_price,
            "change_type": change_type,
            "sector":      sector,
            "rank_previous": prev_portfolio.get(symbol),
        })
        changes.append({
            "symbol":       symbol,
            "change_type":  change_type,
            "rank_current": rank,
            "rank_previous": prev_portfolio.get(symbol),
            "momentum_1m":  float(s["momentum_1m"]),
        })

    current_symbols = {s["symbol"] for s in top30}
    exits = mark_exits(week_start, prev_portfolio, current_symbols, score_map)

    save_portfolio(week_start, top30)
    all_changes = changes + exits
    save_changes(week_start, all_changes)

    logger.info(
        f"Portfolio saved: {len(top30)} stocks, "
        f"{sum(1 for c in changes if c['change_type']=='NEW ENTRY')} new entries, "
        f"{len(exits)} exits."
    )
    logger.info("=== Weekly Momentum completed ===")

    return {
        "week_start": week_start,
        "top30":      top30,
        "changes":    changes,
        "exits":      exits,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from emailer.sender import send_momentum_email
    result = run()
    if result:
        send_momentum_email(result["top30"], result["changes"], result["exits"], result["week_start"])
