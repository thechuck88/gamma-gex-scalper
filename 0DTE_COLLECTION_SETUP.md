# 0DTE Data Collection Setup - Tradier API

## Overview

Automated daily collection of SPX 0DTE (same-day expiration) options data using Tradier API.

**Date**: 2026-01-10
**Status**: ✅ READY TO DEPLOY
**Cost**: FREE (uses Tradier sandbox API)

---

## What This Does

### Collects 0DTE Options Data

**What**: SPX options that expire the same day (0DTE)
**When**: Mon/Wed/Fri (SPX daily expiration days)
**How Often**: Every 30 minutes during market hours (13 snapshots/day)
**Storage**: SQLite database (`market_data.db`)

### Data Collected

For each option contract:
- Symbol
- Bid/Ask/Last prices
- Open/High/Low/Close
- Volume
- Strike price
- Option type (Call/Put)
- Underlying price
- Timestamp (ET timezone)

### Why This Matters

**Problem**: Databento historical data has NO 0DTE (confirmed)
**Solution**: Collect our own 0DTE data going forward
**Timeline**: After 30-60 days, enough data for backtest validation
**Cost**: $0 (free Tradier API)

---

## Quick Start

### 1. Run Setup Script

```bash
cd /gamma-scalper
bash setup_0dte_collection.sh
```

**What it does**:
- ✓ Checks for Tradier API key
- ✓ Creates log file
- ✓ Makes script executable
- ✓ Installs cron jobs (13/day on Mon/Wed/Fri)

### 2. Verify Setup

```bash
# Check cron jobs installed
crontab -l | grep 0DTE

# Check status
python3 collect_0dte_tradier.py --status
```

### 3. Test Collection (Optional)

```bash
# Test on next Mon/Wed/Fri when market is open
source /etc/gamma.env
python3 collect_0dte_tradier.py --symbol SPX
```

---

## Collection Schedule

### Daily Collection (Mon/Wed/Fri only)

**Market Hours**: 9:30 AM - 4:00 PM ET

| Time (ET) | Time (UTC) | Purpose |
|-----------|------------|---------|
| 10:00 AM | 15:00 | Market open snapshot |
| 10:30 AM | 15:30 | Early morning |
| 11:00 AM | 16:00 | Mid-morning |
| 11:30 AM | 16:30 | Late morning |
| 12:00 PM | 17:00 | Noon |
| 12:30 PM | 17:30 | Early afternoon |
| 1:00 PM | 18:00 | Mid-afternoon |
| 1:30 PM | 18:30 | Late afternoon |
| 2:00 PM | 19:00 | Approaching close |
| 2:30 PM | 19:30 | Late session |
| 3:00 PM | 20:00 | Final hour |
| 3:30 PM | 20:30 | Final 30 min |
| 4:00 PM | 21:00 | Market close |

**Total**: 13 snapshots per day × 3 days/week = **39 snapshots/week**

### Why This Schedule?

**30-minute intervals**:
- Captures intraday price changes
- Not too frequent (avoid rate limits)
- Enough granularity for 1-minute backtest interpolation

**Mon/Wed/Fri only**:
- SPX has daily expirations on these days
- No 0DTE on Tue/Thu (SPX schedule)

**Start at 10:00 AM**:
- Your strategy enters at 10 AM
- Captures entry prices accurately

---

## Files Created

### 1. Collection Script

**File**: `/gamma-scalper/collect_0dte_tradier.py`

**Features**:
- Queries Tradier for 0DTE expirations
- Gets option chain for today's expiration
- Fetches real-time quotes
- Stores in database with timestamp
- Rate limiting (0.5s between batches)

**Usage**:
```bash
# Single snapshot (default)
python3 collect_0dte_tradier.py --symbol SPX

# View collection status
python3 collect_0dte_tradier.py --status

# Collect all day (30-min intervals)
python3 collect_0dte_tradier.py --symbol SPX --all-day
```

### 2. Setup Script

**File**: `/gamma-scalper/setup_0dte_collection.sh`

**What it does**:
- Validates environment
- Creates log file
- Installs 13 cron jobs (every 30 min on Mon/Wed/Fri)
- Shows schedule

### 3. Database Table

**Table**: `option_bars_0dte`

**Schema**:
```sql
CREATE TABLE option_bars_0dte (
    symbol TEXT,               -- SPX260110C05900000
    datetime TEXT,             -- 2026-01-10 10:00:00 (ET)
    open REAL,                 -- Opening price
    high REAL,                 -- High price
    low REAL,                  -- Low price
    close REAL,                -- Closing price (or last)
    volume INTEGER,            -- Volume
    bid REAL,                  -- Bid price
    ask REAL,                  -- Ask price
    last REAL,                 -- Last trade price
    expiration_date TEXT,      -- 2026-01-10 (0DTE!)
    trade_date TEXT,           -- 2026-01-10 (same day)
    strike REAL,               -- 5900.0
    option_type TEXT,          -- call or put
    underlying_price REAL,     -- SPX spot price
    UNIQUE(symbol, datetime)
);
```

**Indexes**:
- `idx_0dte_symbol_datetime` - Fast symbol + time lookup
- `idx_0dte_trade_date` - Fast date filtering
- `idx_0dte_expiration` - Fast expiration filtering

---

## Data Timeline

### First Month (Building Dataset)

**Week 1** (3 days × 13 snapshots):
- 39 snapshots total
- ~50-100 options per snapshot
- ~2,000-4,000 data points

**Month 1** (12-13 trading days):
- ~150 snapshots
- ~8,000-15,000 data points
- Enough for initial validation

**Month 2** (25-26 trading days):
- ~300 snapshots
- ~15,000-30,000 data points
- **Good for backtest validation**

**Month 3+** (38-39 trading days):
- ~450+ snapshots
- ~25,000-50,000 data points
- **Excellent dataset for optimization**

### Expected Database Growth

**Per Collection**:
- SPX typically has 200-400 strikes per expiration
- At-the-money ±10 strikes = ~40-80 contracts
- Per snapshot: ~50-100 options × 15 fields = ~750-1,500 bytes/snapshot

**Per Month** (12 days):
- 150 snapshots × 75 options × 15 fields = ~170k data points
- Database size: ~5-10 MB/month (compressed with SQLite)

**Per Year** (156 days):
- 2,000 snapshots × 75 options = ~150k contracts
- Database size: ~50-75 MB/year

---

## Validation Timeline

### When Can We Validate?

**Minimum** (10 trading days):
- 130 snapshots
- Basic validation of entry prices
- Can compare $1-2 estimation vs actual

**Recommended** (30 trading days):
- 390 snapshots
- Good validation of entry/exit prices
- Win rate validation
- P&L validation

**Ideal** (60 trading days):
- 780 snapshots
- Full backtest validation
- Parameter optimization
- Multiple market conditions

### What to Validate

**After 10 days**:
- ✓ Average entry credit ($1-2 estimation)
- ✓ Bid/ask spreads
- ✓ Liquidity (volume data)

**After 30 days**:
- ✓ Win rate (60-65% expected)
- ✓ Average profit per trade
- ✓ Stop loss frequency
- ✓ Daily P&L ($40-50 expected)

**After 60 days**:
- ✓ Full backtest re-run with real prices
- ✓ Parameter optimization
- ✓ Seasonal patterns
- ✓ Multi-month validation

---

## Manual Collection

### Test Collection Now

```bash
# Collect single snapshot (if market is open on Mon/Wed/Fri)
source /etc/gamma.env
python3 /gamma-scalper/collect_0dte_tradier.py --symbol SPX
```

**Expected Output**:
```
======================================================================
COLLECTING 0DTE DATA: SPX
======================================================================

Collection Time: 2026-01-13 10:00:00 EST
Looking for: Options expiring TODAY (2026-01-13)

Step 1: Getting option expirations...
✓ Found 55 expirations
✓ Found 0DTE expiration: 2026-01-13

Step 2: Getting option chain for 2026-01-13 expiration...
✓ Found 387 options in chain
   Underlying price: $5897.50

Step 3: Getting real-time quotes for 387 options...
✓ Received 387 quotes

Step 4: Storing in database...
✓ Inserted 387 option quotes

======================================================================
COLLECTION COMPLETE
======================================================================

Symbol: SPX
Expiration: 2026-01-13 (0DTE)
Options Collected: 387
Underlying Price: $5897.50
Collection Time: 10:00:00 EST
Database: market_data.db
```

### View Collected Data

```bash
# Show status
python3 collect_0dte_tradier.py --status

# Query database directly
sqlite3 /gamma-scalper/market_data.db <<EOF
SELECT
    trade_date,
    COUNT(*) as snapshots,
    COUNT(DISTINCT symbol) as options,
    MIN(datetime) as first_collection,
    MAX(datetime) as last_collection
FROM option_bars_0dte
GROUP BY trade_date
ORDER BY trade_date DESC
LIMIT 10;
EOF
```

---

## Monitoring

### Check Collection Logs

```bash
# View recent logs
tail -f /var/log/0dte_collector.log

# Check for errors
grep ERROR /var/log/0dte_collector.log

# Check today's collections
grep "$(date +%Y-%m-%d)" /var/log/0dte_collector.log
```

### Verify Cron is Running

```bash
# Check cron jobs
crontab -l | grep 0DTE

# Check cron execution
grep CRON /var/log/syslog | grep 0dte_tradier
```

### Database Status

```bash
# Check database size
ls -lh /gamma-scalper/market_data.db

# Count records
sqlite3 /gamma-scalper/market_data.db "SELECT COUNT(*) FROM option_bars_0dte"

# Check latest collection
sqlite3 /gamma-scalper/market_data.db "SELECT MAX(datetime) FROM option_bars_0dte"
```

---

## Troubleshooting

### No Data Collected

**Check 1**: Is today Mon/Wed/Fri?
```bash
date +%A  # Should be Monday, Wednesday, or Friday
```

**Check 2**: Is market open?
```bash
# Market hours: 9:30 AM - 4:00 PM ET
date  # Check current time
```

**Check 3**: Does SPX have 0DTE today?
```bash
# Some days may not have 0DTE (holidays, special cases)
source /etc/gamma.env
python3 collect_0dte_tradier.py --symbol SPX
# Check output for "No 0DTE expiration found"
```

### API Errors

**Check API Key**:
```bash
grep TRADIER_SANDBOX_KEY /etc/gamma.env
# Should show: TRADIER_SANDBOX_KEY="bApaaX..."
```

**Rate Limiting**:
- Tradier allows 120 requests/minute
- Script includes 0.5s delays between batches
- Should not hit limits

**Sandbox vs Live**:
- Script uses sandbox API for data collection
- Sandbox has full historical data access
- No real money involved

---

## Integration with Backtest

### After 30 Days of Collection

**Step 1**: Export collected data
```python
import sqlite3
import pandas as pd

conn = sqlite3.connect('market_data.db')

# Get all 0DTE data
df = pd.read_sql_query("""
    SELECT * FROM option_bars_0dte
    ORDER BY datetime
""", conn)

print(f"Collected {len(df)} 0DTE option quotes")
print(f"Date range: {df['trade_date'].min()} to {df['trade_date'].max()}")
```

**Step 2**: Compare to estimation
```python
# Filter for your strategy entry time (10:00 AM)
df_entry = df[df['datetime'].str.contains('10:00:00')]

# Calculate average credit for 5-point spread
# (Rough estimate - need to match strikes)
avg_premium = df_entry['last'].mean()
print(f"Average option premium at 10 AM: ${avg_premium:.2f}")
```

**Step 3**: Re-run backtest with real prices
```python
# Use collected 0DTE data instead of estimation
# Match strikes to your strategy rules
# Calculate real P&L vs estimated P&L
```

---

## Cost Analysis

### Tradier API Usage

**Free Tier**:
- ✓ Unlimited market data requests
- ✓ Sandbox account (no real money)
- ✓ Full option chains
- ✓ Real-time quotes

**Cost**: $0/month

### Comparison to Paid Data

**ThetaData** ($150/month):
- Has historical 0DTE
- Immediate access
- Cost: $150 × 3 months = **$450**

**Our Approach** (Free):
- Collect going forward
- Takes 30-60 days
- Cost: **$0**

**Savings**: $450 (if you can wait 2 months)

---

## Next Steps

### 1. Deploy Now

```bash
cd /gamma-scalper
bash setup_0dte_collection.sh
```

### 2. Wait for Data

**First collection**: Next Mon/Wed/Fri at 10:00 AM ET
**Usable data**: After 10-15 trading days (2-3 weeks)
**Full validation**: After 30-40 trading days (6-8 weeks)

### 3. Meanwhile: Paper Trade

While collecting data:
- Run 0DTE strategy in paper mode
- Track actual fills vs estimation
- Validate win rate and P&L
- Compare to backtest results

### 4. Validate After 30 Days

Once you have 30 days of 0DTE data:
- Compare real credits to $1-2 estimation
- Re-run backtest with real prices
- Adjust parameters if needed
- Decide: Go live or collect more data

---

## Summary

**What We're Doing**:
- ✅ Collecting SPX 0DTE options data daily
- ✅ Using free Tradier API
- ✅ Storing in database for backtest validation
- ✅ Automated via cron (Mon/Wed/Fri)

**Timeline**:
- Week 1: First data collected
- Week 2-3: 10-15 days (initial validation possible)
- Week 6-8: 30-40 days (full validation ready)

**Cost**:
- $0 (free Tradier sandbox API)
- Saves $150-200/month vs paid data providers

**Status**: Ready to deploy!

---

**Created**: 2026-01-10
**Status**: ✅ READY - Run setup script to deploy
**Next**: `bash setup_0dte_collection.sh`
