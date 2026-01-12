#!/usr/bin/env python3
"""
Track Gamma GEX Strategy Performance (Clean Slate from Jan 12, 2026)

Usage:
    python track_performance.py              # Paper account stats
    python track_performance.py --live       # Live account stats
"""

import sys
import csv
import json
from datetime import datetime
from collections import defaultdict

# Baseline date - only count trades after this
BASELINE_DATE = datetime(2026, 1, 12, 0, 0, 0)

def load_trades(mode='paper'):
    """Load trades from CSV, filter for post-baseline only."""
    trades_file = '/root/gamma/data/trades.csv'

    trades = []
    try:
        with open(trades_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Parse timestamp
                timestamp = datetime.strptime(row['Timestamp_ET'], '%Y-%m-%d %H:%M:%S')

                # Only include post-baseline trades
                if timestamp < BASELINE_DATE:
                    continue

                # Filter by account
                account = row['Account_ID']
                if mode == 'paper' and 'VA' not in account:
                    continue
                if mode == 'live' and 'VA' in account:
                    continue

                # Parse P/L
                pnl_str = row.get('P/L_$', '').replace('+', '').replace('$', '')
                if pnl_str:
                    pnl = float(pnl_str)
                else:
                    pnl = None

                trades.append({
                    'timestamp': timestamp,
                    'trade_id': row['Trade_ID'],
                    'strategy': row['Strategy'],
                    'entry_credit': float(row['Entry_Credit']),
                    'exit_reason': row.get('Exit_Reason', ''),
                    'pnl': pnl,
                    'duration_min': int(row.get('Duration_Min', 0)) if row.get('Duration_Min') else None
                })
    except FileNotFoundError:
        print(f"No trades file found at {trades_file}")
        return []
    except Exception as e:
        print(f"Error loading trades: {e}")
        return []

    return trades

def analyze_trades(trades):
    """Generate performance statistics."""
    if not trades:
        return None

    # Filter completed trades only
    completed = [t for t in trades if t['pnl'] is not None]

    if not completed:
        return None

    # Basic stats
    total_trades = len(completed)
    winners = [t for t in completed if t['pnl'] > 0]
    losers = [t for t in completed if t['pnl'] <= 0]

    total_pnl = sum(t['pnl'] for t in completed)
    gross_wins = sum(t['pnl'] for t in winners)
    gross_losses = abs(sum(t['pnl'] for t in losers))

    win_rate = len(winners) / total_trades * 100 if total_trades > 0 else 0
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')

    avg_win = gross_wins / len(winners) if winners else 0
    avg_loss = gross_losses / len(losers) if losers else 0

    # Max drawdown (simplified - just largest loss)
    max_loss = min([t['pnl'] for t in completed]) if completed else 0

    # Trades per day
    if completed:
        first_trade = min(t['timestamp'] for t in completed)
        last_trade = max(t['timestamp'] for t in completed)
        days = (last_trade - first_trade).days + 1
        trades_per_day = total_trades / days if days > 0 else 0
    else:
        days = 0
        trades_per_day = 0

    # Strategy breakdown
    by_strategy = defaultdict(lambda: {'count': 0, 'pnl': 0})
    for t in completed:
        by_strategy[t['strategy']]['count'] += 1
        by_strategy[t['strategy']]['pnl'] += t['pnl']

    # Exit reason breakdown
    by_exit = defaultdict(int)
    for t in completed:
        reason = t['exit_reason'].split('(')[0].strip()  # Remove percentages
        by_exit[reason] += 1

    return {
        'total_trades': total_trades,
        'winners': len(winners),
        'losers': len(losers),
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'gross_wins': gross_wins,
        'gross_losses': gross_losses,
        'profit_factor': profit_factor,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'max_loss': max_loss,
        'days': days,
        'trades_per_day': trades_per_day,
        'by_strategy': dict(by_strategy),
        'by_exit': dict(by_exit)
    }

def print_report(stats, mode, starting_balance=20000):
    """Print formatted performance report."""
    if stats is None:
        print(f"\n{'='*60}")
        print(f"  GAMMA GEX STRATEGY - {mode.upper()} PERFORMANCE")
        print(f"{'='*60}")
        print(f"\nBaseline Date: {BASELINE_DATE.strftime('%Y-%m-%d')}")
        print(f"Starting Balance: ${starting_balance:,.0f}")
        print(f"\n⚠️  NO TRADES YET")
        print(f"\nBot is running but hasn't found valid GEX setups.")
        print(f"Check logs: tail -f /root/gamma/data/monitor_{mode}.log")
        return

    final_balance = starting_balance + stats['total_pnl']
    roi = (stats['total_pnl'] / starting_balance) * 100

    print(f"\n{'='*60}")
    print(f"  GAMMA GEX STRATEGY - {mode.upper()} PERFORMANCE")
    print(f"{'='*60}")
    print(f"Baseline Date: {BASELINE_DATE.strftime('%Y-%m-%d')}")
    print(f"Days Tracked: {stats['days']}")
    print(f"")
    print(f"{'ACCOUNT BALANCE':-^60}")
    print(f"Starting:  ${starting_balance:>10,.0f}")
    print(f"Current:   ${final_balance:>10,.0f}")
    print(f"P&L:       ${stats['total_pnl']:>+10,.0f}  ({roi:+.1f}%)")
    print(f"")
    print(f"{'TRADE STATISTICS':-^60}")
    print(f"Total Trades:      {stats['total_trades']:>4}")
    print(f"Winners:           {stats['winners']:>4}  ({stats['win_rate']:.1f}%)")
    print(f"Losers:            {stats['losers']:>4}")
    print(f"Trades/Day:        {stats['trades_per_day']:>4.1f}  (backtest claimed 3.9)")
    print(f"")
    print(f"{'PROFITABILITY':-^60}")
    print(f"Gross Wins:        ${stats['gross_wins']:>10,.0f}")
    print(f"Gross Losses:      ${stats['gross_losses']:>10,.0f}")
    print(f"Profit Factor:     {stats['profit_factor']:>10.2f}")
    print(f"Avg Win:           ${stats['avg_win']:>10,.0f}")
    print(f"Avg Loss:          ${stats['avg_loss']:>10,.0f}")
    print(f"Max Loss (Trade):  ${stats['max_loss']:>10,.0f}")
    print(f"")
    print(f"{'STRATEGY BREAKDOWN':-^60}")
    for strategy, data in sorted(stats['by_strategy'].items()):
        print(f"{strategy:>6}: {data['count']:>3} trades  ${data['pnl']:>+8,.0f}")
    print(f"")
    print(f"{'EXIT REASONS':-^60}")
    for reason, count in sorted(stats['by_exit'].items(), key=lambda x: -x[1]):
        pct = (count / stats['total_trades']) * 100
        print(f"{reason:<30} {count:>3}  ({pct:.0f}%)")
    print(f"")

    # Validation check
    print(f"{'VALIDATION STATUS':-^60}")
    if stats['days'] < 30:
        print(f"⏳ Need {30 - stats['days']} more days (minimum 30 for validation)")
    else:
        checks = []
        if stats['total_pnl'] > 0:
            checks.append("✅ Positive P&L")
        else:
            checks.append("❌ Negative P&L")

        if stats['win_rate'] > 50:
            checks.append("✅ Win rate > 50%")
        elif stats['win_rate'] > 40:
            checks.append("⚠️  Win rate 40-50%")
        else:
            checks.append("❌ Win rate < 40%")

        if stats['profit_factor'] > 2.0:
            checks.append("✅ Profit factor > 2.0")
        elif stats['profit_factor'] > 1.5:
            checks.append("⚠️  Profit factor 1.5-2.0")
        else:
            checks.append("❌ Profit factor < 1.5")

        if stats['trades_per_day'] >= 0.5:
            checks.append("✅ Adequate trade frequency")
        else:
            checks.append("⚠️  Low trade frequency (< 0.5/day)")

        print("\n".join(checks))

        # Overall verdict
        fails = sum(1 for c in checks if c.startswith("❌"))
        if fails == 0:
            print(f"\n🎯 STRATEGY VALIDATED - Consider live deployment")
        elif fails <= 1:
            print(f"\n⚠️  NEEDS IMPROVEMENT - Continue monitoring")
        else:
            print(f"\n❌ STRATEGY NOT VIABLE - Consider abandoning")

    print(f"{'='*60}\n")

def main():
    mode = 'live' if '--live' in sys.argv else 'paper'

    print(f"\nLoading {mode} trades since {BASELINE_DATE.strftime('%Y-%m-%d')}...")
    trades = load_trades(mode)

    if not trades:
        stats = None
    else:
        stats = analyze_trades(trades)

    print_report(stats, mode, starting_balance=20000)

if __name__ == '__main__':
    main()
