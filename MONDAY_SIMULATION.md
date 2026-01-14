# Monday 9:36 AM ET - Expected Scalper Execution Flow

## Test Results (Just Completed)

✅ **All 6 critical components working**:
1. Index config (SPX + NDX) ✓
2. Tradier API credentials ✓
3. Tradier API connectivity ✓ (SPY = $694.07)
4. Option symbol formatting ✓
5. Min credit thresholds ✓ (NDX = 5× SPX)
6. Data files initialized ✓

## What Happens Monday 9:36 AM ET

### Step 1: Cron Triggers (14:36 UTC)

```bash
# Four scalpers run simultaneously:
/usr/bin/python3 /gamma-scalper/scalper.py SPX PAPER >> scalper_spx_paper.log
/usr/bin/python3 /gamma-scalper/scalper.py NDX PAPER >> scalper_ndx_paper.log
/usr/bin/python3 /gamma-scalper/scalper.py SPX LIVE >> scalper_spx_live.log
/usr/bin/python3 /gamma-scalper/scalper.py NDX LIVE >> scalper_ndx_live.log
```

### Step 2: Each Scalper Executes

**For SPX PAPER** (example):

```
[09:36:01] Scalper starting...
[09:36:01] Lock acquired (PID: xxxxx)
[09:36:01] GEX Scalper started
[09:36:02] SPX: 6012 (direct from Tradier LIVE)
[09:36:02] VIX: 16.5
[09:36:02] SPX: 6012 | VIX: 16.50
[09:36:03] Expected 2hr move: ±18.3 pts (1σ, 68% prob)
[09:36:03] RSI (14-period): 52.3
[09:36:03] PAPER MODE — RSI filter bypassed
[09:36:03] PAPER MODE — Friday filter bypassed
[09:36:03] Consecutive down days: 0
[09:36:03] Gap size: 0.3% — within 0.5% threshold
[09:36:04] GEX pin price: $6010 (from GEX calculation)
[09:36:04] Distance to pin: 2 pts (near)
[09:36:04] Setup: Iron Condor (SPX near pin)
[09:36:04] Strikes: 6030/6035/5990/5985
[09:36:05] EXPECTED CREDIT ≈ $2.85 → $285 per contract
[09:36:05] Position limit check: 0/3 positions (OK)
[09:36:06] Account balance: $20,000
[09:36:06] Position size: 1 contract (Kelly calculation)
[09:36:06] 💰 Position size: 1 contract @ $2.85 = $285 total premium
[09:36:07] Sending entry order...
[09:36:08] ENTRY SUCCESS → Real Order ID: 23456789
[09:36:08] Monitoring order 23456789 for fill (timeout: 300s)
[09:36:18] [10s] Order status: open, fill_price: None
[09:36:28] [20s] Order status: filled, fill_price: 2.90
[09:36:28] ACTUAL CREDIT RECEIVED: $2.90 → $290 per contract
[09:36:28] FINAL 50% PROFIT TARGET → Close at $1.45 → +$145 profit
[09:36:28] FINAL 10% STOP LOSS → Close at $3.19 → -$29 loss
[09:36:28] Discord entry alert sent
[09:36:28] Order 23456789 saved to monitor tracking file
[09:36:28] Trade complete — monitor.py will handle TP/SL exits.
[09:36:28] Lock released
```

### Step 3: Discord Alert Received

**You'll see in Discord**:
```
🎯 NEW TRADE - SPX PAPER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy: Iron Condor
Strikes: 6030/6035/5990/5985
Entry Credit: $2.90
Confidence: HIGH
TP Target: 50%
Stop Loss: 10%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPX: 6012 | VIX: 16.5 | Expected Move: ±18.3 pts
Time: 09:36 ET
0DTE SPX
```

### Step 4: Monitor Tracks Position

**Every 15 seconds**:
```
[09:36:30] Checking 1 open position(s)...
[09:36:30] Order 23456789: entry=$2.90 mid=$2.85 ask=$2.90 profit=+$5 (+1.7%) | TP: 50% | SL: -10%
[09:36:45] Order 23456789: entry=$2.90 mid=$2.75 ask=$2.80 profit=+$10 (+3.4%) | TP: 50% | SL: -10%
[09:37:00] Order 23456789: entry=$2.90 mid=$2.60 ask=$2.65 profit=+$25 (+8.6%) | TP: 50% | SL: -10%
...
[10:15:30] Order 23456789: entry=$2.90 mid=$1.40 ask=$1.45 profit=+$145 (+50.0%) | TP: 50% ✓ HIT
[10:15:30] 🎯 PROFIT TARGET HIT — Closing position
[10:15:31] Close order sent: 23456790
[10:15:32] EXIT SUCCESS — Position closed
[10:15:32] Discord exit alert sent
```

### Step 5: Discord Exit Alert

```
💰 TRADE CLOSED - SPX PAPER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Order ID: 23456789
Strategy: Iron Condor
Strikes: 6030/6035/5990/5985
Entry Credit: $2.90
Exit Value: $1.45
P/L: +$145.00 (+50.0%)
Exit Reason: Profit Target (50%)
Duration: 39 min
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
0DTE SPX
```

### Step 6: Trade Logged

**In `/gamma-scalper/data/trades.csv`**:
```csv
Timestamp_ET,Trade_ID,Account_ID,Strategy,Strikes,Entry_Credit,Confidence,TP%,Exit_Time,Exit_Value,P/L_$,P/L_%,Exit_Reason,Duration_Min
2026-01-13 09:36:28,23456789,VA45627947,IC,6030/6035/5990/5985,2.90,HIGH,50%,2026-01-13 10:15:30,1.45,+145.00,+50.0%,Profit Target (50%),39
```

## Expected First Day Results

**Monday Jan 13, 2026**:

**Entry times**: 9:36, 10:00, 10:30, 11:00, 11:30, 12:00, 12:30 AM (7 windows)

**Per window** (4 scalpers):
- SPX PAPER: 0-1 entry (if GEX setup valid)
- NDX PAPER: 0-1 entry (if GEX setup valid)
- SPX LIVE: 0-1 entry (if GEX setup valid)
- NDX LIVE: 0-1 entry (if GEX setup valid)

**Max positions**: 3 per index per mode = 12 total max

**Realistic first day**:
- VIX check: Blocks ~30% of entries (VIX < 12)
- GEX setup: Valid ~40% of entry windows
- Expected entries: 3-6 total (mix of SPX + NDX)

**First trade completion**:
- Fastest: 20-30 min (profit target hit quickly)
- Typical: 1-3 hours (gradual decay to TP)
- Latest: 3:30 PM auto-close (if still open)

## What You Should Do Monday

### Before Market Open (8:30 AM ET)
1. Check services running:
   ```bash
   systemctl status gamma-scalper-monitor-*
   ```

2. Check Discord webhooks working

3. Verify /etc/trading-day flag exists:
   ```bash
   ls -l /etc/trading-day
   ```

### During Trading (9:30 AM - 4:00 PM)
1. Watch Discord for alerts
2. Check logs occasionally:
   ```bash
   tail -f /gamma-scalper/data/scalper_spx_paper.log
   ```

3. Monitor positions:
   ```bash
   cat /gamma-scalper/data/orders_paper.json | jq
   ```

### After Market Close (4:30 PM)
1. Review trades.csv
2. Check win rate and P/L
3. Verify all positions closed
4. Note any errors in logs

## Warning Signs to Watch For

❌ **Critical Issues**:
- No scalper runs at scheduled times → Check cron + /etc/trading-day
- Services crashed → Check systemctl status
- Partial fills → Should be blocked by AON, if happens: emergency stop
- Credit calculation errors → Check logs

⚠️ **Minor Issues**:
- No entries all day → VIX too low (< 12) or no valid GEX setups
- API rate limits → Tradier throttling (temporary)
- Discord webhook failures → Network issue (alerts still logged)

## Success Metrics

**First Week Goals**:
- ✅ At least 3-5 trades executed
- ✅ Win rate > 50%
- ✅ Profit factor > 2.0
- ✅ No system crashes
- ✅ All positions properly tracked and closed

**If goals met** → Increase position size from 1 to 2-3 contracts
**If goals NOT met** → Analyze logs and adjust parameters

---

**System Status**: ✅ READY FOR MONDAY 9:36 AM ET

Good luck! 🚀
