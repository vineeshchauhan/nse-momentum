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
            SELECT bs.date, bs.symbol, s.name,
                   bs.price_change_pct, bs.volume_ratio,
                   bs.close_price, bs.suggested_strike, bs.result_next_day
            FROM btst_signals bs
            LEFT JOIN stocks s ON s.symbol = bs.symbol
            WHERE bs.date >= CURRENT_DATE - %s
            ORDER BY bs.date DESC, bs.volume_ratio DESC
        """, (days,))
        return cur.fetchall()


def get_btst_filter_stats(days=30):
    with get_cursor() as cur:
        cur.execute("""
            SELECT date, scanned, no_price, missing_data, failed_price_chg,
                   failed_volume, failed_near_high, failed_trend, failed_adr, passed
            FROM btst_filter_stats
            WHERE date >= CURRENT_DATE - %s
            ORDER BY date DESC
        """, (days,))
        return cur.fetchall()


def get_btst_filter_detail(date_str, stage):
    with get_cursor() as cur:
        cur.execute("""
            SELECT fd.symbol, s.name, fd.value
            FROM btst_filter_detail fd
            LEFT JOIN stocks s ON s.symbol = fd.symbol
            WHERE fd.date = %s AND fd.filter_stage = %s
            ORDER BY fd.value DESC NULLS LAST
        """, (date_str, stage))
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
            SELECT mp.rank, mp.symbol, s.name, mp.momentum_1m, mp.entry_price,
                   mc.change_type, mc.rank_previous, s.sector
            FROM momentum_portfolio mp
            LEFT JOIN momentum_changes mc
                   ON mc.week_start = mp.week_start AND mc.symbol = mp.symbol
            LEFT JOIN stocks s ON s.symbol = mp.symbol
            WHERE mp.week_start = %s
            ORDER BY mp.rank
        """, (week_start,))
        return cur.fetchall()
