# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

```bash
# Start PostgreSQL (required before anything else)
docker-compose up -d

# One-time historical backfill (~30 min for 500 stocks)
python scripts/seed_historical.py

# Start the scheduler (blocking — runs all jobs on cron)
python main.py

# Run strategies manually without the scheduler
python -c "from strategies.btst import run; from emailer.sender import send_btst_email; sigs = run(); send_btst_email(sigs) if sigs else None"
python -c "from strategies.momentum import run; from emailer.sender import send_momentum_email; r = run(); send_momentum_email(r['top30'], r['changes'], r['exits'], r['week_start'])"

# Run daily batch manually
python -c "from data_pipeline.daily_batch import run; run()"

# Inspect the database
docker exec -it trading_postgres psql -U trading_user -d trading
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

### Angel One proxy (DO server)

All SmartAPI calls are routed through a DigitalOcean droplet (`168.144.31.99`) running nginx, which forwards to Angel One's API. Angel One's API key is configured with the DO server's public IP as the allowed IP — direct calls from other IPs will be rejected.

**How routing works:**

```
Python code  →  http://168.144.31.99/rest/...
                        ↓ nginx proxy_pass
             https://apiconnect.angelbroking.com/rest/...
```

`ANGEL_BASE_URL=http://168.144.31.99` in `.env` is passed as `root=ANGEL_BASE_URL` to `SmartConnect()`. The SDK constructs all URLs relative to this root, so no other code changes are needed.

**nginx config on DO server** (`/etc/nginx/sites-available/angelone-proxy`):

```nginx
server {
    listen 80;
    server_name 168.144.31.99;

    location /rest/ {
        proxy_pass            https://apiconnect.angelbroking.com;
        proxy_ssl_server_name on;
        proxy_set_header      Host apiconnect.angelbroking.com;
        proxy_set_header      X-Real-IP $remote_addr;
        proxy_set_header      X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header      Authorization $http_authorization;
        proxy_pass_request_headers on;
        proxy_read_timeout    30s;
        proxy_redirect        off;
    }

    location /gtt-service/ {
        proxy_pass            https://apiconnect.angelbroking.com;
        proxy_ssl_server_name on;
        proxy_set_header      Host apiconnect.angelbroking.com;
        proxy_set_header      X-Real-IP $remote_addr;
        proxy_set_header      X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header      Authorization $http_authorization;
        proxy_pass_request_headers on;
        proxy_read_timeout    30s;
        proxy_redirect        off;
    }
}
```

Enable and reload on the DO server:
```bash
sudo ln -s /etc/nginx/sites-available/angelone-proxy /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

**Known issues / gotchas:**
- Port 443 is not configured on the DO server — proxy is HTTP-only on port 80.
- The `/rest/` upstream must be `apiconnect.angelbroking.com`, not `apiconnect.angelone.in` — the SmartConnect SDK defaults to the `.com` domain and Angel One may validate the Host header.
- If nginx returns its own 404 (not Angel One's), the config file is not symlinked in `sites-enabled` or nginx has not been reloaded.
- All SmartAPI routes use `/rest/` prefix except GTT orders which use `/gtt-service/rest/`.

**Test the proxy connection:**
```bash
python tests/test_angel_proxy.py
```
