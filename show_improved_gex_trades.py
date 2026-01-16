#!/usr/bin/env python3
"""
Show improved GEX trades in horizontal table format.
"""

import numpy as np
from backtest_gex_improved import backtest_gex_improved

def format_duration(seconds):
    """Convert seconds to human-readable duration."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"

def print_horizontal_trades(trades):
    """Print trades in horizontal table format."""

    print("\n" + "="*180)
    print("GEX IMPROVED STRATEGY: ALL TRADES (Horizontal Table)")
    print("="*190)
    print("\nIMPROVEMENTS:")
    print("  • Trailing activation: 20% → 30% (hold winners longer)")
    print("  • Emergency stop: 40% → 25% (tighter risk control)")
    print("  • Skip entries before 10:00 AM (avoid low-probability setups)")

    if not trades:
        print("\nNo trades found.")
        return

    # Overall stats
    total_pl = sum(t['pl'] for t in trades)
    winners = [t for t in trades if t['winner']]
    losers = [t for t in trades if not t['winner']]

    print(f"\n" + "="*180)
    print("SUMMARY")
    print("="*190)
    print(f"Total trades: {len(trades)} ({len(winners)} winners, {len(losers)} losers)")
    print(f"Win Rate: {len(winners)/len(trades)*100:.1f}%")
    print(f"Total P/L: ${total_pl:,.0f}")
    print(f"Avg P/L/trade: ${total_pl/len(trades):,.0f}")

    total_wins = sum(t['pl'] for t in winners)
    total_losses = abs(sum(t['pl'] for t in losers))
    pf = total_wins / total_losses if total_losses > 0 else float('inf')
    print(f"Profit Factor: {pf:.2f}")

    # Print all trades in horizontal format
    print(f"\n" + "="*180)
    print("ALL TRADES")
    print("="*190)

    # Header
    header = (
        f"{'#':<4} {'Strategy':<8} {'Date':<10} {'Time':<8} {'SPX':<8} {'VIX':<5} "
        f"{'Strike':<7} {'Entry':<6} {'Exit':<6} {'P/L':<7} {'Dur':<8} {'Exit Reason':<35} {'W/L':<4}"
    )
    print(header)
    print("-"*190)

    # Trade rows
    for i, t in enumerate(trades, 1):
        duration = format_duration(t['duration_sec'])
        result = 'WIN' if t['winner'] else 'LOSS'

        row = (
            f"{i:<4} {'GEX':<8} {t['date']:<10} {t['time']:<8} "
            f"${t['underlying']:<7.2f} {t['vix']:<5.2f} {t['strikes']:<7} "
            f"${t['entry_credit']:<5.2f} ${t['exit_credit']:<5.2f} "
            f"${t['pl']:>6.0f} {duration:<8} {t['exit_reason']:<35} {result:<4}"
        )
        print(row)

    print("="*190)

    # Daily breakdown
    print("\nDAILY BREAKDOWN")
    print("-"*80)

    dates = sorted(set(t['date'] for t in trades))
    for date in dates:
        day_trades = [t for t in trades if t['date'] == date]
        day_winners = [t for t in day_trades if t['winner']]
        day_losers = [t for t in day_trades if not t['winner']]
        day_pl = sum(t['pl'] for t in day_trades)
        day_wr = len(day_winners) / len(day_trades) * 100

        print(f"{date}: {len(day_trades):>2} trades ({len(day_winners)}W/{len(day_losers)}L), "
              f"{day_wr:>4.1f}% WR, ${day_pl:>6.0f} total")

    # Entry time breakdown
    print("\nENTRY TIME BREAKDOWN")
    print("-"*80)

    entry_times = sorted(set(t['time'][:5] for t in trades))
    for entry_time in entry_times:
        time_trades = [t for t in trades if t['time'].startswith(entry_time)]
        time_winners = [t for t in time_trades if t['winner']]
        time_losers = [t for t in time_trades if not t['winner']]
        time_pl = sum(t['pl'] for t in time_trades)
        time_wr = len(time_winners) / len(time_trades) * 100

        print(f"{entry_time}: {len(time_trades):>2} trades ({len(time_winners)}W/{len(time_losers)}L), "
              f"{time_wr:>4.1f}% WR, ${time_pl:>6.0f} total, ${time_pl/len(time_trades):>4.0f} avg")


if __name__ == '__main__':
    np.random.seed(42)
    trades = backtest_gex_improved()
    print_horizontal_trades(trades)

    # Save to file
    with open('/root/gamma/BACKTEST_GEX_IMPROVED_TRADES.txt', 'w') as f:
        import sys
        old_stdout = sys.stdout
        sys.stdout = f
        print_horizontal_trades(trades)
        sys.stdout = old_stdout

    print("\n✓ Detailed trades saved to: /root/gamma/BACKTEST_GEX_IMPROVED_TRADES.txt")
