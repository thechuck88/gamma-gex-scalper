# LIVE vs BACKTEST: Complete Analysis

**Date:** 2026-01-14
**Issue:** Backtest showing 12.3% win rate vs actual live system showing 23.1% win rate
**Root Cause:** BACKTEST BUG - Unclosed trades treated as breakeven losses

---

## Executive Summary

**CRITICAL FINDING:** The backtest is ARTIFICIALLY LOWERING the win rate by including 34 unclosed trades as zero P/L breakevens, which are then counted as losses.

- **Live System Actual Performance:** 23.1% win rate (9 winners / 39 closed trades)
- **Backtest Result:** 12.3% win rate (9 winners / 73 total trades including unclosed)
- **Difference:** 11.3 percentage points (49% worse in backtest)
- **Cause:** Backtest includes 34 unclosed trades with NaN P/L as P/L=0.00 (loss)

---

## Detailed Analysis

### 1. Trade Data Composition

```
Total trades in trades.csv: 73
├─ Closed trades (with P/L values):     39 trades
│  ├─ Winners (P/L > 0):                9 trades (23.1%)
│  └─ Losers (P/L <= 0):               30 trades (76.9%)
└─ Unclosed trades (NaN P/L):          34 trades
   └─ Backtest treats as:               P/L=0.00 (losses)
```

### 2. Win Rate Calculation

**LIVE SYSTEM (Correct):**
```
Win Rate = 9 winners / 39 closed trades = 23.1%
Status:   Only analyzes trades with definite outcomes
```

**BACKTEST (Bug):**
```
Win Rate = 9 winners / 73 total trades = 12.3%
Status:   Includes 34 unclosed trades counted as breakevens
```

### 3. Backtest Code Logic

**File:** `/root/gamma/backtest_broken_wing_ic_1year.py` (lines 81-85)

```python
pnl = float(trade.get('P/L_$', 0)) if pd.notna(trade.get('P/L_$')) else 0

# Skip if P/L is missing
if pd.isna(pnl):
    continue
```

**Problem:** The code skips NaN check AFTER converting NaN to 0, so:
- Unclosed trades with NaN P/L become pnl=0.0
- Line 85's NaN check fails (already converted to float 0.0)
- Result: 34 unclosed trades counted as 0% profit (breakeven/loss)

---

## Live Trading Code vs Backtest

### Entry Logic (MATCHED ✓)

**LIVE:** `/root/gamma/scalper.py` (lines 1067-1403)
- GEX pin calculation ✓
- Credit threshold check ✓
- RSI filter (LIVE only) ✓
- VIX floor check ✓
- Position limit check (max 3 concurrent) ✓

**BACKTEST:** Uses actual trades from CSV
- Entry data already collected
- No simulation of entry filters

**Match:** ENTRY DATA IS FROM ACTUAL LIVE TRADES ✓

### Exit Logic (NOT COMPARED)

**LIVE:** `/root/gamma/monitor.py` (lines 881-1143)
- Profit target: 50% of credit (line 75)
- Stop loss: 10% (line 76)
- Grace period: 3 minutes (line 88)
- Trailing stop: 20% trigger (line 82)
- Emergency stop: 40% loss (line 89)
- Auto-close: 3:50 PM ET (line 77)

**BACKTEST:** Uses actual P/L from CSV
- Does NOT simulate exit logic
- Does NOT check timestamps for auto-close eligibility
- Does NOT validate that unclosed trades have actually expired

**Match:** CRITICAL - BACKTEST DOES NOT VERIFY TRADES HAVE EXPIRED ✗

---

## Critical Issues Found

### Issue #1: Unclosed Trades Treated as Zero P/L (PRIMARY)

**Problem:** 34 unclosed trades are included as P/L=0.00

**Evidence:**
```python
# Backtest code - problematic pattern:
pnl = float(trade.get('P/L_$', 0)) if pd.notna(trade.get('P/L_$')) else 0
# This CONVERTS NaN to 0.0, then the next check fails

if pd.isna(pnl):  # This is ALWAYS False now
    continue
```

**Impact:**
- Artificially adds 34 "zero trades" (breakevens treated as losses)
- Reduces win rate from 23.1% to 12.3% (11.3 percentage point drop)
- Makes P/L calculation incorrect (-$493 in 39 trades vs -$493 in 73 trades)

**Fix:** Exclude trades without exit timestamps or P/L values

---

### Issue #2: No Timestamp Validation for Expiration

**Problem:** Backtest doesn't check if unclosed trades have passed 4:00 PM (0DTE expiration)

**Evidence:**
```
Unclosed trade example (index 0-31): Entry_Time=2025-12-09 13:39:28, Exit_Time=EMPTY
Backtest treats as: 0% loss (breakeven)
Reality: Position may still be open or expired without being closed
```

**Fix:** Filter trades to only those:
- Option A: With explicit exit timestamps (P/L recorded)
- Option B: With entry times > 4 PM yesterday (definitely expired)
- Option C: Simulate exit logic based on price movement

---

### Issue #3: BWIC Comparison Flawed

**Problem:** BWIC backtest (lines 168-204) applies random credit adjustments to flawed base data

```python
if strategy_type == 'BWIC':
    correct_prediction = np.random.random() < 0.60  # 60% accuracy assumption
    if correct_prediction:
        credit_adjustment = 1.05
    else:
        credit_adjustment = 0.97
```

**Issue:** This applies random adjustments to a dataset that already includes 34 phantom trades

**Fix:** Calculate BWIC separately using only closed trades

---

## Recommended Fixes

### Fix A: Exclude Unclosed Trades (Recommended - Minimal)

**File:** `/root/gamma/backtest_broken_wing_ic_1year.py`

**Change Lines 80-85:**
```python
# BEFORE (includes unclosed trades as zeros):
pnl = float(trade.get('P/L_$', 0)) if pd.notna(trade.get('P/L_$')) else 0
if pd.isna(pnl):
    continue

# AFTER (exclude unclosed trades):
if pd.isna(trade.get('P/L_$')):
    continue  # Skip trades without explicit exit
pnl = float(trade.get('P/L_$'))
```

**Expected Result:**
- Only 39 closed trades analyzed
- Win rate: 23.1% (matches live)
- Total P/L: -$493
- Validates BWIC on real closed trades only

### Fix B: Add Expiration Check (Recommended - Moderate)

**File:** `/root/gamma/backtest_broken_wing_ic_1year.py`

**Add at line 80:**
```python
# BEFORE:
pnl = float(trade.get('P/L_$', 0)) if pd.notna(trade.get('P/L_$')) else 0

# AFTER:
entry_time = pd.to_datetime(trade.get('Timestamp_ET', None))
exit_time = trade.get('Exit_Time')

# Require either explicit exit OR trade entry before yesterday's 4 PM
if pd.isna(exit_time) and entry_time.date() >= datetime.now().date() - timedelta(days=1):
    continue  # Skip if unclosed and entered today/yesterday

pnl = float(trade.get('P/L_$', 0)) if pd.notna(trade.get('P/L_$')) else 0
if pd.isna(pnl):
    continue
```

### Fix C: Simulate Exit Logic (Advanced - Most Accurate)

Would require:
1. Loading historical price data (bar-by-bar)
2. Simulating entry filter logic
3. Simulating exit logic from monitor.py
4. Calculating P/L based on simulated exit price

---

## Live System Performance vs Backtest

### Actual Live Performance (39 Closed Trades)

| Metric | Value |
|--------|-------|
| Total Trades | 39 |
| Winners | 9 |
| Losers | 30 |
| **Win Rate** | **23.1%** |
| Total P/L | -$493.00 |
| Avg P/L/Trade | -$12.64 |
| Max Loss | -$120.00 |

### Backtest Results (73 Total Trades - FLAWED)

| Metric | Value | Issue |
|--------|-------|-------|
| Total Trades | 73 | Includes 34 unclosed as zeros |
| Winners | 9 | Correct |
| Losers | 64 | 34 phantom + 30 real |
| **Win Rate** | **12.3%** | Artificially low by 11.3 pp |
| Total P/L | -$493.00 | Correct (zeros don't change total) |
| Avg P/L/Trade | -$6.75 | Artificially better (spread over more trades) |
| Max Loss | -$120.00 | Correct |

### Corrected Backtest (39 Closed Trades - Using Fix A)

| Metric | Value |
|--------|-------|
| Total Trades | 39 |
| Winners | 9 |
| Losers | 30 |
| **Win Rate** | **23.1%** |
| Total P/L | -$493.00 |
| Avg P/L/Trade | -$12.64 |
| Max Loss | -$120.00 |

---

## Validation: Detailed Trade Review

### Unclosed Trades (34 total - Examples)

```
Entry #0:  2025-12-09 13:39:28 | Entry: $2.74 | Exit: NONE | P/L: (missing)
Entry #1:  2025-12-09 14:15:53 | Entry: $2.74 | Exit: NONE | P/L: (missing)
Entry #2:  2025-12-09 14:18:13 | Entry: $2.74 | Exit: NONE | P/L: (missing)
...
Entry #31: 2025-12-11 11:24:11 | Entry: $2.74 | Exit: NONE | P/L: (missing)

Status: Backtest treats each as P/L=0.00 → Counts as LOSS
Reality: Still open or expired worthless (no recorded exit)
```

### Closed Trades (39 total - Samples)

```
Entry #33:  2025-12-10 13:07:01 | Entry: $3.00 | Exit: $3.45 | P/L: -$45 (LOSS)
Entry #36:  2025-12-11 11:30:17 | Entry: $2.74 | Exit: $1.65 | P/L: +$109 (WIN)
Entry #40:  2025-12-11 11:53:02 | Entry: $1.30 | Exit: $0.65 | P/L: +$65 (WIN)
Entry #43:  2025-12-11 12:15:04 | Entry: $1.40 | Exit: $1.95 | P/L: -$55 (LOSS)

Status: Backtest correctly includes these with actual P/L values
Reality: Trades have definitive outcomes (closed or expired)
```

---

## Recommendations

### Immediate Actions

1. **Run corrected backtest** (Fix A): See `/root/gamma/backtest_broken_wing_ic_1year_FIXED.py`
   - Validates that 23.1% WR is correct for closed trades
   - Confirms live system matches backtest expectations

2. **Understand actual performance:** 23.1% WR with -$493 total is actually WORSE than expected
   - Bootstrap stats assumed 58.2% WR (per `/root/gamma/scalper.py` line 779)
   - Actual live performance: 23.1% WR
   - **This 60%+ gap suggests entry/exit logic differences OR market regime changes**

3. **Investigate live performance gap:**
   - Compare actual exit prices to configured thresholds
   - Check if stop loss is triggering too early (grace period issue?)
   - Verify profit target thresholds vs actual market movement
   - Check if VIX regime is affecting performance

### Medium-term Actions

1. **Review entry quality:**
   - 34 unclosed trades suggests entries may be too aggressive
   - No P/L recorded = likely expired worthless or manually abandoned
   - Check GEX pin accuracy during entry times

2. **Review exit logic:**
   - 30 losses vs 9 wins suggests stop loss activating too frequently
   - Check grace period (3 minutes) is appropriate
   - Consider if market regime requires tighter stops or wider bands

3. **Update backtest suite:**
   - Add validation to exclude unclosed trades
   - Add expiration check for old entries
   - Consider simulating full trade lifecycle instead of using historical P/Ls

### Long-term Actions

1. **Implement realistic backtest:**
   - Load historical bars for each entry time
   - Simulate actual price movement during holding period
   - Apply monitor.py exit logic to simulated trades
   - Compare simulated performance to actual trades

2. **Separate sims from prod:**
   - Paper trading backtest (uses past data)
   - Live paper trading monitor (uses current data)
   - Reconcile differences between simulated and actual results

---

## Files Referenced

- **Backtest:** `/root/gamma/backtest_broken_wing_ic_1year.py` (FLAWED)
- **Live Scalper:** `/root/gamma/scalper.py` (lines 1067-1403 entry logic)
- **Live Monitor:** `/root/gamma/monitor.py` (lines 881-1143 exit logic)
- **Trade CSV:** `/root/gamma/data/trades.csv` (73 total trades, 39 closed, 34 unclosed)

---

## Conclusion

The 12.3% backtest win rate is **NOT representative** of live performance because:

1. **34 unclosed trades are phantom entries** - they have no exit timestamps and are treated as zero P/L (breakevens/losses)
2. **23.1% actual live win rate** is correct for the 39 truly closed trades
3. **Backtest should exclude unclosed trades** to make valid comparisons
4. **Even at 23.1%, performance is far below bootstrap expectations** (58.2% assumed), suggesting entry quality or market regime issues need investigation

The corrected backtest will show 23.1% win rate, validating that the live system is performing according to how it was programmed - but also revealing that the programmed logic is producing worse results than expected.

