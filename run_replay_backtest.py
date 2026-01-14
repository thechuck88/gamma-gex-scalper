#!/usr/bin/env python3
"""
run_replay_backtest.py - Simple entry point for replay harness backtest

Usage:
    python run_replay_backtest.py --date 2026-01-12              # Single day
    python run_replay_backtest.py --start 2026-01-12 --end 2026-01-13  # Date range
    python run_replay_backtest.py --symbol NDX                    # NDX instead of SPX
    python run_replay_backtest.py --output results.json           # Save to file
"""

import argparse
import json
from datetime import datetime, timedelta
from replay_execution import ReplayExecutionHarness


def format_results(stats: dict, period_desc: str, elapsed_seconds: float) -> str:
    """Format backtest results for display."""
    lines = [
        "\n" + "="*70,
        "REPLAY HARNESS BACKTEST RESULTS",
        "="*70,
        f"Period:              {period_desc}",
        f"Database:            /root/gamma/data/gex_blackbox.db",
        f"Execution Time:      {elapsed_seconds:.2f} seconds",
        f"\nTrade Summary:",
        f"  Total Trades:      {stats['total_trades']}",
        f"  Winners:           {stats['winning_trades']} ({stats['win_rate']*100:.1f}%)",
        f"  Losers:            {stats['losing_trades']}",
        f"  Break-Even:        {stats['break_even_trades']}",
        f"\nP&L Analysis:",
        f"  Total P&L:         ${stats['total_pnl']:+,.0f}",
        f"  Avg Win:           ${stats['avg_win']:+,.0f}",
        f"  Avg Loss:          ${stats['avg_loss']:+,.0f}",
        f"  Max Win:           ${stats['max_win']:+,.0f}",
        f"  Max Loss:          ${stats['max_loss']:+,.0f}",
        f"  Profit Factor:     {stats['profit_factor']:.2f}x",
        f"\nAccount Summary:",
        f"  Starting Balance:  ${stats['current_balance'] - stats['total_pnl']:,.0f}",
        f"  Ending Balance:    ${stats['current_balance']:,.0f}",
        f"  Return %:          {stats['return_percent']:+.2f}%",
        f"  Max Drawdown:      ${stats['max_drawdown']:+,.0f}",
        "="*70,
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='Run replay harness backtest on GEX Blackbox database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single day backtest (2026-01-12)
  python run_replay_backtest.py --date 2026-01-12

  # Date range backtest
  python run_replay_backtest.py --start 2026-01-10 --end 2026-01-13

  # NDX backtest instead of SPX
  python run_replay_backtest.py --symbol NDX --start 2026-01-12 --end 2026-01-13

  # Save results to JSON file
  python run_replay_backtest.py --date 2026-01-12 --output results.json

  # Custom VIX filter and entry credit minimum
  python run_replay_backtest.py --date 2026-01-12 --vix-floor 14 --vix-ceiling 25 --min-credit 2.0
        """
    )

    parser.add_argument(
        '--date',
        type=str,
        help='Single date to backtest (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--start',
        type=str,
        default='2026-01-12',
        help='Start date (YYYY-MM-DD), default: 2026-01-12'
    )
    parser.add_argument(
        '--end',
        type=str,
        default=None,
        help='End date (YYYY-MM-DD), default: one day after start'
    )
    parser.add_argument(
        '--symbol',
        type=str,
        choices=['SPX', 'NDX'],
        default='SPX',
        help='Index symbol: SPX (default) or NDX'
    )
    parser.add_argument(
        '--starting-balance',
        type=float,
        default=100000.0,
        help='Starting account balance, default: 100000'
    )
    parser.add_argument(
        '--vix-floor',
        type=float,
        default=12.0,
        help='Minimum VIX to trade, default: 12.0'
    )
    parser.add_argument(
        '--vix-ceiling',
        type=float,
        default=30.0,
        help='Maximum VIX to trade, default: 30.0'
    )
    parser.add_argument(
        '--min-credit',
        type=float,
        default=1.50,
        help='Minimum entry credit ($), default: 1.50'
    )
    parser.add_argument(
        '--stop-loss',
        type=float,
        default=0.10,
        help='Stop loss threshold (e.g. 0.10 for 10 percent), default: 0.10'
    )
    parser.add_argument(
        '--profit-target',
        type=float,
        default=0.50,
        help='Profit target threshold (e.g. 0.50 for 50 percent), default: 0.50'
    )
    parser.add_argument(
        '--no-trailing-stop',
        action='store_true',
        help='Disable trailing stop logic'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Output JSON file for results'
    )

    args = parser.parse_args()

    # Parse dates
    if args.date:
        start_date = datetime.strptime(args.date, '%Y-%m-%d')
        end_date = start_date + timedelta(days=1)
        period_desc = args.date
    else:
        start_date = datetime.strptime(args.start, '%Y-%m-%d')
        if args.end:
            # End date is inclusive - add 1 day to run through end of that day
            end_date = datetime.strptime(args.end, '%Y-%m-%d') + timedelta(days=1)
            period_desc = f"{args.start} to {args.end}"
        else:
            end_date = start_date + timedelta(days=1)
            period_desc = args.start

    # Add market close time (4:30 PM ET)
    end_date = end_date.replace(hour=16, minute=30, second=0)

    # Create harness
    print(f"\n[BACKTEST] Starting replay harness...")
    print(f"[BACKTEST] Index: {args.symbol}")
    print(f"[BACKTEST] Period: {period_desc}")
    print(f"[BACKTEST] VIX Range: {args.vix_floor}-{args.vix_ceiling}")
    print(f"[BACKTEST] Min Credit: ${args.min_credit:.2f}")
    print(f"[BACKTEST] Stop Loss: {args.stop_loss*100:.0f}%")
    print(f"[BACKTEST] Profit Target: {args.profit_target*100:.0f}%")
    print(f"[BACKTEST] Trailing Stop: {'Enabled' if not args.no_trailing_stop else 'Disabled'}")

    import time
    start_time = time.time()

    try:
        harness = ReplayExecutionHarness(
            db_path='/root/gamma/data/gex_blackbox.db',
            start_date=start_date,
            end_date=end_date,
            index_symbol=args.symbol,
            starting_balance=args.starting_balance,
            vix_floor=args.vix_floor,
            vix_ceiling=args.vix_ceiling,
            min_entry_credit=args.min_credit,
            stop_loss_percent=args.stop_loss,
            profit_target_percent=args.profit_target,
            trailing_stop_enabled=not args.no_trailing_stop
        )

        stats = harness.run_replay()
        elapsed = time.time() - start_time

        # Display results
        output = format_results(stats, period_desc, elapsed)
        print(output)

        # Save to file if requested
        if args.output:
            output_data = {
                'period': period_desc,
                'symbol': args.symbol,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'parameters': {
                    'starting_balance': args.starting_balance,
                    'vix_floor': args.vix_floor,
                    'vix_ceiling': args.vix_ceiling,
                    'min_credit': args.min_credit,
                    'stop_loss_percent': args.stop_loss,
                    'profit_target_percent': args.profit_target,
                    'trailing_stop_enabled': not args.no_trailing_stop
                },
                'results': stats,
                'execution_seconds': elapsed
            }

            with open(args.output, 'w') as f:
                json.dump(output_data, f, indent=2, default=str)
            print(f"\n[BACKTEST] Results saved to: {args.output}")

    except Exception as e:
        print(f"\n[ERROR] Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
