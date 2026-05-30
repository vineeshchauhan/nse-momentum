import logging

from db.connection import get_cursor

logger = logging.getLogger(__name__)


def create_tables():
    ddl = """
    CREATE TABLE IF NOT EXISTS stocks (
        symbol      VARCHAR(20) PRIMARY KEY,
        name        VARCHAR(200),
        isin        VARCHAR(12),
        sector      VARCHAR(100),
        token       VARCHAR(20),
        is_fo       BOOLEAN DEFAULT FALSE,
        is_nifty500 BOOLEAN DEFAULT TRUE
    );
    -- migration: no-op if column already exists (idempotent on existing DBs)
    ALTER TABLE stocks ADD COLUMN IF NOT EXISTS token VARCHAR(20);

    CREATE TABLE IF NOT EXISTS ohlcv (
        symbol  VARCHAR(20)    NOT NULL,
        date    DATE           NOT NULL,
        open    NUMERIC(12,2),
        high    NUMERIC(12,2),
        low     NUMERIC(12,2),
        close   NUMERIC(12,2),
        volume  BIGINT,
        PRIMARY KEY (symbol, date)
    );

    CREATE INDEX IF NOT EXISTS idx_ohlcv_date ON ohlcv(date);

    CREATE TABLE IF NOT EXISTS btst_signals (
        id                SERIAL PRIMARY KEY,
        date              DATE           NOT NULL,
        symbol            VARCHAR(20)    NOT NULL,
        price_change_pct  NUMERIC(8,2),
        volume_ratio      NUMERIC(8,2),
        close_price       NUMERIC(12,2),
        suggested_strike  NUMERIC(12,2),
        result_next_day   NUMERIC(8,2),
        UNIQUE(date, symbol)
    );

    CREATE TABLE IF NOT EXISTS momentum_portfolio (
        week_start   DATE         NOT NULL,
        symbol       VARCHAR(20)  NOT NULL,
        rank         INTEGER      NOT NULL,
        momentum_1m  NUMERIC(8,2),
        entry_price  NUMERIC(12,2),
        exit_price   NUMERIC(12,2),
        PRIMARY KEY (week_start, symbol)
    );

    CREATE TABLE IF NOT EXISTS momentum_changes (
        week_start      DATE        NOT NULL,
        symbol          VARCHAR(20) NOT NULL,
        change_type     VARCHAR(20) NOT NULL,
        rank_current    INTEGER,
        rank_previous   INTEGER,
        momentum_1m     NUMERIC(8,2),
        PRIMARY KEY (week_start, symbol)
    );

    CREATE TABLE IF NOT EXISTS scheduler_runs (
        id           SERIAL PRIMARY KEY,
        job_id       VARCHAR(50)   NOT NULL,
        job_name     VARCHAR(100)  NOT NULL,
        started_at   TIMESTAMPTZ   NOT NULL,
        finished_at  TIMESTAMPTZ,
        status       VARCHAR(20)   NOT NULL,
        error_msg    TEXT,
        duration_s   NUMERIC(10,3),
        num_signals  INTEGER,
        email_sent   BOOLEAN DEFAULT FALSE
    );

    CREATE INDEX IF NOT EXISTS idx_scheduler_runs_started
        ON scheduler_runs(started_at DESC);
    """
    with get_cursor(commit=True) as cur:
        cur.execute(ddl)
    logger.info("Database tables created (or already exist).")


if __name__ == "__main__":
    create_tables()
