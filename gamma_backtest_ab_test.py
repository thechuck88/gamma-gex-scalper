#!/usr/bin/env python3
"""
Gamma A-B Test: Compare backtest with and without Market Veto Cache

Uses on-demand Claude API caching (same system as stock bot).
"""

import sqlite3
import datetime
import numpy as np
from collections import defaultdict
import sys
sys.path.insert(0, '/root/gamma')

from market_veto_cache import MarketVetoCache

DB_PATH = "/root/gamma/data/gex_blackbox.db"

# ============================================================================
# STRATEGY PARAMETERS
# ============================================================================

PROFIT_TARGET_HIGH = 0.50
PROFIT_TARGET_MEDIUM = 0.70
STOP_LOSS_PCT = 0.10
VIX_MAX_THRESHOLD = 20
VIX_FLOOR = 13.0

TRAILING_STOP_ENABLED = True
TRAILING_TRIGGER_PCT = 0.20
TRAILING_LOCK_IN_PCT = 0.12
TRAILING_DISTANCE_MIN = 0.08

ENTRY_TIMES_ET = [
    "09:36", "10:00", "10:30", "11:00",
    "11:30", "12:00", "12:30", "13:00"
]

CUTOFF_HOUR = 13  # Stop after 1 PM ET


def get_optimized_connection():
    """Get SQLite connection with optimizations."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA cache_size = -128000")  # 128MB cache
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def estimate_entry_credit(pin_strike, vix, underlying_price):
    """Estimate entry credit based on distance and VIX."""
    distance_pct = abs(pin_strike - underlying_price) / underlying_price * 100

    # Base credit: $2.50 baseline
    base_credit = 2.50

    # Adjust for VIX (higher VIX = higher premium)
    vix_multiplier = max(0.5, min(2.0, vix / 15.0))

    # Adjust for distance (farther = less credit)
    distance_factor = max(0.3, 1.0 - (distance_pct / 2.0))

    credit = base_credit * vix_multiplier * distance_factor
    return max(0.50, min(5.00, credit))


def simulate_exit(entry_credit, underlying, pin_strike, vix, days_held=0):
    """Simulate realistic exit scenarios."""

    # Probability of hitting profit target
    distance_pct = abs(pin_strike - underlying) / underlying * 100

    # Closer to pin = higher win rate
    if distance_pct < 0.5:
        win_prob = 0.75
    elif distance_pct < 1.0:
        win_prob = 0.65
    elif distance_pct < 1.5:
        win_prob = 0.55
    else:
        win_prob = 0.45

    # VIX affects slippage
    vix_factor = max(0.8, min(1.2, vix / 15.0))

    # Random outcome
    if np.random.random() < win_prob:
        # Winner: Exit at profit target
        target = PROFIT_TARGET_HIGH if distance_pct < 1.0 else PROFIT_TARGET_MEDIUM
        exit_credit = entry_credit * (1 - target) * vix_factor
        return exit_credit, f"Profit Target ({target*100:.0f}%)", True
    else:
        # Loser: Exit at stop loss
        exit_credit = entry_credit * (1 + STOP_LOSS_PCT) * vix_factor
        return exit_credit, f"Stop Loss ({STOP_LOSS_PCT*100:.0f}%)", False


def run_backtest(with_veto=False, days=7):
    """Run backtest with or without veto blocks."""

    # Initialize veto cache if enabled
    veto_cache = MarketVetoCache() if with_veto else None

    conn = get_optimized_connection()
    cursor = conn.cursor()

    # Get all SPX snapshots with real GEX PIN data (limited by days)
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
      AND s.timestamp >= datetime('now', '-{} days')
    ORDER BY s.timestamp ASC
    """.format(days)

    cursor.execute(query)
    snapshots = cursor.fetchall()
    conn.close()

    trades = []
    vetoed_trades = []

    for snapshot in snapshots:
        timestamp, date_et, time_et, symbol, underlying, vix, pin_strike, gex, distance = snapshot

        # Apply standard filters
        hour = int(time_et.split(':')[0])
        minute = int(time_et.split(':')[1])
        entry_time = f"{hour:02d}:{minute:02d}"

        if entry_time not in ENTRY_TIMES_ET:
            continue
        if hour >= CUTOFF_HOUR:
            continue
        if vix >= VIX_MAX_THRESHOLD or vix < VIX_FLOOR:
            continue
        if pin_strike is None or gex is None or gex == 0:
            continue

        # Check veto if enabled (ON-DEMAND CLAUDE CALL)
        if with_veto:
            # Convert timestamp to datetime (UTC) and convert to ET
            dt_utc = datetime.datetime.fromisoformat(timestamp)
            dt_et = dt_utc - datetime.timedelta(hours=5)  # UTC to ET

            should_block, reason = veto_cache.should_block_trading(dt_et, market="options")

            if should_block:
                vetoed_trades.append({
                    'date': date_et,
                    'time': time_et,
                    'timestamp': timestamp,
                    'reason': reason,
                    'vix': vix,
                    'pin_strike': pin_strike
                })
                continue

        # Entry
        entry_credit = estimate_entry_credit(pin_strike, vix, underlying)
        if entry_credit < 0.50:
            continue

        # Exit (simulate realistic outcome)
        exit_credit, exit_reason, is_winner = simulate_exit(
            entry_credit, underlying, pin_strike, vix, days_held=0
        )

        # P&L calculation
        width = 5.0
        pl = (entry_credit - exit_credit) * 100  # Per contract P&L

        trades.append({
            'date': date_et,
            'time': time_et,
            'pin_strike': pin_strike,
            'underlying': underlying,
            'vix': vix,
            'entry_credit': entry_credit,
            'exit_credit': exit_credit,
            'exit_reason': exit_reason,
            'pl': pl,
            'winner': is_winner,
            'gex': gex,
        })

    # Get veto cache stats
    veto_stats = veto_cache.get_stats() if veto_cache else {}

    return trades, vetoed_trades, veto_stats


def print_comparison_report(baseline_trades, veto_trades, vetoed_list, veto_stats):
    """Print side-by-side comparison of baseline vs veto performance."""

    print("\n" + "="*100)
    print("GAMMA BACKTEST: A-B TEST WITH MARKET VETO CACHE")
    print("="*100)
    print()

    # Baseline stats
    baseline_pnl = sum(t['pl'] for t in baseline_trades)
    baseline_wins = sum(1 for t in baseline_trades if t['winner'])
    baseline_losses = len(baseline_trades) - baseline_wins
    baseline_wr = (baseline_wins / len(baseline_trades) * 100) if baseline_trades else 0

    # Veto stats
    veto_pnl = sum(t['pl'] for t in veto_trades)
    veto_wins = sum(1 for t in veto_trades if t['winner'])
    veto_losses = len(veto_trades) - veto_wins
    veto_wr = (veto_wins / len(veto_trades) * 100) if veto_trades else 0

    # Comparison
    print(f"{'Metric':<25} {'Without Veto (A)':<20} {'With Veto (B)':<20} {'Change':<15}")
    print("-" * 80)
    print(f"{'Total P&L':<25} ${baseline_pnl:>18,.2f} ${veto_pnl:>18,.2f} ${veto_pnl - baseline_pnl:>+13,.2f}")
    print(f"{'Total Trades':<25} {len(baseline_trades):>18,} {len(veto_trades):>18,} {len(veto_trades) - len(baseline_trades):>+13,}")
    print(f"{'Win Rate':<25} {baseline_wr:>17.1f}% {veto_wr:>17.1f}% {veto_wr - baseline_wr:>+12.1f}%")
    print()

    # Veto cache statistics
    if veto_stats:
        print(f"Veto Statistics:")
        print(f"  Signals vetoed: {len(vetoed_list)}")
        print(f"  Cache hit rate: {veto_stats.get('hit_rate_pct', 0):.1f}%")
        print(f"  API cost: ${veto_stats.get('cost_spent', 0):.4f}")
        print()

    # Sample vetoed trades
    if vetoed_list:
        print(f"Sample Vetoed Signals (first 5):")
        for veto in vetoed_list[:5]:
            print(f"  {veto['date']} {veto['time']}: SPX @ ${veto['pin_strike']:.0f} (VIX {veto['vix']:.1f})")
            print(f"    Reason: {veto['reason'][:70]}...")
        print()

    # Impact analysis
    pnl_change_pct = ((veto_pnl - baseline_pnl) / abs(baseline_pnl) * 100) if baseline_pnl != 0 else 0
    print(f"Impact Analysis:")
    print(f"  P&L Change: ${veto_pnl - baseline_pnl:+,.2f} ({pnl_change_pct:+.1f}%)")
    print(f"  Trades Reduced: {len(baseline_trades) - len(veto_trades)} ({(len(baseline_trades) - len(veto_trades)) / len(baseline_trades) * 100:.1f}%)")

    if veto_pnl > baseline_pnl:
        print(f"  ✅ VETO IMPROVED P&L by ${veto_pnl - baseline_pnl:,.2f}")
    elif veto_pnl < baseline_pnl:
        print(f"  ❌ VETO REDUCED P&L by ${baseline_pnl - veto_pnl:,.2f}")
    else:
        print(f"  ➖ VETO HAD NO IMPACT on P&L")

    print()
    print("="*100)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Gamma A-B test with market veto cache')
    parser.add_argument('--days', type=int, default=7, help='Number of days to backtest')
    args = parser.parse_args()

    np.random.seed(42)  # Reproducible results

    print(f"\n🔍 Running A-B test on {args.days} days of Gamma data...\n")

    # Run baseline
    print("Running VERSION A (no veto)...")
    baseline_trades, _, _ = run_backtest(with_veto=False, days=args.days)

    # Run with veto
    print("Running VERSION B (with veto)...")
    veto_trades, vetoed_list, veto_stats = run_backtest(with_veto=True, days=args.days)

    # Print comparison
    print_comparison_report(baseline_trades, veto_trades, vetoed_list, veto_stats)
