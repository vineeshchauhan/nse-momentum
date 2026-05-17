# Strategy Definitions

All numeric thresholds are set in `config.py`. Edit there to change behaviour without touching strategy code.

---

## 1. Weekly Momentum Portfolio

**File:** `strategies/momentum.py`  
**Schedule:** Every Monday at 9:00 AM IST  

### What it does
Ranks all Nifty 500 stocks by 1-month return, selects the top N, compares with last week's portfolio, and emails the delta (new entries, continuations, exits).

### Ranking metric
```
momentum_1m = (close_today - close_20_trading_days_ago) / close_20_trading_days_ago × 100
```
- "20 trading days ago" = the 21st most recent row in `ohlcv` for that symbol.
- No risk adjustment — raw price return only.
- Sorted descending; top N selected by simple slice.

### Parameters (`config.py`)
| Parameter | Default | Meaning |
|---|---|---|
| `MOMENTUM_TOP_N` | 30 | Number of stocks to hold in portfolio |
| `MOMENTUM_LOOKBACK_DAYS` | 20 | Trading days for return calculation (rn=21) |
| `MOMENTUM_UNIVERSE` | `nifty500` | Filter: only `is_nifty500 = TRUE` stocks |

### Output
- Saved to `momentum_portfolio` (symbol, rank, momentum_1m, entry_price) and `momentum_changes` (NEW ENTRY / CONTINUATION / EXIT).
- Email sent with top N list + weekly delta.

### Ideas to improve
- [ ] Add volatility adjustment: rank by `momentum_1m / stddev(daily_returns)` (Sharpe-like)
- [ ] Add a second lookback (e.g. 3-month return) and blend the two scores
- [ ] Skip stocks with abnormally high return (possible corporate action / data error)
- [ ] Add minimum price or minimum market-cap filter to avoid illiquid stocks
- [ ] Try 12-1 momentum: 12-month return excluding the most recent month (skips short-term reversal)
- [ ] Sector-cap: limit max N stocks per sector to avoid concentration
- [ ] Add Nifty gate: skip week if Nifty 50 is below its 20-week SMA (bear market filter)

---

## 2. BTST Screener (Buy Today Sell Tomorrow)

**File:** `strategies/btst.py`  
**Schedule:** Monday–Friday at 3:00 PM IST  

### What it does
Scans F&O stocks in the Nifty 500 for strong intraday price+volume breakouts near market close. Signals are intended as overnight swing trades (buy at close, sell next morning).

### Gate condition
If Nifty 50 is down more than `BTST_NIFTY_DOWN_THRESHOLD` on the day → entire run aborts, no signals, no email.

### Stock filters (both must pass)
| Filter | Formula | Default threshold |
|---|---|---|
| Price change | `(close_today - prev_close) / prev_close × 100` | >= 5% |
| Volume surge | `today_volume / 20d_avg_volume` | >= 1.5× |

- `prev_close` and `20d_avg_volume` come from the `ohlcv` DB table (no live call).
- `close_today` and `today_volume` fetched via Angel One intraday candle (9:00 AM – 3:10 PM window).
- Universe: `is_fo = TRUE AND is_nifty500 = TRUE`.

### Parameters (`config.py`)
| Parameter | Default | Meaning |
|---|---|---|
| `BTST_MIN_PRICE_CHANGE_PCT` | 5.0 | Minimum % price move vs previous close |
| `BTST_MIN_VOLUME_RATIO` | 1.5 | Minimum multiple of 20-day avg volume |
| `BTST_NIFTY_DOWN_THRESHOLD` | -1.0 | Abort if Nifty % change is below this |

### Output
- Signals sorted by volume ratio descending.
- Saved to `btst_signals` (date, symbol, price_change_pct, volume_ratio, close_price, suggested_strike).
- `result_next_day` filled the following evening by `daily_batch.py`.
- Email sent only if signals exist.

### Ideas to improve
- [ ] Add RSI filter: only take signals where RSI(14) < 70 to avoid already-overbought stocks
- [ ] Add a relative strength filter: stock must be outperforming Nifty on the day
- [ ] Tighten the price change band: e.g. 5–15% (exclude >15% as likely news/circuit-driven)
- [ ] Add a price floor (e.g. close > ₹100) to avoid penny stocks
- [ ] Consider time-of-day: check if the surge happened in the last 30 min vs early morning gap
- [ ] Track `result_next_day` outcomes and back-test to tune thresholds empirically
- [ ] Add sector filter: avoid signals from the same sector as a recent circuit-hit stock
- [ ] Try a 5-day avg volume instead of 20-day to catch recently-emerging momentum
