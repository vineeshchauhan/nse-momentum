# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

```bash
# Start everything (postgres + app) via Docker
docker compose up -d --build

# One-time historical backfill (~30 min for 500 stocks)
docker compose run --rm app python scripts/seed_historical.py

# Run strategies manually inside the running app container
docker exec trading_app python -c "from strategies.btst import run; from emailer.sender import send_btst_email; sigs = run(); send_btst_email(sigs) if sigs else None"
docker exec trading_app python -c "from strategies.momentum import run; from emailer.sender import send_momentum_email; r = run(); send_momentum_email(r['top30'], r['changes'], r['exits'], r['week_start'])"

# Run daily batch manually
docker exec trading_app python -c "from data_pipeline.daily_batch import run; run()"

# Inspect the database
docker exec -it trading_postgres psql -U trading_user -d trading

# View app logs
docker logs -f trading_app
# Or tail the persistent log file
docker exec trading_app tail -f logs/trading.log
```

## Architecture

All strategy parameters (thresholds, top-N, lookback days) live in `config.py` — that's the single place to tune them.

### Data flow

```
NSE archives CSV ──┐
                   ├─► nse_universe.build_universe() ──► stocks table
Angel instrument   ┘         (symbol → token mapping)
master JSON

Angel SmartAPI (getCandleData) ──► ohlcv table  (PRIMARY KEY: symbol + date)
```

`ohlcv` is the single source of truth for all price calculations. Both strategies read exclusively from it — no live price calls during strategy execution except BTST (which fetches the current day's intraday candle at 3 PM before market close).

### DB access pattern

`db/connection.py` exposes one primitive: `get_cursor(commit=False)` — a context manager that opens a connection, yields a `RealDictCursor`, and closes on exit. All rows come back as dicts. Pass `commit=True` for writes. There is no ORM and no connection pool — each call opens and closes a fresh connection.

### Strategy internals

**BTST** (`strategies/btst.py`): Requires a live Angel login because it fetches the current day's candle (market is open). Previous-close and 20-day average volume are read from `ohlcv`. The Nifty gate (`NIFTY_TOKEN = "99926000"`) is checked first — if Nifty is down >1% the entire run aborts. `result_next_day` on `btst_signals` is filled the following evening by `daily_batch.py`, not by the screener itself.

**Momentum** (`strategies/momentum.py`): Entirely DB-driven — no live API calls. The 1-month return is computed in a single window-function SQL query (rn=1 for latest close, rn=21 for 20 trading days ago). EXIT records are for stocks that *left* the top 30 and are written into `momentum_changes` alongside the current week's ENTRY/CONTINUATION rows.

### Email rendering

`emailer/sender.py` uses Jinja2 (`jinja2` package) loaded lazily. Templates are in `emailer/` next to `sender.py` — `TEMPLATE_DIR` is `Path(__file__).parent`. If Jinja2 is unavailable it falls back to naive `{{ var }}` string substitution (no loop support).

### NSE data fetching quirks

- Use `archives.nseindia.com` for the Nifty 500 CSV — the main `www.nseindia.com` domain blocks bots.
- The `_LaxTLSAdapter` in `nse_universe.py` (sets `SECLEVEL=1`) is required for NSE's TLS — Python 3.13's stricter OpenSSL defaults reject their ciphers.
- NSE's CSV contains `DUMMY*` placeholder symbols during index rebalancing — filtered out before processing.
- Angel One lists some stocks with series suffixes (`-EQ`, `-BE`, `-BZ`, etc.) — all stripped via regex `r"-[A-Z]{2}$"` before symbol matching.

### Scheduler

`scheduler.py` / `main.py` use APScheduler 3.x `BlockingScheduler`. Jobs are registered with `CronTrigger` and `misfire_grace_time`. All times are Asia/Kolkata. `next_run_time` is only available *after* `scheduler.start()` — do not access it before.

### Angel One authentication

`AngelClient.login()` calls `pyotp.TOTP(ANGEL_TOTP_SECRET).now()` to generate the TOTP code at runtime — `ANGEL_TOTP_SECRET` is the static Base32 seed, not a rotating code. The `_api` attribute is lazily initialised via the `api` property.

Angel One's API key is configured with the DO droplet's public IP as the allowed IP — the Dockerized app connects to Angel One directly (`https://apiconnect.angelbroking.com`), and the outbound traffic uses the droplet's IP so the IP whitelist is satisfied. Leave `ANGEL_BASE_URL` blank in `.env` (or unset it) to use the default.

### Deployment on DigitalOcean

The app and postgres both run as Docker containers on the DO droplet.

**First deploy:**
```bash
# On the DO droplet
git clone <repo> nse-momentum && cd nse-momentum
cp .env.example .env
# Fill in .env with real credentials
docker compose up -d --build
# One-time backfill
docker compose run --rm app python scripts/seed_historical.py
```

**Redeploy after code changes:**
```bash
git pull
docker compose up -d --build app
```

**Logs and monitoring:**
```bash
docker compose ps
docker logs -f trading_app
```
