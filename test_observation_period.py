#!/usr/bin/env python3
"""
Test script for observation period module

Simulates a GEX pin entry scenario and runs observation period
to demonstrate dangerous condition detection.

Usage:
    python3 test_observation_period.py
"""

import sys
import logging
from observation_period import ObservationPeriod, log_observation_decision

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_observation_quiet_market():
    """Test observation period during quiet market conditions"""
    print("\n" + "=" * 80)
    print("TEST 1: Quiet Market (should PASS)")
    print("=" * 80)

    config = {
        'enabled': True,
        'period_seconds': 30,  # Shorter for testing
        'max_range_pct': 0.15,
        'max_direction_changes': 5,
        'emergency_stop_threshold': 0.40,
        'min_tick_interval': 2.0,
    }

    observer = ObservationPeriod(config)

    # Simulate credit spread parameters
    entry_credit = 2.50  # $250 per contract
    spread_width = 10.0  # 10-point spread
    direction = 'PUT'    # PUT credit spread

    is_safe, reason = observer.observe(
        index_symbol='SPX',
        entry_credit=entry_credit,
        spread_width=spread_width,
        direction=direction
    )

    summary = observer.get_summary()
    log_observation_decision(is_safe, reason, summary)

    print("\n" + "-" * 80)
    print(f"Result: {'✅ SAFE' if is_safe else '🚫 DANGEROUS'}")
    print(f"Reason: {reason}")
    print("-" * 80)

    return is_safe


def test_observation_volatile_market():
    """Test observation period with tighter thresholds (simulate volatile conditions)"""
    print("\n" + "=" * 80)
    print("TEST 2: Volatile Market Detection (should FAIL)")
    print("=" * 80)

    config = {
        'enabled': True,
        'period_seconds': 30,  # Shorter for testing
        'max_range_pct': 0.05,  # Very tight (5% instead of 15%)
        'max_direction_changes': 2,  # Very tight
        'emergency_stop_threshold': 0.40,
        'min_tick_interval': 2.0,
    }

    observer = ObservationPeriod(config)

    # Same parameters as test 1
    entry_credit = 2.50
    spread_width = 10.0
    direction = 'PUT'

    is_safe, reason = observer.observe(
        index_symbol='SPX',
        entry_credit=entry_credit,
        spread_width=spread_width,
        direction=direction
    )

    summary = observer.get_summary()
    log_observation_decision(is_safe, reason, summary)

    print("\n" + "-" * 80)
    print(f"Result: {'✅ SAFE' if is_safe else '🚫 DANGEROUS'}")
    print(f"Reason: {reason}")
    print("-" * 80)

    return is_safe


def main():
    """Run all tests"""
    print("\n" + "=" * 80)
    print("OBSERVATION PERIOD TEST SUITE")
    print("=" * 80)

    # Test 1: Should pass in normal conditions
    try:
        result1 = test_observation_quiet_market()
        print(f"\n✅ Test 1 completed: {'PASSED (safe)' if result1 else 'FAILED (dangerous)'}")
    except Exception as e:
        print(f"\n❌ Test 1 error: {e}")

    # Test 2: Should fail with tight thresholds
    try:
        result2 = test_observation_volatile_market()
        print(f"\n✅ Test 2 completed: {'PASSED (safe)' if result2 else 'FAILED (dangerous - expected)'}")
    except Exception as e:
        print(f"\n❌ Test 2 error: {e}")

    print("\n" + "=" * 80)
    print("TESTS COMPLETE")
    print("=" * 80)
    print("\nCheck /root/gamma/data/observation_decisions.jsonl for logged decisions")


if __name__ == "__main__":
    main()
