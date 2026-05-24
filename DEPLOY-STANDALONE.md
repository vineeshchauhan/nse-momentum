# Deployment Guide — Fresh DO Setup

Use this guide when deploying to a DigitalOcean droplet that has **only Docker installed** — no existing postgres, no n8n, nothing else running.

This setup uses `docker-compose.standalone.yml` which creates and manages its own PostgreSQL container.

---

## Prerequisites

- A DigitalOcean droplet (Ubuntu 22.04+ recommended, minimum 1 GB RAM)
- Docker installed

If Docker is not yet installed:
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
docker --version   # verify
```

---

## Step 1 — Transfer files to the droplet

From your **Windows machine** (PowerShell). Replace `<KEY>`, `<DO_IP>`, and `<REMOTE_PATH>` with your values.

```powershell
$KEY    = "C:\Users\Vini\.ssh\id_rsa"   # your SSH private key
$DO     = "root@<DO_IP>"
$REMOTE = "<REMOTE_PATH>"               # e.g. /home/vineesh/apps/nse-momentum

# Create remote directory first
ssh -i $KEY $DO "mkdir -p $REMOTE"

scp -i $KEY C:\dev\nse-momentum\Dockerfile                     "${DO}:${REMOTE}/Dockerfile"
scp -i $KEY C:\dev\nse-momentum\.dockerignore                  "${DO}:${REMOTE}/.dockerignore"
scp -i $KEY C:\dev\nse-momentum\docker-compose.standalone.yml  "${DO}:${REMOTE}/docker-compose.standalone.yml"
scp -i $KEY C:\dev\nse-momentum\requirements.txt               "${DO}:${REMOTE}/requirements.txt"
scp -i $KEY C:\dev\nse-momentum\main.py                        "${DO}:${REMOTE}/main.py"
scp -i $KEY C:\dev\nse-momentum\config.py                      "${DO}:${REMOTE}/config.py"
scp -i $KEY C:\dev\nse-momentum\scheduler.py                   "${DO}:${REMOTE}/scheduler.py"
scp -r -i $KEY C:\dev\nse-momentum\data_pipeline               "${DO}:${REMOTE}/"
scp -r -i $KEY C:\dev\nse-momentum\db                          "${DO}:${REMOTE}/"
scp -r -i $KEY C:\dev\nse-momentum\emailer                     "${DO}:${REMOTE}/"
scp -r -i $KEY C:\dev\nse-momentum\strategies                  "${DO}:${REMOTE}/"
scp -r -i $KEY C:\dev\nse-momentum\scripts                     "${DO}:${REMOTE}/"
```

---

## Step 2 — Configure `.env`

SSH in and create the `.env` file:

```bash
ssh -i ~/.ssh/id_rsa root@<DO_IP>
cd <REMOTE_PATH>
cp .env.example .env
nano .env
```

Fill in all values:

```env
ANGEL_API_KEY=<from Angel One dashboard>
ANGEL_CLIENT_ID=<your client ID>
ANGEL_PASSWORD=<your login password>
ANGEL_TOTP_SECRET=<Base32 seed from Angel One TOTP setup — NOT a rotating code>

ANGEL_BASE_URL=
# Leave blank — the app calls Angel One directly from the DO server.
# DO's IP must be whitelisted in your Angel One API key settings.

DB_HOST=localhost
# DB_HOST in .env is ignored at runtime — docker-compose.standalone.yml injects
# DB_HOST=postgres automatically. Set to localhost for local dev convenience.

DB_PORT=5432
DB_NAME=trading
DB_USER=trading_user
DB_PASSWORD=<choose a strong password>

EMAIL_SENDER=your_gmail@gmail.com
EMAIL_PASSWORD=<Gmail app password — not your Gmail login password>
EMAIL_RECEIVER=recipient@example.com
```

---

## Step 3 — Build and start

```bash
cd <REMOTE_PATH>
docker compose -f docker-compose.standalone.yml up -d --build
```

This starts two containers:
- `trading_postgres` — PostgreSQL 16, initialised with your DB credentials
- `trading_app` — the scheduler, waits for postgres to be healthy before starting

Check both are running:
```bash
docker compose -f docker-compose.standalone.yml ps
docker logs trading_app
```

Expected log output:
```
Initialising database tables...
Tables created (or already exist).
Scheduler starting. Press Ctrl+C to stop.
  Registered: Daily OHLCV + BTST result update -> trigger: cron[hour='18', minute='0']
  Registered: BTST Screener -> trigger: cron[day_of_week='mon-fri', hour='15', minute='0']
  Registered: Weekly Momentum Portfolio -> trigger: cron[day_of_week='mon', hour='9', minute='0']
Scheduler started
```

---

## Step 4 — Seed historical data (one-time, ~30 min)

Run inside a `screen` session so it survives SSH disconnect:

```bash
screen -S seed
docker compose -f docker-compose.standalone.yml run --rm app python scripts/seed_historical.py
# Ctrl+A then D to detach
# screen -r seed to reattach and check progress
```

Verify data loaded:
```bash
docker exec -it trading_postgres psql -U trading_user -d trading -c "SELECT COUNT(*) FROM ohlcv;"
# Should show ~250,000+ rows after seed completes
```

---

## Ongoing operations

### View logs
```bash
docker logs -f trading_app
docker exec trading_app tail -f logs/trading.log
```

### Trigger jobs manually

```bash
# Daily OHLCV fetch + BTST result backfill
docker exec trading_app python -c "from data_pipeline.daily_batch import run; run()"

# BTST screener — today
docker exec trading_app python -c "from strategies.btst import run; from emailer.sender import send_btst_email; sigs = run(); send_btst_email(sigs) if sigs else None"

# BTST screener — specific past date (reads from OHLCV, no live API)
docker exec trading_app python -c "from datetime import date; from strategies.btst import run; from emailer.sender import send_btst_email; sigs = run(target_date=date(2026, 5, 20)); send_btst_email(sigs) if sigs else None"

# Weekly momentum portfolio
docker exec trading_app python -c "from strategies.momentum import run; from emailer.sender import send_momentum_email; r = run(); send_momentum_email(r['top30'], r['changes'], r['exits'], r['week_start'])"
```

### Redeploy after code changes

From Windows:
```powershell
# Copy changed files (example: emailer/sender.py changed)
scp -i $KEY C:\dev\nse-momentum\emailer\sender.py "${DO}:${REMOTE}/emailer/sender.py"
```

On the droplet:
```bash
cd <REMOTE_PATH>
docker compose -f docker-compose.standalone.yml up -d --build app
```

### Inspect the database
```bash
docker exec -it trading_postgres psql -U trading_user -d trading
```

### Stop everything
```bash
docker compose -f docker-compose.standalone.yml down
# To also delete all data (irreversible):
docker compose -f docker-compose.standalone.yml down -v
```

---

## Known issues

### Outbound SMTP blocked by DigitalOcean
DO blocks outbound ports 25, 465, and 587 on new droplets. The email sender will time out. Options:
- **Raise a DO support ticket** asking to unblock port 587 — they approve it for established accounts.
- **Switch to an HTTP email API** (SendGrid, Mailgun) — uses port 443 which is never blocked.

### Angel One IP whitelist
Angel One's API key is configured to accept requests only from the DO droplet's public IP. Update the allowed IP in the Angel One developer console whenever you change servers.

### TOTP secret
`ANGEL_TOTP_SECRET` is the static Base32 seed you scanned when setting up 2FA — it is not a rotating 6-digit code.
