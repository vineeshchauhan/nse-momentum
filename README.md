# NSE Momentum Trading System

Python-based algorithmic trading system for NSE India.  
Strategies: BTST Screener + Weekly Momentum Portfolio (Nifty 500).

---

## Prerequisites

- Python 3.11+
- Docker + Docker Compose
- Angel One account with SmartAPI access (get API key from [smartapi.angelbroking.com](https://smartapi.angelbroking.com))
- Gmail account with an **App Password** enabled (not your regular password)

---

## Setup

### 1. Clone and configure environment

```bash
git clone <repo-url>
cd nse-momentum
cp .env.example .env
```

Edit `.env` and fill in all values:

```env
ANGEL_API_KEY=your_api_key
ANGEL_CLIENT_ID=your_client_id
ANGEL_PASSWORD=your_password
ANGEL_TOTP_SECRET=your_totp_base32_secret

DB_HOST=localhost
DB_PORT=5432
DB_NAME=trading
DB_USER=trading_user
DB_PASSWORD=your_secure_password

EMAIL_SENDER=your@gmail.com
EMAIL_PASSWORD=your_gmail_app_password
EMAIL_RECEIVER=recipient@example.com
```

> **TOTP Secret**: In the Angel One app, go to Profile → Two Factor Auth → show the Base32 secret (not the QR code URL).

### 2. Start PostgreSQL + pgAdmin

```bash
docker-compose up -d
```

- PostgreSQL is available at `localhost:5432`

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

> Add `jinja2` to requirements if email rendering is needed: `pip install jinja2`

### 4. Seed historical data (one-time)

Backfills 1 year of daily OHLCV for all ~500 Nifty 500 stocks.  
Takes ~30–45 minutes due to Angel One rate limits.

```bash
python scripts/seed_historical.py
```

### 5. Start the scheduler

```bash
python main.py
```

The scheduler runs continuously and fires jobs at:

| Job | Schedule |
|-----|----------|
| Daily OHLCV fetch + BTST result update | Every day at 6:00 PM IST |
| BTST Screener + email | Mon–Fri at 3:00 PM IST |
| Momentum Portfolio + email | Every Monday at 9:00 AM IST |

---

## Running on a Server (DigitalOcean Droplet)

```bash
# Install dependencies
sudo apt update && sudo apt install -y python3-pip docker.io docker-compose

# Clone and setup
git clone <repo-url> /opt/nse-momentum
cd /opt/nse-momentum
cp .env.example .env
# Edit .env

# Start DB
docker-compose up -d

# Seed historical data
python3 scripts/seed_historical.py

# Run as background process (use screen or systemd)
screen -S trading
python3 main.py
# Detach: Ctrl+A, D
```

To run as a systemd service, create `/etc/systemd/system/nse-trading.service`:

```ini
[Unit]
Description=NSE Momentum Trading System
After=docker.service

[Service]
WorkingDirectory=/opt/nse-momentum
ExecStart=/usr/bin/python3 main.py
Restart=always
User=ubuntu

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable nse-trading
sudo systemctl start nse-trading
```

---

## Manual Execution

Run individual strategies outside the scheduler:

```bash
# Run daily batch manually
python -c "from data_pipeline.daily_batch import run; run()"

# Run BTST screener manually
python -c "from strategies.btst import run; from emailer.sender import send_btst_email; sigs = run(); send_btst_email(sigs) if sigs else None"

# Run momentum strategy manually
python -c "from strategies.momentum import run; from emailer.sender import send_momentum_email; r = run(); send_momentum_email(r['top30'], r['changes'], r['exits'], r['week_start'])"
```

---

## Project Structure

```
nse-momentum/
├── .env                        # Your credentials (never commit this)
├── .env.example                # Template for credentials
├── docker-compose.yml          # PostgreSQL + pgAdmin
├── requirements.txt
├── main.py                     # Entry point — starts scheduler
├── config.py                   # Loads env vars
├── scheduler.py                # APScheduler job definitions
├── db/
│   ├── connection.py           # psycopg2 connection helpers
│   └── models.py               # CREATE TABLE DDL
├── data_pipeline/
│   ├── angel_client.py         # Angel One SmartAPI wrapper
│   ├── nse_universe.py         # Nifty 500 list + token mapping
│   └── daily_batch.py          # Daily OHLCV + BTST result update
├── strategies/
│   ├── btst.py                 # BTST screener logic
│   └── momentum.py             # Weekly momentum portfolio logic
├── emailer/
│   ├── sender.py               # smtplib email sender + Jinja2 render
│   ├── btst_template.html      # BTST email HTML template
│   └── momentum_template.html  # Momentum email HTML template
└── scripts/
    └── seed_historical.py      # One-time 1-year OHLCV backfill
```

---

## Database Schema

| Table | Description |
|-------|-------------|
| `stocks` | Symbol master — name, ISIN, sector, F&O flag |
| `ohlcv` | Daily OHLCV for all Nifty 500 stocks |
| `btst_signals` | BTST screener output with next-day result |
| `momentum_portfolio` | Weekly top-30 portfolio snapshots |
| `momentum_changes` | NEW ENTRY / CONTINUATION / EXIT per week |

---

## Troubleshooting

**Angel login fails**: TOTP secret must be the raw Base32 string, not a URL or QR code.  
**No OHLCV data**: Run `seed_historical.py` first; daily_batch only fetches today's data.  
**Email not sent**: Ensure you're using a Gmail **App Password**, not your account password. Enable 2FA first.  
**NSE CSV fetch fails**: NSE rate-limits scrapers — the script sets a User-Agent and seeds cookies. Retry during off-peak hours.
