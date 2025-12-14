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
    if vix < 15:
        return 5
    elif vix < 20:
        return 10
    elif vix < 25:
        return 15
    else:
        return 20


def get_gex_trade_setup(pin_price: float, spx_price: float, vix: float,
                         vix_threshold: float = 20.0) -> GEXTradeSetup:
    """
    PURE FUNCTION: Determine trade setup based on GEX pin level.

    This is the SINGLE SOURCE OF TRUTH for trade setup logic.
    Both live scalper and backtests must use this function.

    Args:
        pin_price: GEX pin price level
        spx_price: Current SPX price
        vix: Current VIX level
        vix_threshold: Skip trading if VIX >= this level

    Returns:
        GEXTradeSetup with strategy details
    """
    pin_price = round(pin_price)
    spx_price = round(spx_price)
    distance = spx_price - pin_price
    abs_distance = abs(distance)
    spread_width = get_spread_width(vix)

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

    # === NEAR PIN (0-6 pts): Iron Condor (symmetric wings) ===
    if abs_distance <= 6:
        ic_buffer = 20
        call_short = round_to_5(pin_price + ic_buffer)
        call_long = round_to_5(call_short + spread_width)
        put_short = round_to_5(pin_price - ic_buffer)
        put_long = round_to_5(put_short - spread_width)

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

    # === MODERATE DISTANCE (7-15 pts): Directional spread (HIGH confidence) ===
    elif 7 <= abs_distance <= 15:
        pin_buffer = 15
        spx_buffer = 8

        if distance > 0:  # SPX ABOVE pin → expect pullback → CALL spread
            pin_based = pin_price + pin_buffer
            spx_based = spx_price + spx_buffer
            short_strike = round_to_5(max(pin_based, spx_based))
            long_strike = round_to_5(short_strike + spread_width)

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
            short_strike = round_to_5(min(pin_based, spx_based))
            long_strike = round_to_5(short_strike - spread_width)

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

    # === FAR FROM PIN (16-25 pts): Conservative spread (MEDIUM confidence) ===
    elif 16 <= abs_distance <= 25:
        pin_buffer = 25
        spx_buffer = 12

        if distance > 0:  # SPX ABOVE pin → CALL spread
            pin_based = pin_price + pin_buffer
            spx_based = spx_price + spx_buffer
            short_strike = round_to_5(max(pin_based, spx_based))
            long_strike = round_to_5(short_strike + spread_width)

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
            short_strike = round_to_5(min(pin_based, spx_based))
            long_strike = round_to_5(short_strike - spread_width)

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

    # === TOO FAR (>25 pts): Skip ===
    else:
        return GEXTradeSetup(
            strategy='SKIP',
            strikes=[],
            direction=None,
            distance=distance,
            confidence='LOW',
            description=f'SPX {abs_distance:.0f}pts from pin — too far, skip',
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
