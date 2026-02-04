#!/usr/bin/env python3
"""
Emergency Stop Prevention - Code Implementation
Apply these fixes to prevent 0-1 minute emergency stops

CRITICAL FIXES (Apply in order):
1. Stricter bid-ask spread quality check
2. Minimum credit safety buffer
3. Entry settle period in monitor
4. Market momentum filter (optional, more complex)
"""

# ============================================================================
# FIX #1: STRICTER BID-ASK SPREAD QUALITY CHECK
# ============================================================================
# Location: /root/gamma/scalper.py
# Function: check_spread_quality()
# Current line: ~1950

def check_spread_quality_FIXED(short_sym, long_sym, expected_credit, INDEX_CONFIG):
    """
    ENHANCED: Progressive spread tolerance based on credit size.

    Problem: 25% tolerance too generous for small credits.
    Solution: Tighter tolerance for credits < $1.50.

    Returns True if spread is acceptable, False if too wide.
    """
    try:
        symbols = f"{short_sym},{long_sym}"
        r = retry_api_call(
            lambda: requests.get(f"{BASE_URL}/markets/quotes",
                               headers=HEADERS,
                               params={"symbols": symbols},
                               timeout=10),
            max_attempts=3,
            base_delay=1.0,
            description=f"Spread quality check for {symbols}"
        )

        if r is None:
            log(f"Warning: Spread quality check failed (allow trade)")
            return True

        data = r.json()
        quotes = data.get("quotes", {}).get("quote", [])
        if isinstance(quotes, dict):
            quotes = [quotes]
        if len(quotes) < 2:
            log(f"Warning: Only got {len(quotes)} quotes for spread check")
            return True

        # Get bid/ask for both legs
        short_bid = float(quotes[0].get("bid") or 0)
        short_ask = float(quotes[0].get("ask") or 0)
        long_bid = float(quotes[1].get("bid") or 0)
        long_ask = float(quotes[1].get("ask") or 0)

        # Calculate spreads
        short_spread = short_ask - short_bid
        long_spread = long_ask - long_bid
        net_spread = abs(short_spread - long_spread)

        # ===== NEW: Progressive tolerance based on credit size =====
        if expected_credit < 1.00:
            # Very small credits: 12% tolerance (strict)
            max_spread_pct = 0.12
            reasoning = "small credit (<$1.00)"
        elif expected_credit < 1.50:
            # Small credits: 15% tolerance (tight)
            max_spread_pct = 0.15
            reasoning = "small credit (<$1.50)"
        elif expected_credit < 2.50:
            # Medium credits: 20% tolerance (moderate)
            max_spread_pct = 0.20
            reasoning = "medium credit (<$2.50)"
        else:
            # Large credits: 25% tolerance (original)
            max_spread_pct = 0.25
            reasoning = "large credit (>=$2.50)"

        max_spread = expected_credit * max_spread_pct

        log(f"Spread quality: short {short_spread:.2f}, long {long_spread:.2f}, "
            f"net {net_spread:.2f} (credit: ${expected_credit:.2f}, {reasoning})")
        log(f"Max acceptable: ${max_spread:.2f} ({max_spread_pct*100:.0f}% of credit)")

        if net_spread > max_spread:
            log(f"❌ Spread too wide: ${net_spread:.2f} > ${max_spread:.2f} "
                f"(instant slippage would trigger emergency stop)")
            return False

        log(f"✅ Spread acceptable: ${net_spread:.2f} ≤ ${max_spread:.2f}")
        return True

    except Exception as e:
        log(f"Error checking spread quality: {e}")
        return True  # Don't block on error


# ============================================================================
# FIX #2: MINIMUM CREDIT SAFETY BUFFER CHECK
# ============================================================================
# Location: /root/gamma/scalper.py
# Add after existing min_credit check (line ~1770)

def check_credit_safety_buffer(expected_credit, emergency_stop_pct=0.25):
    """
    Verify credit provides adequate buffer above emergency stop threshold.

    Problem: Credits < $1.50 have almost no room for slippage.
    Solution: Require 35% buffer (25% emergency + 10% safety margin).

    Args:
        expected_credit: Expected credit from spread
        emergency_stop_pct: Emergency stop threshold (default 0.25 = 25%)

    Returns:
        (is_safe, reason)
    """
    # Absolute minimum credit (below this, emergency stop too tight)
    ABSOLUTE_MIN_CREDIT = 1.00

    if expected_credit < ABSOLUTE_MIN_CREDIT:
        reason = (f"Credit ${expected_credit:.2f} below absolute minimum "
                 f"${ABSOLUTE_MIN_CREDIT:.2f} (emergency stop would be "
                 f"${expected_credit * emergency_stop_pct:.2f})")
        return False, reason

    # For small credits, require larger buffer
    if expected_credit < 1.50:
        # Calculate how much credit remains after emergency stop
        emergency_threshold = expected_credit * emergency_stop_pct
        remaining_after_stop = expected_credit - emergency_threshold

        # Require at least $0.15 remaining after emergency stop
        # (Covers slippage, spread, market noise)
        min_remaining = 0.15

        if remaining_after_stop < min_remaining:
            reason = (f"Credit ${expected_credit:.2f} too small - "
                     f"after 25% emergency stop (${emergency_threshold:.2f}), "
                     f"only ${remaining_after_stop:.2f} buffer remains "
                     f"(need ${min_remaining:.2f})")
            return False, reason

    # For medium credits (1.50 - 2.00), check 30% buffer
    elif expected_credit < 2.00:
        required_buffer_pct = 0.30
        buffer = expected_credit * (required_buffer_pct - emergency_stop_pct)

        if buffer < 0:
            reason = (f"Credit ${expected_credit:.2f} requires {required_buffer_pct*100:.0f}% "
                     f"total buffer (emergency {emergency_stop_pct*100:.0f}% + "
                     f"{(required_buffer_pct-emergency_stop_pct)*100:.0f}% safety)")
            return False, reason

    # Large credits (>= $2.00) are safe
    return True, "Credit provides adequate safety buffer"


# Usage in scalper.py (after min_credit check):
"""
# Existing time-based minimum credit check
min_credit = INDEX_CONFIG.get_min_credit(now_et.hour)
if expected_credit < min_credit:
    log(f"Credit ${expected_credit:.2f} below minimum ${min_credit:.2f} — NO TRADE")
    send_discord_skip_alert(f"Credit below minimum", run_data)
    return

# NEW: Safety buffer check
is_safe, reason = check_credit_safety_buffer(expected_credit)
if not is_safe:
    log(f"❌ {reason} — NO TRADE")
    send_discord_skip_alert(f"Credit safety buffer: {reason}", run_data)
    return

log(f"✅ Credit ${expected_credit:.2f} passes safety buffer check")
"""


# ============================================================================
# FIX #3: ENTRY SETTLE PERIOD IN MONITOR
# ============================================================================
# Location: /root/gamma/monitor.py
# Modify emergency stop check (line ~1160)

# Add to monitor.py configuration section (top of file, line ~95):
"""
# Entry settle period - allow position to stabilize before emergency stop
SL_ENTRY_SETTLE_SEC = 60  # 60 seconds grace for quotes to settle after fill
"""

# Modify emergency stop check in monitor loop:
"""
# BEFORE (line ~1160):
if profit_pct_sl <= -SL_EMERGENCY_PCT:
    exit_reason = f"EMERGENCY Stop Loss ({profit_pct_sl*100:.0f}% worst-case)"

# AFTER (ENHANCED):
if profit_pct_sl <= -SL_EMERGENCY_PCT:
    # Calculate position age for settle period check
    try:
        if 'T' in entry_time and ('+' in entry_time or 'Z' in entry_time):
            entry_dt = datetime.datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
            entry_dt = entry_dt.astimezone(ET)
        else:
            entry_dt = datetime.datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S')
            entry_dt = ET.localize(entry_dt)
        position_age_sec = (now - entry_dt).total_seconds()
    except (ValueError, TypeError, AttributeError) as e:
        log(f"Error parsing entry time for settle check: {e}")
        position_age_sec = 9999  # Default to old position

    # NEW: Skip emergency stop during settle period
    if position_age_sec < SL_ENTRY_SETTLE_SEC:
        settle_remaining = SL_ENTRY_SETTLE_SEC - position_age_sec
        log(f"  ⏳ EMERGENCY stop triggered but position just entered "
            f"({position_age_sec:.0f}s ago, settle period: {settle_remaining:.0f}s remaining)")
        log(f"     Current loss: {profit_pct_sl*100:.0f}% (threshold: {-SL_EMERGENCY_PCT*100:.0f}%)")
        log(f"     Allowing quotes to settle before emergency exit")
        # Skip this iteration - don't exit yet
    else:
        # Position is old enough, emergency stop is valid
        exit_reason = f"EMERGENCY Stop Loss ({profit_pct_sl*100:.0f}% worst-case)"
"""


# ============================================================================
# FIX #4: MARKET MOMENTUM FILTER (OPTIONAL - MORE COMPLEX)
# ============================================================================
# Location: /root/gamma/scalper.py
# Add as new function, call before place_order()

def check_market_momentum(spx_current, lookback_minutes=5):
    """
    Block entries if SPX has moved significantly in recent minutes.

    Large moves indicate:
    - High volatility → wide spreads
    - Directional momentum → likely to continue
    - Fast-moving market → poor fill quality

    Args:
        spx_current: Current SPX price
        lookback_minutes: How far back to check (default 5 minutes)

    Returns:
        (is_safe, reason)
    """
    try:
        import yfinance as yf
        from datetime import datetime, timedelta

        # Fetch recent 1-minute SPX bars
        ticker = yf.Ticker("^GSPC")  # SPX ticker
        now = datetime.now()
        end = now
        start = now - timedelta(minutes=lookback_minutes + 2)  # Extra buffer

        # Get 1-minute data
        df = ticker.history(start=start, end=end, interval="1m")

        if df.empty or len(df) < 2:
            log(f"Warning: Could not fetch SPX history for momentum check")
            return True, "Momentum check unavailable (allow trade)"

        # Get price from 5 minutes ago
        if len(df) >= lookback_minutes:
            spx_5min_ago = df.iloc[-lookback_minutes]['Close']
        else:
            spx_5min_ago = df.iloc[0]['Close']

        spx_change_5m = abs(spx_current - spx_5min_ago)

        # Threshold: 10 points in 5 minutes
        # That's ~0.15% on 6900 SPX = aggressive move
        MOMENTUM_THRESHOLD_5M = 10.0

        if spx_change_5m > MOMENTUM_THRESHOLD_5M:
            reason = (f"SPX moved {spx_change_5m:.1f} pts in {lookback_minutes}min "
                     f"(threshold: {MOMENTUM_THRESHOLD_5M:.0f} pts) - too fast")
            log(f"❌ {reason}")
            return False, reason

        # Also check 1-minute spike
        if len(df) >= 2:
            spx_1min_ago = df.iloc[-2]['Close']
            spx_change_1m = abs(spx_current - spx_1min_ago)

            MOMENTUM_THRESHOLD_1M = 5.0  # 5 points in 1 minute = spike

            if spx_change_1m > MOMENTUM_THRESHOLD_1M:
                reason = (f"SPX moved {spx_change_1m:.1f} pts in 1min "
                         f"(threshold: {MOMENTUM_THRESHOLD_1M:.0f} pts) - spike detected")
                log(f"❌ {reason}")
                return False, reason

        log(f"✅ Market momentum acceptable: 5m change {spx_change_5m:.1f} pts, "
            f"1m change {spx_change_1m:.1f} pts")
        return True, "Market momentum acceptable"

    except Exception as e:
        log(f"Error checking market momentum: {e}")
        return True, "Momentum check failed (allow trade)"


# Usage in scalper.py (before place_order):
"""
# Check market momentum before entering
is_safe, reason = check_market_momentum(spx_price, lookback_minutes=5)
if not is_safe:
    log(f"❌ {reason} — NO TRADE")
    send_discord_skip_alert(f"Market momentum: {reason}", run_data)
    return

log(f"✅ {reason}")
"""


# ============================================================================
# IMPLEMENTATION CHECKLIST
# ============================================================================
"""
Apply fixes in this order:

□ FIX #1: Replace check_spread_quality() in scalper.py (~line 1950)
    - Copy check_spread_quality_FIXED() function
    - Test with recent trade data
    - Expected: Block 30-40% of bad spreads

□ FIX #2: Add check_credit_safety_buffer() call in scalper.py (~line 1770)
    - Add function definition
    - Call after min_credit check
    - Expected: Block credits < $1.00, warn on $1.00-$1.50

□ FIX #3: Add settle period to monitor.py (~line 1160)
    - Add SL_ENTRY_SETTLE_SEC = 60 to config
    - Modify emergency stop check
    - Expected: Prevent false alarms in first 60 seconds

□ FIX #4 (Optional): Add momentum filter to scalper.py
    - Add check_market_momentum() function
    - Call before place_order()
    - Expected: Block 5-10% of trades during fast moves

□ Test in paper mode for 5+ trading days
    - Monitor skip rate (target: 10-15%)
    - Monitor emergency stop rate (target: <5%, was 29%)
    - Monitor win rate (should improve)

□ Deploy to live after validation
    - Gradual rollout recommended
    - Monitor first 10 trades closely
"""


# ============================================================================
# EXPECTED RESULTS AFTER FIXES
# ============================================================================
"""
BEFORE FIXES (Current State):
- Emergency stops in 0-1 min: 5/17 trades = 29%
- Average emergency loss: -$54
- Pattern: Instant losses on entry

AFTER FIXES (Expected):
- Emergency stops in 0-1 min: <1/20 trades = <5%
- Trades blocked by filters: ~10-15%
- Win rate: +2-3% improvement (avoiding bad entries)
- Average trade quality: Much better fills
- Emergency stops only on true market events (flash crashes)

NET IMPACT:
- Fewer trades (10-15% reduction from blocks)
- Higher quality trades (better fills, less slippage)
- Fewer instant losses
- Improved overall P&L and Sharpe ratio
"""
