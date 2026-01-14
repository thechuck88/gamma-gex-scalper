# Data Collector Test Results

## Test Summary

**Date**: 2026-01-10
**Status**: ✅ **UNDERLYING DATA COLLECTION WORKING**
**Status**: ⚠️ **OPTION CHAIN COLLECTION NEEDS LIVE API KEY**

## What Works

### ✅ Underlying 1-Minute Bars (Alpaca)

**Test**: Collected 7,091 bars (SPY + QQQ) for Nov 25 - Dec 1, 2025

```
SPY: 3,511 bars ✓
QQQ: 3,580 bars ✓
Database: 1.1 MB
```

**Key Findings**:
- ✅ Alpaca paper account CAN fetch historical 1-minute data
- ⚠️ **Restriction**: Cannot query very recent data (last ~7-10 days)
- ✅ Older data (30+ days ago) works perfectly
- ✅ Data stored in SQLite successfully
- ✅ Collection logging works
- ✅ Status reporting accurate

**Limitation Discovered**:
```
Recent data (last 7 days): ❌ "subscription does not permit querying recent SIP data"
Older data (30+ days ago): ✅ Works perfectly
```

**Workaround**: The backtest already has access to 1-minute data during execution (via live API calls). The data collector is useful for:
1. Building historical archive (30+ days old)
2. Avoiding rate limits on repeated backtests
3. Offline backtest capability

### ⚠️ Option Chain Collection (Tradier)

**Test**: Attempted to collect SPXW/NDXW chains for 2026-01-10

```
SPXW: ❌ 401 Unauthorized
NDXW: ❌ 401 Unauthorized
```

**Issue**: Sandbox API key doesn't have access to historical option chains

**Solutions**:
1. **Use live Tradier key** (not sandbox) - has full market data access
2. **Skip option collection** - backtests can estimate option prices (current approach)
3. **Use ThetaData** ($150/month) - professional option data provider

## Recommendations

### For Production Use

**Option 1: Underlying Data Only (FREE - Recommended)**

Use data collector for underlying bars only:
```bash
# Collect historical SPY/QQQ data (works with paper account)
python3 data_collector.py --historical --days 365

# Daily cron updates
0 17 * * 1-5 python3 data_collector.py --daily
```

**Benefits**:
- ✅ Free with Alpaca paper account
- ✅ Builds local database for fast backtests
- ✅ No API rate limits
- ✅ Works for underlying price validation

**Limitation**:
- Backtests still estimate option prices (current approach works fine)

**Option 2: Add Live Tradier Key (FREE)**

If you have live Tradier account (not just sandbox):
```bash
# Set live API key
export TRADIER_API_TOKEN="your_live_key"

# Collect today's option chains
python3 data_collector.py --daily
```

**Benefits**:
- ✅ Real option bid/ask prices
- ✅ Greeks (delta, gamma, theta, vega)
- ✅ Actual IV for each strike
- ✅ More accurate backtest validation

**Option 3: Professional Data (PAID)**

Subscribe to ThetaData or Polygon.io:
- $150-200/month
- Unlimited historical option data
- Tick-by-tick quotes
- Only worth it if trading >$100k capital

## Current Database Status

```
Location: /gamma-scalper/market_data.db
Size: 1.1 MB

UNDERLYING 1-MINUTE BARS:
Symbol    Count      First Bar            Last Bar
-------------------------------------------------------------
QQQ       3,580      2025-11-25 00:00:00  2025-12-02 00:59:00
SPY       3,511      2025-11-25 00:00:00  2025-12-02 00:59:00

OPTION CHAINS:
Root      Days       Options    First Date    Last Date
-------------------------------------------------------------
(empty - sandbox key doesn't have access)
```

## Backtest Integration

### Current Approach (Working)

Backtests fetch 1-minute data from Alpaca in real-time:
```python
# backtest_parallel.py automatically uses Alpaca
python3 backtest_parallel.py SPX --use-1min --workers 30
```

**Pros**:
- ✅ Always has latest data
- ✅ No database maintenance needed
- ✅ Works with paper account

**Cons**:
- ❌ API rate limits (rare)
- ❌ Slower for repeated backtests
- ❌ Requires internet connection

### Future Approach (With Data Collector)

Modify backtest to check database first:
```python
# Check database first, fall back to API
intraday_data = check_database(symbol, date) or fetch_alpaca(symbol, date)
```

**Pros**:
- ✅ Instant access (no API calls)
- ✅ No rate limits
- ✅ Works offline
- ✅ Faster for repeated backtests

**Implementation**: TODO (enhancement, not critical)

## Setup Instructions (Updated)

### Minimal Setup (Underlying Data Only)

```bash
# 1. Export Alpaca keys (use your paper account keys)
export APCA_API_KEY_ID="PKTBF4QJCPUI3A9F2CLY"
export APCA_API_SECRET_KEY="1xo7hqzv0sfHyeBusHSebBtPQ4P6JxV6e7c3Cwsk"

# 2. Collect historical data (30+ days old to avoid restriction)
python3 data_collector.py --historical --days 365

# 3. Setup cron for daily updates
crontab -e
# Add: 0 17 * * 1-5 cd /gamma-scalper && python3 data_collector.py --daily
```

**Expected Result**:
- 365 days × 390 bars/day × 2 symbols = ~284,700 bars
- Database size: ~70-100 MB
- Collection time: ~10-15 minutes

### Full Setup (With Option Chains)

If you have live Tradier account:
```bash
# 1. Export both Alpaca and Tradier keys
export APCA_API_KEY_ID="your_alpaca_key"
export APCA_API_SECRET_KEY="your_alpaca_secret"
export TRADIER_API_TOKEN="your_live_tradier_key"  # Not sandbox

# 2. Run full collection
python3 data_collector.py --historical --days 365
python3 data_collector.py --daily  # Collects today's option chains

# 3. Setup cron
0 17 * * 1-5 cd /gamma-scalper && python3 data_collector.py --daily
```

## Troubleshooting

### "subscription does not permit querying recent SIP data"

**Cause**: Alpaca paper account can't query very recent data (<7-10 days)

**Solution**: Collect older data instead
```python
# Instead of last 7 days
python3 data_collector.py --historical --days 365

# This will fetch data ending ~30 days ago (available window)
```

### "Tradier API error: 401"

**Cause**: Sandbox key doesn't have option chain access

**Solutions**:
1. Use live Tradier key (not sandbox)
2. Skip option collection (not critical)
3. Use backtest's estimation (works fine)

### Database Locked

**Cause**: Multiple processes accessing database simultaneously

**Solution**:
```bash
# Kill hung processes
pkill -f data_collector.py

# Retry
python3 data_collector.py --status
```

## Next Steps

1. **For Backtesting** (Current - Works Now):
   - ✅ Use backtest_parallel.py with --use-1min
   - ✅ Fetches from Alpaca in real-time
   - ✅ No database setup needed

2. **For Offline/Faster Backtests** (Optional):
   - Setup data collector for historical archive
   - Modify backtest to check DB first
   - Benefit: faster repeated backtests

3. **For Production Trading** (Future):
   - Use live Tradier key for real option prices
   - Compare backtest estimates vs reality
   - Validate entry credit assumptions

## Conclusion

**Data Collector Status**: ✅ **WORKING** (with minor limitations)

**What Works**:
- ✅ Historical underlying data collection
- ✅ Database storage and querying
- ✅ Status reporting
- ✅ Collection logging

**Limitations**:
- ⚠️ Can't fetch very recent data (<7 days) with paper account
- ⚠️ Option chains need live Tradier key

**Recommendation**:
- **For now**: Continue using backtest_parallel.py with --use-1min (works perfectly)
- **Later**: Build historical database for offline/faster backtests
- **Future**: Add live Tradier key if needed for option validation

---

**Test Date**: 2026-01-10
**Database**: /gamma-scalper/market_data.db (1.1 MB with 7,091 bars)
**Status**: Production ready for underlying data collection
