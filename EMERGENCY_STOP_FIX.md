# Emergency Stop Loss Analysis & Fixes (2025-12-27)

## Problem: Multiple Emergency Stops on 12/11

### Disaster Timeline
```
Time    | Credit | Loss   | Reason
--------|--------|--------|------------------
14:54   | $0.25  | -20%   | Stop Loss
14:58   | $0.30  | -33%   | Stop Loss
14:59   | $0.30  | -33%   | Stop Loss
15:05   | $0.25  | -20%   | Stop Loss
15:06   | $0.25  | -20%   | Stop Loss
15:08   | $0.35  | -14%   | Trailing Stop
15:16   | $0.20  | -50%   | ⚠️ EMERGENCY
15:22   | $0.20  | -50%   | ⚠️ EMERGENCY
15:23   | $0.15  | -80%   | ⚠️ EMERGENCY
15:24   | $0.15  | -67%   | ⚠️ EMERGENCY
15:25   | $0.15  | -100%  | ⚠️ EMERGENCY
```

**Total Loss**: -$493 (39 trades, only 9 wins = 23% win rate)

### Root Causes

1. **PAPER MODE bypasses time cutoff**
   - LIVE blocks trades after 2 PM (scalper.py:610)
   - PAPER has NO time restrictions (scalper.py:616)
   - Result: Trading at 3:25 PM on 0DTE expiration

2. **Minimum credit filter failed**
   - Required: $1.50 after 1 PM (scalper.py:835)
   - Actual: $0.15-$0.35 got through
   - Cause: Unknown - needs investigation

3. **No absolute 0DTE cutoff**
   - 0DTE expires at 4:00 PM ET
   - Last trade at 3:25 PM = 35 minutes to expiration
   - Bid/ask spreads explode near expiration

4. **Overtrading during volatility**
   - 8 trades in 31 minutes (15:05-15:25)
   - No rate limiting
   - Chasing losses in deteriorating market

5. **Emergency stop slippage**
   - Emergency triggers at -40% (monitor.py:84)
   - Actual losses: -50% to -100%
   - Near expiration, market makers widen spreads instantly

### Why Emergency Stops Failed

**Normal Market (before 3 PM):**
```
Entry: $2.50 credit
-40% Emergency: $3.50 exit target
Slippage: 5-10% → -45% realized loss
```

**Expiration Chaos (after 3 PM on 0DTE):**
```
Entry: $0.15 credit ($15 per contract)
-40% Emergency: $0.21 exit target
Bid/Ask Spread: $0.10 → $0.40 (4x widening)
Slippage: 100%+ → -100% realized loss
```

**Math:**
- $0.15 credit = only $15 buffer
- Market move + spread widening = $0.30 loss
- Result: -100% loss (-$15 realized)

## Proposed Fixes

### 1. Apply Time Cutoff to PAPER Mode

**File:** `/root/gamma/scalper.py`

**Current (lines 608-616):**
```python
if mode == "REAL" and now_et.hour >= CUTOFF_HOUR:
    log(f"Time is {now_et.strftime('%H:%M')} ET — past cutoff. NO NEW TRADES.")
    raise SystemExit
elif mode == "PAPER":
    log(f"PAPER MODE — no time restrictions")
```

**Proposed:**
```python
# Time cutoff applies to BOTH LIVE and PAPER (same risk profile)
if now_et.hour >= CUTOFF_HOUR:
    log(f"Time is {now_et.strftime('%H:%M')} ET — past 2 PM cutoff. NO NEW TRADES.")
    log("Existing positions remain active for TP/SL management.")
    send_discord_skip_alert(f"Past {CUTOFF_HOUR}:00 PM ET cutoff", {'setup': 'Time cutoff'})
    raise SystemExit
```

### 2. Stricter Last-Hour Cutoff for 0DTE

**Add after line 616:**
```python
# ABSOLUTE CUTOFF: No trades in last hour of 0DTE (expiration risk)
ABSOLUTE_CUTOFF_HOUR = 15  # 3:00 PM ET - last hour before 4 PM expiration
if now_et.hour >= ABSOLUTE_CUTOFF_HOUR:
    log(f"Time is {now_et.strftime('%H:%M')} ET — within last hour of 0DTE expiration")
    log("NO TRADES — bid/ask spreads too wide, gamma risk too high")
    send_discord_skip_alert(f"Last hour before 0DTE expiration ({now_et.strftime('%H:%M')} ET)", run_data)
    raise SystemExit
```

### 3. Enforce Minimum Credit (Debug Why It Failed)

**Current minimum credit check (lines 828-840):**
```python
if now_et.hour < 12:
    MIN_CREDIT = 0.75   # Before noon: $0.75
elif now_et.hour < 13:
    MIN_CREDIT = 1.00   # 12-1 PM: $1.00
else:
    MIN_CREDIT = 1.50   # 1-2 PM: $1.50 (after 2 PM blocked anyway)

if expected_credit < MIN_CREDIT:
    log(f"Credit ${expected_credit:.2f} below minimum ${MIN_CREDIT:.2f} — NO TRADE")
    send_discord_skip_alert(f"Credit ${expected_credit:.2f} below ${MIN_CREDIT:.2f} minimum", run_data)
    raise SystemExit
```

**Issue:** This check is AFTER the time cutoff check (line 610), so it should have blocked $0.15 credits at 3:23 PM.

**Hypothesis:** PAPER mode bypassed time cutoff, then used $0.75 minimum (before noon) instead of $1.50.

**Fix:** Make minimum credit check independent of time:
```python
# ABSOLUTE MINIMUM CREDIT (prevents tiny premiums with no buffer)
ABSOLUTE_MIN_CREDIT = 1.00  # Never trade below $1.00 regardless of time

if expected_credit < ABSOLUTE_MIN_CREDIT:
    log(f"Credit ${expected_credit:.2f} below absolute minimum ${ABSOLUTE_MIN_CREDIT:.2f} — NO TRADE")
    send_discord_skip_alert(f"Credit ${expected_credit:.2f} below absolute minimum ${ABSOLUTE_MIN_CREDIT:.2f}", run_data)
    raise SystemExit

# Time-based minimum (stricter)
if now_et.hour < 12:
    MIN_CREDIT = 1.25   # Before noon: $1.25 (raised from $0.75)
elif now_et.hour < 13:
    MIN_CREDIT = 1.50   # 12-1 PM: $1.50 (raised from $1.00)
else:
    MIN_CREDIT = 2.00   # 1-2 PM: $2.00 (raised from $1.50)

if expected_credit < MIN_CREDIT:
    log(f"Credit ${expected_credit:.2f} below time-based minimum ${MIN_CREDIT:.2f} — NO TRADE")
    send_discord_skip_alert(f"Credit ${expected_credit:.2f} below ${MIN_CREDIT:.2f} minimum for {now_et.strftime('%H:%M')} ET", run_data)
    raise SystemExit
```

### 4. Add Rate Limiting (Prevent Overtrading)

**Add at top of scalper.py (near line 228):**
```python
RATE_LIMIT_FILE = "/tmp/gex_last_trade_time.txt"
MIN_TRADE_INTERVAL_SEC = 15 * 60  # 15 minutes between trades
```

**Add before order placement (around line 854):**
```python
# === RATE LIMITING (prevent overtrading during volatility) ===
import time as time_module
if os.path.exists(RATE_LIMIT_FILE):
    try:
        with open(RATE_LIMIT_FILE, 'r') as f:
            last_trade_time = float(f.read().strip())
        time_since_last = time_module.time() - last_trade_time
        if time_since_last < MIN_TRADE_INTERVAL_SEC:
            wait_minutes = (MIN_TRADE_INTERVAL_SEC - time_since_last) / 60
            log(f"Rate limit: {time_since_last/60:.1f} min since last trade (need {MIN_TRADE_INTERVAL_SEC/60} min)")
            log(f"NO TRADE — wait {wait_minutes:.1f} more minutes")
            send_discord_skip_alert(f"Rate limit: wait {wait_minutes:.1f} min", run_data)
            raise SystemExit
    except (ValueError, IOError) as e:
        log(f"Rate limit file read error (ignoring): {e}")

# After successful order placement (around line 898):
with open(RATE_LIMIT_FILE, 'w') as f:
    f.write(str(time_module.time()))
```

### 5. Force Close 0DTE Positions at 3:30 PM

**File:** `/root/gamma/monitor.py`

**Add after loading positions (around line 200):**
```python
# === FORCE CLOSE 0DTE POSITIONS BEFORE EXPIRATION ===
# Close all 0DTE positions at 3:30 PM to avoid expiration chaos
FORCE_CLOSE_HOUR = 15   # 3:00 PM ET
FORCE_CLOSE_MINUTE = 30 # 3:30 PM ET

now_et = datetime.now(ET)
if now_et.hour == FORCE_CLOSE_HOUR and now_et.minute >= FORCE_CLOSE_MINUTE:
    # Check if any positions are 0DTE (expire today)
    today_str = date.today().strftime("%y%m%d")

    for order in orders[:]:  # Iterate over copy since we may modify
        option_symbols = order.get('option_symbols', [])

        # Check if any option symbol contains today's date (0DTE)
        is_0dte = any(today_str in sym for sym in option_symbols)

        if is_0dte:
            order_id = order.get('order_id')
            entry_credit = order.get('entry_credit', 0)
            log(f"⏰ FORCE CLOSE 0DTE: Order {order_id} (entry ${entry_credit:.2f})")
            log(f"   Reason: 3:30 PM cutoff - avoid expiration liquidity crisis")

            # Calculate current P&L for logging
            current_value = get_spread_value(order, mode)
            if current_value is not None:
                pnl = (entry_credit - current_value) * 100
                pnl_pct = (pnl / (entry_credit * 100)) if entry_credit > 0 else 0
                log(f"   Current P&L: ${pnl:+.2f} ({pnl_pct:+.1%})")

            # Close position at market
            close_position(order, "Force close at 3:30 PM (0DTE expiration protection)", mode)
```

## Implementation Priority

1. **CRITICAL (Implement Today):**
   - Fix #1: Apply time cutoff to PAPER mode
   - Fix #2: Add absolute 3:00 PM cutoff for 0DTE
   - Fix #3: Raise absolute minimum credit to $1.00

2. **HIGH (Implement This Week):**
   - Fix #4: Add 15-minute rate limiting
   - Fix #5: Force close 0DTE at 3:30 PM

3. **MEDIUM (Investigate):**
   - Debug why $0.15 credits bypassed $1.50 minimum
   - Review monitor.py slippage protection

## Additional Problem: Instant Stops (0-Minute Trades)

### Duration Analysis
```
Duration    | Count | Pattern
------------|-------|------------------------------------------
0 minutes   | 10    | Instant stop (entry slippage → emergency)
1-3 minutes | 15    | Quick stop (no fighting chance)
4-10 minutes| 9     | Some chance, but mostly losses
> 10 minutes| 6     | Winners (time to work)
```

**Pattern:** 25 out of 40 trades lasted ≤ 3 minutes (62.5%)

### Root Cause: Entry Slippage on Tiny Credits

**Example with $0.20 credit:**
```
Quoted Credit: $0.20 (mid price)
Bid/Ask Spread: $0.15 bid / $0.25 ask
Entry Fill: $0.18 (market order slippage)
Immediate Mark: $0.28 (ask side for closing)
Instant P&L: ($0.18 - $0.28) / $0.18 = -55% → EMERGENCY STOP
Exit Fill: $0.30 (slippage on close)
Realized Loss: ($0.18 - $0.30) / $0.18 = -67%
```

**Why grace period doesn't help:**
- Grace period: 3.5 minutes (monitor.py:83)
- Emergency stop: -40% (bypasses grace period)
- Tiny credits + bid/ask spread = instant -40% to -60% loss
- Result: Emergency triggers on entry, position closed at 0 minutes

### Fix #6: Entry Quality Filter (Bid/Ask Spread Check)

**Add to scalper.py after getting expected_credit (around line 827):**

```python
# === BID/ASK SPREAD CHECK (prevent instant stops from slippage) ===
# Wide spreads = high slippage = instant emergency stop on entry
# Only enter when spread is tight enough to avoid entry slippage losses

if setup['strategy'] == 'IC':
    # Check both call and put spreads
    call_spread_quality = check_spread_quality(short_syms[0], long_syms[0], call_credit)
    put_spread_quality = check_spread_quality(short_syms[1], long_syms[1], put_credit)

    if not call_spread_quality or not put_spread_quality:
        log("IC spread quality check failed — NO TRADE")
        send_discord_skip_alert("Bid/ask spreads too wide (high slippage risk)", run_data)
        raise SystemExit
else:
    spread_quality = check_spread_quality(short_sym, long_sym, expected_credit)

    if not spread_quality:
        log("Spread quality check failed — NO TRADE")
        send_discord_skip_alert("Bid/ask spreads too wide (high slippage risk)", run_data)
        raise SystemExit

def check_spread_quality(short_sym, long_sym, expected_credit):
    """
    Check if bid/ask spread is tight enough for safe entry.

    Returns True if spread is acceptable, False if too wide.

    Logic:
    - Calculate net spread: (short_ask - short_bid) - (long_ask - long_bid)
    - If net spread > 25% of expected credit, too risky
    - Example: $2.00 credit → max $0.50 net spread
    """
    try:
        symbols = f"{short_sym},{long_sym}"
        r = retry_api_call(
            lambda: requests.get(f"{BASE_URL}/markets/quotes", headers=HEADERS,
                               params={"symbols": symbols}, timeout=10),
            max_attempts=2,
            base_delay=0.5,
            description=f"Spread quality check for {symbols}"
        )

        if r is None or r.status_code != 200:
            log(f"Warning: Could not check spread quality for {symbols}")
            return True  # Don't block trade on quote fetch failure

        data = r.json()
        quotes = data.get("quotes", {}).get("quote", [])
        if isinstance(quotes, dict):
            quotes = [quotes]
        if len(quotes) < 2:
            log(f"Warning: Incomplete quotes for spread quality check")
            return True

        # Short leg
        short_bid = float(quotes[0].get("bid") or 0)
        short_ask = float(quotes[0].get("ask") or 0)
        short_spread = short_ask - short_bid

        # Long leg
        long_bid = float(quotes[1].get("bid") or 0)
        long_ask = float(quotes[1].get("ask") or 0)
        long_spread = long_ask - long_bid

        # Net spread (what we pay in slippage)
        net_spread = short_spread - long_spread  # Short spread costs us, long spread saves us
        net_spread = abs(net_spread)  # Take absolute value

        # Maximum acceptable spread: 25% of credit
        max_spread = expected_credit * 0.25

        log(f"Spread quality: short {short_spread:.2f}, long {long_spread:.2f}, net {net_spread:.2f}")
        log(f"Max acceptable spread: ${max_spread:.2f} (25% of ${expected_credit:.2f} credit)")

        if net_spread > max_spread:
            log(f"❌ Spread too wide: ${net_spread:.2f} > ${max_spread:.2f} (instant slippage would trigger emergency stop)")
            return False

        log(f"✅ Spread acceptable: ${net_spread:.2f} ≤ ${max_spread:.2f}")
        return True

    except Exception as e:
        log(f"Error checking spread quality: {e}")
        return True  # Don't block trade on error
```

### Fix #7: Use Limit Orders Instead of Market Orders

**File:** `/root/gamma/scalper.py`

**Current (line 856):**
```python
entry_data = {
    "class": "multileg", "symbol": "SPXW", "type": "market", "duration": "day",
```

**Proposed:**
```python
# Use limit order at expected credit (or slightly better)
# This prevents entry slippage from triggering instant emergency stops
limit_price = round(expected_credit * 0.95, 2)  # Accept 5% worse than mid

entry_data = {
    "class": "multileg", "symbol": "SPXW",
    "type": "credit", "price": limit_price, "duration": "day",
```

**Trade-off:**
- PRO: No entry slippage (enter at limit or better)
- PRO: Prevents instant -40% losses from market order fills
- CON: May not fill immediately (need to wait for price)
- CON: May miss trade if market moves away

**Recommendation:** Start with limit orders, monitor fill rates. If <70% fill rate, increase to 0.90 (accept 10% worse).

## Expected Impact

**Before fixes (12/11):**
- 8 trades in last hour
- 5 emergency stops (-50% to -100% losses)
- 25 trades lasted ≤ 3 minutes (62.5%)
- -$493 total loss
- 23% win rate (9W/30L)

**After fixes:**
- 0 trades after 2:00 PM (time cutoff)
- 0 trades in last hour (absolute cutoff)
- 0 instant stops from entry slippage (spread quality check + limit orders)
- Only trades with >$1.00 credit (absolute minimum)
- 15-minute rate limit (prevents overtrading)
- Force close at 3:30 PM (prevents expiration chaos)

**Expected improvement:**
- Win rate: 23% → 40-50% (eliminate bad setups)
- Avg hold time: 7 min → 15-30 min (trades get fighting chance)
- Emergency stops: 5/day → 0-1/day (only from genuine volatility spikes)
- Max daily loss: -$493 → -$150 (better risk management)

## Testing Plan

1. **Dry run test at 2:55 PM ET:**
   ```bash
   python scalper.py 6900 6905  # Should be blocked by 2 PM cutoff
   ```

2. **Dry run test with low credit:**
   ```bash
   python scalper.py PAPER  # Verify $1.00 minimum enforced
   ```

3. **Rate limit test:**
   ```bash
   python scalper.py PAPER
   python scalper.py PAPER  # Should be blocked for 15 min
   ```

4. **Monitor test at 3:35 PM:**
   - Verify all 0DTE positions auto-closed
   - Check logs for "Force close at 3:30 PM"

## Files to Modify

1. `/root/gamma/scalper.py` - Entry logic fixes
2. `/root/gamma/monitor.py` - Force close 0DTE positions
3. `/root/gamma/EMERGENCY_STOP_FIX.md` - This document (for reference)

## Rollback Plan

If fixes cause issues:
```bash
cd /root/gamma
git checkout scalper.py monitor.py
systemctl restart gamma-monitor-paper
systemctl restart gamma-monitor-live
```

## Notes

- Emergency stop is at -40% (monitor.py:84) - this is appropriate
- The problem is NOT the emergency stop threshold
- The problem is allowing trades that can't be managed (tiny credits near expiration)
- Prevention > Mitigation
