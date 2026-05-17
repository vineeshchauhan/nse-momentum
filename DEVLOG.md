# NSE Momentum — Dev Log & Troubleshooting Reference

A record of every issue encountered during setup and the fix applied.

---

## Project Build

Built a Python-based algorithmic trading system for NSE India with:
- **Strategy 1 — BTST Screener**: runs weekdays at 3 PM IST, scans F&O stocks for >5% price move + >1.5x volume surge
- **Strategy 2 — Weekly Momentum Portfolio**: runs every Monday 9 AM IST, ranks Nifty 500 by 1-month return, selects top 30
- **Data pipeline**: Angel One SmartAPI for OHLCV, NSE archives for stock universe
- **Scheduler**: APScheduler with Asia/Kolkata timezone
- **Email**: smtplib + Jinja2 HTML templates

---

## Issue Log

---

### Issue 1 — pgAdmin4 unnecessary

**Question**: Why is pgAdmin4 in docker-compose?

**Answer**: It was only included as a convenience GUI for browsing tables. Not required by any code.

**Fix**: Removed the `pgadmin` service from `docker-compose.yml` entirely. Use `docker exec` instead if DB inspection is needed:
```bash
docker exec -it trading_postgres psql -U trading_user -d trading
```

---

### Issue 2 — Angel One TOTP in .env concern

**Question**: The app runs at 3 PM automatically. How is TOTP possible if it's in `.env`?

**Answer**: `ANGEL_TOTP_SECRET` is the static Base32 **seed** (e.g. `JBSWY3DPEHPK3PXP`), not the rotating 6-digit code. `pyotp.TOTP(secret).now()` generates the correct time-based code at runtime — exactly what Google Authenticator / Authy do internally.

```python
totp = pyotp.TOTP(ANGEL_TOTP_SECRET).now()   # generates fresh code every call
api.generateSession(CLIENT_ID, PASSWORD, totp)
```

No human input needed. The secret is static; the code is computed on the fly.

**Where to find it**: In the Angel One app → Profile → Two Factor Auth → "Can't scan? Enter manually" — that Base32 string is your `ANGEL_TOTP_SECRET`.

---

### Issue 3 — `psycopg2-binary==2.9.9` build failure

**Error**:
```
Error: pg_config executable not found.
psycopg2-binary==2.9.9 has no pre-built wheel for this Python/platform combination.
```

**Cause**: `psycopg2-binary==2.9.9` had no pre-built `.whl` for the installed Python version on Windows, so pip fell back to building from source — which requires PostgreSQL dev tools (`pg_config`).

**Fix** in `requirements.txt`:
```
# Before
psycopg2-binary==2.9.9

# After
psycopg2-binary>=2.9
```

---

### Issue 4 — `pandas==2.2.2` and `numpy==1.26.4` build failure

**Error**:
```
Could not find C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe
pandas==2.2.2 has no pre-built wheel for Python 3.13
```

**Cause**: `pandas==2.2.2` and `numpy==1.26.4` were released before Python 3.13 existed — no wheels published for `cp313`.

**Fix** in `requirements.txt`:
```
# Before
pandas==2.2.2
numpy==1.26.4

# After
pandas>=2.2.3
numpy>=2.0
```

---

### Issue 5 — `requests==2.31.0` conflicts with `langchain-community`

**Error**:
```
langchain-community 0.4.1 requires requests<3.0.0,>=2.32.5, but you have requests 2.31.0
```

**Cause**: `langchain-community` (pre-installed on the system for other projects) requires `requests>=2.32.5`.

**Fix** in `requirements.txt`:
```
# Before
requests==2.31.0

# After
requests>=2.31
```

---

### Issue 6 — NSE `www1.nseindia.com` SSL error

**Error**:
```
ssl.SSLError: [SSL: TLSV1_ALERT_INTERNAL_ERROR] tlsv1 alert internal error
```

**Cause**: Two problems:
1. `www1.nseindia.com` is an outdated domain — NSE moved the CSV to `archives.nseindia.com`
2. Python 3.13's stricter OpenSSL defaults (`SECLEVEL=2`) reject NSE's older cipher suites

**Fix in `nse_universe.py`**:

```python
# 1. Custom TLS adapter lowering security level to 1
class _LaxTLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

# 2. Updated URL
NSE_NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
```

`archives.nseindia.com` is a CDN-backed static server — no cookies, no anti-bot, just a plain CSV download.

---

### Issue 7 — NSE `www.nseindia.com` API returns encrypted/empty body

**During debugging**, the main NSE domain was tested as an alternative:
```
Homepage status: 403 | cookies: []
API status: 200
Body bytes[:20]: b'\xf0\xff\x03\x80\\\xa4\xb3z}U...'
```

**Cause**: NSE's main domain blocks automated requests (returns 403 on homepage, garbled binary on API). Cookies are never set, so the API response is unreadable.

**Conclusion**: `archives.nseindia.com` is the correct source — it requires no cookies and returns a clean CSV.

---

### Issue 8 — Only 499 stocks in DB instead of 500

**Cause**: Two problems in the pipeline:

1. **NSE CSV contains 4 dummy rows** — NSE adds `DUMMYVEDL1`, `DUMMYVEDL2`, `DUMMYVEDL3`, `DUMMYVEDL4` as placeholder entries during index rebalancing. The CSV had 504 rows, not 500.

2. **SCHNEIDER listed as `SCHNEIDER-BE`** in Angel One — the stock trades in the BE (Book Entry / Trade-to-Trade) series, not EQ. The original code only stripped `-EQ` suffixes, so `SCHNEIDER-BE` didn't match `SCHNEIDER` from NSE.

**Fix in `nse_universe.py`**:

```python
# Filter dummy placeholder rows
df = df[~df["symbol"].str.startswith("DUMMY")]

# Strip all NSE series suffixes (-EQ, -BE, -BZ, -SM, -IL, etc.)
nse_eq["symbol"] = nse_eq["symbol"].str.replace(r"-[A-Z]{2}$", "", regex=True).str.strip()
```

**Result**: NSE CSV: 504 rows → 500 after dummy filter. Angel token matches: 500/500.

---

### Issue 9 — `AttributeError: Job has no attribute 'next_run_time'`

**Error**:
```
AttributeError: 'apscheduler.job.Job' object has no attribute 'next_run_time'
```

**Cause**: In APScheduler 3.x, `next_run_time` is only populated after `scheduler.start()` is called. Jobs printed before `.start()` are in a "tentative" state with no run time assigned yet.

**Fix in `main.py`**:
```python
# Before
logger.info(f"  Registered: {job.name} → next run: {job.next_run_time}")

# After
logger.info(f"  Registered: {job.name} -> trigger: {job.trigger}")
```

---

### Issue 10 — `UnicodeEncodeError` on Windows terminal (arrow character)

**Error**:
```
UnicodeEncodeError: 'charmap' codec can't encode character '→' in position 88
```

**Cause**: The `→` arrow (`→`) can't be encoded by Windows cp1252 (the default terminal encoding).

**Fix in `main.py`**: Replace Unicode arrow with ASCII `->`:
```python
logger.info(f"  Registered: {job.name} -> trigger: {job.trigger}")
```

---

## Final Working State

```
python main.py
```

```
INFO  Initialising database tables...
INFO  Scheduler starting. Press Ctrl+C to stop.
INFO    Registered: Daily OHLCV + BTST result update -> trigger: cron[hour='18', minute='0']
INFO    Registered: BTST Screener -> trigger: cron[day_of_week='mon-fri', hour='15', minute='0']
INFO    Registered: Weekly Momentum Portfolio -> trigger: cron[day_of_week='mon', hour='9', minute='0']
INFO  Scheduler started
```

---

## Final `requirements.txt`

```
smartapi-python==1.3.9
psycopg2-binary>=2.9
python-dotenv==1.0.1
APScheduler==3.10.4
pyotp==2.9.0
requests>=2.31
pandas>=2.2.3
numpy>=2.0
websocket-client==1.7.0
logzero==1.7.0
jinja2==3.1.4
```

---

## Quick Reference — Key Design Decisions

| Decision | Reason |
|----------|--------|
| `archives.nseindia.com` for Nifty 500 CSV | Main domain blocks bots; archives CDN is open |
| `SECLEVEL=1` TLS adapter | NSE's servers use older ciphers rejected by Python 3.13 defaults |
| `pyotp` generates TOTP at runtime | Allows fully automated login without human input |
| `ON CONFLICT DO NOTHING` for OHLCV upserts | Makes seed script safely re-runnable |
| Strip all `-[A-Z]{2}` series suffixes | Angel One uses -EQ, -BE, -BZ etc.; NSE CSV has bare symbols |
| Filter `DUMMY*` symbols from NSE CSV | NSE adds placeholder rows during index rebalancing |
