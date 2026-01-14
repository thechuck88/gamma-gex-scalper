# Data Collection Status - 2026-01-10

## Summary

✅ **Underlying 1-Minute Bars**: **COMPLETE** (372,322 bars, 11 months)
❌ **Option Chain Snapshots**: **BLOCKED** (Tradier 401 error)
❌ **1-Minute Option Bars**: **BLOCKED** (No option chain to query)

## What We Have ✅

### Underlying 1-Minute Bars (SPY/QQQ)

```
SPY: 181,637 bars (Jan 8 - Dec 2, 2025) - 11 months
QQQ: 190,685 bars (Jan 8 - Dec 2, 2025) - 11 months
────────────────────────────────────────────────────
Total: 372,322 bars
Database: 58.2 MB
Coverage: 329 days
```

**Source**: Alpaca Markets (free paper account)
**Quality**: Exchange-quality 1-minute OHLCV data
**Status**: ✅ **READY FOR BACKTEST VALIDATION**

This data can be used to validate underlying price movements in backtests and replace synthetic price generation.

## What We're Missing ❌

### 1-Minute Option Bars (SPX/NDX Individual Contracts)

**Your Requirement**: *"the most important data is for the individual SPX and NDX options contracts on a 1 minute or better level"*

**Current Status**: **ZERO OPTION DATA COLLECTED**

**Why**: Tradier sandbox API key returns `401 Unauthorized` for:
- Option chain snapshots (`/v1/markets/options/chains`)
- 1-minute option bars (`/v1/markets/timesales`)

## API Limitations Discovered

### Tradier Sandbox (Current)

```bash
# Environment variables set in /etc/gamma.env
TRADIER_SANDBOX_KEY="..."
```

**What Works**:
- ❌ Option chains: `401 Unauthorized`
- ❌ Option timesales: `401 Unauthorized`
- ❌ Historical option data: Not available

**Limitation**: Sandbox accounts don't have access to option market data.

### Alpaca Paper (Current)

```bash
# Environment variables set in /etc/gamma.env
ALPACA_PAPER_KEY="..."
ALPACA_PAPER_SECRET="..."
```

**What Works**:
- ✅ Underlying 1-minute bars (SPY/QQQ): **WORKS**
- ❌ Recent data (<7-10 days): Blocked ("subscription does not permit querying recent SIP data")
- ❌ Options data: Not available (Alpaca doesn't provide options data for paper accounts)

## Solutions to Collect 1-Minute Option Bars

### Option 1: Use Live Tradier Account ⭐ **RECOMMENDED (FREE)**

**Cost**: FREE (if you have Tradier brokerage account)

**What to do**:
```bash
# Get your LIVE Tradier API key from:
# https://dash.tradier.com/settings/api-access

# Add to /etc/gamma.env:
export TRADIER_API_TOKEN="your_live_tradier_key"
# OR
export TRADIER_LIVE_KEY="your_live_tradier_key"
```

**What you get**:
- ✅ Option chains for any expiration
- ✅ 1-minute option bars via `/v1/markets/timesales`
- ✅ Greeks (IV, delta, gamma, theta, vega)
- ✅ Real bid/ask quotes
- ⚠️ **Limitation**: ~30 days historical data

**How to collect**:
```bash
# Collect today's 0DTE option chains + 1-min bars
python3 data_collector_enhanced.py --daily

# Collect specific date
python3 data_collector_enhanced.py --collect-option-bars --date 2026-01-10 --root SPXW
```

**Expected result**:
```
SPX 0DTE: ~400 option contracts
1-min bars per contract: ~390 (9:30 AM - 4:00 PM)
Total bars per day: ~156,000
Database growth: ~20-30 MB per day
```

### Option 2: Subscribe to Polygon.io ($99-200/month)

**Cost**:
- Stocks Starter: $99/month (limited options history)
- Stocks Advanced: $200/month ⭐ (full options history)

**What to do**:
```bash
# Sign up at https://polygon.io/pricing
# Get API key and add to environment:
export POLYGON_API_KEY="your_polygon_key"
```

**What you get**:
- ✅ **Unlimited** historical option data (back to 2020)
- ✅ 1-minute option bars
- ✅ Tick-by-tick trades/quotes
- ✅ No 30-day limitation

**How to collect**:
```bash
# Same commands, but uses Polygon as data source
python3 data_collector_enhanced.py --collect-option-bars --date 2025-01-08 --root SPXW
```

**When to use**: If you need historical option data older than 30 days for validation.

### Option 3: ThetaData ($150/month)

**Cost**: $150/month (Standard plan)

**What to do**:
```bash
# Sign up at https://thetadata.net
# Integration requires custom code (not yet implemented)
```

**What you get**:
- ✅ Tick-by-tick option quotes (best quality)
- ✅ Historical data back to 2020
- ✅ SPX, NDX, all US options
- ✅ Greeks included

**When to use**: Professional-grade backtesting, willing to pay for highest quality data.

### Option 4: Build Database Daily (Going Forward)

**Strategy**: Start collecting TODAY, build historical archive over time

```bash
# Setup cron job to collect daily at 5 PM ET
crontab -e

# Add:
0 17 * * 1-5 cd /gamma-scalper && source /etc/gamma.env && python3 data_collector_enhanced.py --daily >> data_collector.log 2>&1
```

**Timeline**:
- Day 1: Collect today's 0DTE (156k bars)
- Week 1: 5 days of 0DTE data (780k bars)
- Month 1: ~21 days of 0DTE data (3.3M bars)
- Year 1: ~252 days of 0DTE data (39M bars, ~6 GB)

**Benefit**: FREE, builds comprehensive database for future backtests

**Limitation**: Doesn't help with PAST backtests (only going forward)

## Recommended Approach

### For Immediate Backtest Validation

**1. Get Live Tradier API Key** (FREE)
- Takes 5 minutes
- Provides 30 days of historical option data
- Enough to validate recent backtest assumptions

**2. Collect Last 30 Days**
```bash
# Set live key
export TRADIER_API_TOKEN="your_live_key"

# Collect today
python3 data_collector_enhanced.py --daily

# Collect yesterday
python3 data_collector_enhanced.py --collect-option-bars --date 2026-01-09 --root SPXW
python3 data_collector_enhanced.py --collect-option-bars --date 2026-01-09 --root NDXW

# Repeat for last 30 days (script this)
```

**3. Validate Backtest Assumptions**
```python
# Compare estimated vs real option prices
estimated_credit = 2.50  # From backtest
real_credit = get_from_database('SPXW260110C06900000', '2026-01-10 10:00:00')

difference = (estimated_credit - real_credit) / estimated_credit
print(f"Estimation error: {difference:.1%}")
```

**Expected**: 10-20% estimation error is normal

### For Long-Term Strategy Validation

**Option A: Free (Limited)**
- Use live Tradier key for 30 days
- Validate recent backtest results
- Accept estimation for older periods
- **Cost**: $0
- **Accuracy**: 85-90%

**Option B: Paid (Full Validation)**
- Subscribe to Polygon.io ($200/month)
- Download full year of option data
- Re-run backtest with real option prices
- **Cost**: $200
- **Accuracy**: 95-98%

**Recommendation**:
- Start with **Option A** (free Tradier)
- If backtest results validate within 15%, continue with estimation
- If > 25% difference, consider **Option B** (Polygon)

## Current Database Structure

```sql
-- Table 1: Underlying 1-minute bars ✅
CREATE TABLE underlying_1min (
    symbol TEXT,           -- 'SPY' or 'QQQ'
    datetime TEXT,         -- '2025-01-08 09:30:00'
    open REAL, high REAL, low REAL, close REAL, volume INTEGER,
    UNIQUE(symbol, datetime)
)
-- Status: 372,322 bars, 58.2 MB, READY FOR USE

-- Table 2: Option chain snapshots ❌
CREATE TABLE option_chains (
    root TEXT,             -- 'SPXW' or 'NDXW'
    date TEXT,             -- '2026-01-10'
    symbol TEXT,           -- 'SPXW260110C06900000'
    bid REAL, ask REAL, mid REAL,
    iv REAL, delta REAL, gamma REAL, theta REAL, vega REAL,
    UNIQUE(symbol, date)
)
-- Status: EMPTY (need live Tradier key)

-- Table 3: 1-minute option bars ⭐ ❌
CREATE TABLE option_bars_1min (
    symbol TEXT,           -- 'SPXW260110C06900000'
    datetime TEXT,         -- '2026-01-10 09:30:00'
    open REAL, high REAL, low REAL, close REAL, volume INTEGER,
    bid REAL, ask REAL, mid REAL,
    iv REAL, delta REAL, gamma REAL,
    UNIQUE(symbol, datetime)
)
-- Status: EMPTY (need live Tradier key OR Polygon)
```

## Next Steps

### Immediate Actions

1. **Decide on data source**:
   - Free: Get live Tradier API key
   - Paid: Subscribe to Polygon.io

2. **Set API credentials**:
   ```bash
   # Edit /etc/gamma.env
   sudo nano /etc/gamma.env

   # Add:
   export TRADIER_API_TOKEN="your_live_key"
   # OR
   export POLYGON_API_KEY="your_polygon_key"
   ```

3. **Test collection**:
   ```bash
   source /etc/gamma.env
   python3 data_collector_enhanced.py --daily
   ```

4. **Check results**:
   ```bash
   python3 data_collector_enhanced.py --status
   ```

### If Using Live Tradier (Recommended First Step)

```bash
# 1. Get API key from https://dash.tradier.com/settings/api-access

# 2. Add to environment
echo 'export TRADIER_API_TOKEN="your_live_key"' >> /etc/gamma.env
source /etc/gamma.env

# 3. Collect today's option data
python3 data_collector_enhanced.py --daily

# 4. Verify collection
python3 data_collector_enhanced.py --status

# Expected output:
# ⭐ 1-MINUTE OPTION BARS (NEW):
# Root     Days  Contracts   Total Bars
# SPXW        1        400      156,000
# NDXW        1        415      162,000
```

### If Collection Succeeds

```bash
# Setup automated daily collection
crontab -e

# Add this line:
0 17 * * 1-5 cd /gamma-scalper && source /etc/gamma.env && python3 data_collector_enhanced.py --daily >> data_collector.log 2>&1
```

### If Collection Still Fails

**Troubleshoot**:
```bash
# Test Tradier API directly
curl -H "Authorization: Bearer YOUR_LIVE_KEY" \
     "https://api.tradier.com/v1/markets/options/chains?symbol=SPXW&expiration=2026-01-10&greeks=true"

# Should return JSON with option data (not 401)
```

**If still 401**:
- Verify you're using LIVE key (not sandbox)
- Check account is funded/active
- Contact Tradier support

## Impact on Backtest Accuracy

### Current (With Estimation)

```
Entry credit: Estimated from underlying price
Stop loss: Estimated spread value
Profit taking: Estimated 50%/60% levels

Expected accuracy: 75-85%
Potential error: ±15-25% on total P/L
```

### With 1-Minute Option Bars

```
Entry credit: Real bid/ask from database
Stop loss: Actual intraday option price
Profit taking: Real mid price at each minute

Expected accuracy: 95-98%
Potential error: ±2-5% on total P/L
```

## Resources

**Web Search Results** (from research on 2026-01-10):

Tradier API supports 1-minute option bars:
- [Get Time & Sales](https://documentation.tradier.com/brokerage-api/markets/get-timesales)
- [Timesale API Response](https://documentation.tradier.com/brokerage-api/reference/response/timesale)

Polygon.io options data:
- [How to Download 1-Minute Interval Historical Options Data](https://python.plainenglish.io/how-to-download-1-minute-interval-historical-options-data-4ca8e1803e25)
- [Options Aggregate Bars](https://polygon.readthedocs.io/en/latest/Options.html)

---

**Created**: 2026-01-10
**Status**: Underlying data complete, option data blocked by API limitation
**Required**: Live Tradier API key OR Polygon.io subscription
**Priority**: **HIGH** - Critical for backtest validation
