#!/usr/bin/env python3
"""
Validate Stop Loss Execution from trades.csv

Shows what we CAN and CANNOT validate about stop loss execution
using only the entry/exit snapshot data in trades.csv.
"""

import csv
import re
from datetime import datetime


def analyze_stop_loss_trades(csv_path="/root/gamma/data/trades.csv"):
    """Analyze stop loss execution from trades.csv."""

    print("\n" + "="*80)
    print("  STOP LOSS EXECUTION VALIDATION - trades.csv Analysis")
    print("="*80)

    sl_trades = []
    tp_trades = []
    trailing_trades = []
    other_trades = []

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get('Exit_Time'):
                continue

            exit_reason = row.get('Exit_Reason', '')

            if 'Stop Loss' in exit_reason:
                sl_trades.append(row)
            elif 'Profit Target' in exit_reason:
                tp_trades.append(row)
            elif 'Trailing Stop' in exit_reason:
                trailing_trades.append(row)
            else:
                other_trades.append(row)

    print(f"\nTrade Distribution:")
    print(f"  Stop Loss:     {len(sl_trades):3d} trades")
    print(f"  Profit Target: {len(tp_trades):3d} trades")
    print(f"  Trailing Stop: {len(trailing_trades):3d} trades")
    print(f"  Other:         {len(other_trades):3d} trades")
    print(f"  {'─'*40}")
    print(f"  Total:         {len(sl_trades)+len(tp_trades)+len(trailing_trades)+len(other_trades):3d} trades")

    # Analyze stop loss trades
    if sl_trades:
        print(f"\n{'-'*80}")
        print("  STOP LOSS VALIDATION")
        print(f"{'-'*80}")

        print(f"\n{'Exit_Reason':<40} {'P/L%':>8} {'Dur':>5} {'Expected':>12} {'Status':>10}")
        print(f"{'-'*40} {'-'*8} {'-'*5} {'-'*12} {'-'*10}")

        validation_passed = 0
        validation_failed = 0

        for trade in sl_trades:
            exit_reason = trade['Exit_Reason']
            pl_str = trade.get('P/L_%', '0%').replace('%', '').replace('+', '')
            duration = trade.get('Duration_Min', '0')

            try:
                pl_pct = float(pl_str)
                dur_min = int(float(duration)) if duration else 0
            except:
                continue

            # Check if emergency vs regular
            is_emergency = 'EMERGENCY' in exit_reason

            if is_emergency:
                expected = "<= -40%"
                valid = pl_pct <= -40
            else:
                expected = "<= -10%"
                valid = pl_pct <= -10

            # Check grace period (5 minutes)
            grace_ok = True
            if not is_emergency and dur_min < 5:
                grace_ok = False

            status = "✓ PASS" if (valid and grace_ok) else "✗ FAIL"

            if valid and grace_ok:
                validation_passed += 1
            else:
                validation_failed += 1

            # Truncate exit reason for display
            reason_short = exit_reason[:40]

            print(f"{reason_short:<40} {pl_pct:>7.1f}% {dur_min:>4}m {expected:>12} {status:>10}")

            if not grace_ok:
                print(f"  └─ WARNING: Regular SL hit before grace period (5 min)")

        print(f"\n  Validation Results:")
        print(f"    PASS: {validation_passed}/{len(sl_trades)}")
        print(f"    FAIL: {validation_failed}/{len(sl_trades)}")

    # Analyze trailing stop trades
    if trailing_trades:
        print(f"\n{'-'*80}")
        print("  TRAILING STOP VALIDATION")
        print(f"{'-'*80}")

        print(f"\n{'Exit_Reason':<50} {'P/L%':>8} {'Peak%':>7}")
        print(f"{'-'*50} {'-'*8} {'-'*7}")

        for trade in trailing_trades:
            exit_reason = trade['Exit_Reason']
            pl_str = trade.get('P/L_%', '0%').replace('%', '').replace('+', '')

            try:
                pl_pct = float(pl_str)
            except:
                continue

            # Try to extract peak from exit reason (e.g., "from peak 48%")
            match = re.search(r'from peak (\d+)%', exit_reason)
            peak_pct = int(match.group(1)) if match else None

            reason_short = exit_reason[:50]

            if peak_pct:
                print(f"{reason_short:<50} {pl_pct:>7.1f}% {peak_pct:>6}%")
            else:
                print(f"{reason_short:<50} {pl_pct:>7.1f}%     N/A")

    # What we CANNOT validate
    print(f"\n{'-'*80}")
    print("  LIMITATIONS - What We CANNOT Validate")
    print(f"{'-'*80}")

    print("""
  ❌ Stop Loss Execution Speed
     - Need: 15-second granularity logs
     - Have: Only entry/exit timestamps (minutes apart)
     - Cannot measure: Time from SL trigger to actual close

  ❌ Price Drift After Trigger
     - Need: Bid/ask prices at trigger vs close time
     - Have: Only final exit value
     - Cannot measure: How much position drifted after trigger

  ❌ Bid/Ask Spread Impact
     - Need: Bid/ask at entry and exit
     - Have: Only mid prices
     - Cannot measure: Slippage from spread vs price movement

  ❌ Peak Profit Tracking
     - Need: P/L every 15 seconds
     - Have: Only final exit P/L
     - Cannot verify: Whether peak was tracked correctly for trailing stops

  ❌ Grace Period Behavior
     - Need: Exact timestamp when SL was triggered
     - Have: Only entry time and duration
     - Cannot verify: Whether grace period was properly applied
""")

    # Recommendations
    print(f"\n{'-'*80}")
    print("  RECOMMENDATIONS")
    print(f"{'-'*80}")

    print("""
  1. Enable Position P/L Logging (HIGH PRIORITY)
     - Log every 15-second monitoring cycle to CSV
     - Track: timestamp, order_id, current_value, profit_pct, best_profit_pct
     - File: /root/gamma/data/position_pl_tracking.csv

  2. Increase Monitor Log Retention
     - Current: 7 days
     - Proposed: 30 days
     - Edit: /etc/logrotate.d/gamma-monitor

  3. Monitor First Week (Jan 13-17)
     - Watch for: SL execution within 15-30 seconds
     - Measure: Average slippage on exits
     - Validate: Trailing stop peak tracking

  4. Build Replay Tools
     - Fetch historical options bars from Tradier API
     - Replay each trade with 1-minute granularity
     - Validate: SL timing, drift, spread impact
""")

    print("\n" + "="*80 + "\n")


def main():
    analyze_stop_loss_trades()


if __name__ == "__main__":
    main()
