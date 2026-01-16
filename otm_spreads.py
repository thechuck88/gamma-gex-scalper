#!/usr/bin/env python3
"""
OTM Spread Strategy - Opportunistic high-probability spreads for no-GEX days

Strategy:
- Sell far OTM iron condors when GEX pin is too far away
- Target 90-95% probability of profit
- Small but consistent credits ($0.30-0.50+)
- 200% stop loss, 50% profit target
- Max 1-2 positions per day
"""

import math
from datetime import datetime, time
import pytz

# Probability thresholds
MIN_PROBABILITY_OF_PROFIT = 0.90  # 90% chance of expiring OTM
IDEAL_PROBABILITY = 0.92           # Target probability

# Credit requirements (per $10 wide spread)
MIN_CREDIT_PER_SPREAD = 0.20       # Minimum $0.20 per 10-point spread
IDEAL_CREDIT_TOTAL = 0.40          # Target $0.40+ for iron condor
MIN_CREDIT_PCT = 0.02              # Must be at least 2% of spread width

# Position limits
MAX_POSITIONS_PER_DAY = 1          # Conservative - only fill dead air
MIN_TIME_UNTIL_CLOSE_HOURS = 2.0   # Don't enter too close to close
MAX_TIME_UNTIL_CLOSE_HOURS = 6.0   # Don't enter too early (need some theta)

# Standard deviations for strike selection
STD_DEV_MULTIPLIER = 2.5           # 2.5 SD = ~99% coverage (leaving 1% tail on each side)

# Trading hours (Eastern Time)
ENTRY_WINDOW_START = time(10, 0)   # 10:00 AM ET
ENTRY_WINDOW_END = time(14, 0)     # 2:00 PM ET


def calculate_expected_move(price, implied_vol_annual, hours_remaining):
    """
    Calculate expected price move using Black-Scholes volatility scaling.

    Args:
        price: Current SPX price
        implied_vol_annual: Annual implied volatility (e.g., 0.12 for 12%)
        hours_remaining: Hours until expiration

    Returns:
        Expected 1 standard deviation move in points
    """
    # Convert annual vol to time-adjusted vol
    # Vol scales with sqrt(time)
    time_fraction = hours_remaining / (252 * 24)  # Trading hours in a year
    time_adjusted_vol = implied_vol_annual * math.sqrt(time_fraction)

    # Expected move = price × volatility
    expected_move = price * time_adjusted_vol

    return expected_move


def get_implied_volatility_estimate(vix_level=None):
    """
    Estimate SPX implied volatility.

    If VIX is available, use it directly (VIX is 30-day SPX vol).
    Otherwise, use a conservative estimate.

    Returns:
        Annual implied volatility as decimal (e.g., 0.12 for 12%)
    """
    if vix_level and vix_level > 0:
        # VIX is already in percentage terms, convert to decimal
        return vix_level / 100.0
    else:
        # Conservative fallback: assume 15% annual vol
        return 0.15


def get_hours_until_close():
    """Calculate hours remaining until 4:00 PM ET today."""
    et = pytz.timezone('America/New_York')
    now = datetime.now(et)

    # Market close at 4:00 PM ET
    close_time = now.replace(hour=16, minute=0, second=0, microsecond=0)

    if now >= close_time:
        # Already past close
        return 0.0

    time_remaining = close_time - now
    hours_remaining = time_remaining.total_seconds() / 3600.0

    return hours_remaining


def is_entry_window():
    """Check if we're in the valid entry time window."""
    et = pytz.timezone('America/New_York')
    now = datetime.now(et).time()

    return ENTRY_WINDOW_START <= now <= ENTRY_WINDOW_END


def calculate_strike_distance(spx_price, implied_vol, hours_remaining):
    """
    Calculate how far from current price to place strikes.

    Returns:
        (call_distance, put_distance) - points away from current price
    """
    # Get expected 1 SD move
    one_sd = calculate_expected_move(spx_price, implied_vol, hours_remaining)

    # Place strikes at 2.5 SD (99% probability coverage)
    strike_distance = one_sd * STD_DEV_MULTIPLIER

    # Round to nearest 5 (SPX strikes are in 5-point increments)
    strike_distance = round(strike_distance / 5) * 5

    return strike_distance


def round_to_strike(price, increment=5):
    """Round price to nearest valid strike (SPX uses 5-point increments)."""
    return round(price / increment) * increment


def find_otm_strikes(spx_price, vix_level=None, skip_time_check=False):
    """
    Find optimal OTM strike prices for iron condor.

    Args:
        spx_price: Current SPX price
        vix_level: Current VIX level (optional, will estimate if not provided)
        skip_time_check: Skip time window validation (for testing)

    Returns:
        dict with strike info or None if conditions not met
    """
    # Check time constraints
    hours_remaining = get_hours_until_close()

    if not skip_time_check:
        if hours_remaining < MIN_TIME_UNTIL_CLOSE_HOURS:
            return None  # Too close to expiration

        if hours_remaining > MAX_TIME_UNTIL_CLOSE_HOURS:
            return None  # Too early (not enough theta decay)

        if not is_entry_window():
            return None  # Outside trading hours

    # Get implied volatility
    implied_vol = get_implied_volatility_estimate(vix_level)

    # Calculate strike distance
    strike_distance = calculate_strike_distance(spx_price, implied_vol, hours_remaining)

    # Ensure minimum distance (safety buffer)
    min_distance = 50  # At least 50 points away
    if strike_distance < min_distance:
        strike_distance = min_distance

    # Calculate strikes
    call_short = round_to_strike(spx_price + strike_distance)
    call_long = call_short + 10  # 10-point spread

    put_short = round_to_strike(spx_price - strike_distance)
    put_long = put_short - 10    # 10-point spread

    return {
        'spx_price': spx_price,
        'call_spread': {
            'short': call_short,
            'long': call_long,
            'distance': call_short - spx_price
        },
        'put_spread': {
            'short': put_short,
            'long': put_long,
            'distance': spx_price - put_short
        },
        'implied_vol': implied_vol * 100,  # Convert to percentage for display
        'hours_remaining': hours_remaining,
        'expected_move_1sd': calculate_expected_move(spx_price, implied_vol, hours_remaining),
        'strike_distance': strike_distance
    }


def evaluate_spread_setup(strikes, call_credit, put_credit):
    """
    Evaluate if the strike setup meets minimum requirements.

    Args:
        strikes: Dict from find_otm_strikes()
        call_credit: Credit for call spread (e.g., 0.25)
        put_credit: Credit for put spread (e.g., 0.22)

    Returns:
        dict with evaluation result or None if doesn't meet criteria
    """
    if not strikes:
        return None

    total_credit = call_credit + put_credit

    # Check minimum credit requirements
    if call_credit < MIN_CREDIT_PER_SPREAD:
        return None  # Call spread credit too low

    if put_credit < MIN_CREDIT_PER_SPREAD:
        return None  # Put spread credit too low

    if total_credit < IDEAL_CREDIT_TOTAL:
        # Log warning but still allow if above minimums
        pass

    # Calculate risk/reward
    spread_width = 10  # Currently hardcoded to 10-point spreads
    max_risk_per_side = (spread_width - call_credit) * 100  # In dollars per contract
    max_profit = total_credit * 100

    # Calculate rough probability (simplified)
    # This is a rough estimate - in production, you'd use more sophisticated models
    call_distance_sd = strikes['call_spread']['distance'] / strikes['expected_move_1sd']
    put_distance_sd = strikes['put_spread']['distance'] / strikes['expected_move_1sd']

    return {
        'valid': True,
        'strikes': strikes,
        'call_credit': call_credit,
        'put_credit': put_credit,
        'total_credit': total_credit,
        'max_profit_per_contract': max_profit,
        'max_risk_per_side': max_risk_per_side,
        'call_distance_sd': call_distance_sd,
        'put_distance_sd': put_distance_sd,
        'summary': f"Iron Condor: {strikes['put_spread']['short']}/{strikes['put_spread']['long']} "
                   f"× {strikes['call_spread']['short']}/{strikes['call_spread']['long']} "
                   f"for ${total_credit:.2f} credit"
    }


def find_single_sided_spread(spx_price, gex_pin_strike, vix_level=None, skip_time_check=False):
    """
    Find optimal OTM strike prices for single-sided spread (PUT or CALL spread only).

    Uses GEX directional bias:
    - If GEX pin > price (bullish): Sell PUT spread
    - If GEX pin < price (bearish): Sell CALL spread

    Args:
        spx_price: Current SPX price
        gex_pin_strike: GEX pin level (determines directional bias)
        vix_level: Current VIX level (optional, will estimate if not provided)
        skip_time_check: Skip time window validation (for testing)

    Returns:
        dict with strike info or None if conditions not met
    """
    # Check time constraints
    hours_remaining = get_hours_until_close()

    if not skip_time_check:
        if hours_remaining < MIN_TIME_UNTIL_CLOSE_HOURS:
            return None  # Too close to expiration

        if hours_remaining > MAX_TIME_UNTIL_CLOSE_HOURS:
            return None  # Too early (not enough theta decay)

        if not is_entry_window():
            return None  # Outside trading hours

    # Determine direction from GEX pin
    if gex_pin_strike > spx_price:
        direction = "BULLISH"
        side = "PUT"
    else:
        direction = "BEARISH"
        side = "CALL"

    # Get implied volatility
    implied_vol = get_implied_volatility_estimate(vix_level)

    # Calculate strike distance
    strike_distance = calculate_strike_distance(spx_price, implied_vol, hours_remaining)

    # Ensure minimum distance (safety buffer)
    min_distance = 50  # At least 50 points away
    if strike_distance < min_distance:
        strike_distance = min_distance

    # Calculate strikes based on direction
    if side == "PUT":
        short_strike = round_to_strike(spx_price - strike_distance)
        long_strike = short_strike - 10  # 10-point spread
        distance_otm = spx_price - short_strike
    else:  # CALL
        short_strike = round_to_strike(spx_price + strike_distance)
        long_strike = short_strike + 10  # 10-point spread
        distance_otm = short_strike - spx_price

    return {
        'spx_price': spx_price,
        'gex_pin': gex_pin_strike,
        'direction': direction,
        'side': side,
        'short_strike': short_strike,
        'long_strike': long_strike,
        'distance_otm': distance_otm,
        'spread_width': 10,
        'implied_vol': implied_vol * 100,  # Convert to percentage for display
        'hours_remaining': hours_remaining,
        'expected_move_1sd': calculate_expected_move(spx_price, implied_vol, hours_remaining),
        'strike_distance': strike_distance
    }


def check_otm_opportunity(spx_price, vix_level=None, get_quotes_func=None):
    """
    Main entry point - check if there's a valid OTM spread opportunity.

    Args:
        spx_price: Current SPX price
        vix_level: Current VIX level (optional)
        get_quotes_func: Function to get option quotes (short_strike, long_strike) -> credit
                        If None, will return strikes without validation

    Returns:
        dict with trade setup or None if no opportunity
    """
    # Find theoretical strikes
    strikes = find_otm_strikes(spx_price, vix_level)

    if not strikes:
        return None  # Time/window constraints not met

    # If no quote function provided, return strikes for manual validation
    if get_quotes_func is None:
        return {
            'valid': True,
            'strikes': strikes,
            'note': 'Strikes calculated, need real quotes to validate credits'
        }

    # Get real quotes
    call_credit = get_quotes_func(
        strikes['call_spread']['short'],
        strikes['call_spread']['long'],
        'call'
    )

    put_credit = get_quotes_func(
        strikes['put_spread']['short'],
        strikes['put_spread']['long'],
        'put'
    )

    # Evaluate if credits are acceptable
    return evaluate_spread_setup(strikes, call_credit, put_credit)


if __name__ == '__main__':
    # Test calculation
    test_spx = 6900
    test_vix = 12.5

    print(f"Testing OTM spread calculation for SPX={test_spx}, VIX={test_vix}")
    print()

    # Test the strike calculation directly (bypass time checks for testing)
    strikes = find_otm_strikes(test_spx, test_vix, skip_time_check=True)

    if strikes:
        print(f"✓ Strikes calculated successfully")
        print(f"  Hours remaining: {strikes['hours_remaining']:.1f}h")
        print(f"  Implied vol: {strikes['implied_vol']:.1f}%")
        print(f"  Expected 1SD move: ±{strikes['expected_move_1sd']:.0f} points")
        print(f"  Strike placement: {strikes['strike_distance']:.0f} points away (2.5 SD)")
        print()
        print(f"  Call spread: {strikes['call_spread']['short']}/{strikes['call_spread']['long']}")
        print(f"    Distance: {strikes['call_spread']['distance']:.0f} points above")
        print()
        print(f"  Put spread: {strikes['put_spread']['short']}/{strikes['put_spread']['long']}")
        print(f"    Distance: {strikes['put_spread']['distance']:.0f} points below")
        print()

        # Test with hypothetical credits
        print("Testing with hypothetical credits:")
        call_credit = 0.25
        put_credit = 0.22
        evaluation = evaluate_spread_setup(strikes, call_credit, put_credit)

        if evaluation:
            print(f"  ✓ Credits meet requirements")
            print(f"    Call credit: ${call_credit:.2f}")
            print(f"    Put credit: ${put_credit:.2f}")
            print(f"    Total credit: ${evaluation['total_credit']:.2f}")
            print(f"    Max profit per contract: ${evaluation['max_profit_per_contract']:.0f}")
            print(f"    Call distance: {evaluation['call_distance_sd']:.1f} SD")
            print(f"    Put distance: {evaluation['put_distance_sd']:.1f} SD")
    else:
        print("✗ No opportunity (outside trading hours)")

    print()
    print("Note: Time window check (10 AM - 2 PM ET) would be enforced in production")
