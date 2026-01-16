#!/usr/bin/env python3
"""
Analyze GEX strategy to identify improvements for profit factor > 1.25
"""

import numpy as np
import pandas as pd
from backtest_gex_and_otm import backtest_gex_and_otm

def analyze_gex_for_improvements(trades):
    """Deep dive into GEX trades to find improvement opportunities."""

    gex_trades = [t for t in trades if t['strategy'] == 'GEX PIN']

    if not gex_trades:
        print("No GEX trades found")
        return

    df = pd.DataFrame(gex_trades)

    # Calculate profit factor
    winners = df[df['winner'] == True]
    losers = df[df['winner'] == False]

    total_wins = winners['pl'].sum()
    total_losses = abs(losers['pl'].sum())
    current_pf = total_wins / total_losses if total_losses > 0 else float('inf')

    print("\n" + "="*120)
    print("GEX STRATEGY IMPROVEMENT ANALYSIS")
    print("="*120)

    print(f"\nCURRENT PERFORMANCE:")
    print(f"  Trades: {len(df)}")
    print(f"  Win Rate: {len(winners)/len(df)*100:.1f}%")
    print(f"  Total Wins: ${total_wins:,.0f}")
    print(f"  Total Losses: ${total_losses:,.0f}")
    print(f"  Net P/L: ${df['pl'].sum():,.0f}")
    print(f"  Profit Factor: {current_pf:.2f} {'❌ BELOW TARGET' if current_pf < 1.25 else '✓ ABOVE TARGET'}")
    print(f"  Avg Winner: ${winners['pl'].mean():.0f}")
    print(f"  Avg Loser: ${losers['pl'].mean():.0f}")

    # Problem diagnosis
    print(f"\n" + "-"*120)
    print("PROBLEM DIAGNOSIS")
    print("-"*120)

    avg_win = winners['pl'].mean()
    avg_loss = abs(losers['pl'].mean())
    win_rate = len(winners) / len(df)

    print(f"\nWin/Loss Ratio: {avg_win/avg_loss:.2f}:1")
    print(f"  → Avg winner (${avg_win:.0f}) is only {avg_win/avg_loss:.2f}x the avg loser (${avg_loss:.0f})")

    # Calculate required changes
    target_pf = 1.25
    required_wins = target_pf * total_losses
    wins_gap = required_wins - total_wins

    print(f"\nTo reach PF = {target_pf}:")
    print(f"  Need total wins: ${required_wins:,.0f}")
    print(f"  Current wins: ${total_wins:,.0f}")
    print(f"  Gap: ${wins_gap:,.0f}")

    print(f"\nOptions to close the gap:")
    print(f"  1. Increase avg winner by ${wins_gap/len(winners):.0f} (from ${avg_win:.0f} to ${avg_win + wins_gap/len(winners):.0f})")
    print(f"  2. Reduce avg loser by ${wins_gap/len(losers):.0f} (from ${avg_loss:.0f} to ${avg_loss - wins_gap/len(losers):.0f})")
    print(f"  3. Eliminate {int(wins_gap/avg_loss)} losing trades via better filters")

    # VIX analysis
    print(f"\n" + "-"*120)
    print("VIX ANALYSIS")
    print("-"*120)

    print(f"\nWinners vs Losers by VIX:")
    print(f"  Winners avg VIX: {winners['vix'].mean():.2f}")
    print(f"  Losers avg VIX:  {losers['vix'].mean():.2f}")
    print(f"  Difference: {abs(winners['vix'].mean() - losers['vix'].mean()):.2f}")

    # VIX bins
    df['vix_bin'] = pd.cut(df['vix'], bins=[0, 15, 16, 17, 18, 100], labels=['<15', '15-16', '16-17', '17-18', '18+'])
    vix_performance = df.groupby('vix_bin').agg({
        'pl': ['sum', 'mean', 'count'],
        'winner': lambda x: (x.sum() / len(x) * 100)
    }).round(1)

    print(f"\nPerformance by VIX range:")
    for vix_range in df['vix_bin'].unique():
        if pd.notna(vix_range):
            trades_in_range = df[df['vix_bin'] == vix_range]
            win_rate_range = (trades_in_range['winner'].sum() / len(trades_in_range)) * 100
            avg_pl_range = trades_in_range['pl'].mean()
            count = len(trades_in_range)
            total_pl = trades_in_range['pl'].sum()
            print(f"  VIX {vix_range}: {count:>2} trades, {win_rate_range:>4.1f}% WR, ${avg_pl_range:>5.0f} avg, ${total_pl:>6.0f} total")

    # Entry time analysis
    print(f"\n" + "-"*120)
    print("ENTRY TIME ANALYSIS")
    print("-"*120)

    df['hour'] = df['time'].str[:2].astype(int)
    df['minute'] = df['time'].str[3:5].astype(int)
    df['entry_time'] = df['hour'].astype(str).str.zfill(2) + ':' + df['minute'].astype(str).str.zfill(2)

    time_performance = df.groupby('entry_time').agg({
        'pl': ['sum', 'mean', 'count'],
        'winner': lambda x: (x.sum() / len(x) * 100)
    }).round(1)

    print(f"\nPerformance by entry time:")
    for entry_time in sorted(df['entry_time'].unique()):
        trades_at_time = df[df['entry_time'] == entry_time]
        win_rate_time = (trades_at_time['winner'].sum() / len(trades_at_time)) * 100
        avg_pl_time = trades_at_time['pl'].mean()
        count = len(trades_at_time)
        total_pl = trades_at_time['pl'].sum()
        print(f"  {entry_time}: {count:>2} trades, {win_rate_time:>4.1f}% WR, ${avg_pl_time:>5.0f} avg, ${total_pl:>6.0f} total")

    # Exit reason analysis
    print(f"\n" + "-"*120)
    print("EXIT REASON ANALYSIS")
    print("-"*120)

    print(f"\nWinners by exit reason:")
    winner_reasons = winners.groupby('exit_reason').agg({
        'pl': ['sum', 'mean', 'count']
    }).round(0)
    for reason in winners['exit_reason'].unique():
        reason_trades = winners[winners['exit_reason'] == reason]
        print(f"  {reason}: {len(reason_trades):>2} trades, ${reason_trades['pl'].mean():>4.0f} avg, ${reason_trades['pl'].sum():>6.0f} total")

    print(f"\nLosers by exit reason:")
    loser_reasons = losers.groupby('exit_reason').agg({
        'pl': ['sum', 'mean', 'count']
    }).round(0)
    for reason in losers['exit_reason'].unique():
        reason_trades = losers[losers['exit_reason'] == reason]
        print(f"  {reason}: {len(reason_trades):>2} trades, ${reason_trades['pl'].mean():>4.0f} avg, ${reason_trades['pl'].sum():>6.0f} total")

    # Date analysis
    print(f"\n" + "-"*120)
    print("DAILY PERFORMANCE ANALYSIS")
    print("-"*120)

    print(f"\nPerformance by day:")
    for date in sorted(df['date'].unique()):
        day_trades = df[df['date'] == date]
        win_rate_day = (day_trades['winner'].sum() / len(day_trades)) * 100
        avg_pl_day = day_trades['pl'].mean()
        count = len(day_trades)
        total_pl = day_trades['pl'].sum()
        winners_count = day_trades['winner'].sum()
        losers_count = len(day_trades) - winners_count
        print(f"  {date}: {count:>2} trades ({winners_count}W/{losers_count}L), {win_rate_day:>4.1f}% WR, ${avg_pl_day:>5.0f} avg, ${total_pl:>6.0f} total")

    # Specific problem trades
    print(f"\n" + "-"*120)
    print("WORST LOSING TRADES")
    print("-"*120)

    worst_losses = losers.nsmallest(10, 'pl')
    print(f"\nTop 10 worst losses:")
    for idx, trade in worst_losses.iterrows():
        print(f"  {trade['date']} {trade['time']} VIX:{trade['vix']:.2f} → ${trade['pl']:.0f} ({trade['exit_reason']})")

    # RECOMMENDATIONS
    print(f"\n" + "="*120)
    print("RECOMMENDED IMPROVEMENTS")
    print("="*120)

    recommendations = []

    # 1. VIX filter
    high_vix_trades = df[df['vix'] >= 16.5]
    if len(high_vix_trades) > 0:
        high_vix_avg = high_vix_trades['pl'].mean()
        if high_vix_avg < 0:
            eliminated_losses = abs(high_vix_trades[high_vix_trades['winner'] == False]['pl'].sum())
            recommendations.append({
                'name': 'Skip VIX >= 16.5',
                'impact': f"Eliminates {len(high_vix_trades)} trades, saves ${eliminated_losses:.0f} in losses",
                'new_pf': (total_wins - high_vix_trades[high_vix_trades['winner'] == True]['pl'].sum()) /
                          (total_losses - eliminated_losses) if (total_losses - eliminated_losses) > 0 else float('inf')
            })

    # 2. Time filter
    early_trades = df[df['hour'] < 10]
    if len(early_trades) > 0:
        early_avg = early_trades['pl'].mean()
        if early_avg < df['pl'].mean():
            eliminated_losses_early = abs(early_trades[early_trades['winner'] == False]['pl'].sum())
            recommendations.append({
                'name': 'Skip entries before 10:00 AM',
                'impact': f"Eliminates {len(early_trades)} trades, saves ${eliminated_losses_early:.0f} in losses",
                'new_pf': (total_wins - early_trades[early_trades['winner'] == True]['pl'].sum()) /
                          (total_losses - eliminated_losses_early) if (total_losses - eliminated_losses_early) > 0 else float('inf')
            })

    # 3. Tighter stop loss
    emergency_stops = losers[losers['exit_reason'].str.contains('EMERGENCY')]
    if len(emergency_stops) > 0:
        avg_emergency_loss = abs(emergency_stops['pl'].mean())
        recommendations.append({
            'name': 'Reduce emergency stop from 40% to 25%',
            'impact': f"Reduces {len(emergency_stops)} emergency stop losses by ~30%",
            'new_pf': total_wins / (total_losses - (avg_emergency_loss * 0.3 * len(emergency_stops))) if (total_losses - (avg_emergency_loss * 0.3 * len(emergency_stops))) > 0 else float('inf')
        })

    # 4. Better profit targets
    early_exits = winners[winners['exit_reason'].str.contains('Trailing Stop')]
    if len(early_exits) > 0:
        avg_early_profit = early_exits['pl'].mean()
        recommendations.append({
            'name': 'Hold winners longer (increase trailing activation from 20% to 30%)',
            'impact': f"Could increase {len(early_exits)} trailing stop exits by ~20%",
            'new_pf': (total_wins + (avg_early_profit * 0.2 * len(early_exits))) / total_losses
        })

    print(f"\nTop improvement opportunities:")
    for i, rec in enumerate(sorted(recommendations, key=lambda x: x['new_pf'], reverse=True)[:5], 1):
        print(f"\n{i}. {rec['name']}")
        print(f"   Impact: {rec['impact']}")
        print(f"   New PF: {rec['new_pf']:.2f} {'✓ ABOVE TARGET' if rec['new_pf'] >= 1.25 else '❌ STILL BELOW'}")

    # Combined recommendation
    print(f"\n" + "-"*120)
    print("OPTIMAL FILTER COMBINATION")
    print("-"*120)

    # Test combinations
    filtered_df = df.copy()

    # Apply multiple filters
    print(f"\nTesting filter combination:")
    filters_applied = []

    # Filter 1: VIX
    if len(high_vix_trades) > 0 and high_vix_avg < 0:
        filtered_df = filtered_df[filtered_df['vix'] < 16.5]
        filters_applied.append("VIX < 16.5")

    # Filter 2: Time
    if len(early_trades) > 0 and early_avg < df['pl'].mean():
        filtered_df = filtered_df[filtered_df['hour'] >= 10]
        filters_applied.append("Entry >= 10:00 AM")

    # Filter 3: Specific losing days
    bad_days = []
    for date in df['date'].unique():
        day_pl = df[df['date'] == date]['pl'].sum()
        if day_pl < -100:
            bad_days.append(date)

    if len(filters_applied) > 0:
        filtered_winners = filtered_df[filtered_df['winner'] == True]
        filtered_losers = filtered_df[filtered_df['winner'] == False]
        filtered_total_wins = filtered_winners['pl'].sum()
        filtered_total_losses = abs(filtered_losers['pl'].sum())
        filtered_pf = filtered_total_wins / filtered_total_losses if filtered_total_losses > 0 else float('inf')

        print(f"  Filters: {', '.join(filters_applied)}")
        print(f"\n  Results:")
        print(f"    Trades: {len(df)} → {len(filtered_df)} (eliminated {len(df) - len(filtered_df)})")
        print(f"    Win Rate: {len(winners)/len(df)*100:.1f}% → {len(filtered_winners)/len(filtered_df)*100:.1f}%")
        print(f"    Net P/L: ${df['pl'].sum():.0f} → ${filtered_df['pl'].sum():.0f}")
        print(f"    Profit Factor: {current_pf:.2f} → {filtered_pf:.2f} {'✓ TARGET ACHIEVED!' if filtered_pf >= 1.25 else '❌ STILL BELOW'}")
        print(f"    Avg Winner: ${winners['pl'].mean():.0f} → ${filtered_winners['pl'].mean():.0f}")
        print(f"    Avg Loser: ${abs(losers['pl'].mean()):.0f} → ${abs(filtered_losers['pl'].mean()):.0f}")


if __name__ == '__main__':
    np.random.seed(42)
    trades = backtest_gex_and_otm()
    analyze_gex_for_improvements(trades)
