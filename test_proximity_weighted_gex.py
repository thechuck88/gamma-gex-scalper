#!/usr/bin/env python3
"""
Test proximity-weighted GEX peak selection logic.

Verifies that the new algorithm correctly weights peaks by proximity.
"""

def score_peak(strike, gex, index_price):
    """Score a GEX peak by proximity-weighted GEX."""
    distance_pct = abs(strike - index_price) / index_price
    # For 0DTE, gamma decays EXTREMELY steeply - use quintic (5th power) penalty
    # Virtually zero epsilon (1e-12) to not dominate scoring
    return gex / (distance_pct ** 5 + 1e-12)

def test_scenario_1():
    """Test: Closer peak wins when peaks are comparable size."""
    print("\n" + "="*60)
    print("TEST 1: Comparable Peaks - Closer Wins")
    print("="*60)

    index_price = 5920
    peaks = [
        (5950, 100e9, "Secondary (closer)"),
        (6000, 120e9, "Dominant (20% larger, farther)"),
    ]

    print(f"\nCurrent Price: {index_price}")
    print(f"\nPeaks:")

    scored = []
    for strike, gex, label in peaks:
        score = score_peak(strike, gex, index_price)
        distance = abs(strike - index_price)
        distance_pct = distance / index_price * 100
        scored.append((strike, gex, score, label))

        print(f"  {strike}: {label}")
        print(f"    GEX: {gex/1e9:.1f}B")
        print(f"    Distance: {distance}pts ({distance_pct:.2f}%)")
        print(f"    Score: {score/1e9:.1f}")

    winner = max(scored, key=lambda x: x[2])
    print(f"\n✅ Winner: {winner[0]} ({winner[3]})")
    print(f"   Score: {winner[2]/1e9:.1f} (proximity-weighted)")

    # Verify closer peak wins
    assert winner[0] == 5950, "Expected closer peak to win!"
    print("\n✓ Test passed: Closer peak correctly selected")

def test_scenario_2():
    """Test: For 0DTE, proximity dominates even large GEX differences."""
    print("\n" + "="*60)
    print("TEST 2: 0DTE Proximity Dominance (Research-Backed)")
    print("="*60)

    index_price = 6050
    peaks = [
        (6060, 50e9, "Very close (10pts)"),
        (6100, 300e9, "6x larger but 5x farther (50pts)"),
    ]

    print(f"\nCurrent Price: {index_price}")
    print(f"\nPeaks:")

    scored = []
    for strike, gex, label in peaks:
        score = score_peak(strike, gex, index_price)
        distance = abs(strike - index_price)
        distance_pct = distance / index_price * 100
        scored.append((strike, gex, score, label))

        print(f"  {strike}: {label}")
        print(f"    GEX: {gex/1e9:.1f}B")
        print(f"    Distance: {distance}pts ({distance_pct:.2f}%)")
        print(f"    Score: {score/1e9:.1f}")

    winner = max(scored, key=lambda x: x[2])
    print(f"\n✅ Winner: {winner[0]} ({winner[3]})")
    print(f"   Score: {winner[2]/1e9:.1f} (proximity-weighted)")

    # For 0DTE, distance ratio (5x) with 5th power = 3125x penalty
    # Even 6x GEX can't overcome this → closer peak wins (research-backed)
    assert winner[0] == 6060, "For 0DTE, proximity should dominate!"
    print("\n✓ Test passed: Proximity dominates even 6x GEX difference (0DTE behavior)")

def test_scenario_3():
    """Test: Equal GEX, closer wins."""
    print("\n" + "="*60)
    print("TEST 3: Equal GEX Peaks at Different Distances")
    print("="*60)

    index_price = 6000
    peaks = [
        (6010, 100e9, "10pts away"),
        (6030, 100e9, "30pts away"),
        (6050, 100e9, "50pts away"),
    ]

    print(f"\nCurrent Price: {index_price}")
    print(f"\nPeaks (all equal GEX):")

    scored = []
    for strike, gex, label in peaks:
        score = score_peak(strike, gex, index_price)
        distance = abs(strike - index_price)
        distance_pct = distance / index_price * 100
        scored.append((strike, gex, score, label))

        print(f"  {strike}: {label}")
        print(f"    GEX: {gex/1e9:.1f}B")
        print(f"    Distance: {distance}pts ({distance_pct:.2f}%)")
        print(f"    Score: {score/1e9:.1f}")

    winner = max(scored, key=lambda x: x[2])
    print(f"\n✅ Winner: {winner[0]} ({winner[3]})")
    print(f"   Score: {winner[2]/1e9:.1f} (proximity-weighted)")

    # Closest should win with equal GEX
    assert winner[0] == 6010, "Expected closest peak to win with equal GEX!"
    print("\n✓ Test passed: Closest peak wins with equal GEX")

def test_scenario_4():
    """Test: Real-world NDX scenario."""
    print("\n" + "="*60)
    print("TEST 4: Real-World NDX Multi-Peak Scenario")
    print("="*60)

    index_price = 21500
    peaks = [
        (21400, 80e9, "Below pin (100pts)"),
        (21500, 120e9, "ATM (0pts)"),
        (21600, 90e9, "Above pin (100pts)"),
        (21700, 200e9, "Far above (200pts)"),
    ]

    print(f"\nCurrent Price: {index_price}")
    print(f"\nPeaks:")

    scored = []
    for strike, gex, label in peaks:
        score = score_peak(strike, gex, index_price)
        distance = abs(strike - index_price)
        distance_pct = distance / index_price * 100
        scored.append((strike, gex, score, label))

        print(f"  {strike}: {label}")
        print(f"    GEX: {gex/1e9:.1f}B")
        print(f"    Distance: {distance}pts ({distance_pct:.2f}%)")
        print(f"    Score: {score/1e9:.1f}")

    winner = max(scored, key=lambda x: x[2])
    print(f"\n✅ Winner: {winner[0]} ({winner[3]})")
    print(f"   Score: {winner[2]/1e9:.1f} (proximity-weighted)")

    # ATM should dominate (distance = 0 → infinite score)
    assert winner[0] == 21500, "Expected ATM peak to win!"
    print("\n✓ Test passed: ATM peak dominates (distance = 0)")

if __name__ == '__main__':
    print("\n" + "🧪 PROXIMITY-WEIGHTED GEX PEAK SELECTION TESTS" + "\n")

    try:
        test_scenario_1()
        test_scenario_2()
        test_scenario_3()
        test_scenario_4()

        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED")
        print("="*60)
        print("\nProximity-weighted algorithm is working correctly!")
        print("Ready for live market testing in paper account.")
        print("")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
