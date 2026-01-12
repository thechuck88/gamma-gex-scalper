#!/usr/bin/env python3
"""
Implement competing peaks detection → Iron Condor logic

Add to scalper.py after proximity-weighted peak selection
"""

def detect_competing_peaks_and_adjust_pin(scored_peaks, index_price):
    """
    Detect when price is between two competing gamma walls.
    Return adjusted pin price for Iron Condor setup.

    Args:
        scored_peaks: List of (strike, gex, score) tuples (already sorted)
        index_price: Current index price

    Returns:
        (pin_price, is_competing_peaks) tuple
        - If competing: Returns midpoint for IC, True
        - If not competing: Returns top peak, False
    """
    if len(scored_peaks) < 2:
        # Only one peak - no competition
        return scored_peaks[0][0], False

    # Get top 2 peaks
    peak1_strike, peak1_gex, peak1_score = scored_peaks[0]
    peak2_strike, peak2_gex, peak2_score = scored_peaks[1]

    # Check if peaks are competing:
    # 1. Comparable score (within 2x of each other) → similar magnetic pull strength
    # 2. On opposite sides of current price → opposing forces
    score_ratio = min(peak1_score, peak2_score) / max(peak1_score, peak2_score)
    opposite_sides = (peak1_strike < index_price < peak2_strike) or \
                     (peak2_strike < index_price < peak1_strike)

    # Additional check: Price should be somewhat centered between peaks
    # Not too close to one edge (would indicate clear bias toward one peak)
    distance1 = abs(peak1_strike - index_price)
    distance2 = abs(peak2_strike - index_price)
    distance_ratio = min(distance1, distance2) / max(distance1, distance2)
    reasonably_centered = distance_ratio > 0.4  # Within 40% of being equidistant

    if score_ratio > 0.5 and opposite_sides and reasonably_centered:
        # COMPETING PEAKS DETECTED
        log(f"⚠️  COMPETING PEAKS DETECTED:")
        log(f"   Peak 1: {peak1_strike} ({peak1_gex/1e9:.1f}B GEX, {distance1:.0f}pts away)")
        log(f"   Peak 2: {peak2_strike} ({peak2_gex/1e9:.1f}B GEX, {distance2:.0f}pts away)")
        log(f"   Score ratio: {score_ratio:.2f} (comparable strength)")
        log(f"   Price between peaks → IC strategy (profit from cage)")

        # Return midpoint for IC setup
        midpoint = (peak1_strike + peak2_strike) / 2
        midpoint_rounded = round_to_5(midpoint)

        return midpoint_rounded, True
    else:
        # No competition - use top peak
        return peak1_strike, False


# ===== USAGE IN SCALPER.PY =====
# Insert after line 606 (after proximity-weighted scoring)

# Old code (line 593-607):
"""
scored_peaks = [(s, g, score_peak(s, g)) for s, g in nearby_peaks]
pin_strike, pin_gex, pin_score = max(scored_peaks, key=lambda x: x[2])

distance = abs(pin_strike - index_price)
distance_pct = distance / index_price * 100
log(f"GEX PIN (proximity-weighted): {pin_strike} (GEX={pin_gex/1e9:.1f}B, {distance_pct:.2f}% away)")

# Log top 3 scored peaks for debugging multi-peak scenarios
sorted_scored = sorted(scored_peaks, key=lambda x: x[2], reverse=True)[:3]
log(f"Top 3 proximity-weighted peaks:")
for s, g, score in sorted_scored:
    dist = abs(s - index_price)
    dist_pct = dist / index_price * 100
    log(f"  {s}: GEX={g/1e9:+.1f}B, dist={dist:.0f}pts ({dist_pct:.2f}%), score={score/1e9:.1f}")

return pin_strike
"""

# New code (with competing peaks detection):
"""
scored_peaks = [(s, g, score_peak(s, g)) for s, g in nearby_peaks]

# Log top 3 scored peaks BEFORE adjustment
sorted_scored = sorted(scored_peaks, key=lambda x: x[2], reverse=True)[:3]
log(f"Top 3 proximity-weighted peaks:")
for s, g, score in sorted_scored:
    dist = abs(s - index_price)
    dist_pct = dist / index_price * 100
    log(f"  {s}: GEX={g/1e9:+.1f}B, dist={dist:.0f}pts ({dist_pct:.2f}%), score={score/1e9:.1f}")

# Detect competing peaks and adjust pin if needed
pin_strike, is_competing = detect_competing_peaks_and_adjust_pin(sorted_scored, index_price)

if is_competing:
    # Find GEX at adjusted pin (for logging)
    pin_gex = sum(g for s, g, _ in sorted_scored[:2]) / 2  # Average of top 2
    distance = abs(pin_strike - index_price)
    distance_pct = distance / index_price * 100
    log(f"GEX PIN (adjusted for competing peaks): {pin_strike}")
    log(f"  Midpoint between competing walls → IC strategy")
else:
    # Use top peak (normal case)
    pin_strike, pin_gex, pin_score = sorted_scored[0]
    distance = abs(pin_strike - index_price)
    distance_pct = distance / index_price * 100
    log(f"GEX PIN (proximity-weighted): {pin_strike} (GEX={pin_gex/1e9:.1f}B, {distance_pct:.2f}% away)")

return pin_strike
"""

# ===== EFFECT ON TRADE SETUP =====
# When is_competing=True and pin is midpoint:
# - Distance from pin will be small (5-25pts typically)
# - Will trigger IC strategy in get_gex_trade_setup()
# - Wings will be placed around both peaks → profit from cage

print("""
Implementation plan:
1. Add detect_competing_peaks_and_adjust_pin() to scalper.py
2. Replace pin selection logic (lines 593-607)
3. Test with between-peaks scenarios
4. Deploy to paper for validation

Expected impact:
- Fewer directional losses on between-peaks days
- More ICs on caged volatility days
- Higher win rate on multi-peak scenarios
""")
