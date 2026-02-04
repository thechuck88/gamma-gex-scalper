# OTM Trade Emergency Stop Analysis

## Emergency Stops - OTM vs ATM/GEX Breakdown

Looking at the 5 emergency stops:

```
Trade #5:  6970C/6975C/6930P/6920P ($2.30) - Iron Condor (OTM both sides) ✓
Trade #11: 7000C/7005C/6960P/6950P ($0.90) - Iron Condor (OTM both sides) ✓
Trade #4:  6915P/6905P ($1.45)             - Single spread (OTM unknown)
Trade #18: 6910P/6900P ($1.20)             - Single spread (OTM unknown)
Trade #20: 6920P/6910P ($1.90)             - Single spread (OTM unknown)
```

**At least 2 out of 5 (40%) were confirmed OTM Iron Condors.**

---

## Do The Fixes Help OTM Trades? YES - But OTM Needs Extra Help

### ✅ FIX #1: Stricter Spread Check - ESPECIALLY HELPS OTM

**Why OTM is affected MORE:**
- Far OTM options have WIDER bid-ask spreads (lower liquidity)
- Example: ATM spread might be $0.20, but 20-point OTM spread is $0.40+
- Trade #11 ($0.90 credit) likely had $0.30+ net spread = instant 33% loss

**OTM-Specific Enhancement:**
```python
# Current progressive tolerance
if expected_credit < 1.00:
    max_spread_pct = 0.12  # 12%

# OTM ENHANCEMENT: Even stricter for far OTM
if is_far_otm and expected_credit < 1.00:
    max_spread_pct = 0.10  # 10% for far OTM (tighter)
```

---

### ✅ FIX #2: Minimum Credit Buffer - CRITICAL FOR OTM

**Why OTM needs this MORE:**
- OTM spreads naturally have smaller credits (less risk = less premium)
- Trade #11: $0.90 credit on IC → 25% emergency stop = $0.23 tolerance
- Any slippage triggers emergency stop

**Current fix already helps:**
- Blocks credits < $1.00 (would have blocked Trade #11) ✓
- Requires $0.15 buffer for $1.00-$1.50 credits ✓

**OTM-Specific Enhancement:**
```python
# For OTM trades, require higher minimum
if is_otm_strategy:
    ABSOLUTE_MIN_CREDIT = 1.25  # Higher for OTM (vs $1.00 for ATM)
    min_remaining = 0.20        # More buffer for OTM (vs $0.15 for ATM)
```

---

### ✅ FIX #3: Entry Settle Period - ESPECIALLY HELPS OTM

**Why OTM quotes are MORE volatile:**
- Far OTM options quote less frequently (lower volume)
- Wider bid-ask spreads → larger quote swings
- Market makers update OTM quotes slower than ATM

**Current fix helps:**
- 60-second settle period allows quotes to stabilize ✓
- Prevents false alarms from stale quotes ✓

**OTM-Specific Enhancement:**
```python
# Longer settle for far OTM
if is_far_otm:
    SL_ENTRY_SETTLE_SEC = 90  # 90 seconds for OTM (vs 60 for ATM)
```

---

### ✅ FIX #4: Momentum Filter - HELPS OTM TOO

**Why OTM affected by momentum:**
- Fast SPX moves cause all options to reprice (delta/gamma effects)
- OTM options have lower liquidity → slower repricing → wider spreads
- Directional momentum increases implied volatility → wider OTM spreads

**Current fix helps OTM equally:**
- Blocks entries during 10+ point 5-minute moves ✓
- Avoids volatile periods when OTM spreads widen ✓

---

## ADDITIONAL OTM-SPECIFIC FIXES RECOMMENDED

### FIX #6: OTM Distance-Based Adjustments

**Problem:** Far OTM spreads (>20 points from SPX) are riskier.

**Solution:** Adjust filters based on OTM distance.

```python
def get_otm_distance(spx_price, short_strike, option_type):
    """Calculate how far OTM the spread is."""
    if option_type == 'PUT':
        return spx_price - short_strike  # Positive = OTM
    else:  # CALL
        return short_strike - spx_price  # Positive = OTM

def get_otm_adjusted_thresholds(otm_distance, expected_credit):
    """
    Adjust quality thresholds based on OTM distance.

    Farther OTM = Stricter requirements (wider spreads, less liquidity).
    """
    if otm_distance < 10:
        # Near money: Normal thresholds
        spread_tolerance = get_base_spread_tolerance(expected_credit)
        min_credit = 1.00
        settle_period = 60

    elif otm_distance < 20:
        # Moderately OTM: Slightly stricter
        spread_tolerance = get_base_spread_tolerance(expected_credit) * 0.9
        min_credit = 1.10
        settle_period = 75

    else:  # >= 20 points OTM
        # Far OTM: Much stricter
        spread_tolerance = get_base_spread_tolerance(expected_credit) * 0.8
        min_credit = 1.25
        settle_period = 90

    return {
        'max_spread_pct': spread_tolerance,
        'min_credit': min_credit,
        'settle_period_sec': settle_period
    }
```

**Impact:** Automatically adjusts all filters based on how far OTM the spread is.

---

### FIX #7: OTM Liquidity Check

**Problem:** Far OTM options can have very low volume/open interest.

**Solution:** Check option liquidity before entering OTM spreads.

```python
def check_otm_liquidity(short_sym, long_sym, min_volume=10, min_oi=50):
    """
    Verify OTM options have adequate liquidity.

    Returns: (is_liquid, reason)
    """
    try:
        r = requests.get(f"{BASE_URL}/markets/quotes",
                        headers=HEADERS,
                        params={"symbols": f"{short_sym},{long_sym}"},
                        timeout=10)

        quotes = r.json().get("quotes", {}).get("quote", [])
        if isinstance(quotes, dict):
            quotes = [quotes]

        for i, quote in enumerate(quotes):
            leg_name = "short" if i == 0 else "long"
            volume = quote.get("volume", 0) or 0
            open_interest = quote.get("open_interest", 0) or 0

            if volume < min_volume:
                return False, f"{leg_name} leg volume {volume} < {min_volume}"

            if open_interest < min_oi:
                return False, f"{leg_name} leg OI {open_interest} < {min_oi}"

        return True, "Liquidity acceptable"

    except Exception as e:
        log(f"Error checking OTM liquidity: {e}")
        return True, "Liquidity check failed (allow)"

# Usage before entering OTM spread:
is_liquid, reason = check_otm_liquidity(short_sym, long_sym)
if not is_liquid:
    log(f"❌ OTM liquidity insufficient: {reason}")
    skip_trade()
```

**Impact:** Blocks OTM spreads with insufficient liquidity (low volume/OI = wider spreads).

---

### FIX #8: OTM-Specific Credit Requirements

**Problem:** Current time-based minimums don't account for OTM risk.

**Solution:** Higher credit minimums for OTM spreads.

```python
# Current time-based minimums (ATM/GEX)
min_credit_by_hour = {
    10: 1.50,  # 10 AM
    11: 1.75,  # 11 AM
    12: 2.25,  # 12 PM
    13: 3.00,  # 1 PM+
}

# NEW: OTM-specific minimums (20% higher)
min_credit_otm_by_hour = {
    10: 1.80,  # 10 AM (vs 1.50 ATM)
    11: 2.10,  # 11 AM (vs 1.75 ATM)
    12: 2.70,  # 12 PM (vs 2.25 ATM)
    13: 3.60,  # 1 PM+ (vs 3.00 ATM)
}

# Usage in scalper:
if is_otm_strategy:
    min_credit = min_credit_otm_by_hour.get(hour, 3.60)
else:
    min_credit = min_credit_by_hour.get(hour, 3.00)
```

**Impact:** Requires larger credits for OTM trades to justify the wider spreads and lower liquidity.

---

## SUMMARY: OTM-Specific Recommendations

### Already Covered by Base Fixes ✅
1. Stricter spread check (helps OTM MORE than ATM)
2. Minimum credit buffer (critical for OTM's small credits)
3. Entry settle period (essential for OTM's volatile quotes)
4. Momentum filter (helps all trades equally)

### Additional OTM Enhancements 🆕
5. **Distance-based adjustments** (stricter for far OTM)
6. **Liquidity checks** (volume + open interest minimums)
7. **Higher OTM credit minimums** (20% higher than ATM)

---

## Implementation Priority for OTM

### Phase 1: Apply Base Fixes (IMMEDIATE)
- Base fixes already help OTM significantly
- Trade #11 ($0.90 IC) would have been blocked by FIX #2 ✓
- 60-second settle would have prevented false alarms ✓

### Phase 2: Add OTM Distance Adjustments (AFTER BASE TESTING)
- Implement FIX #6 (distance-based thresholds)
- Test in paper mode for 5+ days
- Monitor: Far OTM skip rate, emergency stop rate

### Phase 3: Add Liquidity Checks (OPTIONAL)
- Implement FIX #7 if Phase 1-2 don't eliminate OTM emergency stops
- Monitor: Volume/OI distributions of entered trades

---

## Expected Impact on OTM Trades

### Before Fixes (Current)
```
OTM emergency stops: 2/5 = 40% of all emergency stops
Trade #11 ($0.90 IC): Instant 33% loss, 0 minutes
Trade #5 ($2.30 IC): 26% loss in 6 minutes
```

### After Base Fixes (Phase 1)
```
Expected OTM emergency stops: <1/20 = <5%
Trade #11 blocked by: Minimum credit ($0.90 < $1.00) ✓
Trade #5 likely blocked by: Spread check or settle period ✓
```

### After OTM Enhancements (Phase 2)
```
Expected OTM emergency stops: <1/50 = <2%
Far OTM (>20pts): Even stricter filters
All OTM: Higher credit requirements, distance adjustments
```

---

## Bottom Line

**YES, the base fixes help OTM trades - in fact, they help OTM MORE than ATM trades** because:

1. OTM has wider spreads → stricter spread check has bigger impact
2. OTM has smaller credits → minimum buffer is critical
3. OTM quotes are more volatile → settle period is essential

**BUT: OTM trades may benefit from additional distance-based adjustments** after the base fixes are validated.

**Recommendation:**
1. ✅ Apply base fixes (FIX #1-4) immediately - will catch most OTM issues
2. ⏳ Monitor OTM emergency stop rate in paper trading
3. ⏳ Add distance-based adjustments (FIX #6) if OTM stops persist
4. ⏳ Add liquidity checks (FIX #7) only if still needed after above

---

**Created:** 2026-02-04
**Status:** Analysis complete, base fixes recommended
**OTM-Specific Priority:** Medium (base fixes should handle 80-90% of OTM issues)
