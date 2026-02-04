# Emergency Stop Prevention - Analysis & Fixes

## Problem Analysis

**Emergency stops within 0-1 minutes indicate the position starts UNDERWATER immediately after entry.**

### Affected Trades:
```
Trade #4:  Entry $1.45 → Exit $1.80 (31% loss in 2m)
Trade #5:  Entry $2.30 → Exit $2.65 (26% loss in 6m)
Trade #11: Entry $0.90 → Exit $1.08 (33% loss in 0m)  ← INSTANT
Trade #18: Entry $1.20 → Exit $1.35 (25% loss in 0m)  ← INSTANT
Trade #20: Entry $1.90 → Exit $2.30 (26% loss in 1m)
```

### Root Causes:

1. **Bad Fill Prices**
   - Order fills at worse price than expected (closer to ask than mid)
   - Entry credit $1.90 means we SOLD for $1.90, but to close we must BUY
   - If spread immediately quoted at $2.30, we're underwater 21% instantly

2. **Market Momentum Against Position**
   - SPX moving rapidly at entry time
   - By the time order fills (2-3 seconds), price has moved against us
   - Example: Selling PUT spread while SPX dropping fast → spreads widen immediately

3. **Wide Bid-Ask Spreads**
   - During volatile periods, option spreads can be $0.50+ wide
   - Fill at ask, then market shows mid = instant 25%+ paper loss
   - Current check allows 25% of credit → might not be strict enough

4. **Low Entry Credits**
   - Trade #11: $0.90 credit → 25% emergency stop = $0.23 tolerance
   - Even $0.25 slippage triggers emergency stop
   - Lower credits = less room for normal market noise

---

## PROPOSED FIXES (Ranked by Impact)

### FIX #1: Stricter Bid-Ask Spread Quality Check ⭐⭐⭐⭐⭐

**Current Logic:**
```python
max_spread = expected_credit * 0.25  # 25% tolerance
if net_spread > max_spread:
    return False  # Block trade
```

**Problem:** 25% tolerance is too generous for 0DTE options.

**Proposed Fix:**
```python
# Progressive spread tolerance based on credit size
if expected_credit < 1.50:
    max_spread_pct = 0.15  # 15% for small credits (tighter control)
elif expected_credit < 2.50:
    max_spread_pct = 0.20  # 20% for medium credits
else:
    max_spread_pct = 0.25  # 25% for large credits

max_spread = expected_credit * max_spread_pct
```

**Impact:** Blocks trades with wide spreads that cause instant losses.

**File:** `scalper.py`, function `check_spread_quality()`

---

### FIX #2: Minimum Credit Safety Buffer ⭐⭐⭐⭐⭐

**Problem:** Emergency stop at 25% means credits below $1.00 have almost no margin for error.

**Current Logic:**
```python
# Entry allowed if credit > time-based minimum
if expected_credit < min_credit:
    skip_trade()
```

**Proposed Fix:**
```python
# ADDITIONAL check: Credit must provide 35% buffer above emergency stop
# Emergency stop = 25%, so need credit that allows 25% loss + 10% breathing room

min_safe_credit = 1.00  # Absolute minimum ($0.25 emergency stop tolerance)

# For small credits, require larger buffer
if expected_credit < 1.50:
    required_buffer = 0.35  # 35% buffer (allows 25% emergency + 10% safety)
    safe_credit = expected_credit * (1 - required_buffer)
    emergency_threshold = expected_credit * 0.25

    if safe_credit < emergency_threshold:
        log(f"❌ Credit ${expected_credit:.2f} too small - "
            f"emergency stop at 25% (${emergency_threshold:.2f}) "
            f"leaves only ${safe_credit:.2f} buffer")
        skip_trade()
```

**Impact:** Prevents entering trades where normal slippage would trigger emergency stop.

**File:** `scalper.py`, after `check_spread_quality()` check

---

### FIX #3: Market Momentum Filter ⭐⭐⭐⭐

**Problem:** Entering while SPX is moving rapidly causes fills at bad prices.

**Proposed Logic:**
```python
def check_market_momentum(spx_current, lookback_minutes=5):
    """
    Block entries if SPX moved significantly in last N minutes.

    Large moves indicate:
    - High volatility → wide spreads
    - Directional momentum → likely to continue against mean reversion
    - Fast-moving market → poor fill quality

    Returns: (is_safe, reason)
    """
    try:
        # Fetch SPX prices from last 5 minutes
        # (Use yfinance 1-minute bars or Tradier timesales)

        spx_5min_ago = get_spx_price_at(now - timedelta(minutes=5))
        spx_change = abs(spx_current - spx_5min_ago)

        # Threshold: 10 points in 5 minutes = 2 pts/min
        # That's ~0.03% per minute on 6900 SPX
        # Equivalent to ~30-40 point move per hour = VERY fast

        if spx_change > 10:
            return False, f"SPX moved {spx_change:.1f} pts in 5min (threshold: 10pts)"

        # Also check 1-minute momentum for instant spikes
        spx_1min_ago = get_spx_price_at(now - timedelta(minutes=1))
        spx_change_1m = abs(spx_current - spx_1min_ago)

        if spx_change_1m > 5:
            return False, f"SPX moved {spx_change_1m:.1f} pts in 1min (threshold: 5pts)"

        return True, "Market momentum acceptable"

    except Exception as e:
        log(f"Error checking momentum: {e}")
        return True, "Momentum check failed (allow trade)"
```

**Impact:** Avoids entering during fast-moving markets where fills are likely to be poor.

**File:** New function in `scalper.py`, called before `place_order()`

---

### FIX #4: Entry Confirmation Wait Period ⭐⭐⭐

**Problem:** Monitor checks position immediately, before spread prices stabilize.

**Current Behavior:**
- Order fills at 10:30:15
- Monitor checks at 10:30:18 (3 seconds later)
- Spread quote shows bad price due to post-fill volatility
- Emergency stop triggers

**Proposed Fix:**
```python
# In monitor.py, add entry timestamp check

SL_ENTRY_SETTLE_SEC = 60  # Wait 60 seconds before checking emergency stop

# In stop loss check:
if profit_pct_sl <= -SL_EMERGENCY_PCT:
    # Check position age
    position_age_sec = (now - entry_dt).total_seconds()

    if position_age_sec < SL_ENTRY_SETTLE_SEC:
        log(f"  ⏳ Emergency stop triggered but position just entered "
            f"({position_age_sec:.0f}s ago, settle period: {SL_ENTRY_SETTLE_SEC}s) - holding")
        continue  # Skip emergency stop during settle period

    exit_reason = f"EMERGENCY Stop Loss ({profit_pct_sl*100:.0f}% worst-case)"
```

**Impact:** Gives position 60 seconds to settle before emergency stop can trigger.

**Trade-off:** Real emergencies (flash crash) would have 60-second delay, but those are rare.

**File:** `monitor.py`, line ~1160 (emergency stop check)

---

### FIX #5: Limit Orders Instead of Market Orders ⭐⭐⭐⭐

**Problem:** Market orders can fill at any price. During volatility, fills can be 10-20% worse than expected.

**Current Behavior:**
```python
# Order type is likely "market" or "credit/debit" without limit
order_data = {
    "class": "multileg",
    "symbol": index_symbol,
    "type": "credit",  # Allows fill at any credit
    "duration": "day",
    # ...
}
```

**Proposed Fix:**
```python
# Calculate minimum acceptable credit (90% of expected)
min_acceptable_credit = expected_credit * 0.90

order_data = {
    "class": "multileg",
    "symbol": index_symbol,
    "type": "credit",
    "price": min_acceptable_credit,  # LIMIT: Won't fill below this credit
    "duration": "day",
    # ...
}

log(f"Placing LIMIT order for credit >= ${min_acceptable_credit:.2f} "
    f"(90% of expected ${expected_credit:.2f})")
```

**Impact:**
- Prevents fills worse than 10% of expected credit
- May result in some orders not filling (unfilled orders better than instant losses)
- 90% threshold balances fill rate vs quality

**Trade-off:** Lower fill rate, but much better fill quality.

**File:** `scalper.py`, order placement section

---

### FIX #6: Post-Fill Credit Verification ⭐⭐⭐⭐

**Problem:** We don't verify actual fill price matches expected credit.

**Proposed Logic:**
```python
# After order fills, immediately fetch fill details
def verify_fill_quality(order_id, expected_credit, tolerance=0.15):
    """
    Check if actual fill price is within tolerance of expected credit.
    If fill is significantly worse, immediately close position.

    Returns: (is_acceptable, actual_credit, message)
    """
    try:
        # Fetch order fill details from Tradier
        r = requests.get(f"{BASE_URL}/orders/{order_id}", headers=HEADERS)
        order_data = r.json()

        actual_credit = float(order_data.get('avg_fill_price', 0))

        if actual_credit == 0:
            return True, None, "Fill price not available yet"

        credit_diff_pct = (expected_credit - actual_credit) / expected_credit

        if credit_diff_pct > tolerance:  # Got 15% less credit than expected
            return False, actual_credit, \
                f"Bad fill: Expected ${expected_credit:.2f}, got ${actual_credit:.2f} " \
                f"({credit_diff_pct*100:.0f}% worse)"

        return True, actual_credit, "Fill quality acceptable"

    except Exception as e:
        log(f"Error verifying fill: {e}")
        return True, None, "Verification failed (allow position)"

# After place_order() succeeds:
is_acceptable, actual_credit, msg = verify_fill_quality(
    order_id, expected_credit, tolerance=0.15
)

if not is_acceptable:
    log(f"❌ {msg}")
    log(f"Immediately closing position to prevent emergency stop")
    close_position(order_id, reason="Bad Fill - Immediate Exit")
    send_discord_alert(f"Bad fill detected and closed: {msg}")
```

**Impact:** Catches bad fills immediately and exits before emergency stop can trigger.

**File:** `scalper.py`, after order placement

---

## RECOMMENDED IMPLEMENTATION ORDER

1. **FIX #1 (Stricter Spread Check)** - Quick win, prevents worst offenders
2. **FIX #2 (Minimum Credit Buffer)** - Blocks inherently risky small-credit trades
3. **FIX #4 (Entry Settle Period)** - Prevents false alarms from quote volatility
4. **FIX #3 (Momentum Filter)** - Requires SPX price history, more complex
5. **FIX #5 (Limit Orders)** - Needs testing to find optimal limit level
6. **FIX #6 (Fill Verification)** - Safety net, catches everything else

---

## EXPECTED IMPACT

**Before Fixes:**
- 5 emergency stops in 0-1 minutes out of 17 trades = 29% bad entry rate
- Average emergency loss: -$54 per occurrence

**After Fixes:**
- Estimated reduction: 80-90% of instant emergency stops
- Blocked trades: ~10-15% (better to skip than lose instantly)
- Emergency stops should only occur during true market emergencies (flash crashes, etc.)

---

## TESTING PLAN

1. **Backtest on recent data** - Apply fixes to last 30 days of SPX data
2. **Paper trading validation** - Run in paper mode for 5+ trading days
3. **Monitor metrics:**
   - Emergency stop rate (target: <5% of trades)
   - Skip rate due to filters (target: 10-15%)
   - Win rate improvement (should increase if avoiding bad entries)
   - Average trade duration (should increase if avoiding instant stops)

---

## FILES TO MODIFY

1. **`/root/gamma/scalper.py`**
   - Line ~1950: Enhance `check_spread_quality()` (FIX #1)
   - Line ~1770: Add minimum credit buffer check (FIX #2)
   - Line ~1800: Add `check_market_momentum()` function (FIX #3)
   - Line ~2100: Add limit order pricing (FIX #5)
   - Line ~2150: Add `verify_fill_quality()` (FIX #6)

2. **`/root/gamma/monitor.py`**
   - Line ~1160: Add entry settle period (FIX #4)

3. **`/root/gamma/core/gex_strategy.py`**
   - No changes needed (logic is sound)

---

## MONITORING AFTER DEPLOYMENT

Track these metrics daily:
- Emergency stops < 60 seconds: Should drop from 29% → <5%
- Trades skipped due to spread quality: Track percentage
- Trades skipped due to momentum: Track percentage
- Overall win rate: Should improve slightly
- Average P/L per trade: Should improve (fewer instant losses)

---

## EDGE CASES TO CONSIDER

1. **Low volatility days** - Filters might be too strict, miss tradeable setups
   - Solution: Make thresholds adaptive to VIX level

2. **Flash crashes** - Even 60-second settle won't help
   - Solution: Keep emergency stop for true emergencies

3. **Limit orders not filling** - Might miss profitable trades
   - Solution: Monitor fill rate, adjust limit threshold if needed

4. **Momentum filter during news** - FOMC days have high momentum
   - Solution: News filter already blocks these days

---

**Created:** 2026-02-04
**Status:** Ready for implementation
**Priority:** CRITICAL (29% of trades hitting instant emergency stops)
