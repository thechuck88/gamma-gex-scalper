"""
GEX Pin Strategy Core - SINGLE SOURCE OF TRUTH

This module contains ALL trade setup logic for the GEX Pin scalping strategy.
Both live scalper and backtests MUST import from here to ensure consistency.

Usage:
    from core.gex_strategy import get_gex_trade_setup, GEXTradeSetup

Strategy Logic:
    - SPX above PIN → expect pullback → sell CALL spreads (bearish)
    - SPX below PIN → expect rally → sell PUT spreads (bullish)
    - SPX at PIN → expect pinning → sell Iron Condor (neutral)
"""

from dataclasses import dataclass
from typing import List, Optional


# ============================================================================
# MEDIUM FIX-1: GEX Strategy Configuration (extracted magic numbers)
# ============================================================================

# Distance thresholds (pts from GEX pin)
NEAR_PIN_MAX = 6           # 0-6pts: Iron Condor (symmetric, HIGH confidence)
MODERATE_DISTANCE_MIN = 7  # 7-15pts: Directional spread (HIGH confidence)
MODERATE_DISTANCE_MAX = 15
FAR_FROM_PIN_MIN = 16      # 16-50pts: Conservative spread (MEDIUM confidence)
FAR_FROM_PIN_MAX = 50      # FIX 2026-01-10: Increased from 25 to 50 (was rejecting all trades)
TOO_FAR_MIN = 51           # >50pts: Skip (too far from pin, LOW confidence)

# Strike buffer distances (pts from pin/SPX)
IC_WING_BUFFER = 20        # Iron Condor: Distance of wings from pin
MODERATE_PIN_BUFFER = 15   # Moderate distance: Buffer from pin
MODERATE_SPX_BUFFER = 8    # Moderate distance: Buffer from current SPX
FAR_PIN_BUFFER = 25        # Far distance: Buffer from pin (more conservative)
FAR_SPX_BUFFER = 12        # Far distance: Buffer from current SPX

# VIX thresholds for spread width
VIX_LEVEL_1 = 15           # VIX < 15: Use 5pt spreads
VIX_LEVEL_2 = 20           # VIX 15-20: Use 10pt spreads
VIX_LEVEL_3 = 25           # VIX 20-25: Use 15pt spreads
                           # VIX > 25: Use 20pt spreads


@dataclass
class GEXTradeSetup:
    """Result of GEX trade setup analysis"""
    strategy: str  # 'IC', 'CALL', 'PUT', 'SKIP'
    strikes: List[int]  # Strike prices for the spread
    direction: Optional[str]  # 'BULLISH', 'BEARISH', 'NEUTRAL', None
    distance: float  # SPX distance from PIN (positive = above)
    confidence: str  # 'HIGH', 'MEDIUM', 'LOW'
    description: str  # Human-readable description
    spread_width: int  # Width of the spread
    vix: float  # VIX level used


def round_to_5(price: float) -> int:
    """Round price to nearest 5-point increment for SPX options"""
    return round(price / 5) * 5


def get_spread_width(vix: float) -> int:
    """
    Determine spread width based on VIX level.
    Higher VIX = wider spreads for safety.
    """
    if vix < VIX_LEVEL_1:
        return 5
    elif vix < VIX_LEVEL_2:
        return 10
    elif vix < VIX_LEVEL_3:
        return 15
    else:
        return 20


def get_gex_trade_setup(pin_price: float, spx_price: float, vix: float,
                         vix_threshold: float = 20.0, index_symbol: str = 'SPX') -> GEXTradeSetup:
    """
    PURE FUNCTION: Determine trade setup based on GEX pin level.

    This is the SINGLE SOURCE OF TRUTH for trade setup logic.
    Both live scalper and backtests must use this function.

    Args:
        pin_price: GEX pin price level
        spx_price: Current price (SPX or NDX depending on index_symbol)
        vix: Current VIX level
        vix_threshold: Skip trading if VIX >= this level
        index_symbol: Index name ('SPX' or 'NDX') for logging purposes

    Returns:
        GEXTradeSetup with strategy details
    """
    pin_price = round(pin_price)
    spx_price = round(spx_price)
    distance = spx_price - pin_price
    abs_distance = abs(distance)
    spread_width = get_spread_width(vix)

    # HIGH-4 FIX (2026-01-13): Defensive check in case get_spread_width() is modified
    if spread_width <= 0:
        spread_width = 5  # Default fallback to 5pt SPX spread

    # INDEX-SPECIFIC TOLERANCE SCALING (2026-01-14)
    # NDX tolerances are 5× larger than SPX due to 10pt strike increment
    tolerance_scale = 5 if index_symbol == 'NDX' else 1
    near_pin_max = NEAR_PIN_MAX * tolerance_scale
    moderate_distance_max = MODERATE_DISTANCE_MAX * tolerance_scale
    far_from_pin_max = FAR_FROM_PIN_MAX * tolerance_scale
    too_far_min = TOO_FAR_MIN * tolerance_scale

    # INDEX-AWARE STRIKE ROUNDING (2026-01-14)
    # SPX: round to 5, NDX: round to 10
    strike_increment = 10 if index_symbol == 'NDX' else 5
    def round_to_increment(price: float) -> int:
        """Round price to nearest strike increment"""
        return round(price / strike_increment) * strike_increment

    # === VIX TOO HIGH: Skip ===
    if vix >= vix_threshold:
        return GEXTradeSetup(
            strategy='SKIP',
            strikes=[],
            direction=None,
            distance=distance,
            confidence='LOW',
            description=f'VIX {vix:.1f} too high (>={vix_threshold}), skip trading',
            spread_width=spread_width,
            vix=vix
        )

    # === NEAR PIN (0-6 pts for SPX, 0-30 pts for NDX): Iron Condor (symmetric wings) ===
    if abs_distance <= near_pin_max:
        ic_buffer = IC_WING_BUFFER * tolerance_scale
        call_short = round_to_increment(pin_price + ic_buffer)
        call_long = round_to_increment(call_short + spread_width)
        put_short = round_to_increment(pin_price - ic_buffer)
        put_long = round_to_increment(put_short - spread_width)

        return GEXTradeSetup(
            strategy='IC',
            strikes=[call_short, call_long, put_short, put_long],
            direction='NEUTRAL',
            distance=distance,
            confidence='HIGH',
            description=f'IC: {call_short}/{call_long}C + {put_short}/{put_long}P (symmetric {ic_buffer}pt wings)',
            spread_width=spread_width,
            vix=vix
        )

    # === MODERATE DISTANCE (7-15 pts for SPX, 35-75 pts for NDX): Directional spread (HIGH confidence) ===
    elif MODERATE_DISTANCE_MIN * tolerance_scale <= abs_distance <= moderate_distance_max:
        pin_buffer = MODERATE_PIN_BUFFER * tolerance_scale
        spx_buffer = MODERATE_SPX_BUFFER * tolerance_scale

        if distance > 0:  # SPX ABOVE pin → expect pullback → CALL spread
            pin_based = pin_price + pin_buffer
            spx_based = spx_price + spx_buffer
            short_strike = round_to_increment(max(pin_based, spx_based))
            long_strike = round_to_increment(short_strike + spread_width)

            return GEXTradeSetup(
                strategy='CALL',
                strikes=[short_strike, long_strike],
                direction='BEARISH',
                distance=distance,
                confidence='HIGH',
                description=f'Sell {short_strike}/{long_strike}C',
                spread_width=spread_width,
                vix=vix
            )
        else:  # SPX BELOW pin → expect rally → PUT spread
            pin_based = pin_price - pin_buffer
            spx_based = spx_price - spx_buffer
            short_strike = round_to_increment(min(pin_based, spx_based))
            long_strike = round_to_increment(short_strike - spread_width)

            return GEXTradeSetup(
                strategy='PUT',
                strikes=[short_strike, long_strike],
                direction='BULLISH',
                distance=distance,
                confidence='HIGH',
                description=f'Sell {short_strike}/{long_strike}P',
                spread_width=spread_width,
                vix=vix
            )

    # === FAR FROM PIN (16-50 pts for SPX, 80-250 pts for NDX): Conservative spread (MEDIUM confidence) ===
    elif FAR_FROM_PIN_MIN * tolerance_scale <= abs_distance <= far_from_pin_max:
        pin_buffer = FAR_PIN_BUFFER * tolerance_scale
        spx_buffer = FAR_SPX_BUFFER * tolerance_scale

        if distance > 0:  # SPX ABOVE pin → CALL spread
            pin_based = pin_price + pin_buffer
            spx_based = spx_price + spx_buffer
            short_strike = round_to_increment(max(pin_based, spx_based))
            long_strike = round_to_increment(short_strike + spread_width)

            return GEXTradeSetup(
                strategy='CALL',
                strikes=[short_strike, long_strike],
                direction='BEARISH',
                distance=distance,
                confidence='MEDIUM',
                description=f'Sell {short_strike}/{long_strike}C (conservative)',
                spread_width=spread_width,
                vix=vix
            )
        else:  # SPX BELOW pin → PUT spread
            pin_based = pin_price - pin_buffer
            spx_based = spx_price - spx_buffer
            short_strike = round_to_increment(min(pin_based, spx_based))
            long_strike = round_to_increment(short_strike - spread_width)

            return GEXTradeSetup(
                strategy='PUT',
                strikes=[short_strike, long_strike],
                direction='BULLISH',
                distance=distance,
                confidence='MEDIUM',
                description=f'Sell {short_strike}/{long_strike}P (conservative)',
                spread_width=spread_width,
                vix=vix
            )

    # === TOO FAR (>50 pts for SPX, >250 pts for NDX): Skip ===
    else:
        return GEXTradeSetup(
            strategy='SKIP',
            strikes=[],
            direction=None,
            distance=distance,
            confidence='LOW',
            description=f'{index_symbol} {abs_distance:.0f}pts from pin — too far, skip (limit: {far_from_pin_max}pts)',
            spread_width=spread_width,
            vix=vix
        )


def get_trade_setup_dict(pin_price: float, spx_price: float, vix: float,
                          vix_threshold: float = 20.0) -> dict:
    """
    Get trade setup as dictionary (for backwards compatibility).

    Returns dict matching original function signature.
    """
    setup = get_gex_trade_setup(pin_price, spx_price, vix, vix_threshold)
    return {
        'strategy': setup.strategy,
        'strikes': setup.strikes,
        'direction': setup.direction,
        'distance': setup.distance,
        'confidence': setup.confidence,
        'description': setup.description
    }


# Quick test
if __name__ == "__main__":
    print("GEX Strategy Core Test")
    print("=" * 50)

    # Test cases
    test_cases = [
        (6050, 6050, 15),   # At pin
        (6050, 6060, 15),   # 10pts above
        (6050, 6040, 15),   # 10pts below
        (6050, 6070, 15),   # 20pts above
        (6050, 6010, 25),   # High VIX
    ]

    for pin, spx, vix in test_cases:
        setup = get_gex_trade_setup(pin, spx, vix)
        print(f"\nPIN={pin} SPX={spx} VIX={vix}")
        print(f"  Strategy: {setup.strategy}")
        print(f"  Direction: {setup.direction}")
        print(f"  Confidence: {setup.confidence}")
        print(f"  {setup.description}")
