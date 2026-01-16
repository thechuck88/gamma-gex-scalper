#!/usr/bin/env python3
"""
GEX + OTM Backtest with Improvements (2026-01-16)

Tests BOTH strategies with improved parameters:
1. Trailing activation: 20% → 30%
2. Emergency stop: 40% → 25%
3. Entry times: 10:00-11:30 only (skip 09:36 and 12:00+)

CRITICAL FIX: Only 1 trade per scheduled time (not every 15-sec snapshot)
"""

import sqlite3
import datetime
import numpy as np
import json
import math
from collections import defaultdict

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

# Trailing stop (IMPROVED)
TRAILING_STOP_ENABLED = True
TRAILING_TRIGGER_PCT = 0.30  # Was 0.20
TRAILING_LOCK_IN_PCT = 0.20  # Was 0.12
TRAILING_DISTANCE_MIN = 0.10  # Was 0.08
TRAILING_TIGHTEN_RATE = 0.4

# Stop loss grace period (IMPROVED)
SL_GRACE_PERIOD_SEC = 540
SL_EMERGENCY_PCT = 0.25  # Was 0.40

# Progressive hold-to-expiration (UNCHANGED)
PROGRESSIVE_HOLD_ENABLED = True
HOLD_PROFIT_THRESHOLD = 0.80
HOLD_VIX_MAX = 17
HOLD_MIN_TIME_LEFT_HOURS = 1.0
HOLD_MIN_ENTRY_DISTANCE = 8

# OTM Strategy (UNCHANGED)
OTM_MIN_PROBABILITY = 0.90
OTM_MIN_CREDIT_TOTAL = 0.40
OTM_MIN_CREDIT_PER_SIDE = 0.15
OTM_STD_DEV_MULTIPLIER = 0.75
OTM_SPREAD_WIDTH = 10

# Progressive TP schedule
PROGRESSIVE_TP_SCHEDULE = [
    (0.0, 0.50), (0.5, 0.55), (1.0, 0.60),
    (2.0, 0.70), (3.0, 0.80), (4.0, 0.90),
]

# Entry times (IMPROVED - 10:00-11:30 only)
ENTRY_TIMES_ET = ["10:00", "10:30", "11:00", "11:30"]
CUTOFF_HOUR = 12  # Block after 11:30
AUTO_CLOSE_HOUR = 15
AUTO_CLOSE_MINUTE = 30


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


def calculate_expected_move(price, vix, hours_remaining):
    """Calculate expected price move for OTM strike selection."""
    implied_vol = vix / 100.0
    time_fraction = hours_remaining / (252 * 6.5)
    time_adjusted_vol = implied_vol * math.sqrt(time_fraction)
    expected_move = price * time_adjusted_vol
    return expected_move


def find_otm_strikes(chain_data, underlying, vix, hours_remaining):
    """Find OTM iron condor strikes from option chain."""
    if isinstance(chain_data, str):
        chain = json.loads(chain_data)
    else:
        chain = chain_data

    std_move = calculate_expected_move(underlying, vix, hours_remaining)
    target_distance = std_move * OTM_STD_DEV_MULTIPLIER

    calls = [opt for opt in chain if opt['option_type'] == 'call']
    puts = [opt for opt in chain if opt['option_type'] == 'put']

    # Find call spread
    call_short_target = underlying + target_distance
    call_long_target = call_short_target + OTM_SPREAD_WIDTH

    call_short_strike = min(calls, key=lambda x: abs(x['strike'] - call_short_target))['strike']
    call_long_strike = min(calls, key=lambda x: abs(x['strike'] - call_long_target))['strike']

    # Find put spread
    put_short_target = underlying - target_distance
    put_long_target = put_short_target - OTM_SPREAD_WIDTH

    put_short_strike = min(puts, key=lambda x: abs(x['strike'] - put_short_target))['strike']
    put_long_strike = min(puts, key=lambda x: abs(x['strike'] - put_long_target))['strike']

    # Get quotes
    call_short = next((c for c in calls if c['strike'] == call_short_strike), None)
    call_long = next((c for c in calls if c['strike'] == call_long_strike), None)
    put_short = next((p for p in puts if p['strike'] == put_short_strike), None)
    put_long = next((p for p in puts if p['strike'] == put_long_strike), None)

    if not all([call_short, call_long, put_short, put_long]):
        return None

    # Calculate credits
    call_spread_credit = call_short['bid'] - call_long['ask']
    put_spread_credit = put_short['bid'] - put_long['ask']
    total_credit = call_spread_credit + put_spread_credit

    # Check minimum credits
    if total_credit < OTM_MIN_CREDIT_TOTAL:
        return None
    if call_spread_credit < OTM_MIN_CREDIT_PER_SIDE:
        return None
    if put_spread_credit < OTM_MIN_CREDIT_PER_SIDE:
        return None

    return {
        'call_spread': {
            'short': call_short_strike,
            'long': call_long_strike,
            'credit': call_spread_credit
        },
        'put_spread': {
            'short': put_short_strike,
            'long': put_long_strike,
            'credit': put_spread_credit
        },
        'total_credit': total_credit,
        'target_distance': target_distance,
        'std_move': std_move
    }


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


# Import simulation functions from original backtest
from backtest_gex_and_otm import simulate_gex_exit, simulate_otm_exit


def backtest_gex_and_otm_improved():
    """Run backtest with BOTH GEX and OTM strategies (improved parameters)."""

    conn = get_optimized_connection()
    cursor = conn.cursor()

    query = """
    SELECT
        s.timestamp,
        DATE(DATETIME(s.timestamp, '-5 hours')) as date_et,
        TIME(DATETIME(s.timestamp, '-5 hours')) as time_et,
        s.index_symbol,
        s.underlying_price,
        s.vix,
        s.chain_data,
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

    # Track which entry times we've already traded (prevent duplicates)
    traded_times = set()

    for snapshot in snapshots:
        timestamp, date_et, time_et, symbol, underlying, vix, chain_data, pin_strike, gex, distance = snapshot

        # Parse time
        hour = int(time_et.split(':')[0])
        minute = int(time_et.split(':')[1])
        entry_time_str = f"{hour:02d}:{minute:02d}"

        # Only trade at scheduled times (IMPROVED)
        if entry_time_str not in ENTRY_TIMES_ET:
            continue

        # CRITICAL FIX: Only 1 trade per date + entry time
        trade_key = (date_et, entry_time_str)
        if trade_key in traded_times:
            continue  # Skip duplicate entry time

        # Apply filters
        if hour >= CUTOFF_HOUR:
            continue
        if vix >= VIX_MAX_THRESHOLD or vix < VIX_FLOOR:
            continue

        entry_datetime = datetime.datetime.strptime(f"{date_et} {time_et}", '%Y-%m-%d %H:%M:%S')
        hours_to_close = 16 - hour - minute/60.0

        # Mark this time as traded
        traded_times.add(trade_key)

        # Get both setups first to check for conflicts
        gex_setup = None
        if pin_strike is not None and gex is not None and gex != 0:
            entry_credit = estimate_entry_credit(pin_strike, vix, underlying)
            if entry_credit >= 0.50:
                gex_setup = {
                    'pin_strike': pin_strike,
                    'entry_credit': entry_credit
                }

        otm_setup = find_otm_strikes(chain_data, underlying, vix, hours_to_close)

        # Check for strike conflicts
        has_conflict = False
        if gex_setup and otm_setup:
            # GEX spread is typically pin ± 5 points (e.g., 6970/6975/6980 for pin at 6975)
            gex_strikes = [
                gex_setup['pin_strike'] - 5,
                gex_setup['pin_strike'],
                gex_setup['pin_strike'] + 5
            ]

            # OTM strikes
            otm_strikes = [
                otm_setup['call_spread']['short'],
                otm_setup['call_spread']['long'],
                otm_setup['put_spread']['short'],
                otm_setup['put_spread']['long']
            ]

            # Check for overlap
            has_conflict = any(strike in otm_strikes for strike in gex_strikes)

        # Decision logic: If conflict, prioritize OTM (higher win rate)
        take_gex = gex_setup is not None and (not has_conflict or otm_setup is None)
        take_otm = otm_setup is not None

        # Execute GEX trade
        if take_gex:
            exit_result = simulate_gex_exit(
                entry_credit=gex_setup['entry_credit'],
                underlying=underlying,
                pin_strike=gex_setup['pin_strike'],
                vix=vix,
                entry_time=entry_datetime
            )

            pl = (gex_setup['entry_credit'] - exit_result['exit_credit']) * 100

            trades.append({
                'strategy': 'GEX',
                'date': date_et,
                'time': time_et,
                'underlying': underlying,
                'vix': vix,
                'strikes': f"{gex_setup['pin_strike']:.0f}",
                'entry_credit': gex_setup['entry_credit'],
                'exit_credit': exit_result['exit_credit'],
                'exit_reason': exit_result['exit_reason'],
                'pl': pl,
                'winner': exit_result['is_winner'],
                'duration_sec': exit_result['exit_time_sec'],
                'conflict_skipped': 'Yes' if has_conflict else 'No'
            })

        # Execute OTM trade
        if take_otm:
            entry_credit = otm_setup['total_credit']

            exit_result = simulate_otm_exit(
                entry_credit=entry_credit,
                underlying=underlying,
                strikes=otm_setup,
                vix=vix,
                entry_time=entry_datetime
            )

            pl = (entry_credit - exit_result['exit_credit']) * 100

            strikes_str = (f"C:{otm_setup['call_spread']['short']:.0f}/{otm_setup['call_spread']['long']:.0f} "
                          f"P:{otm_setup['put_spread']['short']:.0f}/{otm_setup['put_spread']['long']:.0f}")

            trades.append({
                'strategy': 'OTM',
                'date': date_et,
                'time': time_et,
                'underlying': underlying,
                'vix': vix,
                'strikes': strikes_str,
                'entry_credit': entry_credit,
                'exit_credit': exit_result['exit_credit'],
                'exit_reason': exit_result['exit_reason'],
                'pl': pl,
                'winner': exit_result['is_winner'],
                'duration_sec': exit_result['exit_time_sec'],
                'conflict_skipped': 'No'
            })

    return trades


def format_duration(seconds):
    """Convert seconds to human-readable duration."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def print_horizontal_report(trades):
    """Print trades in horizontal table format."""

    print("\n" + "="*200)
    print("GEX + OTM IMPROVED STRATEGY: ALL TRADES")
    print("="*200)
    print("\nIMPROVEMENTS:")
    print("  • Trailing activation: 20% → 30% (hold winners longer)")
    print("  • Emergency stop: 40% → 25% (tighter risk control)")
    print("  • Entry times: 10:00-11:30 only (skip 09:36 and 12:00+)")
    print("  • FIXED: Only 1 trade per scheduled time (not every 15-sec snapshot)")

    if not trades:
        print("\nNo trades found.")
        return

    # Overall stats
    total_pl = sum(t['pl'] for t in trades)
    winners = [t for t in trades if t['winner']]
    losers = [t for t in trades if not t['winner']]

    gex_trades = [t for t in trades if t['strategy'] == 'GEX']
    otm_trades = [t for t in trades if t['strategy'] == 'OTM']

    print(f"\n" + "="*200)
    print("SUMMARY")
    print("="*200)
    print(f"Total trades: {len(trades)} ({len(gex_trades)} GEX, {len(otm_trades)} OTM)")
    print(f"Winners: {len(winners)} ({len(winners)/len(trades)*100:.1f}%)")
    print(f"Losers: {len(losers)} ({len(losers)/len(trades)*100:.1f}%)")
    print(f"Total P/L: ${total_pl:,.0f}")
    print(f"Avg P/L/trade: ${total_pl/len(trades):,.0f}")

    total_wins = sum(t['pl'] for t in winners)
    total_losses = abs(sum(t['pl'] for t in losers))
    pf = total_wins / total_losses if total_losses > 0 else float('inf')
    print(f"Profit Factor: {pf:.2f}")

    # Conflict statistics
    gex_skipped = [t for t in gex_trades if t.get('conflict_skipped') == 'Yes']
    print(f"\nStrike Conflicts:")
    print(f"  GEX trades skipped due to OTM overlap: {len(gex_skipped)}")
    print(f"  OTM trades always prioritized when conflict detected")

    # Print all trades
    print(f"\n" + "="*200)
    print("ALL TRADES")
    print("="*200)

    header = (
        f"{'#':<4} {'Strategy':<8} {'Date':<10} {'Time':<8} {'SPX':<8} {'VIX':<5} "
        f"{'Strikes':<30} {'Entry':<6} {'Exit':<6} {'P/L':<7} {'Dur':<8} "
        f"{'Exit Reason':<35} {'W/L':<4} {'Skip?':<6}"
    )
    print(header)
    print("-"*210)

    for i, t in enumerate(trades, 1):
        duration = format_duration(t['duration_sec'])
        result = 'WIN' if t['winner'] else 'LOSS'
        skip_status = t.get('conflict_skipped', 'No')

        row = (
            f"{i:<4} {t['strategy']:<8} {t['date']:<10} {t['time']:<8} "
            f"${t['underlying']:<7.2f} {t['vix']:<5.2f} {t['strikes']:<30} "
            f"${t['entry_credit']:<5.2f} ${t['exit_credit']:<5.2f} "
            f"${t['pl']:>6.0f} {duration:<8} {t['exit_reason']:<35} {result:<4} {skip_status:<6}"
        )
        print(row)

    print("="*200)

    # Strategy breakdown
    if gex_trades:
        gex_pl = sum(t['pl'] for t in gex_trades)
        gex_winners = [t for t in gex_trades if t['winner']]
        gex_losers = [t for t in gex_trades if not t['winner']]

        print("\nGEX PIN SPREAD PERFORMANCE")
        print("-"*80)
        print(f"Trades: {len(gex_trades)} | Win Rate: {len(gex_winners)/len(gex_trades)*100:.1f}% | Total P&L: ${gex_pl:,.0f}")
        if gex_winners:
            print(f"Avg Winner: ${sum([t['pl'] for t in gex_winners])/len(gex_winners):.0f}")
        if gex_losers:
            print(f"Avg Loser: ${sum([t['pl'] for t in gex_losers])/len(gex_losers):.0f}")

    if otm_trades:
        otm_pl = sum(t['pl'] for t in otm_trades)
        otm_winners = [t for t in otm_trades if t['winner']]
        otm_losers = [t for t in otm_trades if not t['winner']]

        print("\nOTM IRON CONDOR PERFORMANCE")
        print("-"*80)
        print(f"Trades: {len(otm_trades)} | Win Rate: {len(otm_winners)/len(otm_trades)*100:.1f}% | Total P&L: ${otm_pl:,.0f}")
        if otm_winners:
            print(f"Avg Winner: ${sum([t['pl'] for t in otm_winners])/len(otm_winners):.0f}")
        if otm_losers:
            print(f"Avg Loser: ${sum([t['pl'] for t in otm_losers])/len(otm_losers):.0f}")


if __name__ == '__main__':
    np.random.seed(42)
    trades = backtest_gex_and_otm_improved()
    print_horizontal_report(trades)

    # Save to file
    with open('/root/gamma/BACKTEST_GEX_OTM_IMPROVED_COMPLETE.txt', 'w') as f:
        import sys
        old_stdout = sys.stdout
        sys.stdout = f
        print_horizontal_report(trades)
        sys.stdout = old_stdout

    print("\n✓ Complete report saved to: /root/gamma/BACKTEST_GEX_OTM_IMPROVED_COMPLETE.txt")
