#!/usr/bin/env python3
"""
Example: Using Black Box Data for Accurate Backtesting

Shows how to:
1. Get GEX pin at entry time
2. Calculate entry credit using live pricing
3. Monitor position with 30-second pricing
4. Test stop losses, profit targets, and hold-to-expiration logic
"""

import sqlite3
from datetime import datetime, timedelta

DB_PATH = "/root/gamma/data/gex_blackbox.db"


def backtest_single_trade_example(trade_date, entry_time_str):
    """
    Example backtest for a single trade.

    Args:
        trade_date: '2026-01-13'
        entry_time_str: '09:36:00'
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    entry_datetime = f"{trade_date} {entry_time_str}"
    print(f"\n{'='*60}")
    print(f"BACKTEST EXAMPLE: {entry_datetime}")
    print(f"{'='*60}")

    # ============================================================
    # STEP 1: Get GEX pin at entry time
    # ============================================================
    cursor.execute("""
        SELECT strike, gex
        FROM gex_peaks
        WHERE index_symbol = 'SPX'
            AND timestamp = ?
            AND peak_rank = 1
    """, (entry_datetime,))

    result = cursor.fetchone()
    if not result:
        print(f"No GEX data found at {entry_datetime}")
        conn.close()
        return

    pin_strike, pin_gex = result
    print(f"\n1. GEX PIN: {pin_strike} (GEX: {pin_gex/1e9:.1f}B)")

    # ============================================================
    # STEP 2: Get underlying price at entry
    # ============================================================
    cursor.execute("""
        SELECT underlying_price
        FROM options_snapshots
        WHERE index_symbol = 'SPX'
            AND timestamp = ?
    """, (entry_datetime,))

    spx_price = cursor.fetchone()[0]
    print(f"   SPX Price: {spx_price:.2f}")

    # ============================================================
    # STEP 3: Determine trade direction and strikes
    # ============================================================
    if spx_price > pin_strike + 6:
        # Price above pin - sell call spread (bearish)
        direction = "CALL SPREAD (bearish)"
        short_strike = pin_strike + 10
        long_strike = pin_strike + 20
        option_type = 'call'
    elif spx_price < pin_strike - 6:
        # Price below pin - sell put spread (bullish)
        direction = "PUT SPREAD (bullish)"
        short_strike = pin_strike - 10
        long_strike = pin_strike - 20
        option_type = 'put'
    else:
        # Near pin - Iron Condor
        direction = "IRON CONDOR"
        print(f"\n2. TRADE: {direction} (near pin, skipping example)")
        conn.close()
        return

    print(f"\n2. TRADE: {direction}")
    print(f"   Short: {short_strike} {option_type}")
    print(f"   Long:  {long_strike} {option_type}")

    # ============================================================
    # STEP 4: Calculate entry credit using live pricing
    # ============================================================
    # Find pricing closest to entry time
    cursor.execute("""
        SELECT strike, mid
        FROM options_prices_live
        WHERE index_symbol = 'SPX'
            AND timestamp >= ?
            AND timestamp < ?
            AND strike IN (?, ?)
            AND option_type = ?
        ORDER BY timestamp ASC
        LIMIT 2
    """, (entry_datetime, f"{trade_date} {entry_time_str[:-2]}37:00",
          short_strike, long_strike, option_type))

    prices = {row[0]: row[1] for row in cursor.fetchall()}

    if len(prices) != 2:
        print(f"\n   ⚠️  Incomplete pricing data at entry")
        conn.close()
        return

    short_price = prices[short_strike]
    long_price = prices[long_strike]
    entry_credit = short_price - long_price

    print(f"\n3. ENTRY PRICING:")
    print(f"   Short {short_strike}: ${short_price:.2f}")
    print(f"   Long {long_strike}:  ${long_price:.2f}")
    print(f"   Credit received: ${entry_credit:.2f}")

    # ============================================================
    # STEP 5: Monitor position throughout day (30-second data)
    # ============================================================
    print(f"\n4. POSITION MONITORING (30-second intervals):")

    # Define exit levels
    stop_loss_value = entry_credit * 1.10  # 10% stop
    profit_target_50 = entry_credit * 0.50  # 50% profit
    profit_target_60 = entry_credit * 0.40  # 60% profit (40% remaining)

    print(f"   Entry credit: ${entry_credit:.2f}")
    print(f"   Stop loss at: ${stop_loss_value:.2f} (+10%)")
    print(f"   Profit target 50%: ${profit_target_50:.2f}")
    print(f"   Profit target 60%: ${profit_target_60:.2f}")

    # Get all pricing snapshots for the day
    cursor.execute("""
        SELECT timestamp, strike, mid
        FROM options_prices_live
        WHERE index_symbol = 'SPX'
            AND DATE(timestamp) = ?
            AND timestamp > ?
            AND strike IN (?, ?)
            AND option_type = ?
        ORDER BY timestamp ASC
    """, (trade_date, entry_datetime, short_strike, long_strike, option_type))

    all_prices = cursor.fetchall()

    # Group by timestamp
    by_timestamp = {}
    for ts, strike, mid in all_prices:
        if ts not in by_timestamp:
            by_timestamp[ts] = {}
        by_timestamp[ts][strike] = mid

    # Check each snapshot
    exit_reason = None
    exit_value = None
    exit_time = None
    max_profit_pct = 0

    print(f"\n   Monitoring {len(by_timestamp)} snapshots...")

    for ts in sorted(by_timestamp.keys()):
        if short_strike not in by_timestamp[ts] or long_strike not in by_timestamp[ts]:
            continue

        current_short = by_timestamp[ts][short_strike]
        current_long = by_timestamp[ts][long_strike]
        current_value = current_short - current_long

        # Calculate profit/loss
        pnl = entry_credit - current_value
        profit_pct = pnl / entry_credit * 100

        # Track max profit reached
        if profit_pct > max_profit_pct:
            max_profit_pct = profit_pct

        # Check stop loss (grace period not shown for simplicity)
        if current_value >= stop_loss_value:
            exit_reason = "STOP LOSS (10%)"
            exit_value = current_value
            exit_time = ts
            break

        # Check profit targets
        if current_value <= profit_target_50:
            exit_reason = "PROFIT TARGET (50%)"
            exit_value = current_value
            exit_time = ts
            break

    # If no exit by 3:30 PM, auto-close
    if exit_reason is None:
        close_time = f"{trade_date} 15:30:00"
        if close_time in by_timestamp:
            if short_strike in by_timestamp[close_time] and long_strike in by_timestamp[close_time]:
                current_short = by_timestamp[close_time][short_strike]
                current_long = by_timestamp[close_time][long_strike]
                exit_value = current_short - current_long
                exit_reason = "AUTO-CLOSE (3:30 PM)"
                exit_time = close_time

    # ============================================================
    # STEP 6: Calculate final P&L
    # ============================================================
    if exit_value is not None:
        exit_cost = exit_value
        pnl = (entry_credit - exit_cost) * 100  # Per contract
        pnl_pct = pnl / (entry_credit * 100) * 100

        print(f"\n5. EXIT:")
        print(f"   Time: {exit_time}")
        print(f"   Reason: {exit_reason}")
        print(f"   Exit cost: ${exit_value:.2f}")
        print(f"   P&L: ${pnl:.2f} ({pnl_pct:+.1f}%)")
        print(f"   Max profit reached: {max_profit_pct:.1f}%")

        if pnl > 0:
            print(f"   Result: ✅ WIN")
        else:
            print(f"   Result: ❌ LOSS")
    else:
        print(f"\n5. NO EXIT DATA (incomplete pricing)")

    conn.close()
    print(f"\n{'='*60}\n")


def show_hold_to_expiration_logic():
    """Show how to determine if trade qualifies for hold-to-expiration."""
    print(f"\n{'='*60}")
    print("HOLD-TO-EXPIRATION QUALIFICATION LOGIC")
    print(f"{'='*60}\n")

    print("""
    During position monitoring, track:

    1. Max profit reached during day
    2. Time when max profit was reached
    3. Current profit at each check

    Hold-to-expiration rules:
    - If position reached 50%+ profit AND stayed profitable
    - If position never hit stop loss
    - If current time > 2:00 PM and position still profitable

    Example:

    entry_credit = 2.50

    10:00 AM: Value = 1.00 (60% profit) ✅ Qualifies
    11:00 AM: Value = 1.20 (52% profit) ✅ Still qualifies
    12:00 PM: Value = 1.25 (50% profit) ✅ Still qualifies
    01:00 PM: Value = 1.30 (48% profit) ⚠️  Below 50%
    02:00 PM: Value = 1.35 (46% profit) ⚠️  Below 50%

    Decision at 2:00 PM:
    - Reached 60% profit earlier ✅
    - Currently at 46% profit (still good) ✅
    - After 2:00 PM cutoff ✅
    → HOLD to expiration (let it decay to worthless)

    vs

    entry_credit = 2.50

    10:00 AM: Value = 1.50 (40% profit) ⚠️  Never reached 50%
    02:00 PM: Value = 1.60 (36% profit) ⚠️  Still below 50%

    Decision at 2:00 PM:
    - Never reached 50% profit ❌
    → TAKE PROFIT at 3:30 PM (don't risk it)
    """)


if __name__ == '__main__':
    print("\n" + "="*60)
    print("BLACK BOX BACKTEST EXAMPLES")
    print("="*60)

    # Example 1: Backtest a single trade (will work after data collection starts)
    print("\nNOTE: This will work after Monday's data collection begins.")
    print("Example shown with date Jan 13, 2026 at 9:36 AM\n")

    # Uncomment after data is collected:
    # backtest_single_trade_example('2026-01-13', '09:36:00')

    # Show hold-to-expiration logic
    show_hold_to_expiration_logic()

    print("\nTo run real backtest after data collection:")
    print("  python3 backtest_example_using_blackbox.py")
    print("\nOr use the functions in your own backtest script:")
    print("  from backtest_example_using_blackbox import backtest_single_trade_example")
    print("  backtest_single_trade_example('2026-01-13', '09:36:00')")
