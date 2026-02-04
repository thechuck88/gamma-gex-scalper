# Smart Settle Period - Fix #4 (2026-02-04)

## Problem

FIX #3 (deployed earlier today) added a 60-second settle period to prevent false emergency stops from bad quotes immediately after entry. However, this created an unintended consequence:

**1-Minute Guaranteed Losses:**
- When position goes bad IMMEDIATELY (genuinely bad, not just bad quotes)
- Emergency stop wants to trigger at 25% loss
- But settle period BLOCKS it for 60 seconds
- Position gets WORSE during those 60 seconds
- At exactly 60 seconds, emergency stop triggers
- Result: **Guaranteed 1-minute loss** for fast-moving bad positions

**Today's Evidence:**
```
Trade 30: 1m LOSS (-$180) - Trailing stop triggered after brief profit
Trade 34: 1m LOSS (-$405) - Emergency stop at EXACTLY 60 seconds
```

## Solution: Smart Settle Period

Instead of blindly waiting 60 seconds, **override settle period early** if:

### Override Condition 1: Bid-Ask Spread Normalized (< 15%)
- Tight spread = reliable quotes
- Position has settled, quotes are trustworthy
- Safe to allow emergency stop

### Override Condition 2: Quote Stable for 10+ Seconds
- Quote hasn't changed > 5 cents in 10 seconds
- Market has stabilized around this price
- No whipsaw movement, safe to exit

### Override Condition 3: Catastrophic Loss (< -35%)
- Loss exceeds -35% worst-case
- This is beyond normal volatility
- Override settle period to prevent account damage

## Implementation

### Configuration (monitor.py:96-101)
```python
SL_ENTRY_SETTLE_SEC = 60        # Base settle period
SL_SETTLE_SPREAD_NORMALIZED = 0.15    # Override if spread < 15%
SL_SETTLE_QUOTE_STABLE_SEC = 10       # Override if quote stable for 10s
SL_SETTLE_CATASTROPHIC_PCT = 0.35     # Override if loss > 35%
SL_SETTLE_QUOTE_CHANGE_THRESHOLD = 0.05  # Quote unchanged if within 5 cents
```

### Helper Function (monitor.py:923-976)
```python
def should_override_settle_period(entry_credit, current_value, bid_value, ask_value,
                                  profit_pct_sl, order, position_age_sec):
    """
    Check if settle period should be overridden for emergency stop.
    Returns: (should_override, reason)
    """
    # Check 3 override conditions...
```

### Quote Tracking (monitor.py:1071-1077)
Tracks quote changes to detect stability:
```python
# Track quote stability for smart settle period
last_quote = order.get('last_quote_value')
if last_quote is None or abs(current_value - last_quote) >= SL_SETTLE_QUOTE_CHANGE_THRESHOLD:
    # Quote changed significantly - reset tracking
    order['last_quote_value'] = current_value
    order['last_quote_time'] = now
```

### Updated Emergency Stop Checks (4 locations)
Lines: 1208-1220, 1247-1259, 1282-1293, 1349-1361

**Before:**
```python
if position_age_sec < SL_ENTRY_SETTLE_SEC:
    # Block emergency stop for 60 seconds
    log("Position just entered, waiting...")
else:
    exit_reason = "EMERGENCY Stop Loss"
```

**After:**
```python
should_override, override_reason = should_override_settle_period(...)

if position_age_sec < SL_ENTRY_SETTLE_SEC and not should_override:
    # Block only if NO override conditions met
    log("Position just entered, waiting...")
else:
    override_msg = f" [override: {override_reason}]" if should_override else ""
    exit_reason = f"EMERGENCY Stop Loss{override_msg}"
```

## Expected Impact

### Trade 30 Prevention (Trailing Stop)
- No change - trailing stops still have no grace period
- This is a separate issue, not addressed by this fix

### Trade 34 Prevention (Emergency Stop)
**Before:**
- Entry at $7.10 credit
- Loss reaches -268% worst-case immediately
- Forced to wait 60 seconds (settle period)
- Position deteriorates further
- Exit at 60 seconds: -$405 loss

**After (with smart settle):**
- Entry at $7.10 credit
- Loss reaches -268% worst-case immediately
- **Catastrophic loss override** (< -35%) triggers
- Exit at ~10-20 seconds: -$250 loss (estimate)
- **Saved: ~$155** (38% improvement)

### Overall Expected Benefits
1. **Faster exits on genuinely bad positions** - No forced 60-second hold
2. **Still protects against bad quotes** - Only override when safe
3. **Reduced 1-minute losses** - Exit when appropriate, not on timer
4. **Better risk control** - Catastrophic losses stopped sooner

## Trade-offs

**Pros:**
- Prevents forced 60-second hold on catastrophic losses
- Allows early exit when quotes stabilize
- Maintains protection against bad initial quotes

**Cons:**
- Slightly more complex logic
- Small risk of early exit on quote stability (but spread check protects)
- May exit 5-10 seconds early in some cases (minor impact)

## Testing Plan

Monitor next 5-10 trades for:
1. Emergency stops with override triggers
2. Exit timing (should see exits at 10-40 seconds, not just 60)
3. Override reasons in logs (spread/stability/catastrophic)
4. False positives (early exits that shouldn't have happened)

## Files Modified

- **monitor.py**: Configuration, helper function, quote tracking, 4 emergency stop checks
- **SMART_SETTLE_PERIOD_FIX.md**: This documentation

## Deployment

**Date**: 2026-02-04 Evening
**Status**: Code complete, syntax validated
**Next**: Restart services and monitor

```bash
sudo systemctl restart gamma-scalper-monitor-live
sudo systemctl restart gamma-scalper-monitor-paper
```

---

**Co-Authored-By:** Claude Sonnet 4.5 <noreply@anthropic.com>
