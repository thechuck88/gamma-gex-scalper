#!/usr/bin/env python3
"""
Kalman Spread Tracker — filters 0DTE option spread mid-price noise.

Thin wrapper around MNQ's KalmanVelocityTracker, tuned for options:
- Higher measurement noise (bid/ask spreads are wide on 0DTE)
- Higher process noise (spreads can move fast near expiry)
- ATR proxy = 10% of entry credit (typical spread fluctuation range)

The noise_level() output drives a three-layer stop defense:
  Layer 1: noise > 3.0 → suppress stop entirely (extreme bid/ask noise)
  Layer 2: noise 1.0-3.0 → let Haiku evaluate (normal conditions)
  Layer 3: noise < 1.0 → execute stop directly (clean signal, real danger)

Usage:
    tracker = create_tracker(entry_credit=3.50)
    tracker.update(mid_price, time.time())
    noise = tracker.noise_level()
    filtered_price = tracker.filtered_price()
"""

import sys
import os

# Add MNQ core to path for KalmanVelocityTracker import
sys.path.insert(0, '/root/topstocks')

from core.kalman_velocity_tracker import KalmanVelocityTracker

# Options-tuned defaults (calibrated for 0DTE SPX credit spreads)
# Measurement noise: 0DTE bid/ask spreads are 5-15 cents wide on a $2-5 spread
# Process noise: spreads can move fast, be more reactive than MNQ
OPTIONS_MEASUREMENT_NOISE = 0.05    # $0.05 typical bid/ask jitter
OPTIONS_PROCESS_NOISE_SCALE = 3.0   # 3× more reactive than MNQ (fast 0DTE moves)
OPTIONS_ATR_FRACTION = 0.10         # ATR proxy = 10% of entry credit


def create_tracker(entry_credit, measurement_noise=OPTIONS_MEASUREMENT_NOISE,
                   process_noise_scale=OPTIONS_PROCESS_NOISE_SCALE):
    """Create a Kalman tracker tuned for option spread mid-prices.

    Args:
        entry_credit: Entry credit received (e.g., 3.50). Used to set ATR proxy.
        measurement_noise: Expected bid/ask noise in dollars.
        process_noise_scale: Reactivity multiplier (higher = trusts new data more).

    Returns:
        KalmanVelocityTracker configured for options.
    """
    atr_proxy = max(entry_credit * OPTIONS_ATR_FRACTION, 0.10)
    return KalmanVelocityTracker(
        atr=atr_proxy,
        process_noise_scale=process_noise_scale,
        measurement_noise=measurement_noise,
    )
