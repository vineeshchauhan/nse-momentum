import pyotp
import time
import logging
from SmartApi import SmartConnect
from config import ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_SECRET, ANGEL_BASE_URL

logger = logging.getLogger(__name__)


class AngelClient:
    def __init__(self):
        self._api = None

    def login(self):
        totp = pyotp.TOTP(ANGEL_TOTP_SECRET).now()
        api = SmartConnect(api_key=ANGEL_API_KEY, root=ANGEL_BASE_URL)
        data = api.generateSession(ANGEL_CLIENT_ID, ANGEL_PASSWORD, totp)
        if data["status"] is False:
            raise RuntimeError(f"Angel login failed: {data['message']}")
        self._api = api
        logger.info("Angel One login successful")
        return api

    @property
    def api(self):
        if self._api is None:
            self.login()
        return self._api

    def get_candle_data(self, symbol_token: str, exchange: str, interval: str,
                        from_date: str, to_date: str) -> list:
        """
        Fetch OHLCV candles from Angel One.
        from_date / to_date format: "YYYY-MM-DD HH:MM"
        interval: ONE_DAY, ONE_HOUR, FIFTEEN_MINUTE, etc.
        """
        logger.debug(
            "getCandleData token=%s exchange=%s interval=%s from=%s to=%s",
            symbol_token, exchange, interval, from_date, to_date,
        )
        params = {
            "exchange": exchange,
            "symboltoken": symbol_token,
            "interval": interval,
            "fromdate": from_date,
            "todate": to_date,
        }
        resp = self.api.getCandleData(params)
        if resp["status"] is False:
            logger.warning(
                "getCandleData failed token=%s: %s", symbol_token, resp["message"]
            )
            raise RuntimeError(f"getCandleData error for {symbol_token}: {resp['message']}")
        candles = resp["data"] or []
        logger.debug("getCandleData token=%s returned %d candles", symbol_token, len(candles))
        return candles

    def get_ltp(self, exchange: str, symbol: str, symbol_token: str) -> float:
        logger.debug("ltpData exchange=%s symbol=%s token=%s", exchange, symbol, symbol_token)
        resp = self.api.ltpData(exchange, symbol, symbol_token)
        if resp["status"] is False:
            logger.warning("ltpData failed symbol=%s: %s", symbol, resp["message"])
            raise RuntimeError(f"ltpData error: {resp['message']}")
        ltp = float(resp["data"]["ltp"])
        logger.debug("ltpData symbol=%s ltp=%.2f", symbol, ltp)
        return ltp

    def get_market_quote(self, tokens: list) -> dict:
        """tokens: list of {"exchange": "NSE", "symboltoken": "99926000"}"""
        logger.debug("getMarketData FULL for %d token(s)", len(tokens))
        resp = self.api.getMarketData("FULL", tokens)
        if resp["status"] is False:
            logger.warning("getMarketData failed: %s", resp["message"])
            raise RuntimeError(f"getMarketData error: {resp['message']}")
        return resp["data"]
