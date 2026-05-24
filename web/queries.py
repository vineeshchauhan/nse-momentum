from db.connection import get_cursor


def get_recent_runs(days=30):
    with get_cursor() as cur:
        cur.execute("""
            SELECT job_id, job_name, started_at, finished_at,
                   status, error_msg, duration_s, num_signals, email_sent
            FROM scheduler_runs
            WHERE started_at >= NOW() - (INTERVAL '1 day' * %s)
            ORDER BY started_at DESC
        """, (days,))
        return cur.fetchall()


def get_btst_signals(days=30):
    with get_cursor() as cur:
        cur.execute("""
            SELECT date, symbol, price_change_pct, volume_ratio,
                   close_price, suggested_strike, result_next_day
            FROM btst_signals
            WHERE date >= CURRENT_DATE - %s
            ORDER BY date DESC, volume_ratio DESC
        """, (days,))
        return cur.fetchall()


def get_momentum_weeks():
    with get_cursor() as cur:
        cur.execute("""
            SELECT DISTINCT week_start FROM momentum_portfolio
            ORDER BY week_start DESC LIMIT 12
        """)
        return [r["week_start"] for r in cur.fetchall()]


def get_momentum_portfolio(week_start):
    with get_cursor() as cur:
        cur.execute("""
            SELECT mp.rank, mp.symbol, mp.momentum_1m, mp.entry_price,
                   mc.change_type, mc.rank_previous, s.sector
            FROM momentum_portfolio mp
            LEFT JOIN momentum_changes mc
                   ON mc.week_start = mp.week_start AND mc.symbol = mp.symbol
            LEFT JOIN stocks s ON s.symbol = mp.symbol
            WHERE mp.week_start = %s
            ORDER BY mp.rank
        """, (week_start,))
        return cur.fetchall()
