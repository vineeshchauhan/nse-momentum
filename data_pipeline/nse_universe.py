"""
Fetches the Nifty 500 stock list from NSE India and the Angel One instrument list,
then cross-references to get symbol tokens needed for SmartAPI calls.
"""
import io
import ssl
import logging
import requests
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

logger = logging.getLogger(__name__)

# archives.nseindia.com is a CDN-backed static server — no cookies or anti-bot needed
NSE_NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
ANGEL_INSTRUMENT_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class _LaxTLSAdapter(HTTPAdapter):
    """Lowers OpenSSL security level to 1 — required for NSE's TLS config."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _session() -> requests.Session:
    session = requests.Session()
    session.mount("https://", _LaxTLSAdapter())
    return session


def fetch_nifty500_list() -> pd.DataFrame:
    """Returns DataFrame with columns: symbol, name, isin, sector."""
    resp = _session().get(NSE_NIFTY500_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    # CSV columns: Company Name, Industry, Symbol, Series, ISIN Code
    df = pd.read_csv(io.StringIO(resp.text))
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns={
        "Company Name": "name",
        "Industry":     "sector",
        "Symbol":       "symbol",
        "ISIN Code":    "isin",
    })
    df["symbol"] = df["symbol"].str.strip()
    # NSE adds placeholder rows during index rebalancing — drop them
    df = df[~df["symbol"].str.startswith("DUMMY")]
    logger.info(f"Fetched {len(df)} stocks from NSE Nifty 500 CSV")
    return df[["symbol", "name", "isin", "sector"]].copy()


def fetch_angel_instruments() -> pd.DataFrame:
    """Returns Angel One instrument master as DataFrame."""
    resp = requests.get(ANGEL_INSTRUMENT_URL, timeout=60)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())
    nse_eq = df[(df["exch_seg"] == "NSE") & (df["instrumenttype"] == "")]
    nse_eq = nse_eq[["symbol", "token", "name", "lotsize"]].copy()
    # Strip NSE series suffixes: -EQ, -BE, -BZ, -SM, -IL, etc.
    nse_eq["symbol"] = nse_eq["symbol"].str.replace(r"-[A-Z]{2}$", "", regex=True).str.strip()
    return nse_eq.drop_duplicates(subset="symbol")


def get_fo_symbols() -> set:
    """Returns set of symbols that are in F&O (have NFO futures contracts)."""
    resp = requests.get(ANGEL_INSTRUMENT_URL, timeout=60)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())
    nfo = df[df["exch_seg"] == "NFO"]
    fo_syms = set()
    for sym in nfo["name"].unique():
        base = sym.split("-")[0].split(" ")[0].strip()
        if base:
            fo_syms.add(base)
    return fo_syms


def build_universe() -> pd.DataFrame:
    """
    Returns merged DataFrame:
    symbol, name, isin, sector, token, is_fo, is_nifty500
    """
    logger.info("Fetching Nifty 500 list from NSE archives...")
    nifty500 = fetch_nifty500_list()

    logger.info("Fetching Angel One instrument master...")
    instruments = fetch_angel_instruments()

    logger.info("Fetching F&O symbols...")
    fo_symbols = get_fo_symbols()

    merged = nifty500.merge(instruments[["symbol", "token"]], on="symbol", how="left")
    merged["is_fo"] = merged["symbol"].isin(fo_symbols)
    merged["is_nifty500"] = True
    missing_token = merged["token"].isna().sum()
    if missing_token:
        logger.warning(f"{missing_token} Nifty500 stocks have no Angel token — will be skipped")
    return merged
