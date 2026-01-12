# GEX Black Box Recorder v2 - DEPLOYED

**Date**: January 12, 2026 (Sunday 2:37 AM ET)
**Status**: ✅ LIVE - Running dual-schedule recording

---

## What Changed from v1

### v1 (Old - Deprecated)
- Recorded full chains every 5 minutes (too frequent for GEX, not granular enough for stops)
- 84 snapshots per day per index
- ~8 MB per day per index

### v2 (New - Current)
- **GEX Peaks**: Only at bot's entry check times (12 times per day)
- **Live Pricing**: Every 30 seconds for strikes near pin (780 times per day)
- Optimized for accurate stop loss backtesting

---

## Dual Recording Architecture

### Thread 1: GEX Peak Recorder

**Schedule**: Runs at bot's exact entry check times
```
09:36 AM - First check (after market open)
10:00 AM
10:30 AM
11:00 AM
11:30 AM
12:00 PM
12:30 PM
01:00 PM
01:30 PM
02:00 PM
02:30 PM
03:00 PM - Last check
```

**What it records**:
- Full options chain (all strikes)
- Calculates GEX by strike
- Identifies top 3 proximity-weighted peaks
- Detects competing peaks scenarios
- Stores to `gex_peaks`, `competing_peaks`, `options_snapshots` tables

**Frequency**: 12 snapshots per day per index = 24 total

---

### Thread 2: Live Price Monitor

**Schedule**: Every 30 seconds during market hours (9:30 AM - 4:00 PM ET)

**What it records**:
- Options pricing for strikes within **±60 points of current pin**
- Only bid, ask, mid, last, volume, OI
- Uses most recent GEX pin from Thread 1

**Frequency**: ~780 snapshots per day per index = 1,560 total

**Why ±60 points?**
- Bot typically places spreads 10-30 points from pin
- 60-point buffer captures all relevant strikes for stop loss testing
- Reduces data size vs recording full chain

**Storage**: New table `options_prices_live`
```sql
CREATE TABLE options_prices_live (
    timestamp DATETIME,
    index_symbol TEXT,
    strike REAL,
    option_type TEXT,  -- 'call' or 'put'
    bid REAL,
    ask REAL,
    mid REAL,
    last REAL,
    volume INTEGER,
    open_interest INTEGER
)
```

---

## How It Works

### Flow at 9:36 AM (Entry Check Time)

1. **GEX Thread wakes up** (detects it's a check time)
2. Records SPX full chain → calculates GEX → finds pin at 6000
3. Records NDX full chain → calculates GEX → finds pin at 21500
4. Sleeps until next check (10:00 AM)

### Flow Every 30 Seconds (Price Monitoring)

1. **Price Thread wakes up** (every 30s)
2. Queries latest pin from `gex_peaks` table
   - SPX pin: 6000 (from 9:36 AM snapshot)
   - NDX pin: 21500 (from 9:36 AM snapshot)
3. Fetches only strikes 5940-6060 for SPX (±60pts)
4. Fetches only strikes 21440-21560 for NDX (±60pts)
5. Stores bid/ask/mid to `options_prices_live`
6. Sleeps 30 seconds, repeats

### Pin Updates Throughout Day

- Pin is recalculated every hour at entry check times
- Price thread automatically uses the latest pin
- Example timeline:
  - 9:36 AM: Pin = 6000 → Price thread monitors 5940-6060
  - 10:00 AM: Pin = 6010 → Price thread now monitors 5950-6070
  - 10:30 AM: Pin = 5995 → Price thread now monitors 5935-6055

---

## Database Schema

### Existing Tables (from v1)
- `options_snapshots` - Full chain snapshots (12 per day)
- `gex_peaks` - Top 3 peaks per snapshot (36 per day)
- `competing_peaks` - IC detection (12 per day)
- `market_context` - Underlying prices, VIX (12 per day)

### New Table (v2)
- `options_prices_live` - Live pricing near pin (780 per day per index)

---

## Data Size Estimates

### Per Day (Both Indices)
- **GEX snapshots**: ~2 MB (12 snapshots × 2 indices)
- **Live pricing**: ~15 MB (780 snapshots × 2 indices × ~20 strikes)
- **Total**: ~17 MB per day

### Over Time
| Period | Total Size |
|--------|------------|
| 1 week | ~120 MB |
| 1 month | ~510 MB |
| 3 months | ~1.5 GB |
| 1 year | ~6.2 GB |

---

## Monitoring Commands

### Check Service Status
```bash
systemctl status gex-blackbox-recorder
```

### View Live Logs (Both Threads)
```bash
journalctl -u gex-blackbox-recorder -f
```

### Query GEX Snapshots (Entry Times Only)
```bash
sqlite3 /root/gamma/data/gex_blackbox.db

SELECT timestamp, index_symbol, COUNT(*) as options_count
FROM options_snapshots
GROUP BY timestamp, index_symbol
ORDER BY timestamp DESC
LIMIT 20;
```

### Query Live Pricing (30-Second Data)
```bash
sqlite3 /root/gamma/data/gex_blackbox.db

SELECT timestamp, index_symbol, COUNT(*) as strikes_recorded
FROM options_prices_live
GROUP BY timestamp, index_symbol
ORDER BY timestamp DESC
LIMIT 20;
```

### Check Data Coverage by Hour
```bash
sqlite3 /root/gamma/data/gex_blackbox.db

-- GEX checks (should be ~12 per day)
SELECT DATE(timestamp) as date, COUNT(*) as gex_checks
FROM gex_peaks
WHERE index_symbol = 'SPX' AND peak_rank = 1
GROUP BY DATE(timestamp)
ORDER BY date DESC;

-- Price snapshots (should be ~780 per day)
SELECT DATE(timestamp) as date, COUNT(DISTINCT timestamp) as price_snapshots
FROM options_prices_live
WHERE index_symbol = 'SPX'
GROUP BY DATE(timestamp)
ORDER BY date DESC;
```

---

## Backtest Usage

### Entry Simulation (Using GEX Peaks)
```python
# Get GEX peak at 9:36 AM
cursor.execute("""
    SELECT strike, gex
    FROM gex_peaks
    WHERE index_symbol = 'SPX'
        AND timestamp >= '2026-01-13 09:36:00'
        AND timestamp < '2026-01-13 09:37:00'
        AND peak_rank = 1
""")
pin_strike, pin_gex = cursor.fetchone()

# Determine entry strikes (bot logic)
if price > pin_strike:
    # Sell call spread
    short_strike = pin_strike + 10
    long_strike = pin_strike + 20
else:
    # Sell put spread
    short_strike = pin_strike - 10
    long_strike = pin_strike - 20
```

### Stop Loss Testing (Using Live Pricing)
```python
# Monitor position every 30 seconds after entry
cursor.execute("""
    SELECT timestamp, strike, option_type, bid, ask, mid
    FROM options_prices_live
    WHERE index_symbol = 'SPX'
        AND timestamp >= ?
        AND timestamp <= ?
        AND strike IN (?, ?)
    ORDER BY timestamp ASC
""", (entry_time, exit_time, short_strike, long_strike))

for row in cursor.fetchall():
    ts, strike, opt_type, bid, ask, mid = row

    # Calculate current spread value
    if strike == short_strike:
        short_price = mid
    else:
        long_price = mid

    spread_value = short_price - long_price

    # Check stop loss (10% on credit)
    if spread_value >= entry_credit * 1.10:
        # STOPPED OUT
        exit_price = spread_value
        break
```

---

## Expected Data Collection

### First Day (Jan 13, 2026)
- **GEX checks**: 24 snapshots (12 SPX + 12 NDX)
- **Price snapshots**: ~1,560 (780 SPX + 780 NDX)
- **Total**: ~17 MB

### First Week (Jan 13-17)
- **GEX checks**: 120 snapshots (5 days × 24)
- **Price snapshots**: ~7,800 (5 days × 1,560)
- **Total**: ~120 MB

### 90 Days (Apr 13, 2026)
- **GEX checks**: ~1,560 snapshots
- **Price snapshots**: ~101,400
- **Total**: ~1.5 GB
- **Status**: Minimum for realistic backtesting

### 1 Year (Jan 13, 2027)
- **GEX checks**: ~6,240 snapshots
- **Price snapshots**: ~405,600
- **Total**: ~6.2 GB
- **Status**: Gold standard for strategy validation

---

## Advantages Over v1

### For Entry Testing
✅ Records GEX only when bot actually checks (not every 5 min)
✅ Captures exact entry conditions at bot's schedule
✅ Reduces redundant data (84 → 12 snapshots per day)

### For Stop Loss Testing
✅ 30-second granularity for accurate stop monitoring
✅ Only records strikes near pin (not full chain)
✅ Enables realistic P&L calculation during trade lifecycle

### Storage Efficiency
✅ Smarter data collection (17 MB/day vs 16 MB/day in v1)
✅ More useful data (780 price snapshots vs 84 full chains)
✅ Optimized for backtest needs

---

## Service Management

### Start/Stop/Restart
```bash
systemctl start gex-blackbox-recorder
systemctl stop gex-blackbox-recorder
systemctl restart gex-blackbox-recorder
```

### Check Status
```bash
systemctl status gex-blackbox-recorder
```

### View Logs
```bash
# Live tail (both threads)
journalctl -u gex-blackbox-recorder -f

# Last 50 lines
journalctl -u gex-blackbox-recorder -n 50

# Errors only
journalctl -u gex-blackbox-recorder -p err
```

---

## Summary

✅ **Dual-thread architecture**: GEX peaks + live pricing
✅ **Smart scheduling**: Entry checks only (12/day) + price monitoring (780/day)
✅ **Optimized storage**: Records only what's needed for backtest
✅ **Stop loss ready**: 30-second pricing for accurate exit testing
✅ **Auto-restart**: Service recovers from crashes automatically

**The black box v2 is running! Data collection begins Monday Jan 13 at 9:36 AM ET.**

🚀 **In 90 days, you'll have realistic entry data AND granular stop loss data for accurate backtesting!**
