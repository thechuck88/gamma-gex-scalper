#!/usr/bin/env python3
"""
Generate formatted report from live data backtest

Similar to show.py but for backtest results.

Usage:
    python3 backtest_report.py                   # ALL available dates (default)
    python3 backtest_report.py 2026-01-12        # Specific date
"""

import sys
from datetime import datetime, date, time as dt_time
from collections import defaultdict

sys.path.insert(0, '/gamma-scalper')
from backtest_live_data import (
    get_gex_peaks_for_time, get_live_prices, get_index_price_at_time,
    determine_strategy, simulate_trade, ENTRY_TIMES,
    get_optimized_connection
)
import pytz

ET = pytz.timezone('America/New_York')


def run_backtest_silent(test_date, index_symbol):
    """Run backtest and return trades list without printing."""
    # Convert ET to UTC
    start_time_et = ET.localize(datetime.combine(test_date, dt_time(9, 30)))
    end_time_et = ET.localize(datetime.combine(test_date, dt_time(16, 0)))
    start_time_utc = start_time_et.astimezone(pytz.UTC)
    end_time_utc = end_time_et.astimezone(pytz.UTC)

    # Load prices
    prices = get_live_prices(index_symbol, start_time_utc, end_time_utc)
    if not prices:
        return []

    timestamps = sorted(set(p['timestamp'] for p in prices))
    trades = []

    # Check each entry time
    for entry_time_obj in ENTRY_TIMES:
        entry_dt_et = ET.localize(datetime.combine(test_date, entry_time_obj))
        entry_dt_utc = entry_dt_et.astimezone(pytz.UTC).replace(tzinfo=None)

        closest_ts = min(timestamps, key=lambda t: abs((t - entry_dt_utc).total_seconds()))
        if abs((closest_ts - entry_dt_utc).total_seconds()) > 120:
            continue

        peaks = get_gex_peaks_for_time(index_symbol, closest_ts)
        if not peaks:
            continue

        pin_strike = peaks[0]['strike']
        current_price = get_index_price_at_time(prices, closest_ts)
        if not current_price:
            continue

        strategy = determine_strategy(pin_strike, current_price, index_symbol)
        if not strategy:
            continue

        trade = simulate_trade(closest_ts, prices, strategy, index_symbol)
        if trade:
            # Add index symbol to trade
            trade['index'] = index_symbol
            trade['pin_strike'] = pin_strike
            trades.append(trade)

    return trades


def format_pl(pl):
    """Format P/L with color."""
    if pl > 0:
        return f"\033[32m${pl:>+7.0f}\033[0m"
    elif pl < 0:
        return f"\033[31m${pl:>+7.0f}\033[0m"
    return f"${pl:>+7.0f}"


def format_pct(pct):
    """Format percentage with color."""
    if pct > 0:
        return f"\033[32m{pct:>+5.0f}%\033[0m"
    elif pct < 0:
        return f"\033[31m{pct:>+5.0f}%\033[0m"
    return f"{pct:>+5.0f}%"


def show_backtest_banner(test_date, spx_trades, ndx_trades):
    """Show header banner similar to show.py."""
    print(f"\n{'='*80}")
    print(f"  GAMMA BACKTEST REPORT — {test_date}")
    print(f"{'='*80}")

    total_spx_pl = sum(t['pnl_dollars'] for t in spx_trades)
    total_ndx_pl = sum(t['pnl_dollars'] for t in ndx_trades)
    total_pl = total_spx_pl + total_ndx_pl

    print(f"\n  {'Index':<8} {'Trades':>8} {'Winners':>8} {'Losers':>8} {'P/L':>12}")
    print(f"  {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*12}")

    if spx_trades:
        spx_wins = len([t for t in spx_trades if t['pnl_dollars'] > 0])
        spx_losses = len(spx_trades) - spx_wins
        print(f"  {'SPX':<8} {len(spx_trades):>8} {spx_wins:>8} {spx_losses:>8} {format_pl(total_spx_pl)}")

    if ndx_trades:
        ndx_wins = len([t for t in ndx_trades if t['pnl_dollars'] > 0])
        ndx_losses = len(ndx_trades) - ndx_wins
        print(f"  {'NDX':<8} {len(ndx_trades):>8} {ndx_wins:>8} {ndx_losses:>8} {format_pl(total_ndx_pl)}")

    print(f"  {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*12}")
    total_trades = len(spx_trades) + len(ndx_trades)
    total_wins = len([t for t in spx_trades + ndx_trades if t['pnl_dollars'] > 0])
    total_losses = total_trades - total_wins
    print(f"  {'TOTAL':<8} {total_trades:>8} {total_wins:>8} {total_losses:>8} {format_pl(total_pl)}")


def show_trade_details(trades, index_name):
    """Show trade-by-trade details."""
    if not trades:
        return

    print(f"\n{'='*80}")
    print(f"  {index_name} TRADES")
    print(f"{'='*80}")

    print(f"\n  {'Entry':<8} {'Exit':<8} {'Strikes':<18} {'Entry':>6} {'Exit':>6} {'P/L':>9} {'%':>7} {'Dur':>5} {'Reason':<14}")
    print(f"  {'-'*8} {'-'*8} {'-'*18} {'-'*6} {'-'*6} {'-'*9} {'-'*7} {'-'*5} {'-'*14}")

    for trade in sorted(trades, key=lambda t: t['entry_time']):
        entry_str = trade['entry_time'].strftime('%H:%M')
        exit_str = trade['exit_time'].strftime('%H:%M')

        # Format strikes
        strikes = trade['strikes']

        # Format prices
        entry_price = f"${trade['entry_credit']:.2f}"
        exit_price = f"${trade['exit_value']:.2f}"

        # Format duration
        dur_min = int(trade['duration_min'])
        if dur_min >= 60:
            dur_str = f"{dur_min//60}h{dur_min%60:02d}"
        else:
            dur_str = f"{dur_min}m"

        # Exit reason (shortened)
        reason_map = {
            'PROFIT_TARGET': 'TARGET',
            'STOP_LOSS': 'STOP',
            'TRAILING_STOP': 'TRAIL',
            'EOD_CLOSE': 'EOD'
        }
        reason = reason_map.get(trade['exit_reason'], trade['exit_reason'][:14])

        # P/L colored
        pl = trade['pnl_dollars']
        pct = trade['pnl_pct']

        print(f"  {entry_str:<8} {exit_str:<8} {strikes:<18} {entry_price:>6} {exit_price:>6} {format_pl(pl)} {format_pct(pct)} {dur_str:>5} {reason:<14}")


def show_statistics(trades, index_name):
    """Show summary statistics for an index."""
    if not trades:
        return

    winners = [t for t in trades if t['pnl_dollars'] > 0]
    losers = [t for t in trades if t['pnl_dollars'] <= 0]

    total_pl = sum(t['pnl_dollars'] for t in trades)
    total_trades = len(trades)
    win_rate = len(winners) / total_trades * 100 if total_trades > 0 else 0

    print(f"\n  {index_name} STATISTICS:")
    print(f"  {'-'*80}")

    if total_trades > 0:
        avg_pl = total_pl / total_trades
        print(f"  Total Trades: {total_trades}")
        print(f"  Win Rate: {win_rate:.1f}% ({len(winners)}W / {len(losers)}L)")
        print(f"  Total P/L: {format_pl(total_pl)}")
        print(f"  Avg P/L per trade: {format_pl(avg_pl)}")

    if winners:
        avg_win = sum(t['pnl_dollars'] for t in winners) / len(winners)
        avg_win_dur = sum(t['duration_min'] for t in winners) / len(winners)
        print(f"  Avg Winner: {format_pl(avg_win)} (avg {avg_win_dur:.0f} min)")

    if losers:
        avg_loss = sum(t['pnl_dollars'] for t in losers) / len(losers)
        avg_loss_dur = sum(t['duration_min'] for t in losers) / len(losers)
        print(f"  Avg Loser: {format_pl(avg_loss)} (avg {avg_loss_dur:.0f} min)")

    if winners and losers:
        total_wins_pl = sum(t['pnl_dollars'] for t in winners)
        total_losses_pl = abs(sum(t['pnl_dollars'] for t in losers))
        profit_factor = total_wins_pl / total_losses_pl if total_losses_pl > 0 else float('inf')
        if profit_factor == float('inf'):
            print(f"  Profit Factor: ∞ (no losses)")
        else:
            print(f"  Profit Factor: {profit_factor:.2f}")


def show_intraday_chart(all_trades):
    """Display ASCII chart of cumulative P/L through the day."""
    if len(all_trades) < 2:
        return

    # Sort by exit time and calculate cumulative
    sorted_trades = sorted(all_trades, key=lambda t: t['exit_time'])
    cumulative = []
    running_total = 0

    for trade in sorted_trades:
        running_total += trade['pnl_dollars']
        time_str = trade['exit_time'].strftime('%H:%M')
        cumulative.append((time_str, running_total, trade['index']))

    # Find min/max for scaling
    values = [v for _, v, _ in cumulative]
    min_val = min(min(values), 0)
    max_val = max(max(values), 0)
    val_range = max_val - min_val if max_val != min_val else 1

    # Chart dimensions
    chart_height = 8
    chart_width = len(cumulative)

    print(f"\n{'='*80}")
    print(f"  INTRADAY P/L")
    print(f"{'='*80}")

    # Build chart rows
    for row in range(chart_height, -1, -1):
        threshold = min_val + (val_range * row / chart_height)

        # Y-axis label
        if row == chart_height:
            label = f"${max_val:>+6.0f}"
        elif row == 0:
            label = f"${min_val:>+6.0f}"
        elif abs(threshold) < 1:
            label = f"     $0"
        else:
            label = "       "

        line = f"  {label} |"

        for i, (time_str, val, idx) in enumerate(cumulative):
            if row == 0 and threshold <= 0 <= val:
                line += "─"
            elif val >= threshold > 0:
                # Color by index
                if idx == 'SPX':
                    line += "\033[32m█\033[0m"  # Green for SPX
                else:
                    line += "\033[34m█\033[0m"  # Blue for NDX
            elif val <= threshold < 0:
                line += "\033[31m█\033[0m"  # Red below zero
            elif threshold <= 0 <= val or threshold >= 0 >= val:
                line += "─"
            else:
                line += " "

        print(line)

    # X-axis with times
    print(f"         +{'-'*chart_width}")
    if cumulative:
        times_line = f"        {cumulative[0][0]}" + " " * (chart_width - 10) + cumulative[-1][0]
        print(f"  {times_line}")

    print(f"\n  Legend: \033[32m█\033[0m SPX   \033[34m█\033[0m NDX")


def main():
    # Default: Use ALL available dates from database
    if len(sys.argv) > 1:
        # Specific date provided
        dates = [datetime.strptime(sys.argv[1], '%Y-%m-%d').date()]
    else:
        # No arguments: Use ALL available dates
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
            print("⚠️  No data found in database")
            return

        print(f"📊 Generating report for ALL available data ({len(dates)} days)")
        print(f"   Date range: {dates[0]} to {dates[-1]}\n")

    for test_date in dates:
        # Run backtests silently
        print(f"\n⏳ Running backtest for {test_date}...")
        spx_trades = run_backtest_silent(test_date, 'SPX')
        ndx_trades = run_backtest_silent(test_date, 'NDX')

        if not spx_trades and not ndx_trades:
            print(f"\n⚠️  No trades found for {test_date}")
            continue

        # Show banner
        show_backtest_banner(test_date, spx_trades, ndx_trades)

        # Show trade details
        if spx_trades:
            show_trade_details(spx_trades, 'SPX')
            show_statistics(spx_trades, 'SPX')

        if ndx_trades:
            show_trade_details(ndx_trades, 'NDX')
            show_statistics(ndx_trades, 'NDX')

        # Combined chart
        all_trades = spx_trades + ndx_trades
        if len(all_trades) >= 2:
            show_intraday_chart(all_trades)

        print()


if __name__ == '__main__':
    main()
