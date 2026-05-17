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
        params = {
            "exchange": exchange,
            "symboltoken": symbol_token,
            "interval": interval,
            "fromdate": from_date,
            "todate": to_date,
        }
        resp = self.api.getCandleData(params)
        if resp["status"] is False:
            raise RuntimeError(f"getCandleData error for {symbol_token}: {resp['message']}")
        return resp["data"]  # list of [timestamp, open, high, low, close, volume]

    def get_ltp(self, exchange: str, symbol: str, symbol_token: str) -> float:
        resp = self.api.ltpData(exchange, symbol, symbol_token)
        if resp["status"] is False:
            raise RuntimeError(f"ltpData error: {resp['message']}")
        return float(resp["data"]["ltp"])

    def get_market_quote(self, tokens: list) -> dict:
        """tokens: list of {"exchange": "NSE", "symboltoken": "99926000"}"""
        resp = self.api.getMarketData("FULL", tokens)
        if resp["status"] is False:
            raise RuntimeError(f"getMarketData error: {resp['message']}")
        return resp["data"]
