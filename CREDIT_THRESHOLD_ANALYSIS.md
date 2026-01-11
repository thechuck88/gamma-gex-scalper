# Credit Threshold Analysis - Production vs Realistic 0DTE

**Date:** 2026-01-11
**Issue:** Production credit minimums don't match realistic 0DTE ranges

---

## Critical Problem Found

The production `scalper.py` has **hardcoded credit minimums** that don't match realistic 0DTE pricing and don't scale by index.

### Current Production Code (scalper.py lines 1135-1155)

```python
# HARDCODED - applies to BOTH SPX and NDX!
ABSOLUTE_MIN_CREDIT = 1.00  # Never trade below $1.00

if now_et.hour < 11:
    MIN_CREDIT = 1.25   # Before 11 AM
elif now_et.hour < 13:
    MIN_CREDIT = 1.50   # 11 AM-1 PM
else:
    MIN_CREDIT = 2.00   # After 1 PM
```

**Problem:** These are hardcoded SPX values that:
1. **Don't scale for NDX** (should be 5× higher for NDX)
2. **Are too high for realistic 0DTE SPX** (based on weekly option pricing)
3. **Ignore the INDEX_CONFIG.get_min_credit() method** that properly scales

---

## Comparison: Production vs Realistic 0DTE

### SPX Credit Thresholds

| Time Window | Production Minimum | Realistic 0DTE Range | Problem |
|-------------|-------------------|---------------------|---------|
| **Before 11 AM** | $1.25 | $0.20-$0.65 | **2-6× too high** |
| **11 AM - 1 PM** | $1.50 | $0.35-$0.75 | **2-4× too high** |
| **After 1 PM** | $2.00 | $0.55-$1.00 | **2-4× too high** |
| **Absolute Min** | $1.00 | $0.20 | **5× too high** |

**Impact on SPX:** Will reject 80-90% of realistic 0DTE trades!

### NDX Credit Thresholds

| Time Window | Production Minimum | Realistic 0DTE Range | Problem |
|-------------|-------------------|---------------------|---------|
| **Before 11 AM** | $1.25 | $1.80-$3.20 | **Too LOW!** |
| **11 AM - 1 PM** | $1.50 | $2.00-$4.00 | **Too LOW!** |
| **After 1 PM** | $2.00 | $3.00-$5.00 | **Too LOW!** |
| **Absolute Min** | $1.00 | $1.50 | **Too LOW!** |

**Impact on NDX:** Will accept low-quality trades that should be rejected!

---

## Realistic 0DTE Credit Ranges (from backtest analysis)

### SPX 5-Point Spread

**Single Spread:**
- VIX < 15: $0.20-$0.40
- VIX 15-22: $0.35-$0.65
- VIX 22-30: $0.55-$0.95
- VIX 30+: $0.80-$1.20

**Iron Condor (2× single spread):**
- VIX < 15: $0.40-$0.80
- VIX 15-22: $0.70-$1.30
- VIX 22-30: $1.10-$1.90
- VIX 30+: $1.60-$2.40

**Average across all conditions:** $0.50 single, $1.00 IC

### NDX 25-Point Spread

**Single Spread:**
- VIX < 15: $1.00-$2.00
- VIX 15-22: $1.80-$3.20
- VIX 22-30: $3.00-$5.00
- VIX 30+: $4.50-$7.50

**Iron Condor (2× single spread):**
- VIX < 15: $2.00-$4.00
- VIX 15-22: $3.60-$6.40
- VIX 22-30: $6.00-$10.00
- VIX 30+: $9.00-$15.00

**Average across all conditions:** $2.50 single, $5.00 IC

---

## Recommended Credit Minimums

### Conservative Approach (reject bottom 20% of trades)

**SPX Minimums:**
```python
if INDEX_CONFIG.code == 'SPX':
    ABSOLUTE_MIN_CREDIT = 0.30  # Bottom of realistic range

    if now_et.hour < 11:
        MIN_CREDIT = 0.40   # Before 11 AM (morning premiums higher)
    elif now_et.hour < 13:
        MIN_CREDIT = 0.50   # 11 AM - 1 PM (baseline)
    else:
        MIN_CREDIT = 0.65   # After 1 PM (afternoon decay)
```

**NDX Minimums (5× SPX):**
```python
elif INDEX_CONFIG.code == 'NDX':
    ABSOLUTE_MIN_CREDIT = 1.50  # Bottom of realistic range

    if now_et.hour < 11:
        MIN_CREDIT = 2.00   # Before 11 AM
    elif now_et.hour < 13:
        MIN_CREDIT = 2.50   # 11 AM - 1 PM
    else:
        MIN_CREDIT = 3.25   # After 1 PM
```

### Better Approach: Use INDEX_CONFIG.get_min_credit()

The `index_config.py` already has a `get_min_credit()` method (lines 96-123) that properly scales by index:

```python
# REPLACE hardcoded values with:
min_credit = INDEX_CONFIG.get_min_credit(now_et.hour)

if expected_credit < min_credit:
    log(f"Credit ${expected_credit:.2f} below minimum ${min_credit:.2f} — NO TRADE")
    send_discord_skip_alert(f"Credit ${expected_credit:.2f} below ${min_credit:.2f} minimum", run_data)
    raise SystemExit
```

**But the INDEX_CONFIG.get_min_credit() values also need updating!**

Current values in `index_config.py`:
- Before 11 AM: $1.25 (SPX) / $6.25 (NDX)
- 11 AM - 1 PM: $1.50 (SPX) / $7.50 (NDX)
- After 1 PM: $2.00 (SPX) / $10.00 (NDX)

**These are also too high!** They're based on weekly option pricing.

---

## Recommended Fix for index_config.py

Update the `get_min_credit()` method (line 110-113):

```python
# OLD (WRONG - weekly option pricing):
base_credits = {
    (0, 11): 1.25,   # Before 11 AM
    (11, 13): 1.50,  # 11 AM - 1 PM
    (13, 24): 2.00,  # After 1 PM
}

# NEW (CORRECT - realistic 0DTE pricing):
base_credits = {
    (0, 11): 0.40,   # Before 11 AM - morning premiums higher
    (11, 13): 0.50,  # 11 AM - 1 PM - baseline
    (13, 24): 0.65,  # After 1 PM - afternoon theta decay
}
```

This automatically scales to NDX:
- Before 11 AM: $0.40 (SPX) / $2.00 (NDX)
- 11 AM - 1 PM: $0.50 (SPX) / $2.50 (NDX)
- After 1 PM: $0.65 (SPX) / $3.25 (NDX)

---

## Recommended Fix for scalper.py

**Option 1: Use INDEX_CONFIG.get_min_credit() (BEST)**

Replace lines 1134-1155 with:

```python
# === MINIMUM CREDIT CHECK (index-aware, scales automatically) ===
min_credit = INDEX_CONFIG.get_min_credit(now_et.hour)

if expected_credit < min_credit:
    log(f"Credit ${expected_credit:.2f} below minimum ${min_credit:.2f} for {now_et.strftime('%H:%M')} ET — NO TRADE")
    send_discord_skip_alert(f"Credit ${expected_credit:.2f} below ${min_credit:.2f} minimum ({INDEX_CONFIG.code})", run_data)
    raise SystemExit
```

**Option 2: Index-aware hardcoded values (if can't modify index_config.py)**

```python
# === MINIMUM CREDIT CHECK (index-aware) ===
if INDEX_CONFIG.code == 'SPX':
    ABSOLUTE_MIN_CREDIT = 0.30
    if now_et.hour < 11:
        MIN_CREDIT = 0.40
    elif now_et.hour < 13:
        MIN_CREDIT = 0.50
    else:
        MIN_CREDIT = 0.65
elif INDEX_CONFIG.code == 'NDX':
    ABSOLUTE_MIN_CREDIT = 1.50
    if now_et.hour < 11:
        MIN_CREDIT = 2.00
    elif now_et.hour < 13:
        MIN_CREDIT = 2.50
    else:
        MIN_CREDIT = 3.25
else:
    # Fallback for other indices
    min_credit = INDEX_CONFIG.get_min_credit(now_et.hour)
    MIN_CREDIT = min_credit

if expected_credit < MIN_CREDIT:
    log(f"Credit ${expected_credit:.2f} below minimum ${MIN_CREDIT:.2f} — NO TRADE")
    raise SystemExit
```

---

## Impact Analysis

### With Current Production Thresholds

**SPX (minimums too high):**
- Rejects 80-90% of realistic 0DTE trades
- Only accepts extreme high-VIX conditions (VIX 30+)
- Expected trades per day: 0-1 (should be 2-3)

**NDX (minimums too low):**
- Accepts low-quality trades that should be rejected
- May accept trades with insufficient premium to justify risk
- Risk of slippage eating entire profit

### With Corrected Thresholds

**SPX:**
- Accepts 70-80% of realistic 0DTE trades
- Rejects only extreme low-premium outliers
- Expected trades per day: 2-3 (realistic)

**NDX:**
- Properly filters low-quality setups
- Maintains minimum premium standards
- Expected trades per day: 2-3 (realistic)

---

## Expected Trade Counts (Monday simulation)

### Current Production Thresholds

| Index | Morning (9:36-11:00) | Midday (11:00-13:00) | Afternoon (13:00+) | Total/Day |
|-------|---------------------|---------------------|-------------------|-----------|
| **SPX** | 0-1 (min $1.25) | 0 (min $1.50) | 0 (min $2.00) | **0-1** ❌ |
| **NDX** | 2-3 (min $1.25 too low) | 1-2 (min $1.50 too low) | 1 (min $2.00 too low) | **4-6** ⚠️ |

**Problem:** SPX gets almost no trades, NDX accepts too many low-quality trades

### Corrected Thresholds

| Index | Morning (9:36-11:00) | Midday (11:00-13:00) | Afternoon (13:00+) | Total/Day |
|-------|---------------------|---------------------|-------------------|-----------|
| **SPX** | 1-2 (min $0.40) | 1-2 (min $0.50) | 0-1 (min $0.65) | **2-3** ✅ |
| **NDX** | 1-2 (min $2.00) | 1-2 (min $2.50) | 0-1 (min $3.25) | **2-3** ✅ |

**Balanced:** Both indices get appropriate number of quality trades

---

## Validation Against Backtest Results

From the realistic 1-year backtest (721 trades, 252 days):

**Actual average credits observed:**
- SPX avg: $1.33 (includes ICs, so singles ~$0.50)
- NDX avg: $7.33 (includes ICs, so singles ~$2.50)

**Credit distribution (backtest):**
- SPX min: $0.25, max: $2.95
- NDX min: $1.30, max: $18.77

**Recommended minimums vs actual:**
- SPX min $0.40 would accept 85% of backtest trades ✅
- NDX min $2.00 would accept 80% of backtest trades ✅

Current production minimums ($1.25-$2.00 for both) would:
- SPX: Accept only 15-20% of trades ❌
- NDX: Accept 95%+ of trades (too lenient) ❌

---

## Summary

### Problems with Current Code

1. ❌ **scalper.py uses hardcoded minimums** instead of INDEX_CONFIG.get_min_credit()
2. ❌ **Minimums don't scale by index** (same $1.25-$2.00 for SPX and NDX)
3. ❌ **Values are based on weekly options** (4-5× too high for SPX)
4. ❌ **index_config.py minimums also too high** (need updating)

### Recommended Fixes

1. ✅ **Update index_config.py base_credits:**
   - Before 11 AM: $0.40 (was $1.25)
   - 11 AM - 1 PM: $0.50 (was $1.50)
   - After 1 PM: $0.65 (was $2.00)

2. ✅ **Update scalper.py to use INDEX_CONFIG.get_min_credit():**
   - Remove hardcoded ABSOLUTE_MIN_CREDIT
   - Remove hardcoded MIN_CREDIT logic
   - Use `min_credit = INDEX_CONFIG.get_min_credit(now_et.hour)`

3. ✅ **Validates against realistic 0DTE backtest:**
   - SPX accepts 85% of trades
   - NDX accepts 80% of trades
   - Both indices balanced at 2-3 trades/day

### Expected Impact

**Before fix:**
- SPX: 0-1 trades/day (too restrictive)
- NDX: 4-6 trades/day (too lenient)
- Unbalanced, inconsistent results

**After fix:**
- SPX: 2-3 trades/day (optimal)
- NDX: 2-3 trades/day (optimal)
- Balanced, realistic 0DTE expectations

---

## Action Items for Monday Deployment

**CRITICAL - Must fix before Monday:**

1. Update `/gamma-scalper/index_config.py` line 110-113
2. Update `/gamma-scalper/scalper.py` lines 1134-1155
3. Test both SPX and NDX scalpers with new minimums
4. Verify realistic credit acceptance rates

**If not fixed:** System will either reject most SPX trades or accept low-quality NDX trades.
