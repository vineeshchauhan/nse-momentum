from db.connection import get_cursor


def create_tables():
    ddl = """
    CREATE TABLE IF NOT EXISTS stocks (
        symbol      VARCHAR(20) PRIMARY KEY,
        name        VARCHAR(200),
        isin        VARCHAR(12),
        sector      VARCHAR(100),
        is_fo       BOOLEAN DEFAULT FALSE,
        is_nifty500 BOOLEAN DEFAULT TRUE
    );

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
    """
    with get_cursor(commit=True) as cur:
        cur.execute(ddl)
    print("Tables created (or already exist).")


if __name__ == "__main__":
    create_tables()
