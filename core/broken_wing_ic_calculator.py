#!/usr/bin/env python3
"""
Broken Wing Iron Condor (BWIC) Calculator

Module for calculating asymmetric wing widths based on GEX polarity.
Used by gex_strategy.py to generate BWIC strikes when GEX shows directional bias.

Author: Claude (2026-01-14)
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional


@dataclass
class GEXPolarityResult:
    """Result of GEX polarity analysis"""
    gpi: float                          # GEX Polarity Index (-1 to +1)
    direction: str                      # 'BULL', 'BEAR', 'NEUTRAL'
    positive_gex_total: float          # Sum of positive GEX
    negative_gex_total: float          # Sum of negative GEX
    magnitude: float                   # Combined GEX magnitude
    confidence: str                    # 'HIGH', 'MEDIUM', 'LOW'
    reasoning: str                     # Human-readable explanation


@dataclass
class BWICWingWidths:
    """BWIC wing width calculation result"""
    call_width: int                    # Call spread width (points)
    put_width: int                     # Put spread width (points)
    narrow_side: str                   # 'CALL' or 'PUT'
    wide_side: str                     # 'CALL' or 'PUT'
    is_bwic: bool                      # True if asymmetric, False if symmetric
    rationale: str                     # Why these widths chosen


class BrokenWingICCalculator:
    """
    Calculate asymmetric wing widths for BWIC strategy.

    Single source of truth for BWIC logic.
    """

    # ========================================================================
    # Configuration Constants
    # ========================================================================

    # GEX Polarity thresholds
    GPI_THRESHOLD = 0.20                # |GPI| > this triggers BWIC
    GEX_MAGNITUDE_MIN = 5e9             # Minimum 5B GEX for confidence
    GEX_MAGNITUDE_STRONG = 15e9         # 15B+ = HIGH confidence

    # Offset multiplier for wing asymmetry
    # offset = base_width * OFFSET_MULT * |GPI|
    # Example: 10pt base * 0.5 * 0.5 GPI = 2.5pt offset
    OFFSET_MULTIPLIER = 0.5             # 0-50% adjustment from base width

    # Minimum wing widths (safety constraint)
    MIN_WING_WIDTH = 2                  # Don't narrow below 2-3 pts
    MAX_WING_RATIO = 2.0                # Don't make wide wing > 2× narrow wing

    # ========================================================================
    # Core Methods
    # ========================================================================

    @staticmethod
    def calculate_gex_polarity(gex_peaks: List[Tuple[float, float]]) -> GEXPolarityResult:
        """
        Calculate GEX Polarity Index from options peaks.

        Args:
            gex_peaks: List of (strike, gex_value) tuples
                       Can have positive or negative GEX values

        Returns:
            GEXPolarityResult with polarity metrics
        """
        if not gex_peaks:
            return GEXPolarityResult(
                gpi=0.0,
                direction='NEUTRAL',
                positive_gex_total=0,
                negative_gex_total=0,
                magnitude=0,
                confidence='LOW',
                reasoning='No GEX peaks provided'
            )

        # Separate positive and negative GEX
        positive_gex = sum(max(0, g) for _, g in gex_peaks)
        negative_gex = abs(sum(min(0, g) for _, g in gex_peaks))

        total = positive_gex + negative_gex

        # Calculate polarity
        if total == 0:
            gpi = 0.0
            direction = 'NEUTRAL'
            confidence = 'LOW'
            magnitude = 0
        else:
            gpi = (positive_gex - negative_gex) / total
            magnitude = total / len(gex_peaks)  # Average magnitude

            # Classify direction
            if gpi > 0.2:
                direction = 'BULL'
            elif gpi < -0.2:
                direction = 'BEAR'
            else:
                direction = 'NEUTRAL'

            # Confidence based on magnitude and polarity strength
            if magnitude > BrokenWingICCalculator.GEX_MAGNITUDE_STRONG and abs(gpi) > 0.5:
                confidence = 'HIGH'
            elif magnitude > BrokenWingICCalculator.GEX_MAGNITUDE_MIN and abs(gpi) > 0.2:
                confidence = 'MEDIUM'
            else:
                confidence = 'LOW'

        reasoning = f"{direction} ({gpi:+.2f}), magnitude={magnitude/1e9:.1f}B"

        return GEXPolarityResult(
            gpi=gpi,
            direction=direction,
            positive_gex_total=positive_gex,
            negative_gex_total=negative_gex,
            magnitude=magnitude,
            confidence=confidence,
            reasoning=reasoning
        )

    @staticmethod
    def get_bwic_wing_widths(
        gpi: float,
        vix: float,
        gex_magnitude: float = 0,
        use_bwic: bool = True,
        base_width: Optional[int] = None
    ) -> BWICWingWidths:
        """
        Determine call and put wing widths based on GEX polarity.

        Args:
            gpi: GEX Polarity Index (-1 to +1)
            vix: VIX level
            gex_magnitude: Optional GEX magnitude (for logging)
            use_bwic: If False, always return equal wings
            base_width: Override base width (for testing). If None, calculate from VIX

        Returns:
            BWICWingWidths with call/put widths and explanation
        """

        # Determine base width from VIX (if not overridden)
        if base_width is None:
            if vix < 15:
                base_width = 5
            elif vix < 20:
                base_width = 10
            elif vix < 25:
                base_width = 15
            else:
                base_width = 20

        # If BWIC disabled or GEX ambiguous, use symmetric wings
        if not use_bwic or abs(gpi) < BrokenWingICCalculator.GPI_THRESHOLD:
            return BWICWingWidths(
                call_width=base_width,
                put_width=base_width,
                narrow_side='NONE',
                wide_side='NONE',
                is_bwic=False,
                rationale=f"Symmetric IC: GEX polarity {gpi:+.2f} below threshold {BrokenWingICCalculator.GPI_THRESHOLD}"
            )

        # Calculate asymmetric widths
        offset = base_width * BrokenWingICCalculator.OFFSET_MULTIPLIER * abs(gpi)
        offset = max(1, int(offset))  # At least 1 pt offset

        narrow_width = max(
            BrokenWingICCalculator.MIN_WING_WIDTH,
            base_width - offset
        )
        wide_width = base_width + offset

        # Safety check: don't make ratio too extreme
        if wide_width > narrow_width * BrokenWingICCalculator.MAX_WING_RATIO:
            wide_width = narrow_width * int(BrokenWingICCalculator.MAX_WING_RATIO)

        # Determine which side is narrow/wide based on GPI direction
        if gpi > 0.2:
            # Bullish GEX → narrow calls, wide puts
            call_width = narrow_width
            put_width = wide_width
            narrow_side = 'CALL'
            wide_side = 'PUT'
            rationale = f"Bullish BWIC (GPI={gpi:+.2f}): narrow calls {call_width}pt (rally expected), wide puts {put_width}pt (downside protection)"
        else:
            # Bearish GEX (gpi < -0.2) → wide calls, narrow puts
            call_width = wide_width
            put_width = narrow_width
            narrow_side = 'PUT'
            wide_side = 'CALL'
            rationale = f"Bearish BWIC (GPI={gpi:+.2f}): wide calls {call_width}pt (upside cushion), narrow puts {put_width}pt (pullback expected)"

        return BWICWingWidths(
            call_width=call_width,
            put_width=put_width,
            narrow_side=narrow_side,
            wide_side=wide_side,
            is_bwic=True,
            rationale=rationale
        )

    @staticmethod
    def should_use_bwic(
        gex_magnitude: float,
        gpi: float,
        has_competing_peaks: bool = False,
        vix: float = 0,
        distance_from_pin: float = 0
    ) -> Tuple[bool, str]:
        """
        Determine if BWIC should be used for this trade.

        Args:
            gex_magnitude: Total GEX magnitude
            gpi: GEX Polarity Index
            has_competing_peaks: If True, peaks are competing (ambiguous)
            vix: VIX level (disable if extreme)
            distance_from_pin: Distance from PIN (disable if far)

        Returns:
            (should_use_bwic, reason)
        """

        # Check each condition
        if not (abs(gpi) >= BrokenWingICCalculator.GPI_THRESHOLD):
            return False, f"GEX polarity {gpi:+.2f} below threshold {BrokenWingICCalculator.GPI_THRESHOLD}"

        if gex_magnitude < BrokenWingICCalculator.GEX_MAGNITUDE_MIN:
            return False, f"GEX magnitude {gex_magnitude/1e9:.1f}B < minimum {BrokenWingICCalculator.GEX_MAGNITUDE_MIN/1e9:.1f}B"

        if has_competing_peaks:
            return False, "Competing peaks detected (ambiguous direction)"

        if vix > 25:
            return False, f"VIX {vix:.1f} > 25 (extreme volatility)"

        if distance_from_pin > 10:
            return False, f"Distance {distance_from_pin:.1f}pts > 10pt threshold (weak edge)"

        return True, "BWIC conditions met"

    @staticmethod
    def calculate_max_risk(
        call_short: float,
        call_long: float,
        put_short: float,
        put_long: float,
        contracts: int = 1,
        point_value: float = 100
    ) -> float:
        """
        Calculate maximum risk for BWIC position.

        Args:
            call_short, call_long, put_short, put_long: Strike prices
            contracts: Number of contracts
            point_value: Dollar value per point (SPX=100, NDX=20)

        Returns:
            Maximum potential loss in dollars
        """
        call_width = call_long - call_short
        put_width = put_short - put_long  # put_long < put_short

        # Max risk = max of (call width, put width) × contracts × point value
        max_width = max(call_width, put_width)
        max_risk = max_width * contracts * point_value

        return max_risk

    @staticmethod
    def validate_bwic_strikes(
        call_short: float,
        call_long: float,
        put_short: float,
        put_long: float,
        current_price: float,
        is_bwic: bool = True
    ) -> Tuple[bool, str]:
        """
        Validate BWIC strikes for validity.

        Args:
            call_short, call_long, put_short, put_long: Strike prices
            current_price: Current index price
            is_bwic: If True, check asymmetric constraints

        Returns:
            (is_valid, reason)
        """
        # Basic validation
        if call_short >= call_long:
            return False, f"Call spread invalid: short {call_short} >= long {call_long}"

        if put_short <= put_long:
            return False, f"Put spread invalid: short {put_short} <= long {put_long}"

        # Check OTM status
        if call_short <= current_price:
            return False, f"Call short strike {call_short} at or ITM (current {current_price})"

        if put_short >= current_price:
            return False, f"Put short strike {put_short} at or ITM (current {current_price})"

        # BWIC-specific: check wing width ratio
        if is_bwic:
            call_width = call_long - call_short
            put_width = put_short - put_long

            ratio = max(call_width, put_width) / min(call_width, put_width)
            if ratio > BrokenWingICCalculator.MAX_WING_RATIO:
                return False, f"Wing ratio {ratio:.1f} exceeds maximum {BrokenWingICCalculator.MAX_WING_RATIO}"

        return True, "Valid strikes"


# ============================================================================
# Quick Test
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("Broken Wing IC Calculator — Test Suite")
    print("=" * 70)

    # Test 1: Bullish GEX
    print("\n[Test 1] Bullish GEX Polarity")
    gex_peaks_bull = [
        (6050, +15.2e9),   # Strong call wall
        (6075, +8.5e9),    # Weaker call wall
        (6025, -12.1e9),   # Put wall
    ]
    polarity = BrokenWingICCalculator.calculate_gex_polarity(gex_peaks_bull)
    print(f"  GPI: {polarity.gpi:+.3f}")
    print(f"  Direction: {polarity.direction}")
    print(f"  Magnitude: {polarity.magnitude / 1e9:.1f}B")
    print(f"  Confidence: {polarity.confidence}")

    widths = BrokenWingICCalculator.get_bwic_wing_widths(
        polarity.gpi, vix=18, use_bwic=True
    )
    print(f"  Call width: {widths.call_width}pt (narrow)")
    print(f"  Put width: {widths.put_width}pt (wide)")
    print(f"  {widths.rationale}")

    # Test 2: Bearish GEX
    print("\n[Test 2] Bearish GEX Polarity")
    gex_peaks_bear = [
        (6050, -18.3e9),   # Strong put wall
        (6025, -10.2e9),   # Weaker put wall
        (6075, +5.0e9),    # Call wall
    ]
    polarity = BrokenWingICCalculator.calculate_gex_polarity(gex_peaks_bear)
    print(f"  GPI: {polarity.gpi:+.3f}")
    print(f"  Direction: {polarity.direction}")
    print(f"  Magnitude: {polarity.magnitude / 1e9:.1f}B")
    print(f"  Confidence: {polarity.confidence}")

    widths = BrokenWingICCalculator.get_bwic_wing_widths(
        polarity.gpi, vix=18, use_bwic=True
    )
    print(f"  Call width: {widths.call_width}pt (wide)")
    print(f"  Put width: {widths.put_width}pt (narrow)")
    print(f"  {widths.rationale}")

    # Test 3: Neutral GEX
    print("\n[Test 3] Neutral GEX Polarity")
    gex_peaks_neutral = [
        (6050, +10.0e9),
        (6025, -10.0e9),
    ]
    polarity = BrokenWingICCalculator.calculate_gex_polarity(gex_peaks_neutral)
    print(f"  GPI: {polarity.gpi:+.3f}")
    print(f"  Direction: {polarity.direction}")

    widths = BrokenWingICCalculator.get_bwic_wing_widths(
        polarity.gpi, vix=18, use_bwic=True
    )
    print(f"  Call width: {widths.call_width}pt")
    print(f"  Put width: {widths.put_width}pt")
    print(f"  Is BWIC: {widths.is_bwic}")
    print(f"  {widths.rationale}")

    # Test 4: BWIC Decision Logic
    print("\n[Test 4] BWIC Decision Logic")
    should_use, reason = BrokenWingICCalculator.should_use_bwic(
        gex_magnitude=15e9, gpi=+0.45, has_competing_peaks=False, vix=18
    )
    print(f"  Should use BWIC: {should_use}")
    print(f"  Reason: {reason}")

    should_use, reason = BrokenWingICCalculator.should_use_bwic(
        gex_magnitude=2e9, gpi=+0.45, has_competing_peaks=False, vix=18
    )
    print(f"  Should use BWIC (weak GEX): {should_use}")
    print(f"  Reason: {reason}")

    # Test 5: Max Risk Calculation
    print("\n[Test 5] Max Risk Calculation")
    risk = BrokenWingICCalculator.calculate_max_risk(
        call_short=6070, call_long=6078,
        put_short=6030, put_long=6038,
        contracts=1, point_value=100
    )
    print(f"  Max risk: ${risk:.0f}")

    print("\n" + "=" * 70)
    print("All tests complete")
    print("=" * 70)
