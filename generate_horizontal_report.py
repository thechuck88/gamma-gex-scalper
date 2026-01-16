#!/usr/bin/env python3
"""
Generate horizontal table format for backtest trades.
"""

import numpy as np
from backtest_gex_and_otm import backtest_gex_and_otm

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
    print("GEX + OTM BACKTEST: Complete Strategy Test")
    print("="*200)
    print("\nDatabase: /root/gamma/data/gex_blackbox.db")
    print("Period: Jan 14-16, 2026 (3 trading days)")
    print("Entry times: 09:36, 10:00, 10:30, 11:00, 11:30, 12:00, 12:30, 13:00")

    if not trades:
        print("\nNo trades matched criteria.")
        return

    # Overall stats
    total_pl = sum(t['pl'] for t in trades)
    winners = [t for t in trades if t['winner']]
    losers = [t for t in trades if not t['winner']]

    print(f"\n" + "="*200)
    print("OVERALL RESULTS")
    print("="*200)
    print(f"Total trades: {len(trades)} ({len(winners)} winners, {len(losers)} losers)")
    print(f"Win Rate: {len(winners)/len(trades)*100:.1f}%")
    print(f"Total P&L: ${total_pl:,.0f}")
    print(f"Avg P/L/trade: ${total_pl/len(trades):,.0f}")

    # Print all trades in horizontal format
    print(f"\n" + "="*200)
    print("ALL TRADES (Horizontal Table)")
    print("="*200)

    # Header
    header = (
        f"{'#':<4} {'Strategy':<16} {'Date':<10} {'Time':<8} {'SPX':<8} {'VIX':<5} "
        f"{'Strikes':<30} {'Entry':<6} {'Exit':<6} {'P/L':<7} {'Dur':<8} {'Exit Reason':<30} {'W/L':<4}"
    )
    print(header)
    print("-"*200)

    # Trade rows
    for i, t in enumerate(trades, 1):
        duration = format_duration(t['duration_sec'])
        result = 'WIN' if t['winner'] else 'LOSS'

        row = (
            f"{i:<4} {t['strategy']:<16} {t['date']:<10} {t['time']:<8} "
            f"${t['underlying']:<7.2f} {t['vix']:<5.2f} {t['strikes']:<30} "
            f"${t['entry_credit']:<5.2f} ${t['exit_credit']:<5.2f} "
            f"${t['pl']:>6.0f} {duration:<8} {t['exit_reason']:<30} {result:<4}"
        )
        print(row)

    print("="*200)

    # Strategy breakdown
    gex_trades = [t for t in trades if t['strategy'] == 'GEX PIN']
    otm_trades = [t for t in trades if t['strategy'] == 'OTM IRON CONDOR']

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
    trades = backtest_gex_and_otm()
    print_horizontal_report(trades)

    # Save to file
    with open('/root/gamma/BACKTEST_ALL_TRADES_HORIZONTAL.txt', 'w') as f:
        import sys
        from io import StringIO
        old_stdout = sys.stdout
        sys.stdout = f
        print_horizontal_report(trades)
        sys.stdout = old_stdout

    print("\n✓ Horizontal report saved to: /root/gamma/BACKTEST_ALL_TRADES_HORIZONTAL.txt")
