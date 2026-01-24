#!/usr/bin/env python3
"""
Universal Strike Conflict Detection

Prevents overlapping positions across ALL strategies (GEX, OTM, future strategies).

Critical safety checks:
1. Exact strike match (buying and selling same strike)
2. Range overlap (spreads that overlap)
3. Too close together (correlated risk)

Usage:
    conflict = check_strike_conflicts(new_setup, all_open_positions)
    if conflict['has_conflict']:
        # Skip trade
    else:
        # Safe to enter
"""

from typing import List, Dict, Optional


# Minimum distance between positions (in points)
MIN_DISTANCE_SAME_STRATEGY = 20  # GEX-to-GEX or OTM-to-OTM
MIN_DISTANCE_DIFF_STRATEGY = 15  # GEX-to-OTM


def check_strike_conflicts(new_setup: Dict, existing_positions: List[Dict]) -> Dict:
    """
    Universal strike conflict detection.

    Checks new trade against ALL existing positions regardless of strategy.

    Args:
        new_setup: {
            'strategy': 'GEX' or 'OTM',
            'short_strike': int,
            'long_strike': int,
            'side': 'CALL' or 'PUT'
        }
        existing_positions: List of all open positions (any strategy)

    Returns:
        {
            'has_conflict': bool,
            'conflict_type': 'exact_strike_match' | 'range_overlap' | 'too_close' | None,
            'conflicting_position': dict or None,
            'detail': str
        }
    """

    new_short = new_setup['short_strike']
    new_long = new_setup['long_strike']
    new_side = new_setup['side']
    new_strategy = new_setup.get('strategy', 'UNKNOWN')

    for pos in existing_positions:
        # Skip closed positions
        if pos.get('status') not in ['open', 'pending']:
            continue

        pos_short = pos['short_strike']
        pos_long = pos['long_strike']
        pos_side = pos['side']
        pos_strategy = pos.get('strategy', 'UNKNOWN')

        # Different option types (CALL vs PUT) = no conflict possible
        if pos_side != new_side:
            continue

        # Check 1: Exact strike match (CATASTROPHIC)
        # This catches:
        # - Same strikes (6915/6920 vs 6915/6920)
        # - Opposite positions (long 6920 in one, short 6920 in other)
        exact_match = (
            new_short == pos_short or
            new_short == pos_long or
            new_long == pos_short or
            new_long == pos_long
        )

        if exact_match:
            return {
                'has_conflict': True,
                'conflict_type': 'exact_strike_match',
                'conflicting_position': pos,
                'detail': (
                    f"New {new_strategy} {new_side} {new_short}/{new_long} "
                    f"has exact strike match with existing "
                    f"{pos_strategy} {pos_side} {pos_short}/{pos_long}"
                )
            }

        # Check 2: Range overlap (DANGEROUS)
        # Example: 6910-6915 overlaps with 6905-6925
        new_min = min(new_short, new_long)
        new_max = max(new_short, new_long)
        pos_min = min(pos_short, pos_long)
        pos_max = max(pos_short, pos_long)

        range_overlap = (new_min <= pos_max and new_max >= pos_min)

        if range_overlap:
            return {
                'has_conflict': True,
                'conflict_type': 'range_overlap',
                'conflicting_position': pos,
                'detail': (
                    f"New {new_strategy} range {new_min}-{new_max} "
                    f"overlaps with existing {pos_strategy} "
                    f"range {pos_min}-{pos_max}"
                )
            }

        # Check 3: Too close (RISKY - especially for same strategy)
        new_center = (new_short + new_long) / 2
        pos_center = (pos_short + pos_long) / 2
        distance = abs(new_center - pos_center)

        # Stricter distance requirement if same strategy
        if new_strategy == pos_strategy:
            min_required = MIN_DISTANCE_SAME_STRATEGY
        else:
            min_required = MIN_DISTANCE_DIFF_STRATEGY

        if distance < min_required:
            return {
                'has_conflict': True,
                'conflict_type': 'too_close',
                'conflicting_position': pos,
                'detail': (
                    f"New {new_strategy} center {new_center:.0f} "
                    f"too close to existing {pos_strategy} "
                    f"center {pos_center:.0f} "
                    f"(distance: {distance:.0f}, min: {min_required})"
                )
            }

    # No conflicts detected
    return {
        'has_conflict': False,
        'conflict_type': None,
        'conflicting_position': None,
        'detail': 'No conflicts detected'
    }


def get_position_summary(position: Dict) -> str:
    """Get human-readable position summary."""
    strategy = position.get('strategy', 'UNKNOWN')
    side = position['side']
    short = position['short_strike']
    long = position['long_strike']
    contracts = position.get('contracts', 1)

    return f"{strategy} {side} {short}/{long} ({contracts}x)"


def validate_setup(setup: Dict) -> bool:
    """
    Validate that setup has all required fields.

    Args:
        setup: Trade setup dict

    Returns:
        True if valid, False otherwise
    """
    required_fields = ['short_strike', 'long_strike', 'side']

    for field in required_fields:
        if field not in setup:
            print(f"ERROR: Missing required field '{field}' in setup")
            return False

    # Validate strikes are numbers
    try:
        int(setup['short_strike'])
        int(setup['long_strike'])
    except (ValueError, TypeError):
        print(f"ERROR: Strikes must be integers")
        return False

    # Validate side
    if setup['side'] not in ['CALL', 'PUT']:
        print(f"ERROR: Side must be 'CALL' or 'PUT', got '{setup['side']}'")
        return False

    return True


if __name__ == '__main__':
    """
    Test cases for conflict detection.
    """

    print("="*80)
    print("STRIKE CONFLICT CHECKER - TEST CASES")
    print("="*80)
    print()

    # Test 1: Exact match (GEX-to-GEX)
    print("Test 1: GEX-to-GEX exact strike match")
    existing = [{
        'strategy': 'GEX',
        'short_strike': 6895,
        'long_strike': 6890,
        'side': 'PUT',
        'status': 'open'
    }]

    new_setup = {
        'strategy': 'GEX',
        'short_strike': 6895,
        'long_strike': 6890,
        'side': 'PUT'
    }

    result = check_strike_conflicts(new_setup, existing)
    print(f"  Result: {result['has_conflict']} - {result['detail']}")
    print()

    # Test 2: Range overlap
    print("Test 2: Range overlap (6920 is long in first, short in second)")
    existing = [{
        'strategy': 'GEX',
        'short_strike': 6915,
        'long_strike': 6920,
        'side': 'CALL',
        'status': 'open'
    }]

    new_setup = {
        'strategy': 'GEX',
        'short_strike': 6920,
        'long_strike': 6925,
        'side': 'CALL'
    }

    result = check_strike_conflicts(new_setup, existing)
    print(f"  Result: {result['has_conflict']} - {result['detail']}")
    print()

    # Test 3: Different sides (no conflict)
    print("Test 3: Different sides (CALL vs PUT) - should be safe")
    existing = [{
        'strategy': 'GEX',
        'short_strike': 6915,
        'long_strike': 6920,
        'side': 'CALL',
        'status': 'open'
    }]

    new_setup = {
        'strategy': 'OTM',
        'short_strike': 6915,
        'long_strike': 6920,
        'side': 'PUT'
    }

    result = check_strike_conflicts(new_setup, existing)
    print(f"  Result: {result['has_conflict']} - {result['detail']}")
    print()

    # Test 4: Safe distance
    print("Test 4: Safe distance (30+ points apart)")
    existing = [{
        'strategy': 'GEX',
        'short_strike': 6895,
        'long_strike': 6890,
        'side': 'PUT',
        'status': 'open'
    }]

    new_setup = {
        'strategy': 'GEX',
        'short_strike': 6925,
        'long_strike': 6920,
        'side': 'PUT'
    }

    result = check_strike_conflicts(new_setup, existing)
    print(f"  Result: {result['has_conflict']} - {result['detail']}")
    print()

    # Test 5: Too close (same strategy)
    print("Test 5: Too close (12 points, same strategy, needs 20+)")
    existing = [{
        'strategy': 'GEX',
        'short_strike': 6895,
        'long_strike': 6890,
        'side': 'PUT',
        'status': 'open'
    }]

    new_setup = {
        'strategy': 'GEX',
        'short_strike': 6905,
        'long_strike': 6900,
        'side': 'PUT'
    }

    result = check_strike_conflicts(new_setup, existing)
    print(f"  Result: {result['has_conflict']} - {result['detail']}")
    print()

    # Test 6: GEX vs OTM (typical safe scenario)
    print("Test 6: GEX vs OTM (typical scenario, 65 points apart)")
    existing = [{
        'strategy': 'GEX',
        'short_strike': 6895,
        'long_strike': 6890,
        'side': 'PUT',
        'status': 'open'
    }]

    new_setup = {
        'strategy': 'OTM',
        'short_strike': 6830,
        'long_strike': 6810,
        'side': 'PUT'
    }

    result = check_strike_conflicts(new_setup, existing)
    print(f"  Result: {result['has_conflict']} - {result['detail']}")
    print()

    print("="*80)
    print("All tests completed!")
    print("="*80)
