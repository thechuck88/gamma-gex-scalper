#!/usr/bin/env python3
"""
AI Hold Advisor — Haiku 0DTE Premium Decay Specialist
======================================================
Called when a trailing stop or profit target triggers on an open credit spread.
Haiku decides: HOLD (suppress the close, let theta work) or CLOSE (take profit).

Architecture:
- Called from monitor.py at the trailing stop / profit target decision point
- Gets full position + market context (SPX, VIX, distance, time, GEX, momentum)
- Returns HOLD or CLOSE with confidence level
- Fail-open: any error → CLOSE (preserves existing behavior)
- Cost: ~$0.001-0.002 per call, max ~10 calls/day

Direction-aware: Understands that CALL spreads profit when SPX stays BELOW the
short strike, and PUT spreads profit when SPX stays ABOVE. Gets this right for
GEX pin trades (near ATM) and far OTM trades alike.
"""

import math
import logging
import time
import pytz
import requests
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# Cooldown: don't ask Haiku more than once per position per N seconds
_COOLDOWN_SEC = 30
_COOLDOWN_SPX_MOVE = 5.0  # Invalidate cache if SPX moved > N pts since last call
_last_call = {}  # order_id → (timestamp, decision, spx_price)


def _load_api_key():
    """Load Anthropic API key from environment files."""
    for env_file in ['/etc/gamma.env', '/etc/trader.env']:
        if Path(env_file).exists():
            with open(env_file) as f:
                for line in f:
                    if line.startswith('ANTHROPIC_API_KEY='):
                        return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None


def _compute_sigma_distance(spx_price, short_strike, vix, hours_to_expiry, is_call):
    """
    Compute how far OTM the short strike is in sigma units.

    For CALL spreads: danger = SPX rising ABOVE short_strike
    For PUT spreads: danger = SPX falling BELOW short_strike
    """
    if hours_to_expiry <= 0 or vix <= 0 or spx_price <= 0:
        return 0.0, 0.0

    # Expected 1σ move for remaining time
    daily_move = spx_price * (vix / 100) / math.sqrt(252)
    remaining_fraction = hours_to_expiry / 6.5  # Trading day = 6.5 hrs
    expected_move = daily_move * math.sqrt(max(remaining_fraction, 0.01))

    # Distance to danger
    if is_call:
        distance_pts = short_strike - spx_price  # Positive = safe (SPX below strike)
    else:
        distance_pts = spx_price - short_strike  # Positive = safe (SPX above strike)

    sigma = distance_pts / expected_move if expected_move > 0 else 0.0
    return sigma, expected_move


def _compute_otm_probability(sigma):
    """Approximate probability of staying OTM based on sigma distance."""
    # Using error function approximation
    return 0.5 * (1 + math.erf(sigma / math.sqrt(2)))


def _load_tradier_key():
    """Load Tradier live API key."""
    for env_file in ['/etc/gamma.env']:
        if Path(env_file).exists():
            with open(env_file) as f:
                for line in f:
                    if line.startswith('TRADIER_LIVE_KEY='):
                        return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None


# Cache: avoid re-fetching SPX bars within same decision cycle
_spx_bars_cache = {'time': 0, 'bars': None}
_SPX_BARS_CACHE_SEC = 15


def _fetch_recent_spx_bars(n_minutes=10):
    """Fetch last N minutes of 1-min SPX bars from Tradier. Returns list of close prices or None."""
    now = time.time()
    if now - _spx_bars_cache['time'] < _SPX_BARS_CACHE_SEC and _spx_bars_cache['bars']:
        return _spx_bars_cache['bars']

    api_key = _load_tradier_key()
    if not api_key:
        return None

    try:
        et = pytz.timezone('America/New_York')
        now_et = datetime.now(et)
        start = now_et.replace(second=0, microsecond=0)
        # Go back n_minutes
        from datetime import timedelta
        start = start - timedelta(minutes=n_minutes)

        resp = requests.get("https://api.tradier.com/v1/markets/timesales",
                            params={"symbol": "SPX", "interval": "1min",
                                    "start": start.strftime('%Y-%m-%d %H:%M'),
                                    "end": now_et.strftime('%Y-%m-%d %H:%M')},
                            headers={"Authorization": f"Bearer {api_key}",
                                     "Accept": "application/json"},
                            timeout=5)
        if resp.status_code != 200:
            return None

        data = resp.json()
        series = data.get('series', {})
        if not series:
            return None

        ticks = series.get('data', [])
        if isinstance(ticks, dict):
            ticks = [ticks]

        closes = [float(t.get('close', t.get('price', 0))) for t in ticks if t.get('close') or t.get('price')]
        if closes:
            _spx_bars_cache['time'] = now
            _spx_bars_cache['bars'] = closes
        return closes if len(closes) >= 3 else None
    except Exception:
        return None


def _compute_momentum_strength(closes, short_strike, is_call, is_ic):
    """
    Compute momentum strength from recent 1-min SPX closes.

    Returns dict with:
        velocity_1m: pts/min over last 1 minute
        velocity_5m: pts/min over last 5 minutes
        acceleration: change in velocity (pts/min²)
        trend: ACCELERATING_TOWARD, DECELERATING, STALLED, REVERSING_AWAY
        description: Human-readable string for Haiku
    """
    if not closes or len(closes) < 3:
        return None

    current = closes[-1]
    prev_1 = closes[-2]
    n = len(closes)

    # Velocity: pts per minute
    velocity_1m = current - prev_1
    mid = max(n // 2, 1)
    velocity_5m = (current - closes[0]) / max(n - 1, 1)

    # Acceleration: change in velocity (compare recent half to first half)
    first_half_vel = (closes[mid] - closes[0]) / max(mid, 1)
    second_half_vel = (current - closes[mid]) / max(n - mid, 1)
    acceleration = second_half_vel - first_half_vel

    # Determine if movement is toward or away from danger
    if is_ic:
        # IC: any strong directional move is concerning
        speed = abs(velocity_5m)
        accel_speed = abs(acceleration)
        if speed < 0.3:
            trend = "STALLED"
            desc = f"STALLED — SPX moving < 0.3 pts/min, no directional threat"
        elif accel_speed > 0.1 and abs(velocity_1m) > abs(velocity_5m):
            trend = "ACCELERATING"
            direction = "UPWARD" if velocity_1m > 0 else "DOWNWARD"
            desc = f"ACCELERATING {direction} — {abs(velocity_1m):.1f} pts/min (was {abs(velocity_5m):.1f}), gaining speed"
        elif abs(velocity_1m) < abs(velocity_5m) * 0.5:
            trend = "DECELERATING"
            desc = f"DECELERATING — was {abs(velocity_5m):.1f} pts/min, now {abs(velocity_1m):.1f}, losing steam"
        else:
            direction = "UPWARD" if velocity_5m > 0 else "DOWNWARD"
            desc = f"STEADY {direction} — {abs(velocity_5m):.1f} pts/min"
            trend = "STEADY"
    else:
        # Single-sided: toward/away from short strike
        if is_call:
            toward = velocity_5m > 0  # Rising = toward CALL danger
        else:
            toward = velocity_5m < 0  # Falling = toward PUT danger

        speed = abs(velocity_5m)

        if speed < 0.3:
            trend = "STALLED"
            desc = f"STALLED — SPX barely moving ({speed:.1f} pts/min), bid/ask noise likely"
        elif toward and abs(velocity_1m) > abs(velocity_5m):
            trend = "ACCELERATING_TOWARD"
            desc = f"ACCELERATING TOWARD strike — {abs(velocity_1m):.1f} pts/min last bar (was {speed:.1f} avg), DANGER increasing"
        elif toward and abs(velocity_1m) < abs(velocity_5m) * 0.5:
            trend = "DECELERATING_TOWARD"
            desc = f"MOVING TOWARD strike but DECELERATING — was {speed:.1f} pts/min, now {abs(velocity_1m):.1f}, losing momentum"
        elif toward:
            trend = "STEADY_TOWARD"
            desc = f"STEADY MOVE TOWARD strike — {speed:.1f} pts/min, consistent pressure"
        elif not toward and abs(velocity_1m) > abs(velocity_5m):
            trend = "ACCELERATING_AWAY"
            desc = f"ACCELERATING AWAY from strike — {abs(velocity_1m):.1f} pts/min, danger DECREASING"
        elif not toward:
            trend = "MOVING_AWAY"
            desc = f"MOVING AWAY from strike — {speed:.1f} pts/min, favorable"
        else:
            trend = "MIXED"
            desc = f"MIXED signals — velocity {velocity_5m:+.1f} pts/min"

    return {
        'velocity_1m': velocity_1m,
        'velocity_5m': velocity_5m,
        'acceleration': acceleration,
        'trend': trend,
        'description': desc,
        'bars_analyzed': n,
        'range': closes[-1] - closes[0],
    }


def ask_haiku_hold_or_close(order, spx_price, vix, trigger_reason, log_fn=None):
    """
    Ask Haiku whether to HOLD or CLOSE an open credit spread.

    Args:
        order: Position dict with keys: order_id, strategy, strikes, entry_credit,
               best_profit_pct, entry_distance, index_entry, vix_entry, entry_time,
               position_size, direction
        spx_price: Current SPX price
        vix: Current VIX level
        trigger_reason: Why the stop triggered (e.g., "Trailing Stop (20% from peak 30%)")
        log_fn: Optional logging function (monitor's log())

    Returns:
        (decision, confidence, reason) — decision is 'HOLD' or 'CLOSE'
        On any error: ('CLOSE', 0, 'AI advisor error — fail-safe close')
    """
    _log = log_fn or logger.info
    order_id = order.get('order_id', 'unknown')

    # Cooldown check — don't spam Haiku (invalidate if SPX moved significantly)
    now = time.time()
    if order_id in _last_call:
        last_time, last_decision, last_spx = _last_call[order_id]
        spx_moved = abs(spx_price - last_spx) if last_spx > 0 else 0
        if now - last_time < _COOLDOWN_SEC and spx_moved < _COOLDOWN_SPX_MOVE:
            _log(f"🧠 AI HOLD: Cooldown active for {order_id} ({_COOLDOWN_SEC}s) — using cached: {last_decision}")
            return last_decision
        elif spx_moved >= _COOLDOWN_SPX_MOVE:
            _log(f"🧠 AI HOLD: Cache invalidated — SPX moved {spx_moved:.1f}pts since last call")

    try:
        import anthropic
        api_key = _load_api_key()
        if not api_key:
            _log("🧠 AI HOLD: No API key — fail-safe CLOSE")
            return ('CLOSE', 0, 'No API key')

        client = anthropic.Anthropic(api_key=api_key)

        # Parse position data
        strategy = order.get('strategy', 'UNKNOWN').upper()
        strikes_str = order.get('strikes', '')
        entry_credit = float(order.get('entry_credit', 0))
        best_profit_pct = float(order.get('best_profit_pct', 0))
        entry_distance = float(order.get('entry_distance', 0))
        position_size = int(order.get('position_size', 1))
        direction = order.get('direction', '').upper()  # BEARISH or BULLISH

        # Determine if CALL or PUT spread
        # Strategy can be: CALL, PUT, IC, OTM_IRON_CONDOR, OTM_SINGLE_SIDED
        # Check IC FIRST — an IC contains both CALL and PUT sides
        is_ic = ('IC' in strategy or 'IRON' in strategy)
        is_call = not is_ic and ('CALL' in strategy or direction == 'BEARISH')
        is_put = not is_ic and ('PUT' in strategy or direction == 'BULLISH')

        if is_ic:
            spread_type = "IRON CONDOR (both CALL and PUT spreads)"
            danger_direction = "either a rally above the CALL short strike OR a drop below the PUT short strike"
            safe_condition = "stays BETWEEN the short strikes"
        elif is_call:
            spread_type = "Short CALL credit spread (BEARISH — profits if SPX stays BELOW short strike)"
            danger_direction = f"SPX RALLYING ABOVE {strikes_str.split('/')[0] if '/' in strikes_str else 'short strike'}"
            safe_condition = "stays BELOW the short strike"
        elif is_put:
            spread_type = "Short PUT credit spread (BULLISH — profits if SPX stays ABOVE short strike)"
            danger_direction = f"SPX DROPPING BELOW {strikes_str.split('/')[0] if '/' in strikes_str else 'short strike'}"
            safe_condition = "stays ABOVE the short strike"
        else:
            spread_type = f"Credit spread ({strategy})"
            danger_direction = "SPX moving toward the short strike"
            safe_condition = "stays away from the short strike"

        # Parse short strike(s) for distance calc
        short_strike = 0
        ic_call_strike = 0
        ic_put_strike = 0
        try:
            strike_parts = strikes_str.replace('C', '').replace('P', '').split('/')
            short_strike = float(strike_parts[0])
            # IC: strikes are CALL_short/CALL_long/PUT_short/PUT_long
            if is_ic and len(strike_parts) >= 4:
                ic_call_strike = float(strike_parts[0])
                ic_put_strike = float(strike_parts[2])
        except (ValueError, IndexError):
            pass

        # Time to expiry
        et = pytz.timezone('America/New_York')
        now_et = datetime.now(et)
        expiry_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        hours_to_expiry = max((expiry_et - now_et).total_seconds() / 3600, 0)

        # Sigma distance — for IC, measure BOTH sides and report the closer (more dangerous) one
        if is_ic and ic_call_strike > 0 and ic_put_strike > 0:
            sigma_call, expected_move = _compute_sigma_distance(
                spx_price, ic_call_strike, vix, hours_to_expiry, True)
            sigma_put, _ = _compute_sigma_distance(
                spx_price, ic_put_strike, vix, hours_to_expiry, False)
            # The closer side is more dangerous — use the smaller sigma
            if sigma_call < sigma_put:
                sigma = sigma_call
                short_strike = ic_call_strike
                distance_pts = ic_call_strike - spx_price
                distance_label = f"CALL side closer, {'ABOVE' if distance_pts > 0 else 'BELOW (ITM!)'}"
                ic_danger_side = 'CALL'
            else:
                sigma = sigma_put
                short_strike = ic_put_strike
                distance_pts = spx_price - ic_put_strike
                distance_label = f"PUT side closer, {'BELOW' if distance_pts > 0 else 'ABOVE (ITM!)'}"
                ic_danger_side = 'PUT'
            otm_prob = _compute_otm_probability(sigma)
            # Add both-side context for Haiku
            ic_distance_str = (f"\n- CALL short strike: {ic_call_strike:.0f} ({abs(ic_call_strike - spx_price):.0f} pts above, {sigma_call:.2f}σ)"
                               f"\n- PUT short strike: {ic_put_strike:.0f} ({abs(spx_price - ic_put_strike):.0f} pts below, {sigma_put:.2f}σ)"
                               f"\n- CLOSER (more dangerous) side: {'CALL' if sigma_call < sigma_put else 'PUT'} at {sigma:.2f}σ")
        else:
            sigma, expected_move = _compute_sigma_distance(
                spx_price, short_strike, vix, hours_to_expiry, is_call)
            otm_prob = _compute_otm_probability(sigma)
            ic_distance_str = ""

        # Distance in points (single-sided)
        if not is_ic:
            if is_call:
                distance_pts = short_strike - spx_price
                distance_label = "ABOVE current price" if distance_pts > 0 else "BELOW current price (ITM!)"
            elif is_put:
                distance_pts = spx_price - short_strike
                distance_label = "BELOW current price" if distance_pts > 0 else "ABOVE current price (ITM!)"
            else:
                distance_pts = abs(short_strike - spx_price)
                distance_label = f"{distance_pts:.0f} pts from current price"

        # Momentum context from entry
        spx_entry = float(order.get('index_entry', 0))
        if spx_entry > 0:
            spx_change = spx_price - spx_entry
            if is_ic and ic_call_strike > 0 and ic_put_strike > 0:
                # IC: determine which side momentum is moving toward
                toward_call = spx_change > 0  # Rising = toward CALL danger
                toward_put = spx_change < 0   # Falling = toward PUT danger
                danger_side = 'CALL short strike' if toward_call else 'PUT short strike'
                momentum_desc = f"{'RISING' if spx_change > 0 else 'FALLING'} {abs(spx_change):.1f} pts since entry (TOWARD {danger_side})"
            elif is_call:
                momentum_safe = spx_change < 0  # Falling = safe for calls
                momentum_desc = f"{'FALLING' if spx_change < 0 else 'RISING'} {abs(spx_change):.1f} pts since entry ({'AWAY from' if momentum_safe else 'TOWARD'} danger)"
            elif is_put:
                momentum_safe = spx_change > 0  # Rising = safe for puts
                momentum_desc = f"{'RISING' if spx_change > 0 else 'FALLING'} {abs(spx_change):.1f} pts since entry ({'AWAY from' if momentum_safe else 'TOWARD'} danger)"
            else:
                momentum_desc = f"Moved {spx_change:+.1f} pts since entry"
        else:
            momentum_desc = "Unknown (no entry price)"

        # Real-time momentum strength (last 10 minutes of 1-min bars)
        strength_str = ""
        try:
            recent_closes = _fetch_recent_spx_bars(10)
            if recent_closes:
                strength = _compute_momentum_strength(recent_closes, short_strike, is_call, is_ic)
                if strength:
                    strength_str = f"\n- REAL-TIME STRENGTH ({strength['bars_analyzed']} bars): {strength['description']}"
                    strength_str += f"\n  Velocity: {strength['velocity_5m']:+.1f} pts/min avg, {strength['velocity_1m']:+.1f} pts/min last bar"
                    if abs(strength['acceleration']) > 0.05:
                        accel_dir = "INCREASING" if strength['acceleration'] > 0 else "DECREASING"
                        strength_str += f" — momentum {accel_dir}"
        except Exception:
            pass  # Non-critical — fail silently

        # GEX context — check if we have it
        gex_pin = order.get('gex_pin', 0)
        gex_str = ""
        if gex_pin:
            pin_dist = spx_price - gex_pin
            gex_str = f"""
GEX (Gamma Exposure):
- Dealer gamma pin: {gex_pin:.0f} (SPX is {abs(pin_dist):.0f} pts {'above' if pin_dist > 0 else 'below'} pin)
- Pin effect: {'STRONG anchor — dampens movement' if abs(pin_dist) < 20 else 'WEAK — SPX has broken away from pin'}"""

        # Max loss calculation
        try:
            strike_vals = [float(s.replace('C','').replace('P','')) for s in strikes_str.split('/')]
            spread_width = abs(strike_vals[1] - strike_vals[0]) if len(strike_vals) >= 2 else 20
        except (ValueError, IndexError):
            spread_width = 20
        max_loss_per_contract = (spread_width - entry_credit) * 100
        max_loss_total = max_loss_per_contract * position_size
        current_profit = entry_credit * best_profit_pct * 100 * position_size

        prompt = f"""You are a 20-year veteran options trader specializing in 0DTE GEX pin trades and far OTM credit spreads. You think like a premium seller — your edge is THETA DECAY, not direction. You've seen thousands of 0DTE trades and know exactly when to hold through noise and when to cut and run.

CRITICAL FRAMEWORK — You are a PREMIUM DECAY specialist:
- You sold premium far from the money. Your edge is TIME DECAY, not delta.
- The spread decays toward $0.00 as 4:00 PM approaches IF SPX {safe_condition}.
- The ONLY question: "Will SPX reach my short strike before 4 PM expiry?"
- Small fluctuations in the spread mid-price are OPTIONS BID/ASK NOISE on illiquid 0DTE strikes, NOT real risk.
- Closing early surrenders ALL remaining theta. Every minute held = more decay in your favor.
- The further OTM and the less time remaining, the STRONGER the hold case.

YOUR DECISION FRAMEWORK:
- Distance > 1.5σ AND momentum away from strike → STRONG HOLD
- Distance > 1.0σ AND no adverse momentum → HOLD
- Distance 0.5–1.0σ AND mixed momentum → Evaluate carefully
- Distance < 0.5σ OR strong momentum TOWARD strike → CLOSE
- SPX anchored at GEX pin AWAY from strike → Strengthens HOLD
- After 2:00 PM with > 1.0σ distance → STRONG HOLD (theta acceleration)
- After 3:00 PM with > 0.5σ distance → STRONG HOLD (extreme decay)

MOMENTUM STRENGTH — Critical for distinguishing noise from real moves:
- STALLED (< 0.3 pts/min): Spread P&L change is almost certainly bid/ask noise → HOLD
- DECELERATING toward strike: Move is losing steam, likely to stall → Lean HOLD
- ACCELERATING TOWARD strike: Real directional pressure, danger increasing → Lean CLOSE
- ACCELERATING AWAY from strike: Moving to safety → STRONG HOLD
- Entry momentum alone can be misleading (SPX moved 40pts 3 hours ago but is flat now) — REAL-TIME STRENGTH is the current truth

⚠️ DIRECTION MATTERS — Get this right:
- This is a {spread_type}
- DANGER = {danger_direction}
- SAFE = SPX {safe_condition}
- You PROFIT from time passing while SPX stays safe. You LOSE only if SPX crosses the short strike.

POSITION:
- Strategy: {spread_type}
- Strikes: {strikes_str}
- Contracts: {position_size}
- Entry credit: ${entry_credit:.2f}/contract
- Max risk: ${max_loss_per_contract:.0f}/contract (${max_loss_total:.0f} total)
- Peak P/L: +{best_profit_pct*100:.1f}% (${current_profit:.0f})
- Entry OTM distance: {entry_distance:.0f} pts

MARKET:
- SPX: {spx_price:.0f}
- Short strike: {short_strike:.0f} ({abs(distance_pts):.0f} pts {distance_label}){ic_distance_str}
- Distance: {sigma:.2f}σ of remaining expected move
- P(stays OTM): ~{otm_prob*100:.0f}%
- Expected remaining move: ±{expected_move:.0f} pts (1σ, {hours_to_expiry:.1f} hrs)
- VIX: {vix:.1f}
- Momentum since entry: {momentum_desc}{strength_str}
{gex_str}

TIME:
- Current: {now_et.strftime('%I:%M %p')} ET
- Expiry: 4:00 PM ET
- Remaining: {hours_to_expiry:.1f} hours
- Theta status: {'EXTREME DECAY (final hour)' if hours_to_expiry < 1 else 'ACCELERATING DECAY' if hours_to_expiry < 2 else 'ACTIVE DECAY' if hours_to_expiry < 4 else 'EARLY — full day of decay ahead'}

TRIGGER: {trigger_reason}

Respond EXACTLY in this format (nothing else):
DECISION: [HOLD|CLOSE]
CONFIDENCE: [0-100]%
REASON: [One sentence — focus on distance, time, direction, and theta edge]
RISK: [One sentence — the specific scenario that would make this decision wrong]
RECHECK: [Price level or time to reassess, e.g., "SPX 6740 or 11:00 AM"]"""

        _log(f"🧠 AI HOLD: Asking Haiku for {order_id} ({strategy} {strikes_str}, "
             f"SPX {spx_price:.0f}, {distance_pts:.0f}pts OTM, {sigma:.2f}σ, {hours_to_expiry:.1f}h left)...")

        t0 = time.time()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        elapsed = time.time() - t0

        text = response.content[0].text.strip()
        _log(f"🧠 AI HOLD RESPONSE ({elapsed:.1f}s, ~${response.usage.input_tokens * 1.0/1e6 + response.usage.output_tokens * 5.0/1e6:.4f}):")
        for line in text.split('\n'):
            if line.strip():
                _log(f"  {line.strip()}")

        # Parse response
        decision = 'CLOSE'  # Default fail-safe
        confidence = 0
        reason = ''

        for line in text.split('\n'):
            line_upper = line.upper().strip()
            if line_upper.startswith('DECISION:'):
                val = line_upper.split(':', 1)[1].strip()
                if 'HOLD' in val:
                    decision = 'HOLD'
                else:
                    decision = 'CLOSE'
            elif line_upper.startswith('CONFIDENCE:'):
                try:
                    confidence = int(''.join(c for c in line.split(':', 1)[1] if c.isdigit()))
                except (ValueError, IndexError):
                    confidence = 50
            elif line_upper.startswith('REASON:'):
                reason = line.split(':', 1)[1].strip()

        result = (decision, confidence, reason)
        _last_call[order_id] = (time.time(), result, spx_price)
        return result

    except Exception as e:
        _log(f"🧠 AI HOLD ERROR: {e} — fail-safe CLOSE")
        return ('CLOSE', 0, f'AI advisor error: {e}')


def clear_cooldown(order_id):
    """Clear the cooldown for a position (call when position closes or conditions change significantly)."""
    _last_call.pop(order_id, None)


def clear_stale_cooldowns(active_order_ids):
    """Remove cooldown entries for orders that no longer exist. Call periodically to prevent memory leak."""
    stale = [oid for oid in _last_call if oid not in active_order_ids]
    for oid in stale:
        del _last_call[oid]
