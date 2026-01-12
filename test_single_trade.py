#!/usr/bin/env python3
"""Test a single trade with debug output to see stop loss behavior."""

import sys
sys.path.insert(0, '/root/gamma')

import numpy as np
import random

# Simple test - one trade
random.seed(2024)
np.random.seed(2024)

# Entry params
entry_credit = 0.06  # $0.06 credit (60% of spread width - realistic!)
spx_start = 6000
short_strike = 5990  # PUT spread: sell 5990P / buy 5980P
long_strike = 5980
spread_width = 10 / 100.0  # $0.10 in dollars (max possible value)

print("="*80)
print("SINGLE TRADE TEST - Random Walk with 0-20 pt moves")
print("="*80)
print(f"Entry: SPX={spx_start}, Credit=${entry_credit:.2f}")
print(f"PUT Spread: {short_strike}P / {long_strike}P")
print(f"Spread Width: ${spread_width:.2f}")
print()

# Simulate 60 minutes
spx_price = spx_start
print(f"{'Min':>3} {'SPX':>8} {'Short$':>7} {'Long$':>7} {'Spread$':>8} {'P/L%':>7} {'Status'}")
print("-"*80)

for minute in range(60):
    # Random walk: 50/50 direction, 0-20 points
    direction = 1 if random.random() < 0.5 else -1
    magnitude = random.uniform(0, 20)
    spx_price += direction * magnitude
    
    # Calculate spread value
    short_intrinsic = max(0, short_strike - spx_price) / 100.0
    long_intrinsic = max(0, long_strike - spx_price) / 100.0
    spread_intrinsic = min(short_intrinsic - long_intrinsic, spread_width)
    
    # Time value (simple exponential decay)
    minutes_left = 390 - minute  # 6.5 hours = 390 minutes
    hours_left = minutes_left / 60.0
    time_value_pct = np.exp(-3 * (6.5 - hours_left) / 6.5)
    extrinsic_remaining = max(0, spread_width - spread_intrinsic)
    time_value = extrinsic_remaining * time_value_pct * (entry_credit / spread_width)
    
    spread_value = min(spread_intrinsic + time_value, spread_width)
    
    # P/L
    profit_pct = (entry_credit - spread_value) / entry_credit
    
    status = ""
    if profit_pct >= 0.50:
        status = "✓ HIT PROFIT TARGET"
    elif profit_pct <= -0.40:
        status = "✗ EMERGENCY STOP"
    elif profit_pct <= -0.10:
        status = "✗ STOP LOSS"
    
    if minute % 5 == 0 or status:  # Print every 5 min or on status change
        print(f"{minute:3d} {spx_price:8.2f} ${short_intrinsic:6.3f} ${long_intrinsic:6.3f} ${spread_value:7.3f} {profit_pct*100:6.1f}% {status}")
    
    # Check exits
    if profit_pct >= 0.50:
        print(f"\n✓ EXIT: Profit target hit at minute {minute}")
        print(f"   Final P/L: ${(profit_pct * entry_credit * 100):+.2f} per contract")
        break
    elif profit_pct <= -0.40:
        print(f"\n✗ EXIT: Emergency stop at minute {minute}")
        print(f"   Final P/L: ${(profit_pct * entry_credit * 100):+.2f} per contract")
        break
    elif profit_pct <= -0.10:
        print(f"\n✗ EXIT: Stop loss at minute {minute}")
        print(f"   Final P/L: ${(profit_pct * entry_credit * 100):+.2f} per contract")
        break
else:
    print(f"\n→ Reached end of test (60 minutes)")
    print(f"   Final P/L: ${(profit_pct * entry_credit * 100):+.2f} per contract")

print("="*80)
