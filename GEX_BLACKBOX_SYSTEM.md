### GEX Black Box Recorder System - Complete Guide

**Purpose**: Record real-time options market data to enable ACCURATE historical backtesting

**Problem Solved**: Previous backtests used fake GEX (random pins). Now we can backtest with REAL historical GEX peaks!

---

## System Overview

### The Black Box Records:
1. **Full options chains** (strikes, OI, gamma, bid/ask)
2. **Calculated GEX by strike** (dealer positioning)
3. **Top 3 proximity-weighted peaks** (same algorithm as bot)
4. **Competing peaks detection** (IC opportunities)
5. **Market context** (underlying price, VIX, SPY/QQQ)

### Database Schema:
```sql
options_snapshots  -- Raw options chain data
gex_peaks          -- Top 3 peaks per snapshot
competing_peaks    -- IC opportunity detection
market_context     -- Underlying prices, VIX
```

---

## Installation & Setup

### 1. Create Data Directory
```bash
mkdir -p /root/gamma/data
chmod 755 /root/gamma/gex_blackbox_recorder.py
chmod 755 /root/gamma/gex_blackbox_backtest.py
```

### 2. Test Manual Recording
```bash
# Record single snapshot for SPX
python3 /root/gamma/gex_blackbox_recorder.py SPX

# Record single snapshot for NDX
python3 /root/gamma/gex_blackbox_recorder.py NDX

# Check database was created
ls -lh /root/gamma/data/gex_blackbox.db
```

### 3. Deploy as Systemd Service (Recommended)

**The black box recorder now runs as a systemd service with auto-restart:**

```bash
# Service is already running!
systemctl status gex-blackbox-recorder

# Service commands
systemctl start gex-blackbox-recorder    # Start service
systemctl stop gex-blackbox-recorder     # Stop service
systemctl restart gex-blackbox-recorder  # Restart service
systemctl enable gex-blackbox-recorder   # Enable on boot (already enabled)

# View live logs
journalctl -u gex-blackbox-recorder -f

# View last 50 log lines
journalctl -u gex-blackbox-recorder -n 50
```

**Service Features:**
- ✅ Auto-starts on boot
- ✅ Auto-restarts on crash (30 second delay)
- ✅ Records SPX and NDX every 5 minutes during market hours
- ✅ Sleeps intelligently outside market hours
- ✅ Checks for trading days (respects `/etc/trading-day` flag)
- ✅ Resource limits (500MB memory, 50% CPU)

**Alternative: Manual Cron (Not Recommended)**
```bash
# If you prefer cron instead of systemd service
crontab -e

# Add these lines:
*/5 9-16 * * 1-5 cd /root/gamma && /usr/bin/python3 /root/gamma/gex_blackbox_recorder.py SPX >> /var/log/gex_recorder.log 2>&1
*/5 9-16 * * 1-5 cd /root/gamma && /usr/bin/python3 /root/gamma/gex_blackbox_recorder.py NDX >> /var/log/gex_recorder.log 2>&1
```

**Recording Frequency:**
- Every 5 minutes during market hours (9 AM - 4 PM ET)
- 84 snapshots per day per index
- ~420 snapshots per week per index
- ~1,680 snapshots per month per index

**Data Size Estimates:**
- Per snapshot: ~50-100 KB (full chain + metadata)
- Per day: ~8 MB per index
- Per month: ~240 MB per index
- Per year: ~2.9 GB per index

---

## Usage

### Recording Data

#### Manual (Single Snapshot):
```bash
# SPX
python3 /root/gamma/gex_blackbox_recorder.py SPX

# NDX
python3 /root/gamma/gex_blackbox_recorder.py NDX
```

#### Automated (Cron):
Once cron is deployed, data collection is automatic!

**Check logs (systemd service):**
```bash
# Live tail
journalctl -u gex-blackbox-recorder -f

# Last 50 lines
journalctl -u gex-blackbox-recorder -n 50

# Check service status
systemctl status gex-blackbox-recorder
```

**Check logs (cron - if using cron instead):**
```bash
tail -f /var/log/gex_recorder.log
```

---

### Analyzing Recorded Data

#### Check Data Coverage:
```bash
# SPX coverage
python3 /root/gamma/gex_blackbox_backtest.py SPX --coverage

# NDX coverage
python3 /root/gamma/gex_blackbox_backtest.py NDX --coverage
```

**Output:**
```
============================================================
DATA COVERAGE: SPX
============================================================
First snapshot: 2026-01-13 09:35:00
Last snapshot:  2026-02-13 16:00:00
Total snapshots: 2,520
Trading days: 30
Avg snapshots/day: 84.0
Days with competing peaks: 6 (20.0%)
```

#### Run Backtest:
```bash
# Last 30 days (default)
python3 /root/gamma/gex_blackbox_backtest.py SPX

# Specific date range
python3 /root/gamma/gex_blackbox_backtest.py SPX 2026-01-13 2026-02-13

# All available data
python3 /root/gamma/gex_blackbox_backtest.py SPX --all
```

---

## Database Queries (Advanced)

### Direct SQLite Access:
```bash
sqlite3 /root/gamma/data/gex_blackbox.db
```

### Useful Queries:

#### 1. Count Snapshots by Date:
```sql
SELECT
    DATE(timestamp) as date,
    COUNT(*) as snapshots
FROM options_snapshots
WHERE index_symbol = 'SPX'
GROUP BY DATE(timestamp)
ORDER BY date DESC
LIMIT 30;
```

#### 2. Days with Competing Peaks:
```sql
SELECT
    DATE(timestamp) as date,
    COUNT(*) as competing_instances,
    GROUP_CONCAT(DISTINCT TIME(timestamp)) as times
FROM competing_peaks
WHERE index_symbol = 'SPX' AND is_competing = 1
GROUP BY DATE(timestamp)
ORDER BY date DESC;
```

#### 3. GEX Peak Statistics:
```sql
SELECT
    DATE(timestamp) as date,
    AVG(gex) as avg_peak_gex,
    AVG(distance_from_price) as avg_distance,
    COUNT(*) as peak_count
FROM gex_peaks
WHERE index_symbol = 'SPX' AND peak_rank = 1
GROUP BY DATE(timestamp)
ORDER BY date DESC
LIMIT 30;
```

#### 4. Intraday GEX Evolution:
```sql
SELECT
    TIME(timestamp) as time,
    strike,
    gex / 1e9 as gex_billions,
    distance_from_price
FROM gex_peaks
WHERE index_symbol = 'SPX'
    AND DATE(timestamp) = '2026-01-13'
    AND peak_rank = 1
ORDER BY timestamp;
```

---

## Building Real Backtests

### Current Status:
The `gex_blackbox_backtest.py` is a **FRAMEWORK** - it demonstrates structure but needs full implementation.

### What's Needed for Production Backtest:

#### 1. **Precise Entry Logic**
```python
def should_enter_trade(snapshot, current_time):
    """
    Determine if bot would enter at this snapshot.

    Checks:
    - Time window (9:36 AM, hourly intervals)
    - VIX filter (>= 12.0)
    - RSI filter (40-80 range)
    - Friday filter
    - Consecutive down days filter
    - Gap size filter
    - Distance from pin
    - Minimum credit threshold
    - Spread quality check
    """
    # Implementation here
```

#### 2. **Strike Selection from Chain**
```python
def select_strikes(snapshot, pin_price, strategy_type):
    """
    Select actual strikes from recorded chain.

    Uses recorded bid/ask to:
    - Find optimal strikes (buffer from pin)
    - Calculate expected credit
    - Verify spread width
    """
    chain = snapshot['chain']
    # Implementation here
```

#### 3. **Credit Calculation**
```python
def calculate_entry_credit(chain, short_strike, long_strike, option_type):
    """
    Calculate credit from recorded bid/ask.

    Returns:
    - Expected credit (short_mid - long_mid)
    - Slippage estimate
    - Spread quality score
    """
    # Find options in chain
    # Calculate mid prices
    # Return credit
```

#### 4. **Exit Monitoring**
```python
def check_exits(position, current_snapshot, snapshots_since_entry):
    """
    Check if any exit condition is met.

    Monitors:
    - Profit target (50% or 60%)
    - Stop loss (10% with grace period)
    - Trailing stop (20% trigger, 12% lock)
    - Auto-close (3:30 PM)
    - Hold-to-expiry qualification
    """
    # Implementation here
```

#### 5. **P&L Calculation**
```python
def calculate_pnl(entry_credit, exit_credit, contracts, commissions):
    """
    Calculate exact P&L.

    Accounts for:
    - Entry credit received
    - Exit debit paid (or $0 if expired worthless)
    - Commissions ($1.32 per contract)
    - Slippage estimates
    """
    # Implementation here
```

### Implementation Template:
```python
def run_production_backtest(index_symbol, start_date, end_date):
    """Full production backtest using recorded data."""

    snapshots = get_snapshots(index_symbol, start_date, end_date)

    positions = []  # Active positions
    trades = []     # Completed trades

    for snapshot in snapshots:
        current_time = snapshot['timestamp']

        # Check exits for active positions
        for position in positions[:]:  # Copy list
            exit_result = check_exits(position, snapshot, snapshots)
            if exit_result['should_exit']:
                trade = close_position(position, snapshot, exit_result)
                trades.append(trade)
                positions.remove(position)

        # Check for new entries
        if should_enter_trade(snapshot, current_time):
            # Select strikes
            strikes = select_strikes(
                snapshot,
                snapshot['adjusted_pin'] if snapshot['is_competing'] else snapshot['peak1_strike'],
                'IC' if snapshot['is_competing'] else 'DIRECTIONAL'
            )

            # Calculate credit
            credit = calculate_entry_credit(snapshot['chain'], strikes)

            if credit >= minimum_credit(current_time):
                # Open position
                position = open_position(snapshot, strikes, credit)
                positions.append(position)

    # Return results
    return analyze_trades(trades)
```

---

## Data Collection Best Practices

### 1. **Start Recording NOW**
Even if backtest isn't ready, START COLLECTING DATA!
```bash
# Deploy cron jobs immediately
crontab -e
# Add the cron entries above
```

**Why:** Data collection takes time. In 90 days you'll have 90 days of data. In 1 year, 1 year of data!

### 2. **Monitor Data Collection**
```bash
# Check daily
python3 /root/gamma/gex_blackbox_backtest.py SPX --coverage

# Check logs for errors
tail -50 /var/log/gex_recorder.log | grep -i error
```

### 3. **Backup Database Regularly**
```bash
# Add to daily cron
0 1 * * * cp /root/gamma/data/gex_blackbox.db /root/gamma/data/backups/gex_blackbox_$(date +\%Y\%m\%d).db
```

### 4. **Handle Missing Data**
Snapshots may fail due to:
- API rate limits
- Network issues
- Market closed days
- Holidays

**Check for gaps:**
```sql
SELECT
    DATE(timestamp) as date,
    COUNT(*) as snapshots,
    MIN(TIME(timestamp)) as first_time,
    MAX(TIME(timestamp)) as last_time
FROM options_snapshots
WHERE index_symbol = 'SPX'
GROUP BY DATE(timestamp)
HAVING snapshots < 70  -- Flag days with < 70 snapshots (should be ~84)
ORDER BY date DESC;
```

---

## Timeline to Usable Backtest

### Immediate (Day 1):
- ✅ Deploy cron jobs
- ✅ Start collecting data
- ✅ Verify database is growing

### Week 1:
- ✅ 5 trading days of data
- ✅ Can test framework on 1 week
- ⚠️ Not enough for validation

### Month 1:
- ✅ 20-22 trading days of data
- ✅ Can test competing peaks frequency
- ⚠️ Still limited sample size

### Month 3 (90 Days):
- ✅ 60-65 trading days of data
- ✅ **MINIMUM for strategy validation**
- ✅ Can measure win rate, profit factor
- ✅ Captures different market regimes

### Month 6 (180 Days):
- ✅ 120-130 trading days
- ✅ Strong statistical significance
- ✅ Covers multiple VIX regimes

### Year 1 (365 Days):
- ✅ 250-260 trading days
- ✅ **GOLD STANDARD** for strategy validation
- ✅ Covers full year of market conditions

---

## Expected Data Collection Timeline

**Starting Date:** January 13, 2026 (Monday)

| Date | Days | Snapshots | Usage |
|------|------|-----------|-------|
| Jan 13 | 1 | 168 | Test framework |
| Jan 20 | 5 | 840 | 1 week test |
| Feb 13 | 22 | 3,696 | 1 month validation |
| Apr 13 | 65 | 10,920 | **3 month backtest (minimum)** |
| Jul 13 | 130 | 21,840 | 6 month backtest (strong) |
| Jan 13, 2027 | 260 | 43,680 | **1 year backtest (gold standard)** |

---

## Advantages Over Fake Backtests

### OLD (Fake GEX):
```python
gex_pin = spx_price + random.uniform(-10, 10)  # FAKE!
```
❌ No real gamma landscape
❌ Can't validate peak selection
❌ Can't test competing peaks logic
❌ Massively inflated trade count
❌ **Results are worthless**

### NEW (Real GEX):
```python
gex_pin = calculate_from_recorded_options_chain()  # REAL!
```
✅ Actual historical GEX peaks
✅ Validates proximity-weighted scoring
✅ Tests competing peaks detection
✅ Realistic trade frequency
✅ **Results are trustworthy**

---

## Next Steps

### Immediate (Today):
1. ✅ **DEPLOYED** - Systemd service running with auto-restart
2. ✅ Database created with correct schema
3. ✅ Service will begin recording at market open (Mon 9:30 AM ET)

### This Week:
1. Monitor data collection (check logs daily)
2. Run coverage checks to verify no gaps
3. Test framework with 1 week of data

### This Month:
1. Keep collecting data (hands-off)
2. Check for competing peaks frequency
3. Prepare for 3-month backtest milestone

### In 3 Months (April 13):
1. Run full production backtest (need to implement)
2. Compare results to fake backtests
3. Validate strategy with real data

### In 1 Year (Jan 13, 2027):
1. Run 1-year backtest (gold standard)
2. Publish results with confidence
3. Deploy live if validated

---

## Summary

✅ **Black Box System Created**
✅ **Records real GEX peaks** (not fake!)
✅ **Framework for replay** (needs production implementation)
✅ **Database schema** optimized for backtesting
✅ **Cron deployment** ready

**✅ DEPLOYED:** Black box recorder is running as systemd service!

```bash
# Service is active and collecting data
systemctl status gex-blackbox-recorder

# Monitor live logs
journalctl -u gex-blackbox-recorder -f
```

**Data collection starts Monday Jan 13, 2026 at 9:30 AM ET**

**In 90 days (Apr 13, 2026), you'll have 90 days of REAL data to backtest!**
**In 1 year (Jan 13, 2027), you'll have 1 year of REAL data - the gold standard!**

🚀 Recording begins at market open!
