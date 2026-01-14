# GEX Blackbox Data Collector - Backfill Feature

## Overview

The GEX blackbox data collector now automatically attempts to backfill missing data when the service restarts during market hours.

## How It Works

### Automatic Backfill on Service Startup

When `gex-blackbox-recorder.service` starts during market hours, it:

1. **Detects Missing Times**: Checks which scheduled GEX snapshots are missing from today's data
   - Compares database against scheduled times: 9:36, 10:00, 10:30, 11:00, 11:30, 12:00, 12:30, 13:00, 13:30, 14:00, 14:30, 15:00

2. **Filters to Past Times**: Only attempts to backfill times that have already passed
   - Skips future scheduled times (those haven't happened yet)

3. **Attempts Historical Data Retrieval**:
   - **Underlying Prices**: Uses Tradier's `timesales` API to get 1-minute historical bars
   - **Option Chains**: Attempts to fetch historical option chains (limited availability)

4. **Calculates and Stores**:
   - Calculates GEX peaks from historical data
   - Stores to database with proper timestamps

### Limitations

**Historical Option Chain Data:**
- Tradier's API only provides **current** option chain data
- Historical intraday option chains are **not available** via Tradier
- Backfill will only work for very recent times (< 1 minute ago)

**What Gets Backfilled:**
- ✅ Underlying prices (SPX via SPY, NDX via QQQ)
- ✅ VIX levels
- ❌ Option chains (not available historically)
- ❌ GEX calculations (require option chains)

### Manual Backfill

You can manually run backfill for a specific date:

```bash
# Backfill today (auto-detect)
python3 /gamma-scalper/gex_blackbox_backfill.py

# Backfill specific date
python3 /gamma-scalper/gex_blackbox_backfill.py 2026-01-13
```

## Example Scenario

**Problem:**
Server reboots at 11:15 AM ET due to kernel update.

**What Happens:**

1. **Missed Data:**
   - 9:36 AM snapshot ✅ (collected before reboot)
   - 10:00 AM snapshot ✅ (collected before reboot)
   - 10:30 AM snapshot ❌ (missed during reboot)
   - 11:00 AM snapshot ❌ (missed during reboot)

2. **Service Restarts at 11:20 AM:**
   ```
   ======================================================================
   STARTUP BACKFILL - Checking for missed data
   ======================================================================

   ⚠️  SPX: Found 2 missed snapshots
     → Attempting 10:30 ET...
       ✓ SPX = 6965.20, VIX = 14.58
       ⚠️  Historical option chain not available (Tradier limitation)
       ❌ Backfill failed (no option data)

     → Attempting 11:00 ET...
       ✓ SPX = 6964.50, VIX = 14.62
       ⚠️  Historical option chain not available (Tradier limitation)
       ❌ Backfill failed (no option data)

   ======================================================================
   BACKFILL COMPLETE: ✅ 0 recovered, ❌ 2 failed
   ======================================================================
   ```

3. **Result:**
   - Service continues forward from 11:20 AM
   - Will catch 11:30 AM, 12:00 PM, etc. going forward
   - 10:30 AM and 11:00 AM data remain missing (option chains not available)

## Real Solution for Historical Data

To truly backfill missed GEX snapshots, you would need:

1. **Historical Options Data Provider**:
   - CBOE DataShop (expensive)
   - OptionMetrics (academic/institutional)
   - HistoricalOptionData.com (commercial)
   - ORATS (options-focused data)

2. **Alternative Approach**:
   - Store more granular snapshots (every 5-10 minutes) during live collection
   - Reduces impact of short outages
   - Still requires service to be running

## Service Status Check

Check if backfill ran on last restart:

```bash
# View recent service logs
journalctl -u gex-blackbox-recorder -n 100 | grep -i backfill

# Should see one of:
# "⏭️  Backfill skipped (outside market hours)"  - Normal after hours
# "STARTUP BACKFILL - Checking for missed data"  - Backfill attempted
```

## Configuration

Backfill is **enabled by default** in the service.

To disable backfill temporarily:
1. Comment out the `run_startup_backfill()` call in `/gamma-scalper/gex_blackbox_service_v2.py`
2. Restart service: `systemctl restart gex-blackbox-recorder`

## Files

| File | Purpose |
|------|---------|
| `/gamma-scalper/gex_blackbox_backfill.py` | Standalone backfill script (can run manually) |
| `/gamma-scalper/gex_blackbox_service_v2.py` | Service with integrated backfill on startup |
| `/gamma-scalper/data/gex_blackbox.db` | SQLite database with collected data |

## Summary

**Current Behavior:**
- ✅ Automatically detects missing data on service restart
- ✅ Attempts to backfill using Tradier APIs
- ⚠️  Limited by Tradier's lack of historical option chain data
- ✅ Non-critical failure (service continues normally if backfill fails)

**Best Practice:**
- Keep service running continuously during market hours
- Monitor with `systemctl status gex-blackbox-recorder`
- Short outages (< 5 minutes) can be backfilled for price data only
- Longer outages will have gaps in GEX data (cannot be backfilled without historical option chains)
