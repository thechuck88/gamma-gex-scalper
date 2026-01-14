# Data Collector System

## Overview

Automated background data collection for GEX scalper backtesting. Collects two types of data:

1. **Underlying 1-minute bars**: SPY/QQQ from Alpaca (free, 5 years history)
2. **Daily option chains**: SPX/NDX from Tradier (30 days history)

All data stored in SQLite for fast local access during backtests.

## Quick Start

```bash
# One-time setup
cd /gamma-scalper
bash data_collector_setup.sh

# Check status
python3 data_collector.py --status

# Manual daily run
python3 data_collector.py --daily
```

## Setup Instructions

### Step 1: Install Dependencies

```bash
pip install alpaca-trade-api requests pandas
```

### Step 2: Configure API Keys

**Alpaca (Required for underlying data)**:
```bash
export APCA_API_KEY_ID="your_alpaca_key"
export APCA_API_SECRET_KEY="your_alpaca_secret"
```

Or add to `/etc/gamma.env`:
```bash
# Alpaca API (free, for underlying data)
APCA_API_KEY_ID=PK...
APCA_API_SECRET_KEY=...
APCA_API_BASE_URL=https://paper-api.alpaca.markets
```

**Tradier (Optional for option chains)**:
```bash
export TRADIER_API_TOKEN="your_tradier_token"
```

Already in `/etc/gamma.env` if you're using the live scalper.

### Step 3: Run Setup Script

```bash
cd /gamma-scalper
bash data_collector_setup.sh
```

This will:
- ✅ Check dependencies
- ✅ Collect 365 days of historical data
- ✅ Setup daily cron job (5 PM ET)
- ✅ Create database and indexes

## Database Schema

### Table: `underlying_1min`

Stores 1-minute OHLCV bars for SPY and QQQ.

| Column | Type | Description |
|--------|------|-------------|
| symbol | TEXT | 'SPY' or 'QQQ' |
| datetime | TEXT | '2026-01-10 09:30:00' (ET) |
| open | REAL | Open price |
| high | REAL | High price |
| low | REAL | Low price |
| close | REAL | Close price |
| volume | INTEGER | Volume |

**Coverage**: 5 years (Alpaca provides up to 5 years free)

**Size**: ~2.5MB per month per symbol (~60MB/year for both)

### Table: `option_chains`

Stores daily option chain snapshots (0DTE).

| Column | Type | Description |
|--------|------|-------------|
| root | TEXT | 'SPXW' or 'NDXW' |
| date | TEXT | '2026-01-10' (collection date) |
| expiration | TEXT | '2026-01-10' (0DTE) |
| strike | REAL | Strike price |
| option_type | TEXT | 'call' or 'put' |
| symbol | TEXT | Full OCC symbol |
| bid | REAL | Bid price |
| ask | REAL | Ask price |
| mid | REAL | Mid price (bid+ask)/2 |
| iv | REAL | Implied volatility |
| delta | REAL | Delta (if available) |
| gamma | REAL | Gamma (if available) |
| theta | REAL | Theta (if available) |

**Coverage**: Growing database (30 days from Tradier on first run, then daily additions)

**Size**: ~500KB per day (~15MB/month for both SPX+NDX)

### Table: `collection_log`

Tracks all collection attempts for debugging.

| Column | Type | Description |
|--------|------|-------------|
| collection_type | TEXT | 'underlying_1min' or 'option_chain' |
| symbol | TEXT | Symbol collected |
| start_date | TEXT | Collection start |
| end_date | TEXT | Collection end |
| bars_collected | INTEGER | Number of records |
| success | BOOLEAN | 1 = success, 0 = failure |
| error_message | TEXT | Error details if failed |
| created_at | TEXT | Timestamp |

## Usage

### Historical Collection (One-Time)

```bash
# Collect 365 days of underlying data
python3 data_collector.py --historical --days 365

# Collect 2 years
python3 data_collector.py --historical --days 730
```

**Note**: Option chains are limited to ~30 days from Tradier. Historical collection will skip options.

### Daily Collection (Automated via Cron)

The setup script creates a cron job:
```
0 17 * * 1-5 cd /gamma-scalper && python3 data_collector.py --daily
```

Runs Monday-Friday at 5:00 PM ET (after market close).

**What it collects**:
- ✅ Yesterday's + today's 1-minute bars (SPY, QQQ)
- ✅ Today's 0DTE option chain (SPX, NDX)

**Manual run**:
```bash
python3 data_collector.py --daily
```

### Check Status

```bash
python3 data_collector.py --status
```

**Output**:
```
======================================================================
DATABASE STATUS
======================================================================

Location: /gamma-scalper/market_data.db
Size: 245.3 MB

UNDERLYING 1-MINUTE BARS:
Symbol   Count      First Bar            Last Bar
----------------------------------------------------------------------
SPY      213,945    2025-01-08 09:30:00  2026-01-09 16:00:00
QQQ      223,554    2025-01-08 09:30:00  2026-01-09 16:00:00

OPTION CHAINS:
Root     Days   Options    First Date   Last Date
----------------------------------------------------------------------
SPXW       30    15,240    2025-12-10   2026-01-09
NDXW       30    12,180    2025-12-10   2026-01-09

RECENT COLLECTIONS (Last 10):
Type            Symbol   Date         Count   Status   Time
----------------------------------------------------------------------
underlying_1min QQQ      2026-01-09     850   ✓ OK     2026-01-09 17:05:12
underlying_1min SPY      2026-01-09     850   ✓ OK     2026-01-09 17:04:58
option_chain    NDXW     2026-01-09     406   ✓ OK     2026-01-09 17:06:33
option_chain    SPXW     2026-01-09     508   ✓ OK     2026-01-09 17:06:21
```

## Integration with Backtests

### Use Collected Data in Backtests

The parallel backtest automatically uses Alpaca data when available. The data collector ensures fresh data is always available locally (no API rate limits).

**Before data collector**:
```python
# Fetches from Alpaca API every backtest (slow, rate limited)
python backtest_parallel.py SPX --use-1min
```

**After data collector**:
```python
# Can read from local SQLite database (instant, no rate limits)
# TODO: Modify backtest_parallel.py to check DB first
```

### Read from Database (Example)

```python
import sqlite3
import pandas as pd

# Connect to database
conn = sqlite3.connect('/gamma-scalper/market_data.db')

# Get SPY 1-minute bars for specific date
query = """
    SELECT datetime, open, high, low, close, volume
    FROM underlying_1min
    WHERE symbol = 'SPY'
      AND datetime >= '2026-01-09 09:30:00'
      AND datetime <= '2026-01-09 16:00:00'
    ORDER BY datetime
"""

df = pd.read_sql_query(query, conn, parse_dates=['datetime'])
conn.close()

print(f"Loaded {len(df)} bars")
```

### Get Option Chain for Specific Date

```python
# Get SPX 0DTE chain for 2026-01-09
query = """
    SELECT strike, option_type, bid, ask, mid, iv, delta, gamma
    FROM option_chains
    WHERE root = 'SPXW'
      AND date = '2026-01-09'
      AND expiration = '2026-01-09'
    ORDER BY strike
"""

options = pd.read_sql_query(query, conn)
```

## Monitoring

### Check Collection Logs

```bash
# Live tail
tail -f /gamma-scalper/data_collector.log

# Last 50 lines
tail -50 /gamma-scalper/data_collector.log

# Search for errors
grep "ERROR\|Failed" /gamma-scalper/data_collector.log
```

### Verify Cron Job

```bash
# List cron jobs
crontab -l | grep data_collector

# Test cron job manually
cd /gamma-scalper && python3 data_collector.py --daily
```

### Database Size Management

```bash
# Check database size
du -h /gamma-scalper/market_data.db

# Vacuum database (reclaim space)
sqlite3 /gamma-scalper/market_data.db "VACUUM;"
```

**Expected sizes**:
- 1 year underlying: ~120MB (both SPY+QQQ)
- 1 year options: ~180MB (both SPX+NDX, daily snapshots)
- **Total**: ~300MB per year

## Troubleshooting

### "Alpaca API keys not found"

```bash
# Check if keys are set
echo $APCA_API_KEY_ID

# If empty, add to environment
export APCA_API_KEY_ID="PK..."
export APCA_API_SECRET_KEY="..."

# Or source from file
source /etc/gamma.env
```

### "Tradier API error: 401"

```bash
# Check Tradier token
echo $TRADIER_API_TOKEN

# Test API manually
curl -H "Authorization: Bearer $TRADIER_API_TOKEN" \
  "https://api.tradier.com/v1/markets/options/chains?symbol=SPXW&expiration=2026-01-10"
```

### "Database locked"

If collection fails with "database is locked":
```bash
# Check for running processes
ps aux | grep data_collector

# Kill hung processes
pkill -f data_collector.py

# Retry
python3 data_collector.py --daily
```

### Cron Job Not Running

```bash
# Check cron service
systemctl status cron

# Check cron logs
grep data_collector /var/log/syslog

# Test cron environment (cron may not have env vars)
# Add to crontab:
SHELL=/bin/bash
BASH_ENV=/etc/gamma.env

0 17 * * 1-5 cd /gamma-scalper && python3 data_collector.py --daily
```

## Advanced Usage

### Backfill Missing Data

```bash
# Backfill specific date range
python3 << 'EOF'
from data_collector import collect_underlying_bars_alpaca
import datetime

start = datetime.datetime(2025, 1, 1)
end = datetime.datetime(2025, 12, 31)

collect_underlying_bars_alpaca('SPY', start, end)
collect_underlying_bars_alpaca('QQQ', start, end)
EOF
```

### Export Data

```bash
# Export to CSV
sqlite3 /gamma-scalper/market_data.db << 'EOF'
.headers on
.mode csv
.output spy_2026.csv
SELECT * FROM underlying_1min WHERE symbol='SPY' AND datetime >= '2026-01-01';
.quit
EOF
```

### Database Optimization

```python
# Create additional indexes for faster queries
import sqlite3

conn = sqlite3.connect('/gamma-scalper/market_data.db')
cursor = conn.cursor()

# Index for date range queries
cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_underlying_date
    ON underlying_1min(symbol, date(datetime))
''')

# Index for option strike lookups
cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_option_strike
    ON option_chains(root, expiration, strike, option_type)
''')

conn.commit()
conn.close()
```

## Integration Roadmap

### Phase 1: Data Collection (Current)
- ✅ Collect underlying 1-minute bars
- ✅ Collect daily option chains
- ✅ Automated cron job
- ✅ Status monitoring

### Phase 2: Backtest Integration (TODO)
- 🔲 Modify `backtest_parallel.py` to check DB first
- 🔲 Fall back to Alpaca API if DB missing data
- 🔲 Use real option prices from DB (not estimated)

### Phase 3: Production Trading (TODO)
- 🔲 Real-time option chain updates during market hours
- 🔲 Compare backtest fills vs real option prices
- 🔲 Track actual vs estimated entry credits

## Cost Analysis

**Free tier (Alpaca + Tradier sandbox)**:
- ✅ Unlimited underlying 1-minute bars
- ✅ 30 days option chain history
- ✅ Daily option chain snapshots
- ✅ No API rate limits (data stored locally)

**Paid alternatives** (if needed):
- ThetaData: $150/month (unlimited option history)
- Polygon.io: $200/month (full market data)

**Recommendation**: Start with free tier, upgrade only if backtesting requires >30 days option chains.

---

**Created**: 2026-01-10
**Purpose**: Historical data collection for accurate backtesting
**Status**: Production ready
