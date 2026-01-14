#!/usr/bin/env python3
"""
Generate backtest report in show.py format (styled tables, colors, summary stats)
"""

from replay_execution import ReplayExecutionHarness
from datetime import datetime
import sys

def format_pl(pl):
    """Format P/L with color (green for wins, red for losses)."""
    if pl > 0:
        return f"\033[32m${pl:>+8.2f}\033[0m"  # Green
    elif pl < 0:
        return f"\033[31m${pl:>+8.2f}\033[0m"  # Red
    return f"${pl:>+8.2f}"

def format_pct(pct):
    """Format percentage with color."""
    if pct > 0:
        return f"\033[32m{pct:>+6.1f}%\033[0m"  # Green
    elif pct < 0:
        return f"\033[31m{pct:>+6.1f}%\033[0m"  # Red
    return f"{pct:>+6.1f}%"

def show_backtest_banner(start_date, end_date, index_symbol, stats):
    """Display backtest header banner."""
    print(f"\n{'='*80}")
    print(f"  GAMMA GEX SCALPER — REPLAY HARNESS BACKTEST REPORT")
    print(f"{'='*80}")
    print(f"\n  Period:              {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print(f"  Index:               {index_symbol} (0DTE Credit Spreads)")
    print(f"  Database:            /root/gamma/data/gex_blackbox.db")
    print(f"  Data Granularity:    30-second snapshots")

    # Summary line
    wins = stats['winning_trades']
    losses = stats['losing_trades']
    total = stats['total_trades']
    wr = stats['win_rate'] * 100

    if total > 0:
        summary = f"{wins}W / {losses}L / {wr:.0f}%"
        pnl_str = format_pl(stats['total_pnl'])
        print(f"\n  Summary:             {summary:<20} | Total P&L: {pnl_str}")

    print(f"{'='*80}\n")

def show_backtest_configuration(harness):
    """Display backtest configuration parameters."""
    config = {
        'VIX Floor': f"{harness.vix_floor:.1f}",
        'VIX Ceiling': f"{harness.vix_ceiling:.1f}",
        'Min Entry Credit': f"${harness.min_entry_credit:.2f}",
        'Stop Loss': f"{harness.stop_loss_percent*100:.0f}%",
        'Profit Target': f"{harness.profit_target_percent*100:.0f}%",
        'Trailing Stop': 'Enabled' if harness.trailing_stop_enabled else 'Disabled',
        'Starting Balance': f"${harness.starting_balance:,.0f}",
    }

    print(f"  CONFIGURATION")
    print(f"  {'-'*78}")
    for key, value in config.items():
        print(f"    {key:<25} {value}")
    print()

def show_backtest_trades(harness):
    """Display trade-by-trade results like show.py format."""
    trades = harness.state_manager.get_closed_trades()

    if not trades:
        print("  No trades executed during backtest period.")
        return

    print(f"  TRADE HISTORY")
    print(f"  {'-'*78}")
    print(f"\n  {'Opened':<16} {'Closed':<16} {'Type':<8} {'Entry':>8} {'Exit':>8} {'P/L':>12} {'%':>8} {'Reason':<24}")
    print(f"  {'-'*16} {'-'*16} {'-'*8} {'-'*8} {'-'*8} {'-'*12} {'-'*8} {'-'*24}")

    for trade in trades:
        opened = trade.entry_time.strftime('%m/%d %H:%M') if trade.entry_time else '-'
        closed = trade.exit_time.strftime('%H:%M') if trade.exit_time else '-'

        # Check if expiration
        if trade.exit_reason and trade.exit_reason.value == 'EXPIRATION':
            closed = '\033[33mEXPIRED\033[0m'  # Yellow

        trade_type = f"{trade.spread_type}"
        entry_credit = f"${trade.entry_credit:.2f}"
        exit_val = f"${trade.exit_spread_value:.2f}" if trade.exit_spread_value else '-'

        # Color P/L and percentage
        pl_str = format_pl(trade.pnl_dollars) if trade.pnl_dollars else "$      0"
        pct_str = format_pct(trade.pnl_percent * 100) if trade.pnl_percent else "   0.0%"

        reason = trade.exit_reason.value if trade.exit_reason else 'N/A'
        if reason == 'EXPIRATION':
            reason = '\033[33m0DTE EXPIRED\033[0m'

        print(f"  {opened:<16} {closed:<16} {trade_type:<8} {entry_credit:>8} {exit_val:>8} {pl_str:>12} {pct_str:>8} {reason:<24}")

    print()

def show_backtest_daily_summary(harness):
    """Display daily summary breakdown."""
    trades = harness.state_manager.get_closed_trades()

    if not trades:
        return

    # Group by date
    daily_stats = {}
    for trade in trades:
        date_key = trade.entry_time.strftime('%Y-%m-%d') if trade.entry_time else 'Unknown'
        if date_key not in daily_stats:
            daily_stats[date_key] = {'trades': 0, 'wins': 0, 'pnl': 0}

        daily_stats[date_key]['trades'] += 1
        if trade.pnl_dollars > 0:
            daily_stats[date_key]['wins'] += 1
        daily_stats[date_key]['pnl'] += trade.pnl_dollars

    print(f"  DAILY BREAKDOWN")
    print(f"  {'-'*78}")
    print(f"\n  {'Date':<12} {'Trades':>6} {'Wins':>6} {'Win %':>8} {'Daily P/L':>12}")
    print(f"  {'-'*12} {'-'*6} {'-'*6} {'-'*8} {'-'*12}")

    for date_key in sorted(daily_stats.keys()):
        stats = daily_stats[date_key]
        win_pct = (stats['wins'] / stats['trades'] * 100) if stats['trades'] > 0 else 0
        daily_pnl = format_pl(stats['pnl'])
        print(f"  {date_key:<12} {stats['trades']:>6} {stats['wins']:>6} {win_pct:>7.1f}% {daily_pnl:>12}")

    print()

def show_backtest_summary(harness, stats):
    """Display comprehensive statistics summary."""
    print(f"  PERFORMANCE SUMMARY")
    print(f"  {'-'*78}")
    print(f"\n  Total Trades:")
    print(f"    {stats['total_trades']} total | {stats['winning_trades']} winners | {stats['losing_trades']} losers | {stats['break_even_trades']} break-even")

    print(f"\n  Win Rate & P/L:")
    print(f"    Win Rate:          {stats['win_rate']*100:>6.1f}%")
    print(f"    Total P/L:         {format_pl(stats['total_pnl'])}")
    print(f"    Average Win:       {format_pl(stats['avg_win'])}")
    print(f"    Average Loss:      {format_pl(stats['avg_loss'])}")
    print(f"    Largest Win:       {format_pl(stats['max_win'])}")
    print(f"    Largest Loss:      {format_pl(stats['max_loss'])}")

    print(f"\n  Risk Metrics:")
    print(f"    Profit Factor:     {stats['profit_factor']:>6.2f}x")
    print(f"    Max Drawdown:      {format_pl(stats['max_drawdown'])}")

    print(f"\n  Account:")
    print(f"    Starting Balance:  ${harness.starting_balance:>10,.2f}")
    print(f"    Ending Balance:    ${stats['current_balance']:>10,.2f}")
    print(f"    Peak Balance:      ${stats['peak_balance']:>10,.2f}")
    print(f"    Return on Capital: {stats['return_percent']:>10.2f}%")

    print()

def main():
    """Generate styled backtest report."""
    import argparse

    parser = argparse.ArgumentParser(description='Generate styled backtest report')
    parser.add_argument('--start', default='2026-01-12', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', default='2026-01-13', help='End date (YYYY-MM-DD)')
    parser.add_argument('--symbol', default='SPX', help='Index symbol (SPX or NDX)')
    parser.add_argument('--output', help='Save report to file')

    args = parser.parse_args()

    # Parse dates
    from datetime import datetime, timedelta
    start_date = datetime.strptime(args.start, '%Y-%m-%d')
    end_date = datetime.strptime(args.end, '%Y-%m-%d') + timedelta(days=1)
    end_date = end_date.replace(hour=16, minute=30)

    # Run backtest
    print(f"\n[BACKTEST] Running replay harness for {args.start} to {args.end}...")
    harness = ReplayExecutionHarness(
        db_path='/root/gamma/data/gex_blackbox.db',
        start_date=start_date,
        end_date=end_date,
        index_symbol=args.symbol,
        starting_balance=100000.0,
        vix_floor=12.0,
        vix_ceiling=30.0,
        min_entry_credit=1.50,
        stop_loss_percent=0.10,
        profit_target_percent=0.50,
        trailing_stop_enabled=True
    )

    stats = harness.run_replay()

    # Capture output if saving to file
    output_lines = []

    # Generate report
    def print_and_capture(text=''):
        print(text)
        output_lines.append(text)

    # Show banner
    show_backtest_banner(start_date, end_date, args.symbol, stats)
    output_lines.append(f"\n{'='*80}")
    output_lines.append(f"  GAMMA GEX SCALPER — REPLAY HARNESS BACKTEST REPORT")
    output_lines.append(f"{'='*80}")
    output_lines.append(f"\n  Period:              {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    output_lines.append(f"  Index:               {args.symbol} (0DTE Credit Spreads)")
    output_lines.append(f"  Database:            /root/gamma/data/gex_blackbox.db")
    output_lines.append(f"  Data Granularity:    30-second snapshots")

    wins = stats['winning_trades']
    losses = stats['losing_trades']
    total = stats['total_trades']
    wr = stats['win_rate'] * 100

    if total > 0:
        summary = f"{wins}W / {losses}L / {wr:.0f}%"
        pnl_val = stats['total_pnl']
        if pnl_val > 0:
            pnl_str = f"${pnl_val:>+8.2f}"
        else:
            pnl_str = f"${pnl_val:>+8.2f}"
        output_lines.append(f"\n  Summary:             {summary:<20} | Total P&L: {pnl_str}")

    output_lines.append(f"{'='*80}\n")

    # Configuration
    show_backtest_configuration(harness)
    output_lines.append(f"  CONFIGURATION")
    output_lines.append(f"  {'-'*78}")
    output_lines.append(f"    {'VIX Floor':<25} {harness.vix_floor:.1f}")
    output_lines.append(f"    {'VIX Ceiling':<25} {harness.vix_ceiling:.1f}")
    output_lines.append(f"    {'Min Entry Credit':<25} ${harness.min_entry_credit:.2f}")
    output_lines.append(f"    {'Stop Loss':<25} {harness.stop_loss_percent*100:.0f}%")
    output_lines.append(f"    {'Profit Target':<25} {harness.profit_target_percent*100:.0f}%")
    output_lines.append(f"    {'Trailing Stop':<25} {'Enabled' if harness.trailing_stop_enabled else 'Disabled'}")
    output_lines.append(f"    {'Starting Balance':<25} ${harness.starting_balance:,.0f}")
    output_lines.append("")

    # Trades
    trades = harness.state_manager.get_closed_trades()
    output_lines.append(f"  TRADE HISTORY")
    output_lines.append(f"  {'-'*78}")
    output_lines.append(f"\n  {'Opened':<16} {'Closed':<16} {'Type':<8} {'Entry':>8} {'Exit':>8} {'P/L':>12} {'%':>8} {'Reason':<24}")
    output_lines.append(f"  {'-'*16} {'-'*16} {'-'*8} {'-'*8} {'-'*8} {'-'*12} {'-'*8} {'-'*24}")

    show_backtest_trades(harness)

    for trade in trades:
        opened = trade.entry_time.strftime('%m/%d %H:%M') if trade.entry_time else '-'
        closed = trade.exit_time.strftime('%H:%M') if trade.exit_time else '-'
        trade_type = f"{trade.spread_type}"
        entry_credit = f"${trade.entry_credit:.2f}"
        exit_val = f"${trade.exit_spread_value:.2f}" if trade.exit_spread_value else '-'

        if trade.pnl_dollars and trade.pnl_dollars > 0:
            pnl_str = f"${trade.pnl_dollars:>+7.2f}"
        else:
            pnl_str = f"${trade.pnl_dollars:>+7.2f}" if trade.pnl_dollars else "$    0"

        pct_str = f"{trade.pnl_percent*100:>+5.1f}%" if trade.pnl_percent else "  0.0%"
        reason = trade.exit_reason.value if trade.exit_reason else 'N/A'

        output_lines.append(f"  {opened:<16} {closed:<16} {trade_type:<8} {entry_credit:>8} {exit_val:>8} {pnl_str:>12} {pct_str:>8} {reason:<24}")

    output_lines.append("")

    # Daily summary
    show_backtest_daily_summary(harness)

    daily_stats = {}
    for trade in trades:
        date_key = trade.entry_time.strftime('%Y-%m-%d') if trade.entry_time else 'Unknown'
        if date_key not in daily_stats:
            daily_stats[date_key] = {'trades': 0, 'wins': 0, 'pnl': 0}
        daily_stats[date_key]['trades'] += 1
        if trade.pnl_dollars > 0:
            daily_stats[date_key]['wins'] += 1
        daily_stats[date_key]['pnl'] += trade.pnl_dollars

    output_lines.append(f"  DAILY BREAKDOWN")
    output_lines.append(f"  {'-'*78}")
    output_lines.append(f"\n  {'Date':<12} {'Trades':>6} {'Wins':>6} {'Win %':>8} {'Daily P/L':>12}")
    output_lines.append(f"  {'-'*12} {'-'*6} {'-'*6} {'-'*8} {'-'*12}")

    for date_key in sorted(daily_stats.keys()):
        d_stats = daily_stats[date_key]
        win_pct = (d_stats['wins'] / d_stats['trades'] * 100) if d_stats['trades'] > 0 else 0
        pnl_val = d_stats['pnl']
        if pnl_val >= 0:
            daily_pnl = f"${pnl_val:>+7.2f}"
        else:
            daily_pnl = f"${pnl_val:>+7.2f}"
        output_lines.append(f"  {date_key:<12} {d_stats['trades']:>6} {d_stats['wins']:>6} {win_pct:>7.1f}% {daily_pnl:>12}")

    output_lines.append("")

    # Summary
    show_backtest_summary(harness, stats)

    output_lines.append(f"  PERFORMANCE SUMMARY")
    output_lines.append(f"  {'-'*78}")
    output_lines.append(f"\n  Total Trades:")
    output_lines.append(f"    {stats['total_trades']} total | {stats['winning_trades']} winners | {stats['losing_trades']} losers | {stats['break_even_trades']} break-even")
    output_lines.append(f"\n  Win Rate & P/L:")
    output_lines.append(f"    Win Rate:          {stats['win_rate']*100:>6.1f}%")
    pnl_val = stats['total_pnl']
    if pnl_val >= 0:
        pnl_str = f"${pnl_val:>+9.2f}"
    else:
        pnl_str = f"${pnl_val:>+9.2f}"
    output_lines.append(f"    Total P/L:         {pnl_str}")

    avg_win = stats['avg_win']
    if avg_win >= 0:
        avg_win_str = f"${avg_win:>+9.2f}"
    else:
        avg_win_str = f"${avg_win:>+9.2f}"
    output_lines.append(f"    Average Win:       {avg_win_str}")

    avg_loss = stats['avg_loss']
    if avg_loss >= 0:
        avg_loss_str = f"${avg_loss:>+9.2f}"
    else:
        avg_loss_str = f"${avg_loss:>+9.2f}"
    output_lines.append(f"    Average Loss:      {avg_loss_str}")

    max_win = stats['max_win']
    if max_win >= 0:
        max_win_str = f"${max_win:>+9.2f}"
    else:
        max_win_str = f"${max_win:>+9.2f}"
    output_lines.append(f"    Largest Win:       {max_win_str}")

    max_loss = stats['max_loss']
    if max_loss >= 0:
        max_loss_str = f"${max_loss:>+9.2f}"
    else:
        max_loss_str = f"${max_loss:>+9.2f}"
    output_lines.append(f"    Largest Loss:      {max_loss_str}")

    output_lines.append(f"\n  Risk Metrics:")
    output_lines.append(f"    Profit Factor:     {stats['profit_factor']:>6.2f}x")

    dd = stats['max_drawdown']
    if dd >= 0:
        dd_str = f"${dd:>+9.2f}"
    else:
        dd_str = f"${dd:>+9.2f}"
    output_lines.append(f"    Max Drawdown:      {dd_str}")

    output_lines.append(f"\n  Account:")
    output_lines.append(f"    Starting Balance:  ${harness.starting_balance:>10,.2f}")
    output_lines.append(f"    Ending Balance:    ${stats['current_balance']:>10,.2f}")
    output_lines.append(f"    Peak Balance:      ${stats['peak_balance']:>10,.2f}")
    output_lines.append(f"    Return on Capital: {stats['return_percent']:>10.2f}%")
    output_lines.append("")

    # Footer
    output_lines.append(f"{'='*80}")
    output_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output_lines.append(f"{'='*80}\n")

    # Save to file if requested
    if args.output:
        with open(args.output, 'w') as f:
            f.write('\n'.join(output_lines))
        print(f"\n[✓] Report saved to: {args.output}")

if __name__ == '__main__':
    main()
