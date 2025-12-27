# Gamma Bot Backtest Critical Bugs
**Date**: December 27, 2025
**File**: `/root/gamma/backtest.py`
**Impact**: Backtest results are unrealistic and overstate actual strategy performance

---

## Executive Summary

The gamma options backtest has **3 critical bugs** that cause it to produce overly optimistic results:

1. **Entry prices are fake** - Uses linear interpolation instead of actual intraday prices
2. **Stop losses don't work** - Checks profit target before stop loss, allowing losses to become winners
3. **Stale market data** - Uses pre-market pin price and VIX for all entry times throughout the day

**Impact**: Backtest win rate and P&L are **significantly inflated** compared to live trading reality.

---

## Bug #1: Fake Entry Prices (Lines 508-512) ⚠️ CRITICAL

### Location
`backtest.py:508-512`

### The Problem

```python
# Estimate SPX price at entry time (interpolate between open and close)
# Simple model: price moves linearly from open toward close
progress = hours_after_open / 6.5
spx_at_entry = spx_open + (spx_close - spx_open) * progress * 0.5  # Dampened
```

**This creates FAKE prices that never existed!**

### Example: Why This is Wrong

**Real Market Data** (hypothetical day):
- 9:30 AM Open: SPX = 5800
- 10:00 AM: SPX = 5900 (rally)
- 11:00 AM: SPX = 5750 (selloff)
- 12:00 PM: SPX = 5820 (recovery)
- 1:00 PM: SPX = 5840
- 4:00 PM Close: SPX = 5850

**Backtest Interpolated Prices** (what the code calculates):
- 9:36 AM (0.1 hrs): 5800 + (50 × 0.1/6.5 × 0.5) = 5800.38 ✅ Close to reality
- 10:00 AM (0.5 hrs): 5800 + (50 × 0.5/6.5 × 0.5) = 5801.92 ❌ WRONG! (Real: 5900)
- 11:00 AM (1.5 hrs): 5800 + (50 × 1.5/6.5 × 0.5) = 5805.77 ❌ WRONG! (Real: 5750)
- 12:00 PM (2.5 hrs): 5800 + (50 × 2.5/6.5 × 0.5) = 5809.62 ❌ WRONG! (Real: 5820)
- 1:00 PM (3.5 hrs): 5800 + (50 × 3.5/6.5 × 0.5) = 5813.46 ❌ WRONG! (Real: 5840)

### Why This Matters

**The backtest assumes a smooth monotonic price path**:
- All 5 entry times see SPX gradually rising from 5800 → 5850
- No intraday volatility
- No reversals
- No whipsaw

**Real market has volatility**:
- 10:00 AM entry at 5900 (much higher!) → Worse entry for credit spreads
- 11:00 AM entry at 5750 (much lower!) → Better entry for puts, worse for calls
- Stop losses and profit targets hit at different times than backtest simulates

### Impact on Strategy

**Credit Spreads** (short options strategy):
- Entry price determines initial credit received
- Higher entry price = different strike selection = different risk/reward
- Backtest using fake smooth prices will show different P&L than real volatile markets

**Example**:
- Backtest: Enter at interpolated 5806, sell 5900/5925 call spread
- Reality: Enter at actual 5900, have to sell 6000/6025 call spread (much worse risk!)

**The backtest is evaluating trades that could NEVER happen in reality.**

---

## Bug #2: Stop Loss Never Fires (Lines 279-317) ⚠️ CRITICAL

### Location
`backtest.py:279-317`

### The Problem

Exit logic checks conditions in WRONG order:

```python
# Line 280: Check if TP was hit (best profit reached TP level)
if best_profit_pct >= tp_pct:
    exit_reason = f"TP ({int(tp_pct*100)}%)"
    final_profit_pct = tp_pct

# Line 285-306: Check trailing stop
elif TRAILING_STOP_ENABLED and best_profit_pct >= TRAILING_TRIGGER_PCT:
    # ... trailing stop logic

# Line 309-311: Check regular stop loss
elif worst_profit_pct <= -STOP_LOSS_PCT:
    exit_reason = "SL (10%)"
    final_profit_pct = -STOP_LOSS_PCT
```

**The code checks "best profit EVER" before checking if stop was hit!**

### Real-World Scenario

**Timeline of actual trade**:
1. 10:00 AM: Enter credit spread for $2.00 credit
2. 10:30 AM: SPX drops, spread value → $2.30 (-15% loss) → **STOP LOSS HIT!**
3. 11:00 AM: Should have exited at -15% loss = -$0.30
4. But in backtest, we keep tracking...
5. 2:00 PM: SPX rallies, spread value drops to $1.00 (+50% profit) → TP level!
6. 4:00 PM: Close at $1.10 (+45% profit)

**Backtest Logic**:
- `best_profit_pct = 50%` (the 2:00 PM high)
- `worst_profit_pct = -15%` (the 10:30 AM low)
- Line 280: `50% >= 50%` → **TRUE** → Exit as "TP (50%)" ✅
- Line 309: Never runs! (already exited)
- **Result**: Trade marked as +50% winner

**Reality**:
- Stop loss triggered at 10:30 AM
- Exited at -15% loss = -$0.30
- **Result**: Trade was a loser

**The backtest converted a -15% loss into a +50% win!**

### Why This is Wrong

The code uses END-OF-DAY extremes (`best_profit_pct`, `worst_profit_pct`) to evaluate INTRADAY exits:

```python
# These are calculated from daily high/low (lines 242-261)
best_profit_pct = ... # Based on day's high/low
worst_profit_pct = ... # Based on day's high/low
```

**The timeline is lost!** The code doesn't know WHEN the high/low occurred, so it can't know if stop loss was hit BEFORE profit target.

### Impact on Win Rate

**Backtest inflates winners**:
- Trades that hit stop loss → Later rally → Marked as TP winners
- Trades that whipsaw → Backtest ignores the stop → Shows as profitable
- Win rate is ARTIFICIALLY HIGH

**Example Impact**:
- Real win rate: 55% (many stop outs)
- Backtest win rate: 75% (stops converted to TPs)
- **20% point difference!**

---

## Bug #3: Stale Pin Price and VIX (Lines 495-514) ⚠️ HIGH

### Location
`backtest.py:495-514`

### The Problem

**Pin price and VIX are calculated ONCE per day** (before market open) and used for ALL 5 entry times:

```python
# Line 495-499: Calculate pin price ONCE using prev_close
if prev_close is None:
    pin_price = round_to_25(spx_open)
else:
    pin_price = round_to_25(prev_close)  # Previous day's close!

# Line 485: Read VIX ONCE per day
vix_val = row['VIX']  # Daily VIX value

# Line 504-514: Loop through ALL entry times
for entry_idx, hours_after_open in enumerate(ENTRY_TIMES):
    # 9:36, 10:00, 11:00, 12:00, 1:00 PM entries

    # Line 514: Uses SAME pin_price and vix_val for all times!
    setup = get_gex_trade_setup(pin_price, spx_at_entry, vix_val)
```

**All 5 entry times use the SAME pre-market pin price and VIX!**

### Example

**Day Setup**:
- Previous close: 5875 → pin_price = 5875 (rounded to 25)
- VIX at open: 14.5
- Daily VIX value: 15.2 (some average)

**Backtest Behavior**:
- 9:36 AM entry: pin=5875, VIX=15.2 ✅ Reasonable
- 10:00 AM entry: pin=5875, VIX=15.2 ❌ STALE!
- 11:00 AM entry: pin=5875, VIX=15.2 ❌ VERY STALE!
- 12:00 PM entry: pin=5875, VIX=15.2 ❌ EXTREMELY STALE!
- 1:00 PM entry: pin=5875, VIX=15.2 ❌ 3.5 hours old!

**Reality** (live bot behavior):
- 9:36 AM: pin=5875, VIX=14.5 (pre-market)
- 10:00 AM: pin=5900, VIX=13.8 (market rallied, VIX dropped)
- 11:00 AM: pin=5850, VIX=16.2 (selloff, VIX spiked)
- 12:00 PM: pin=5875, VIX=15.5 (back to pin, VIX cooling)
- 1:00 PM: pin=5880, VIX=15.0 (slight move)

### Why This Matters

**GEX pin price drives strike selection**:
- `get_gex_trade_setup()` uses pin to determine:
  - Whether to trade (far from pin = skip)
  - Which strikes to sell (relative to pin)
  - Call vs put bias

**Using stale pin = wrong strikes**:
- 11:00 AM backtest: Uses pin=5875 → Sells 5925/5950 call spread
- 11:00 AM reality: Pin=5850 → Should sell 5900/5925 call spread
- **Different trade entirely!**

**VIX affects strategy**:
- VIX > 20 → Skips trade (in some strategies)
- Using daily average VIX vs real-time VIX → Wrong skip decisions
- Miss trades that should happen, take trades that shouldn't

### Impact on Backtest Accuracy

**Later entry times are COMPLETELY WRONG**:
- 12:00 PM and 1:00 PM entries are 2.5-3.5 hours stale
- Pin price could have moved 50-100 points
- VIX could have moved 2-5 points
- **These entries are simulating trades that would never be taken in reality**

**Example**:
- Backtest: Enter at 1:00 PM using pin=5875 (from prev close)
- Reality: Market at 5950, pin now 5950, live bot would SKIP (too far from pin)
- **Backtest takes trades that live bot wouldn't, or vice versa**

---

## Combined Impact of All 3 Bugs

### How They Work Together to Inflate Results

1. **Fake entry prices** → Smooth interpolated prices hide volatility
2. **Broken stop loss** → Losses become winners when market rallies later
3. **Stale pin/VIX** → Wrong trade selection, especially for later entries

**Result**: Backtest shows MUCH better performance than reality.

### Example Full-Day Scenario

**Market Conditions**:
- Previous close: 5800
- Open: 5820 (gap up)
- 10:30 AM: Rallies to 5880 (VIX drops to 12)
- 11:30 AM: Sells off to 5760 (VIX spikes to 18)
- Close: 5850 (recovery)

**11:00 AM Entry - Backtest**:
- Pin: 5800 (from prev close) ❌
- SPX: 5805 (interpolated) ❌ Real: 5870
- VIX: 14.5 (daily value) ❌ Real: 17 (spiking)
- Enters credit spread, hits stop at -15% at 11:30 AM
- Market recovers by close → best_profit_pct = +30%
- **Exit reason**: "TP (50%)" ❌ Wrong! Should be "SL (10%)"
- **P&L**: +50% ✅ Backtest shows WIN

**11:00 AM Entry - Reality**:
- Pin: 5880 (current market) ✅
- SPX: 5870 (actual price) ✅
- VIX: 17 (spiking) ✅
- May not even enter (VIX too high or too far from pin)
- If enters, hits stop at 11:30 AM → Exits at -15%
- **Exit reason**: "SL (15%)" ✅
- **P&L**: -15% ❌ LOSS

**Backtest vs Reality**:
- Backtest: +50% winner
- Reality: -15% loser (or no trade)
- **Difference**: 65% P&L points on one trade!

---

## Recommended Fixes

### Fix #1: Use Actual Intraday Prices

**Current** (lines 508-512):
```python
progress = hours_after_open / 6.5
spx_at_entry = spx_open + (spx_close - spx_open) * progress * 0.5
```

**Option A - Intraday Data** (Best, requires data):
```python
# Load 5-minute or 1-minute intraday SPX data
# Get actual SPX price at entry time
entry_time = market_open + timedelta(hours=hours_after_open)
spx_at_entry = intraday_df.loc[entry_time, 'SPX']
```

**Option B - Conservative Estimate** (Simpler, more realistic):
```python
# Use worst-case price based on daily range
if hours_after_open < 3.25:  # Before mid-day
    # Assume price at daily high or low (whichever is worse for entry)
    spx_at_entry = spx_high if strategy == 'call_spread' else spx_low
else:  # After mid-day
    # Use close price (known at entry time)
    spx_at_entry = spx_close
```

**Option C - Disable Multiple Entry Times** (Simplest):
```python
# Only backtest 9:36 AM entry (at/near open)
# This avoids the interpolation problem entirely
ENTRY_TIMES = [0.1]  # Only 9:36 AM
```

### Fix #2: Fix Exit Logic Order

**Current** (lines 279-311):
```python
if best_profit_pct >= tp_pct:
    exit_reason = "TP"
elif worst_profit_pct <= -STOP_LOSS_PCT:
    exit_reason = "SL"
```

**Fixed** (check stop loss FIRST):
```python
# Check stop loss FIRST (happened earlier in timeline)
if worst_profit_pct <= -STOP_LOSS_PCT:
    # Stop was definitely hit at some point
    # Did we later reach TP?
    if best_profit_pct >= tp_pct:
        # Both stop and TP hit - need to know ORDER
        # Conservative: assume stop hit first
        exit_reason = "SL"
        final_profit_pct = -STOP_LOSS_PCT
    else:
        # Only stop hit
        exit_reason = "SL"
        final_profit_pct = -STOP_LOSS_PCT

# Check TP (only if stop NOT hit)
elif best_profit_pct >= tp_pct:
    exit_reason = "TP"
    final_profit_pct = tp_pct

# Trailing stop, etc.
elif ...
```

**Better Fix** (with intraday data):
```python
# Simulate price path through the day
# Check each minute/5-minute bar:
#   - If stop hit → exit immediately
#   - If TP hit → exit immediately
#   - If trailing stop hit → exit immediately
# This requires intraday data but is most accurate
```

### Fix #3: Update Pin Price and VIX Intraday

**Current** (lines 495-514):
```python
# Calculate pin ONCE per day
pin_price = round_to_25(prev_close)

# Use same pin for all entry times
for entry_idx, hours_after_open in enumerate(ENTRY_TIMES):
    setup = get_gex_trade_setup(pin_price, spx_at_entry, vix_val)
```

**Fixed** (recalculate pin at each entry time):
```python
# Calculate pin based on current market
for entry_idx, hours_after_open in enumerate(ENTRY_TIMES):
    # Estimate current pin based on entry time
    if hours_after_open < 0.5:
        # Pre-market: use prev close
        current_pin = round_to_25(prev_close)
    elif hours_after_open < 3.0:
        # Morning: use current SPX or open
        current_pin = round_to_25(spx_at_entry)
    else:
        # Afternoon: use close (more stable)
        current_pin = round_to_25(spx_close)

    # For VIX: if have intraday data, use it
    # Otherwise, use daily VIX (limitation acknowledged)
    setup = get_gex_trade_setup(current_pin, spx_at_entry, vix_val)
```

**Better Fix** (with intraday VIX data):
```python
# Load intraday VIX from database
vix_at_entry = get_vix_at_time(date, entry_time)
setup = get_gex_trade_setup(current_pin, spx_at_entry, vix_at_entry)
```

---

## Impact Assessment

### Current Backtest Results are UNRELIABLE

**Estimated Impact**:
- **Win Rate**: Likely inflated by 10-20% (stop losses marked as TPs)
- **P&L**: Likely inflated by 30-50% (fake prices + broken stops)
- **Trade Count**: Possibly inflated or deflated (wrong pin/VIX → wrong skips)

**Cannot trust current backtest to predict live performance!**

### Before Fixing

**Do NOT**:
- Make parameter decisions based on current backtest
- Compare strategies using current backtest
- Set position sizes based on current backtest results
- Claim any P&L numbers from current backtest

**Backtest is for DIRECTION only** (is strategy viable?), not for MAGNITUDE (how much profit?).

### After Fixing

**With fixes**:
- Win rate will drop (stop losses work correctly)
- P&L will drop (no more fake price advantage)
- Results will match live trading more closely
- Can make informed decisions about strategy viability

---

## Testing Plan

### 1. Implement Fixes

Choose fix approach for each bug (Option A, B, or C above).

### 2. Run Side-by-Side Comparison

```bash
# Save current backtest results
python backtest.py > results_before_fix.txt

# Implement fixes
# ...

# Run fixed backtest
python backtest.py > results_after_fix.txt

# Compare
diff results_before_fix.txt results_after_fix.txt
```

### 3. Compare to Live Trading

If live bot has trading history:
```bash
# Compare backtest P&L to actual live trades
# Win rate should match within 5-10%
# Average P&L per trade should match within 20%
```

### 4. Validate Edge Cases

Test days with:
- Big intraday reversals (open high, close low)
- VIX spikes mid-day
- Gap moves
- Trending days (monotonic move)

Ensure backtest handles each correctly.

---

## Conclusion

The gamma bot backtest has **3 critical bugs** that make results unrealistic:

1. ❌ **Fake entry prices** - Creates smooth price paths that don't exist
2. ❌ **Broken stop loss** - Converts losses into wins by checking TP first
3. ❌ **Stale data** - Uses pre-market pin/VIX for all entry times

**Impact**: Backtest overstates win rate and P&L significantly.

**Recommendation**:
1. Fix bugs before making any strategy decisions
2. Re-run backtest with fixes
3. Compare to live trading results
4. Only trust fixed backtest for go/no-go decisions

**Priority**: HIGH - These bugs affect core strategy viability assessment.

---

**Status**: Documented, awaiting fixes
**Date**: December 27, 2025
