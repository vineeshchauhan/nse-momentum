# Deployment Guide — Existing DO Setup

Use this guide when deploying to a DigitalOcean droplet that already has **n8n and PostgreSQL running as Docker containers**.

The trading app joins the existing `n8n_default` Docker network and uses the existing `n8n-postgres` container — no new postgres is created.

---

## Prerequisites

- Docker installed on the droplet
- `n8n-postgres` container running on the `n8n_default` Docker network
- SSH access to the droplet
- The `trading` database and user already created in the existing postgres (see step 3)

Verify the existing setup:
```bash
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}"
# Should show n8n-postgres and n8n

docker inspect n8n-postgres --format '{{json .NetworkSettings.Networks}}' | python3 -m json.tool
# Should show n8n_default network
```

---

## Step 1 — Transfer files to the droplet

From your **Windows machine** (PowerShell), copy the application files. Replace `<KEY>`, `<DO_IP>`, and `<REMOTE_PATH>` with your values.

```powershell
$KEY    = "C:\Users\Vini\.ssh\id_rsa"   # your SSH private key
$DO     = "root@<DO_IP>"
$REMOTE = "<REMOTE_PATH>"               # e.g. /home/vineesh/apps/nse-momentum

# Copy all source files (exclude .env — that stays on the server)
scp -i $KEY C:\dev\nse-momentum\Dockerfile              "${DO}:${REMOTE}/Dockerfile"
scp -i $KEY C:\dev\nse-momentum\.dockerignore           "${DO}:${REMOTE}/.dockerignore"
scp -i $KEY C:\dev\nse-momentum\docker-compose.yml      "${DO}:${REMOTE}/docker-compose.yml"
scp -i $KEY C:\dev\nse-momentum\requirements.txt        "${DO}:${REMOTE}/requirements.txt"
scp -i $KEY C:\dev\nse-momentum\main.py                 "${DO}:${REMOTE}/main.py"
scp -i $KEY C:\dev\nse-momentum\config.py               "${DO}:${REMOTE}/config.py"
scp -i $KEY C:\dev\nse-momentum\scheduler.py            "${DO}:${REMOTE}/scheduler.py"
scp -r -i $KEY C:\dev\nse-momentum\data_pipeline        "${DO}:${REMOTE}/"
scp -r -i $KEY C:\dev\nse-momentum\db                   "${DO}:${REMOTE}/"
scp -r -i $KEY C:\dev\nse-momentum\emailer              "${DO}:${REMOTE}/"
scp -r -i $KEY C:\dev\nse-momentum\strategies           "${DO}:${REMOTE}/"
scp -r -i $KEY C:\dev\nse-momentum\scripts              "${DO}:${REMOTE}/"
```

---

## Step 2 — Configure `.env`

SSH into the droplet and create the `.env` file if it doesn't exist:

```bash
ssh -i ~/.ssh/id_rsa root@<DO_IP>
cd <REMOTE_PATH>
cp .env.example .env
nano .env
```

Fill in all values. Key notes:

```env
ANGEL_API_KEY=<from Angel One dashboard>
ANGEL_CLIENT_ID=<your client ID>
ANGEL_PASSWORD=<your login password>
ANGEL_TOTP_SECRET=<Base32 seed from Angel One TOTP setup — NOT a rotating code>

ANGEL_BASE_URL=
# Leave blank — the app calls Angel One directly from the DO server.
# DO's IP is whitelisted in Angel One's API key settings.

DB_HOST=localhost
# DB_HOST in .env is ignored — docker-compose.yml injects DB_HOST=n8n-postgres at runtime.
# Set this to localhost so local dev works if you ever run without Docker.

DB_PORT=5432
DB_NAME=trading
DB_USER=trading_user
DB_PASSWORD=<choose a strong password>

EMAIL_SENDER=your_gmail@gmail.com
EMAIL_PASSWORD=<Gmail app password — not your Gmail login password>
EMAIL_RECEIVER=recipient@example.com
```

---

## Step 3 — Create the trading database (one-time)

The `trading` database and user must exist in the `n8n-postgres` container before the app starts.

```bash
# Connect as postgres superuser
docker exec -it n8n-postgres psql -U postgres

# Inside psql:
CREATE USER trading_user WITH PASSWORD 'your_db_password_here';
CREATE DATABASE trading OWNER trading_user;
GRANT ALL PRIVILEGES ON DATABASE trading TO trading_user;
\q
```

Verify access:
```bash
docker exec -it n8n-postgres psql -U trading_user -d trading -c "\dt"
# Will show "No relations found" — that's fine, tables are created by the app on startup.
```

---

## Step 4 — Build and start

```bash
cd <REMOTE_PATH>
docker compose up -d --build
```

Check both containers are running:
```bash
docker compose ps
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

## Step 5 — Seed historical data (one-time, ~30 min)

Run inside a `screen` session so it survives SSH disconnect:

```bash
screen -S seed
docker compose run --rm app python scripts/seed_historical.py
# Ctrl+A then D to detach
# screen -r seed to reattach and check progress
```

Verify data loaded:
```bash
docker exec -it n8n-postgres psql -U trading_user -d trading -c "SELECT COUNT(*) FROM ohlcv;"
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
docker compose up -d --build app
```

### Inspect the database
```bash
docker exec -it n8n-postgres psql -U trading_user -d trading
```

---

## Known issues

### Outbound SMTP blocked by DigitalOcean
DO blocks outbound ports 25, 465, and 587 on new droplets. The email sender will time out. Options:
- **Raise a DO support ticket** asking to unblock port 587 — they approve it for established accounts.
- **Switch to an HTTP email API** (SendGrid, Mailgun) — uses port 443 which is never blocked.

### Angel One IP whitelist
Angel One's API key is configured to accept requests only from the DO droplet's public IP. If you move to a different server, update the allowed IP in the Angel One developer console and update `ANGEL_BASE_URL` accordingly.

### TOTP secret
`ANGEL_TOTP_SECRET` is the static Base32 seed you scanned when setting up 2FA — it is not a rotating 6-digit code. Do not regenerate it unless you also re-setup your authenticator app.
