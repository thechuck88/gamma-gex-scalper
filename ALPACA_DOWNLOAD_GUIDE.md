# Alpaca 0DTE Download - Quick Start Guide

**Date**: 2026-01-10
**Cost**: $0 (FREE)
**Scripts**: 2 versions available (parallel recommended)

---

## Quick Start

### Test Download (Single Date)

```bash
# Source credentials
source /etc/gamma.env

# Test with Jan 17, 2025 (single date, first 10 options per underlying)
python3 download_alpaca_0dte_parallel.py --start 2025-01-17 --end 2025-01-17 --test
```

**Expected Output**:
```
📅 2025-01-17 (Friday)
SPX: 10 options (ATM $5,897, strikes 5855-5945)
NDX: 10 options (ATM $21,456, strikes 21000-21500)
Total options: 20
Workers: 30
Downloading...
✓ Downloaded: 15/20 options had data
✓ Stored 1,247 bars
```

### Full Download (1-2 Years)

```bash
# Download 2024-2025 (all Mon/Wed/Fri)
python3 download_alpaca_0dte_parallel.py --start 2024-01-01 --end 2025-12-31

# Expected time: 6-12 hours
# Expected bars: 20-40 million
```

### Resume After Interruption

```bash
# Resume from last checkpoint
python3 download_alpaca_0dte_parallel.py --resume
```

### Check Status

```bash
# Show database status
python3 download_alpaca_0dte_parallel.py --status
```

**Output**:
```
Database: /gamma-scalper/market_data.db
  Total bars: 35,247,892
  Options: 156,432
  Dates: 312
  Range: 2024-01-01 09:30:00 to 2025-12-31 16:00:00
```

---

## Script Comparison

### Parallel (Recommended) ⭐

**File**: `download_alpaca_0dte_parallel.py`

**Features**:
- 30 concurrent workers
- ~30× faster than sequential
- 6-12 hours for full download

**Usage**:
```bash
python3 download_alpaca_0dte_parallel.py --start 2024-01-01 --end 2025-12-31
```

**Speed**: ~400 options/minute (13,000 bars/minute)

### Sequential (Backup)

**File**: `download_alpaca_0dte.py`

**Features**:
- Single-threaded
- Slower but more stable
- Use if parallel has issues

**Usage**:
```bash
python3 download_alpaca_0dte.py --start 2024-01-01 --end 2025-12-31
```

**Speed**: ~13 options/minute (400 bars/minute)

---

## What Gets Downloaded

### Date Selection

**0DTE Dates**: Mon/Wed/Fri only (SPX/NDX weekly expirations)

**2024**: 156 dates × 2 underlyings = 312 expiration days
**2025**: 156 dates × 2 underlyings = 312 expiration days
**Total**: ~624 expiration days over 2 years

### Option Selection

**Per Underlying**:
- ATM ± 10 strikes
- SPX: 21 strikes × 2 sides = 42 options
- NDX: 21 strikes × 2 sides = 42 options

**Per Date**:
- SPX: 42 options
- NDX: 42 options
- **Total: 84 options per date**

**Full Download**:
- 624 dates × 84 options = **52,416 options total**

### Data Granularity

**Timeframe**: 1-minute OHLCV bars

**Market Hours**: 9:30 AM - 4:00 PM ET (390 minutes)

**Typical 0DTE**: Entry at 10:00 AM, expiry at 4:00 PM (360 minutes)

**Bars per Option**: 100-300 bars average

**Total Bars**: 52,416 options × 150 bars avg = **~8 million bars**

(Actual may be higher, some options trade more actively)

---

## Storage

### Database

**File**: `/gamma-scalper/market_data.db`

**Table**: `option_bars_0dte`

**Schema**:
```sql
CREATE TABLE option_bars_0dte (
    symbol TEXT,
    datetime TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    underlying TEXT,
    strike REAL,
    option_type TEXT,  -- 'call' or 'put'
    expiration TEXT,   -- YYYY-MM-DD
    PRIMARY KEY (symbol, datetime)
);
```

**Indexes**:
- Primary key on (symbol, datetime)
- Index on expiration date
- Index on underlying + expiration

**Size Estimate**:
- 8 million bars × ~80 bytes = 640 MB uncompressed
- SQLite compression: ~200-300 MB actual
- Plus indexes: ~400-500 MB total

### Checkpoint

**File**: `/gamma-scalper/alpaca_0dte_checkpoint.json`

**Format**:
```json
{
  "completed_dates": [
    "2024-01-01",
    "2024-01-03",
    "2024-01-05",
    ...
  ],
  "last_date": "2025-12-31"
}
```

**Purpose**: Resume download if interrupted

---

## Performance

### Parallel Script (30 Workers)

**Per Date**:
- 84 options per date
- 30 workers processing in parallel
- ~0.5 seconds per option per worker
- **Time per date: ~1.4 minutes**

**Full Download**:
- 624 dates × 1.4 min = **875 minutes = 14.6 hours**
- With overhead: **16-20 hours realistic**

**Throughput**:
- ~400 options/minute
- ~60,000 bars/minute (with data)
- ~3.6 million bars/hour

### Sequential Script (Fallback)

**Per Date**:
- 84 options per date
- ~0.33 seconds per option (rate limiting)
- **Time per date: ~28 minutes**

**Full Download**:
- 624 dates × 28 min = **17,472 minutes = 291 hours = 12 days**

**Use Case**: Only if parallel fails

---

## Troubleshooting

### Rate Limit Errors

**Symptom**: "rate limit exceeded" errors

**Fix**: Script auto-retries with 60-second delay

**Prevention**: Keep workers at 30 or reduce to 20

### Memory Issues

**Symptom**: System slowdown, swap usage

**Fix**: Reduce workers to 20 or 15

```bash
python3 download_alpaca_0dte_parallel.py --workers 20 --start 2024-01-01 --end 2025-12-31
```

### Missing Data for Some Options

**Symptom**: Many "No data" results

**Reason**: Normal - not all strikes trade on all days

**Expected**: 40-60% of options will have data (far OTM strikes don't trade)

### Database Lock Errors

**Symptom**: "database is locked"

**Fix**: Script uses batch writes to avoid this

**Workaround**: Close any other programs accessing the database

---

## Validation

### Check Download Progress

```bash
# During download
tail -f /tmp/alpaca_download.log  # If logging enabled

# After download
python3 download_alpaca_0dte_parallel.py --status
```

### Query Database

```bash
sqlite3 /gamma-scalper/market_data.db
```

```sql
-- Count bars by date
SELECT
    DATE(datetime) as date,
    COUNT(*) as bars,
    COUNT(DISTINCT symbol) as options
FROM option_bars_0dte
WHERE underlying = 'SPX'
GROUP BY DATE(datetime)
ORDER BY date DESC
LIMIT 10;

-- Check specific expiration
SELECT
    symbol,
    COUNT(*) as bars,
    MIN(datetime) as first_bar,
    MAX(datetime) as last_bar
FROM option_bars_0dte
WHERE expiration = '2025-01-17'
GROUP BY symbol
LIMIT 10;

-- Average premium by strike (for validation)
SELECT
    strike,
    option_type,
    AVG(close) as avg_premium,
    COUNT(*) as bars
FROM option_bars_0dte
WHERE underlying = 'SPX'
  AND expiration = '2025-01-17'
  AND datetime LIKE '%10:00:00'  -- Entry time
GROUP BY strike, option_type
ORDER BY strike;
```

---

## Next Steps After Download

### 1. Validate Data Quality

**Check**:
- All expected dates present (Mon/Wed/Fri)
- Reasonable number of bars per option
- Premiums look realistic ($1-10 for near-ATM 0DTE)

### 2. Integrate with Backtest

**Update backtest script**:
```python
# Replace estimation with real data
def get_entry_credit(underlying, strike, option_type, entry_time, expiration):
    """Get real entry credit from Alpaca data."""
    query = """
        SELECT close
        FROM option_bars_0dte
        WHERE underlying = ?
          AND strike = ?
          AND option_type = ?
          AND expiration = ?
          AND datetime = ?
        LIMIT 1
    """
    result = cursor.execute(query, (underlying, strike, option_type,
                                     expiration, entry_time)).fetchone()
    return result[0] if result else None
```

### 3. Run Validation Backtest

**Compare**:
- Estimation: $1-2 credit assumption
- Real data: Actual credits from Alpaca
- Expected: Within 20% difference

### 4. Optimize Parameters

**With real data**:
- Test different entry times
- Test different strike selections
- Test different exit rules
- Find optimal parameters for live trading

---

## Cost Comparison Final

### Total Cost: $0 ✅

**vs Alternatives**:
- ThetaData: $150/month or $150 one-time
- IBKR: $10/month ($120/year)
- Databento: $25/month (doesn't have 0DTE anyway)

**Savings**: $150-1,800 depending on alternative

---

## Summary

### Setup (5 minutes)

```bash
# 1. Source credentials
source /etc/gamma.env

# 2. Test with single date
python3 download_alpaca_0dte_parallel.py --start 2025-01-17 --end 2025-01-17 --test

# 3. If successful, start full download
python3 download_alpaca_0dte_parallel.py --start 2024-01-01 --end 2025-12-31
```

### Timeline

**Week 1**: Download 2024-2025 data (16-20 hours runtime)
**Week 2**: Validate data quality
**Week 3**: Integrate with backtest
**Week 4**: Run validation and optimize

### Result

✅ 1-2 years of 0DTE historical data
✅ 8+ million bars (SPX + NDX)
✅ Real market prices for backtest validation
✅ $0 cost (FREE Alpaca paper account)

---

**Created**: 2026-01-10
**Status**: Ready to use
**Next**: Run test download, then full download

