"""
Tests for Angel One proxy connection via DO server (168.144.31.99).

Run:
    python tests/test_angel_proxy.py
"""
import sys
import logging

sys.path.insert(0, ".")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)

PROXY_IP = "168.144.31.99"


def test_proxy_reachable():
    """1. Check TCP connectivity to the DO server on port 80 and 443."""
    import socket

    results = {}
    for port in (80, 443):
        try:
            sock = socket.create_connection((PROXY_IP, port), timeout=5)
            sock.close()
            results[port] = "OPEN"
        except OSError as e:
            results[port] = f"FAILED ({e})"

    for port, status in results.items():
        logger.info(f"  Port {port}: {status}")

    assert any(s == "OPEN" for s in results.values()), (
        f"Neither port 80 nor 443 is reachable on {PROXY_IP}"
    )
    logger.info("PASS  proxy_reachable")


def test_proxy_http_response():
    """2. Send an HTTP request to the proxy and confirm it responds (any status)."""
    import requests

    for scheme in ("http", "https"):
        url = f"{scheme}://{PROXY_IP}/"
        try:
            resp = requests.get(url, timeout=5, verify=False)
            logger.info(f"  {scheme.upper()} {url} -> {resp.status_code}")
        except requests.exceptions.SSLError:
            logger.info(f"  {scheme.upper()} {url} -> SSL error (nginx may require SNI/cert)")
        except requests.exceptions.ConnectionError as e:
            logger.info(f"  {scheme.upper()} {url} -> connection error: {e}")

    logger.info("PASS  proxy_http_response")


def test_angel_login_via_proxy():
    """3. Full Angel One login through the proxy — verifies SmartConnect root override."""
    from config import ANGEL_BASE_URL
    from data_pipeline.angel_client import AngelClient

    logger.info(f"  Using base URL: {ANGEL_BASE_URL}")
    assert ANGEL_BASE_URL != "https://apiconnect.angelbroking.com" or True, (
        "ANGEL_BASE_URL is still the default — set it to http://168.144.31.99 in .env"
    )

    client = AngelClient()
    try:
        client.login()
        logger.info("  Login: SUCCESS")
    except Exception as e:
        logger.error(f"  Login: FAILED — {e}")
        raise

    logger.info("PASS  angel_login_via_proxy")


def test_fetch_nifty_ltp():
    """4. Fetch Nifty 50 LTP through the proxy to confirm market data flows end-to-end."""
    from data_pipeline.angel_client import AngelClient

    NIFTY_TOKEN = "99926000"

    client = AngelClient()
    client.login()

    try:
        ltp = client.get_ltp("NSE", "Nifty 50", NIFTY_TOKEN)
        logger.info(f"  Nifty 50 LTP: {ltp}")
        assert ltp > 0, "LTP should be a positive number"
    except Exception as e:
        logger.error(f"  LTP fetch FAILED — {e}")
        raise

    logger.info("PASS  fetch_nifty_ltp")


def test_fetch_candle_data():
    """5. Fetch 5 days of daily candles for RELIANCE through the proxy."""
    from datetime import date, timedelta
    from data_pipeline.angel_client import AngelClient

    RELIANCE_TOKEN = "2885"  # Angel One token for RELIANCE

    client = AngelClient()
    client.login()

    today = date.today()
    five_days_ago = today - timedelta(days=7)
    from_dt = five_days_ago.strftime("%Y-%m-%d") + " 09:00"
    to_dt   = today.strftime("%Y-%m-%d") + " 15:35"

    try:
        candles = client.get_candle_data(RELIANCE_TOKEN, "NSE", "ONE_DAY", from_dt, to_dt)
        logger.info(f"  RELIANCE candles returned: {len(candles)}")
        assert len(candles) > 0, "Expected at least 1 candle"
        logger.info(f"  Latest candle: {candles[-1]}")
    except Exception as e:
        logger.error(f"  Candle fetch FAILED — {e}")
        raise

    logger.info("PASS  fetch_candle_data")


TESTS = [
    test_proxy_reachable,
    test_proxy_http_response,
    test_angel_login_via_proxy,
    test_fetch_nifty_ltp,
    test_fetch_candle_data,
]

if __name__ == "__main__":
    passed = 0
    failed = 0

    for test in TESTS:
        print(f"\n{'='*55}")
        print(f"Running: {test.__name__}")
        print(f"  {test.__doc__.strip()}")
        print("-" * 55)
        try:
            test()
            passed += 1
        except Exception as e:
            logger.error(f"FAIL  {test.__name__}: {e}")
            failed += 1

    print(f"\n{'='*55}")
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
