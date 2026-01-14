#!/usr/bin/env python3
"""
Export detailed trade data to CSV for review

Creates a CSV file with all trade details including:
- Entry/exit times
- Strikes
- Credits
- P/L
- Exit reasons
- Minute-by-minute price tracking

Usage:
    python3 export_trades_detailed.py                    # ALL available dates (default)
    python3 export_trades_detailed.py 2026-01-12         # Specific date
    python3 export_trades_detailed.py 2026-01-12 out.csv # Specific date, custom output
"""

import sys
import csv
from datetime import datetime

sys.path.insert(0, '/root/gamma')
from backtest_report import run_backtest_silent
from gex_blackbox_recorder import get_optimized_connection


def export_trades_to_csv(test_date, output_file):
    """Export all trades to CSV with detailed information."""

    # Run backtests
    print(f"Running backtest for {test_date}...")
    spx_trades = run_backtest_silent(test_date, 'SPX')
    ndx_trades = run_backtest_silent(test_date, 'NDX')

    all_trades = spx_trades + ndx_trades

    if not all_trades:
        print(f"No trades found for {test_date}")
        return

    # Sort by entry time
    all_trades.sort(key=lambda t: t['entry_time'])

    # Write to CSV
    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)

        # Header
        writer.writerow([
            'Trade_Num',
            'Index',
            'Entry_Time_ET',
            'Exit_Time_ET',
            'Duration_Min',
            'Strategy',
            'Strikes',
            'Entry_Credit',
            'Exit_Value',
            'PL_Dollars',
            'PL_Percent',
            'Exit_Reason',
            'Best_Profit_Pct',
            'Pin_Strike'
        ])

        # Write trades
        for i, trade in enumerate(all_trades, 1):
            # Convert times to ET for display
            entry_et = trade['entry_time'].replace(tzinfo=None)  # Already converted in report
            exit_et = trade['exit_time'].replace(tzinfo=None)

            writer.writerow([
                i,
                trade['index'],
                entry_et.strftime('%Y-%m-%d %H:%M:%S'),
                exit_et.strftime('%Y-%m-%d %H:%M:%S'),
                f"{trade['duration_min']:.1f}",
                trade['strategy'],
                trade['strikes'],
                f"{trade['entry_credit']:.2f}",
                f"{trade['exit_value']:.2f}",
                f"{trade['pnl_dollars']:.2f}",
                f"{trade['pnl_pct']:.1f}",
                trade['exit_reason'],
                f"{trade['best_profit_pct']:.1f}",
                f"{trade['pin_strike']:.0f}"
            ])

    print(f"\n✓ Exported {len(all_trades)} trades to {output_file}")

    # Summary
    winners = [t for t in all_trades if t['pnl_dollars'] > 0]
    losers = [t for t in all_trades if t['pnl_dollars'] <= 0]
    total_pl = sum(t['pnl_dollars'] for t in all_trades)

    print(f"\nSummary:")
    print(f"  Total Trades: {len(all_trades)}")
    print(f"  Winners: {len(winners)} ({len(winners)/len(all_trades)*100:.1f}%)")
    print(f"  Losers: {len(losers)}")
    print(f"  Total P/L: ${total_pl:+,.2f}")


def export_all_dates_to_csv(output_file):
    """Export all available dates to a single CSV."""
    # Get all available dates
    conn = get_optimized_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT DATE(timestamp) as trade_date
        FROM options_prices_live
        ORDER BY trade_date ASC
    """)
    dates = [datetime.strptime(row[0], '%Y-%m-%d').date() for row in cursor.fetchall()]
    conn.close()

    if not dates:
        print(f"No data found in database")
        return

    print(f"Running backtest for {len(dates)} days ({dates[0]} to {dates[-1]})...")

    # Collect all trades from all dates
    all_trades = []
    for test_date in dates:
        spx_trades = run_backtest_silent(test_date, 'SPX')
        ndx_trades = run_backtest_silent(test_date, 'NDX')
        all_trades.extend(spx_trades + ndx_trades)

    if not all_trades:
        print(f"No trades found")
        return

    # Sort by entry time
    all_trades.sort(key=lambda t: t['entry_time'])

    # Write to CSV
    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)

        # Header
        writer.writerow([
            'Trade_Num',
            'Index',
            'Entry_Time_ET',
            'Exit_Time_ET',
            'Duration_Min',
            'Strategy',
            'Strikes',
            'Entry_Credit',
            'Exit_Value',
            'PL_Dollars',
            'PL_Percent',
            'Exit_Reason',
            'Best_Profit_Pct',
            'Pin_Strike'
        ])

        # Write trades
        for i, trade in enumerate(all_trades, 1):
            # Convert times to ET for display
            entry_et = trade['entry_time'].replace(tzinfo=None)
            exit_et = trade['exit_time'].replace(tzinfo=None)

            writer.writerow([
                i,
                trade['index'],
                entry_et.strftime('%Y-%m-%d %H:%M:%S'),
                exit_et.strftime('%Y-%m-%d %H:%M:%S'),
                f"{trade['duration_min']:.1f}",
                trade['strategy'],
                trade['strikes'],
                f"{trade['entry_credit']:.2f}",
                f"{trade['exit_value']:.2f}",
                f"{trade['pnl_dollars']:.2f}",
                f"{trade['pnl_pct']:.1f}",
                trade['exit_reason'],
                f"{trade['best_profit_pct']:.1f}",
                f"{trade['pin_strike']:.0f}"
            ])

    print(f"\n✓ Exported {len(all_trades)} trades to {output_file}")

    # Summary
    winners = [t for t in all_trades if t['pnl_dollars'] > 0]
    losers = [t for t in all_trades if t['pnl_dollars'] <= 0]
    total_pl = sum(t['pnl_dollars'] for t in all_trades)

    print(f"\nSummary:")
    print(f"  Total Trades: {len(all_trades)}")
    print(f"  Winners: {len(winners)} ({len(winners)/len(all_trades)*100:.1f}%)")
    print(f"  Losers: {len(losers)}")
    print(f"  Total P/L: ${total_pl:+,.2f}")


def main():
    # Default: Export ALL available dates
    if len(sys.argv) > 1:
        # Specific date provided
        test_date = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()

        if len(sys.argv) > 2:
            output_file = sys.argv[2]
        else:
            output_file = f"/root/gamma/data/trades_{test_date.strftime('%Y%m%d')}.csv"

        export_trades_to_csv(test_date, output_file)
    else:
        # No arguments: Export all available dates to one file
        output_file = "/root/gamma/data/trades_all.csv"
        export_all_dates_to_csv(output_file)


if __name__ == '__main__':
    main()
