import os
from dotenv import load_dotenv

load_dotenv()

ANGEL_API_KEY = os.getenv("ANGEL_API_KEY", "")
ANGEL_CLIENT_ID = os.getenv("ANGEL_CLIENT_ID", "")
ANGEL_PASSWORD = os.getenv("ANGEL_PASSWORD", "")
ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")
ANGEL_BASE_URL = os.getenv("ANGEL_BASE_URL", "https://apiconnect.angelbroking.com")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]

EMAIL_SENDER = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_RECEIVER = os.environ["EMAIL_RECEIVER"]

TIMEZONE = "Asia/Kolkata"

# Momentum strategy params
MOMENTUM_UNIVERSE = "nifty500"
MOMENTUM_TOP_N = 30
MOMENTUM_LOOKBACK_DAYS = 20

# BTST params
BTST_MIN_PRICE_CHANGE_PCT = 5.0
BTST_MIN_VOLUME_RATIO = 1.5
BTST_NIFTY_DOWN_THRESHOLD = -1.0
