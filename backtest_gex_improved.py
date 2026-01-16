#!/usr/bin/env python3
"""
GEX Backtest with Improvements (2026-01-16)

CHANGES FROM BASELINE:
1. Trailing activation: 20% → 30% (hold winners longer)
2. Emergency stop: 40% → 25% (tighter risk control)
3. Skip entries before 10:00 AM (avoid low-probability setup)

Expected: PF improvement from 1.18 → 1.42+
"""

import sqlite3
import datetime
import numpy as np
import json

DB_PATH = "/root/gamma/data/gex_blackbox.db"

# ============================================================================
# IMPROVED PARAMETERS
# ============================================================================

# Profit targets (UNCHANGED)
PROFIT_TARGET_PCT = 0.50
PROFIT_TARGET_MEDIUM = 0.60

# Stop loss (UNCHANGED)
STOP_LOSS_PCT = 0.15

# VIX filters (UNCHANGED)
VIX_MAX_THRESHOLD = 20
VIX_FLOOR = 13.0

# Trailing stop (IMPROVED - hold winners longer)
TRAILING_STOP_ENABLED = True
TRAILING_TRIGGER_PCT = 0.30  # WAS 0.20 - Now 30%!
TRAILING_LOCK_IN_PCT = 0.20  # WAS 0.12 - Proportionally adjusted
TRAILING_DISTANCE_MIN = 0.10  # WAS 0.08 - Proportionally adjusted
TRAILING_TIGHTEN_RATE = 0.4  # UNCHANGED

# Stop loss grace period (IMPROVED - tighter emergency)
SL_GRACE_PERIOD_SEC = 540  # UNCHANGED
SL_EMERGENCY_PCT = 0.25  # WAS 0.40 - Tighter emergency stop!

# Progressive hold-to-expiration (UNCHANGED)
PROGRESSIVE_HOLD_ENABLED = True
HOLD_PROFIT_THRESHOLD = 0.80
HOLD_VIX_MAX = 17
HOLD_MIN_TIME_LEFT_HOURS = 1.0
HOLD_MIN_ENTRY_DISTANCE = 8

# Entry times (IMPROVED - skip 09:36)
ENTRY_TIMES_ET = [
    # "09:36",  # REMOVED - Poor performance
    "10:00", "10:30", "11:00",
    "11:30", "12:00", "12:30", "13:00"
]
CUTOFF_HOUR = 13
AUTO_CLOSE_HOUR = 15
AUTO_CLOSE_MINUTE = 30

# Progressive TP schedule (UNCHANGED)
PROGRESSIVE_TP_SCHEDULE = [
    (0.0, 0.50), (0.5, 0.55), (1.0, 0.60),
    (2.0, 0.70), (3.0, 0.80), (4.0, 0.90),
]


def get_optimized_connection():
    """Get database connection with optimizations."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def estimate_entry_credit(pin_strike, vix, underlying):
    """Estimate GEX PIN entry credit."""
    iv = vix / 100.0
    distance_pct = abs(pin_strike - underlying) / underlying

    if distance_pct < 0.005:
        credit = underlying * iv * 0.05
    elif distance_pct < 0.01:
        credit = underlying * iv * 0.03
    else:
        credit = underlying * iv * 0.02

    return max(0.50, min(credit, 2.50))


def simulate_spread_quotes(entry_credit, profit_pct):
    """Simulate realistic bid/ask spread."""
    mid_value = entry_credit * (1 - profit_pct)

    if mid_value < 0.50:
        spread = 0.05
    elif mid_value < 1.00:
        spread = 0.10
    else:
        spread = 0.15

    bid_value = max(0, mid_value - spread/2)
    ask_value = mid_value + spread/2

    return round(mid_value, 2), round(bid_value, 2), round(ask_value, 2)


def simulate_gex_exit(entry_credit, underlying, pin_strike, vix, entry_time):
    """Simulate GEX PIN spread exit using IMPROVED parameters."""
    spread_width = 5.0
    confidence = 'HIGH' if vix < 18 else 'MEDIUM'
    profit_target = PROFIT_TARGET_PCT if confidence == 'HIGH' else PROFIT_TARGET_MEDIUM
    entry_distance = abs(pin_strike - underlying)

    best_profit_pct = 0
    trailing_active = False
    hold_qualified = False

    elapsed_sec = 0
    check_interval_sec = 15

    # Simulate market behavior (PIN pull + random walk)
    distance_from_pin = underlying - pin_strike
    pin_pull_strength = 0.3

    while elapsed_sec < 23400:  # Max 6.5 hours
        elapsed_sec += check_interval_sec
        current_time_dt = entry_time + datetime.timedelta(seconds=elapsed_sec)
        hours_elapsed = elapsed_sec / 3600.0

        # Auto-close check
        if current_time_dt.hour >= AUTO_CLOSE_HOUR:
            if current_time_dt.hour > AUTO_CLOSE_HOUR or current_time_dt.minute >= AUTO_CLOSE_MINUTE:
                if not hold_qualified:
                    profit_pct = np.random.uniform(0.30, 0.70)
                    mid_value, _, _ = simulate_spread_quotes(entry_credit, profit_pct)
                    return {
                        'exit_credit': mid_value,
                        'exit_reason': 'Auto-close 3:30 PM',
                        'is_winner': True,
                        'exit_time_sec': elapsed_sec
                    }

        # Expiration check
        if current_time_dt.hour >= 16:
            if hold_qualified or np.random.random() < 0.85:
                return {
                    'exit_credit': 0.0,
                    'exit_reason': 'Hold-to-Expiry: Worthless' if hold_qualified else '0DTE Expiration',
                    'is_winner': True,
                    'exit_time_sec': elapsed_sec
                }
            else:
                loss_pct = np.random.uniform(0.20, 0.50)
                mid_value = entry_credit * (1 + loss_pct)
                return {
                    'exit_credit': mid_value,
                    'exit_reason': 'Expire ITM',
                    'is_winner': False,
                    'exit_time_sec': elapsed_sec
                }

        # Simulate price movement
        volatility_per_hour = vix * 0.5
        random_move = np.random.normal(0, volatility_per_hour / np.sqrt(252 * 6.5))
        pin_pull = -distance_from_pin * pin_pull_strength * (check_interval_sec / 3600.0)
        distance_from_pin += random_move + pin_pull

        # Calculate profit
        initial_distance = abs(underlying - pin_strike)
        current_distance = abs(distance_from_pin)
        if initial_distance > 0:
            distance_improvement = (initial_distance - current_distance) / initial_distance
            profit_pct = distance_improvement * 0.8
        else:
            profit_pct = 0.0

        profit_pct += np.random.normal(0, 0.05)
        profit_pct = np.clip(profit_pct, -1.0, 0.95)

        mid_value, bid_value, ask_value = simulate_spread_quotes(entry_credit, profit_pct)
        profit_pct_mid = (entry_credit - mid_value) / entry_credit
        profit_pct_sl = (entry_credit - ask_value) / entry_credit

        if profit_pct_mid > best_profit_pct:
            best_profit_pct = profit_pct_mid

        # Trailing stop (IMPROVED PARAMETERS)
        if TRAILING_STOP_ENABLED and not trailing_active and profit_pct_mid >= TRAILING_TRIGGER_PCT:
            trailing_active = True

        if trailing_active:
            initial_trail_distance = TRAILING_TRIGGER_PCT - TRAILING_LOCK_IN_PCT
            profit_above_trigger = best_profit_pct - TRAILING_TRIGGER_PCT
            trail_distance = initial_trail_distance - (profit_above_trigger * TRAILING_TIGHTEN_RATE)
            trail_distance = max(trail_distance, TRAILING_DISTANCE_MIN)
            trailing_stop_level = best_profit_pct - trail_distance

            if profit_pct_mid <= trailing_stop_level:
                return {
                    'exit_credit': mid_value,
                    'exit_reason': f'Trailing Stop ({trailing_stop_level*100:.0f}%)',
                    'is_winner': profit_pct_mid > 0,
                    'exit_time_sec': elapsed_sec
                }

        # Progressive TP
        schedule_times = [t for t, _ in PROGRESSIVE_TP_SCHEDULE]
        schedule_tps = [tp for _, tp in PROGRESSIVE_TP_SCHEDULE]
        progressive_tp_pct = np.interp(hours_elapsed, schedule_times, schedule_tps)

        # Hold qualification
        if PROGRESSIVE_HOLD_ENABLED and not hold_qualified and profit_pct_mid >= HOLD_PROFIT_THRESHOLD:
            hours_to_expiry = (16 - current_time_dt.hour) + (0 - current_time_dt.minute) / 60.0
            if (vix < HOLD_VIX_MAX and hours_to_expiry >= HOLD_MIN_TIME_LEFT_HOURS and
                entry_distance >= HOLD_MIN_ENTRY_DISTANCE):
                hold_qualified = True

        # Profit target
        if profit_pct_mid >= progressive_tp_pct and not hold_qualified:
            return {
                'exit_credit': mid_value,
                'exit_reason': f'Profit Target ({progressive_tp_pct*100:.0f}%)',
                'is_winner': True,
                'exit_time_sec': elapsed_sec
            }

        # Stop losses (IMPROVED EMERGENCY STOP)
        if not trailing_active and not hold_qualified:
            if profit_pct_sl <= -SL_EMERGENCY_PCT:
                return {
                    'exit_credit': ask_value,
                    'exit_reason': f'EMERGENCY Stop Loss ({profit_pct_sl*100:.0f}%)',
                    'is_winner': False,
                    'exit_time_sec': elapsed_sec
                }

            if profit_pct_sl <= -STOP_LOSS_PCT and elapsed_sec >= SL_GRACE_PERIOD_SEC:
                return {
                    'exit_credit': ask_value,
                    'exit_reason': f'Stop Loss ({profit_pct_sl*100:.0f}%)',
                    'is_winner': False,
                    'exit_time_sec': elapsed_sec
                }

    return {
        'exit_credit': 0.0,
        'exit_reason': 'Simulation Timeout',
        'is_winner': True,
        'exit_time_sec': elapsed_sec
    }


def backtest_gex_improved():
    """Run backtest with IMPROVED GEX parameters."""

    conn = get_optimized_connection()
    cursor = conn.cursor()

    # Get all snapshots
    query = """
    SELECT
        s.timestamp,
        DATE(DATETIME(s.timestamp, '-5 hours')) as date_et,
        TIME(DATETIME(s.timestamp, '-5 hours')) as time_et,
        s.index_symbol,
        s.underlying_price,
        s.vix,
        g.strike as pin_strike,
        g.gex as pin_gex,
        g.distance_from_price
    FROM options_snapshots s
    LEFT JOIN gex_peaks g ON s.timestamp = g.timestamp
        AND s.index_symbol = g.index_symbol
        AND g.peak_rank = 1
    WHERE s.index_symbol = 'SPX'
    ORDER BY s.timestamp ASC
    """

    cursor.execute(query)
    snapshots = cursor.fetchall()
    conn.close()

    trades = []

    for snapshot in snapshots:
        timestamp, date_et, time_et, symbol, underlying, vix, pin_strike, gex, distance = snapshot

        # Parse time
        hour = int(time_et.split(':')[0])
        minute = int(time_et.split(':')[1])
        entry_time_str = f"{hour:02d}:{minute:02d}"

        # Only trade at scheduled times (IMPROVED - no 09:36)
        if entry_time_str not in ENTRY_TIMES_ET:
            continue

        # Apply filters
        if hour >= CUTOFF_HOUR:
            continue
        if vix >= VIX_MAX_THRESHOLD or vix < VIX_FLOOR:
            continue

        # Must have valid GEX peak
        if pin_strike is None or gex is None or gex == 0:
            continue

        entry_datetime = datetime.datetime.strptime(f"{date_et} {time_et}", '%Y-%m-%d %H:%M:%S')

        entry_credit = estimate_entry_credit(pin_strike, vix, underlying)
        if entry_credit < 0.50:
            continue

        exit_result = simulate_gex_exit(
            entry_credit=entry_credit,
            underlying=underlying,
            pin_strike=pin_strike,
            vix=vix,
            entry_time=entry_datetime
        )

        pl = (entry_credit - exit_result['exit_credit']) * 100

        trades.append({
            'strategy': 'GEX PIN (IMPROVED)',
            'date': date_et,
            'time': time_et,
            'underlying': underlying,
            'vix': vix,
            'strikes': f"{pin_strike:.0f}",
            'entry_credit': entry_credit,
            'exit_credit': exit_result['exit_credit'],
            'exit_reason': exit_result['exit_reason'],
            'pl': pl,
            'winner': exit_result['is_winner'],
            'duration_sec': exit_result['exit_time_sec'],
        })

    return trades


def print_comparison_report(baseline_trades, improved_trades):
    """Print side-by-side comparison of baseline vs improved."""

    print("\n" + "="*120)
    print("GEX STRATEGY: BASELINE vs IMPROVED")
    print("="*120)

    print("\nIMPROVEMENTS APPLIED:")
    print("  1. Trailing activation: 20% → 30% (hold winners longer)")
    print("  2. Emergency stop: 40% → 25% (tighter risk control)")
    print("  3. Skip entries before 10:00 AM (avoid low-probability setups)")

    # Baseline stats
    baseline_winners = [t for t in baseline_trades if t['winner']]
    baseline_losers = [t for t in baseline_trades if not t['winner']]
    baseline_total_wins = sum(t['pl'] for t in baseline_winners)
    baseline_total_losses = abs(sum(t['pl'] for t in baseline_losers))
    baseline_pf = baseline_total_wins / baseline_total_losses if baseline_total_losses > 0 else float('inf')

    # Improved stats
    improved_winners = [t for t in improved_trades if t['winner']]
    improved_losers = [t for t in improved_trades if not t['winner']]
    improved_total_wins = sum(t['pl'] for t in improved_winners)
    improved_total_losses = abs(sum(t['pl'] for t in improved_losers))
    improved_pf = improved_total_wins / improved_total_losses if improved_total_losses > 0 else float('inf')

    print(f"\n" + "-"*120)
    print(f"{'METRIC':<30} {'BASELINE':<25} {'IMPROVED':<25} {'CHANGE':<25}")
    print("-"*120)

    print(f"{'Total Trades':<30} {len(baseline_trades):<25} {len(improved_trades):<25} {len(improved_trades) - len(baseline_trades):+d}")

    print(f"{'Win Rate':<30} {len(baseline_winners)/len(baseline_trades)*100:.1f}%{'':<20} "
          f"{len(improved_winners)/len(improved_trades)*100:.1f}%{'':<20} "
          f"{(len(improved_winners)/len(improved_trades) - len(baseline_winners)/len(baseline_trades))*100:+.1f}%")

    print(f"{'Total Wins':<30} ${baseline_total_wins:,.0f}{'':<20} "
          f"${improved_total_wins:,.0f}{'':<20} "
          f"${improved_total_wins - baseline_total_wins:+,.0f}")

    print(f"{'Total Losses':<30} ${baseline_total_losses:,.0f}{'':<20} "
          f"${improved_total_losses:,.0f}{'':<20} "
          f"${improved_total_losses - baseline_total_losses:+,.0f}")

    baseline_net = sum(t['pl'] for t in baseline_trades)
    improved_net = sum(t['pl'] for t in improved_trades)
    print(f"{'Net P/L':<30} ${baseline_net:,.0f}{'':<20} "
          f"${improved_net:,.0f}{'':<20} "
          f"${improved_net - baseline_net:+,.0f}")

    print(f"{'Profit Factor':<30} {baseline_pf:.2f}{'':<20} "
          f"{improved_pf:.2f}{'':<20} "
          f"{improved_pf - baseline_pf:+.2f}")

    print(f"{'Avg Winner':<30} ${sum(t['pl'] for t in baseline_winners)/len(baseline_winners):.0f}{'':<20} "
          f"${sum(t['pl'] for t in improved_winners)/len(improved_winners):.0f}{'':<20} "
          f"${sum(t['pl'] for t in improved_winners)/len(improved_winners) - sum(t['pl'] for t in baseline_winners)/len(baseline_winners):+.0f}")

    if baseline_losers and improved_losers:
        print(f"{'Avg Loser':<30} ${sum(t['pl'] for t in baseline_losers)/len(baseline_losers):.0f}{'':<20} "
              f"${sum(t['pl'] for t in improved_losers)/len(improved_losers):.0f}{'':<20} "
              f"${sum(t['pl'] for t in improved_losers)/len(improved_losers) - sum(t['pl'] for t in baseline_losers)/len(baseline_losers):+.0f}")

    print("-"*120)

    print(f"\n{'✓ TARGET ACHIEVED!' if improved_pf >= 1.25 else '❌ TARGET MISSED'}")
    if improved_pf >= 1.25:
        print(f"  Profit Factor improved from {baseline_pf:.2f} → {improved_pf:.2f} (target: 1.25)")
    else:
        print(f"  Profit Factor {improved_pf:.2f} still below target of 1.25")

    print("\n" + "="*120)


if __name__ == '__main__':
    np.random.seed(42)

    # Run baseline for comparison
    print("Running baseline backtest...")
    from backtest_gex_and_otm import backtest_gex_and_otm
    all_trades = backtest_gex_and_otm()
    baseline_trades = [t for t in all_trades if t['strategy'] == 'GEX PIN']

    print("Running improved backtest...")
    improved_trades = backtest_gex_improved()

    print_comparison_report(baseline_trades, improved_trades)

    # Save detailed results
    with open('/root/gamma/BACKTEST_GEX_IMPROVED.txt', 'w') as f:
        import sys
        old_stdout = sys.stdout
        sys.stdout = f
        print_comparison_report(baseline_trades, improved_trades)
        sys.stdout = old_stdout

    print("\n✓ Results saved to: /root/gamma/BACKTEST_GEX_IMPROVED.txt")
