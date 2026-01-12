#!/usr/bin/env python3
"""
Analyze Historical 0DTE Trades from Production System

Parses real trades from trades.csv and analyzes:
1. Actual credit ranges for SPX spreads
2. Spread widths used in production
3. Win rates and P/L distribution
4. Validates backtest credit assumptions
"""

import csv
import re
from collections import defaultdict
from datetime import datetime
import statistics


def parse_strikes(strikes_str):
    """Parse strike string like '6850/6840P' or '6880/6890/6820/6810' (IC).

    Returns:
        tuple: (spread_width, option_type, is_iron_condor)
    """
    if not strikes_str or strikes_str == 'N/A':
        return None, None, False

    # Remove option type suffix (P or C)
    clean = strikes_str.replace('P', '').replace('C', '')

    # Split into strikes
    strikes = [int(s) for s in clean.split('/') if s.strip()]

    if len(strikes) == 2:
        # Single spread
        width = abs(strikes[0] - strikes[1])
        opt_type = 'PUT' if 'P' in strikes_str else 'CALL' if 'C' in strikes_str else 'UNKNOWN'
        return width, opt_type, False
    elif len(strikes) == 4:
        # Iron Condor - two spreads
        # Typically formatted as: upper_short/upper_long/lower_short/lower_long
        call_width = abs(strikes[0] - strikes[1])
        put_width = abs(strikes[2] - strikes[3])
        return (call_width, put_width), 'IC', True

    return None, None, False


def analyze_trades_csv(csv_path="/root/gamma/data/trades.csv"):
    """Analyze production trades from CSV."""

    trades = []

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Only process completed trades (have Exit_Time and P/L)
            if not row.get('Exit_Time'):
                continue

            entry_credit = float(row.get('Entry_Credit', 0))
            if entry_credit == 0:
                continue

            strikes = row.get('Strikes', '')
            width, opt_type, is_ic = parse_strikes(strikes)

            # Parse P/L
            pl_str = row.get('P/L_$', '$0').replace('$', '').replace('+', '').replace(',', '')
            try:
                pl = float(pl_str)
            except:
                pl = 0

            # Parse timestamp
            timestamp = row.get('Timestamp_ET', '')
            time_hour = None
            if timestamp:
                try:
                    dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                    time_hour = dt.hour
                except:
                    pass

            trades.append({
                'timestamp': timestamp,
                'time_hour': time_hour,
                'strikes': strikes,
                'spread_width': width,
                'option_type': opt_type,
                'is_ic': is_ic,
                'entry_credit': entry_credit,
                'pl': pl,
                'exit_reason': row.get('Exit_Reason', ''),
                'duration_min': row.get('Duration_Min', ''),
                'strategy': row.get('Strategy', '')
            })

    return trades


def print_analysis(trades):
    """Print comprehensive analysis of trades."""

    print("\n" + "="*80)
    print("  REAL 0DTE TRADES ANALYSIS - Production System Historical Data")
    print("="*80)

    print(f"\nTotal Completed Trades: {len(trades)}")

    if not trades:
        print("No completed trades found in CSV")
        return

    # Date range
    timestamps = [t['timestamp'] for t in trades if t['timestamp']]
    if timestamps:
        dates = [datetime.strptime(ts, '%Y-%m-%d %H:%M:%S') for ts in timestamps]
        print(f"Date Range: {min(dates).strftime('%Y-%m-%d')} to {max(dates).strftime('%Y-%m-%d')}")

    # Spread width analysis
    print(f"\n{'-'*80}")
    print("  SPREAD WIDTH DISTRIBUTION")
    print(f"{'-'*80}")

    width_counts = defaultdict(int)
    for t in trades:
        if not t['is_ic']:
            width_counts[t['spread_width']] += 1
        else:
            # IC has two widths
            call_w, put_w = t['spread_width']
            width_counts[f"IC: {call_w}/{put_w}"] += 1

    # Sort with integers first, then strings
    sorted_widths = sorted(width_counts.items(), key=lambda x: (isinstance(x[0], str), x[0]))
    for width, count in sorted_widths:
        pct = count / len(trades) * 100
        width_str = str(width) if isinstance(width, int) else width
        print(f"  {width_str:>15}: {count:3d} trades ({pct:4.1f}%)")

    # Single spreads only (exclude ICs for credit analysis)
    single_spreads = [t for t in trades if not t['is_ic']]

    if single_spreads:
        print(f"\n{'-'*80}")
        print("  CREDIT ANALYSIS (Single Spreads Only)")
        print(f"{'-'*80}")

        # Group by spread width
        by_width = defaultdict(list)
        for t in single_spreads:
            by_width[t['spread_width']].append(t['entry_credit'])

        print(f"\n{'Width':>6} {'Count':>6} {'Min':>8} {'Max':>8} {'Avg':>8} {'Median':>8}")
        print(f"{'-'*6} {'-'*6} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

        for width in sorted(by_width.keys()):
            credits = by_width[width]
            print(f"{width:>6} {len(credits):>6} ${min(credits):>7.2f} ${max(credits):>7.2f} "
                  f"${statistics.mean(credits):>7.2f} ${statistics.median(credits):>7.2f}")

        # Time-of-day analysis
        print(f"\n{'-'*80}")
        print("  CREDIT BY TIME OF DAY (10-point spreads)")
        print(f"{'-'*80}")

        ten_pt = [t for t in single_spreads if t['spread_width'] == 10 and t['time_hour']]

        if ten_pt:
            by_hour = defaultdict(list)
            for t in ten_pt:
                by_hour[t['time_hour']].append(t['entry_credit'])

            print(f"\n{'Hour':>5} {'Count':>6} {'Avg Credit':>12}")
            print(f"{'-'*5} {'-'*6} {'-'*12}")

            for hour in sorted(by_hour.keys()):
                credits = by_hour[hour]
                avg = statistics.mean(credits)
                print(f"{hour:>5} {len(credits):>6} ${avg:>11.2f}")

    # P/L Analysis
    print(f"\n{'-'*80}")
    print("  P/L ANALYSIS")
    print(f"{'-'*80}")

    pls = [t['pl'] for t in trades]
    winners = [p for p in pls if p > 0]
    losers = [p for p in pls if p < 0]

    win_rate = len(winners) / len(pls) * 100 if pls else 0

    print(f"\nWin Rate:        {win_rate:.1f}% ({len(winners)}W / {len(losers)}L)")
    print(f"Total P/L:       ${sum(pls):+,.2f}")
    if winners:
        print(f"Avg Winner:      ${statistics.mean(winners):+.2f}")
    if losers:
        print(f"Avg Loser:       ${statistics.mean(losers):+.2f}")

    # Best/Worst trades
    sorted_trades = sorted(trades, key=lambda t: t['pl'], reverse=True)

    print(f"\nTop 5 Best Trades:")
    for i, t in enumerate(sorted_trades[:5], 1):
        print(f"  {i}. {t['timestamp'][:10]} {t['strikes']:20s} ${t['entry_credit']:.2f} credit → ${t['pl']:+.2f}")

    print(f"\nTop 5 Worst Trades:")
    for i, t in enumerate(sorted_trades[-5:], 1):
        print(f"  {i}. {t['timestamp'][:10]} {t['strikes']:20s} ${t['entry_credit']:.2f} credit → ${t['pl']:+.2f}")

    # Compare to backtest assumptions
    print(f"\n{'-'*80}")
    print("  BACKTEST ASSUMPTION VALIDATION")
    print(f"{'-'*80}")

    # Get 10pt spread credits for comparison
    ten_pt = [t['entry_credit'] for t in single_spreads if t['spread_width'] == 10]

    if ten_pt:
        print(f"\nREAL PRODUCTION DATA (10-point SPX spreads):")
        print(f"  Credit Range:  ${min(ten_pt):.2f} - ${max(ten_pt):.2f}")
        print(f"  Average:       ${statistics.mean(ten_pt):.2f}")
        print(f"  Median:        ${statistics.median(ten_pt):.2f}")

        # Scale down to 5-point equivalent
        five_pt_min = min(ten_pt) * 0.5
        five_pt_max = max(ten_pt) * 0.5
        five_pt_avg = statistics.mean(ten_pt) * 0.5

        print(f"\nSCALED TO 5-POINT EQUIVALENT:")
        print(f"  Credit Range:  ${five_pt_min:.2f} - ${five_pt_max:.2f}")
        print(f"  Average:       ${five_pt_avg:.2f}")

        print(f"\nBACKTEST ASSUMPTIONS (5-point SPX spreads):")
        print(f"  VIX < 15:      $0.20 - $0.40")
        print(f"  VIX 15-22:     $0.35 - $0.65")
        print(f"  VIX 22-30:     $0.55 - $0.95")
        print(f"  VIX > 30:      $0.80 - $1.20")

        print(f"\nCONCLUSION:")
        if five_pt_avg >= 0.35 and five_pt_avg <= 0.95:
            print(f"  ✓ Production data VALIDATES backtest assumptions")
            print(f"    5-point equiv avg ${five_pt_avg:.2f} falls within VIX 15-30 range")
        else:
            print(f"  ⚠ Production data suggests backtest may need adjustment")
            print(f"    5-point equiv avg ${five_pt_avg:.2f} vs backtest $0.35-$0.95")


def main():
    """Main entry point."""
    trades = analyze_trades_csv()
    print_analysis(trades)
    print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    main()
