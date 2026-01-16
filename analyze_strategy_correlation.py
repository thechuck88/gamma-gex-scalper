#!/usr/bin/env python3
"""
Analyze correlation between GEX PIN and OTM IRON CONDOR strategies.
"""

import numpy as np
from backtest_gex_and_otm import backtest_gex_and_otm
from collections import defaultdict

def analyze_correlation(trades):
    """Analyze if GEX and OTM strategies complement each other."""

    # Group trades by date and entry time
    grouped = defaultdict(lambda: {'gex': None, 'otm': None})

    for t in trades:
        key = (t['date'], t['time'])
        if t['strategy'] == 'GEX PIN':
            grouped[key]['gex'] = t
        else:
            grouped[key]['otm'] = t

    # Analyze pairs where both strategies entered
    both_entered = []
    only_gex = []
    only_otm = []

    for key, pair in grouped.items():
        if pair['gex'] and pair['otm']:
            both_entered.append((pair['gex'], pair['otm']))
        elif pair['gex']:
            only_gex.append(pair['gex'])
        elif pair['otm']:
            only_otm.append(pair['otm'])

    print("\n" + "="*120)
    print("GEX + OTM STRATEGY CORRELATION ANALYSIS")
    print("="*120)

    print(f"\nEntry Pattern:")
    print(f"  Both strategies entered: {len(both_entered)} times")
    print(f"  Only GEX entered: {len(only_gex)} times")
    print(f"  Only OTM entered: {len(only_otm)} times")

    if not both_entered:
        print("\nNo simultaneous entries - strategies are INDEPENDENT (mutually exclusive entry conditions)")
        return

    # Analyze simultaneous entries
    print(f"\n" + "-"*120)
    print(f"SIMULTANEOUS ENTRY ANALYSIS ({len(both_entered)} pairs)")
    print("-"*120)

    both_win = 0
    both_lose = 0
    gex_win_otm_lose = 0
    gex_lose_otm_win = 0

    for gex, otm in both_entered:
        if gex['winner'] and otm['winner']:
            both_win += 1
        elif not gex['winner'] and not otm['winner']:
            both_lose += 1
        elif gex['winner'] and not otm['winner']:
            gex_win_otm_lose += 1
        else:  # gex loses, otm wins
            gex_lose_otm_win += 1

    print(f"\nOutcome Correlation:")
    print(f"  Both WIN:  {both_win:>3} ({both_win/len(both_entered)*100:>5.1f}%)")
    print(f"  Both LOSE: {both_lose:>3} ({both_lose/len(both_entered)*100:>5.1f}%)")
    print(f"  GEX wins, OTM loses: {gex_win_otm_lose:>3} ({gex_win_otm_lose/len(both_entered)*100:>5.1f}%)")
    print(f"  GEX loses, OTM wins: {gex_lose_otm_win:>3} ({gex_lose_otm_win/len(both_entered)*100:>5.1f}%)")

    # Calculate correlation coefficient
    # 1 = both win, 0 = both lose, -1 = opposite
    gex_results = [1 if g['winner'] else 0 for g, o in both_entered]
    otm_results = [1 if o['winner'] else 0 for g, o in both_entered]

    if len(gex_results) > 1:
        correlation = np.corrcoef(gex_results, otm_results)[0, 1]
        print(f"\nCorrelation coefficient: {correlation:.3f}")
        if correlation > 0.7:
            print("  → HIGHLY CORRELATED (tend to win/lose together)")
        elif correlation > 0.3:
            print("  → MODERATELY CORRELATED (some tendency to move together)")
        elif correlation > -0.3:
            print("  → UNCORRELATED (independent outcomes)")
        else:
            print("  → NEGATIVELY CORRELATED (tend to have opposite outcomes)")

    # P/L analysis
    print(f"\n" + "-"*120)
    print("P/L COMPARISON (simultaneous entries)")
    print("-"*120)

    gex_pls = [g['pl'] for g, o in both_entered]
    otm_pls = [o['pl'] for g, o in both_entered]
    combined_pls = [g['pl'] + o['pl'] for g, o in both_entered]

    print(f"\nGEX PIN alone:")
    print(f"  Total P/L: ${sum(gex_pls):,.0f}")
    print(f"  Avg P/L:   ${np.mean(gex_pls):,.0f}")
    print(f"  Win Rate:  {sum(1 for g, o in both_entered if g['winner'])/len(both_entered)*100:.1f}%")

    print(f"\nOTM IRON CONDOR alone:")
    print(f"  Total P/L: ${sum(otm_pls):,.0f}")
    print(f"  Avg P/L:   ${np.mean(otm_pls):,.0f}")
    print(f"  Win Rate:  {sum(1 for g, o in both_entered if o['winner'])/len(both_entered)*100:.1f}%")

    print(f"\nBOTH strategies combined:")
    print(f"  Total P/L: ${sum(combined_pls):,.0f}")
    print(f"  Avg P/L:   ${np.mean(combined_pls):,.0f}")
    print(f"  Win Rate:  {sum(1 for pl in combined_pls if pl > 0)/len(combined_pls)*100:.1f}%")

    # Risk analysis
    gex_winners = [pl for pl in gex_pls if pl > 0]
    gex_losers = [pl for pl in gex_pls if pl < 0]
    otm_winners = [pl for pl in otm_pls if pl > 0]
    otm_losers = [pl for pl in otm_pls if pl < 0]

    print(f"\n" + "-"*120)
    print("RISK PROFILE COMPARISON")
    print("-"*120)

    print(f"\nGEX PIN:")
    if gex_winners:
        print(f"  Avg Winner: ${np.mean(gex_winners):,.0f}")
    if gex_losers:
        print(f"  Avg Loser:  ${np.mean(gex_losers):,.0f}")
        print(f"  Max Loser:  ${min(gex_losers):,.0f}")

    print(f"\nOTM IRON CONDOR:")
    if otm_winners:
        print(f"  Avg Winner: ${np.mean(otm_winners):,.0f}")
    if otm_losers:
        print(f"  Avg Loser:  ${np.mean(otm_losers):,.0f}")
        print(f"  Max Loser:  ${min(otm_losers):,.0f}")

    # Diversification benefit
    print(f"\n" + "-"*120)
    print("DIVERSIFICATION BENEFIT")
    print("-"*120)

    # Compare volatility
    gex_std = np.std(gex_pls)
    otm_std = np.std(otm_pls)
    combined_std = np.std(combined_pls)

    print(f"\nStandard Deviation (volatility):")
    print(f"  GEX alone:     ${gex_std:.0f}")
    print(f"  OTM alone:     ${otm_std:.0f}")
    print(f"  Combined:      ${combined_std:.0f}")

    expected_combined_std = np.sqrt(gex_std**2 + otm_std**2)  # If uncorrelated
    diversification_benefit = (expected_combined_std - combined_std) / expected_combined_std * 100

    if diversification_benefit > 0:
        print(f"\n  → Diversification reduces risk by {diversification_benefit:.1f}% vs running both independently")
    else:
        print(f"\n  → Combined risk is HIGHER than expected (correlation increases risk)")

    # Sharpe-like ratio (return/risk)
    print(f"\nReturn/Risk Ratio:")
    print(f"  GEX alone:     {np.mean(gex_pls)/gex_std:.3f}")
    print(f"  OTM alone:     {np.mean(otm_pls)/otm_std:.3f}")
    print(f"  Combined:      {np.mean(combined_pls)/combined_std:.3f}")

    # Recommendation
    print(f"\n" + "="*120)
    print("RECOMMENDATION")
    print("="*120)

    otm_better_return = np.mean(otm_pls) > np.mean(gex_pls)
    otm_better_winrate = sum(1 for o in otm_pls if o > 0) > sum(1 for g in gex_pls if g > 0)
    combined_better_sharpe = (np.mean(combined_pls)/combined_std) > max(np.mean(gex_pls)/gex_std, np.mean(otm_pls)/otm_std)

    if otm_better_return and otm_better_winrate:
        print("\n✓ OTM strategy DOMINATES GEX strategy (better return AND win rate)")
        print("  → Consider running OTM ONLY instead of both")
        print(f"  → OTM generates ${sum(otm_pls):,.0f} vs GEX ${sum(gex_pls):,.0f} ({sum(otm_pls)/sum(gex_pls):.1f}x more)")
    elif combined_better_sharpe:
        print("\n✓ Running BOTH strategies together improves risk-adjusted returns")
        print("  → Diversification benefit justifies the added complexity")
    else:
        print("\n⚠ Strategies have similar risk/return profiles")
        print("  → May be redundant, consider running best performer only")

    # Capital requirement
    print(f"\n" + "-"*120)
    print("CAPITAL REQUIREMENTS")
    print("-"*120)
    print(f"\nMax simultaneous positions:")
    print(f"  GEX only:  1 position × $1,000 max risk = $1,000 capital")
    print(f"  OTM only:  1 position × $2,000 max risk = $2,000 capital")
    print(f"  Both:      2 positions = $3,000 capital")
    print(f"\nReturn on capital (simultaneous entries only):")
    print(f"  GEX only:  ${sum(gex_pls):,.0f} / $1,000 = {sum(gex_pls)/1000*100:.1f}%")
    print(f"  OTM only:  ${sum(otm_pls):,.0f} / $2,000 = {sum(otm_pls)/2000*100:.1f}%")
    print(f"  Both:      ${sum(combined_pls):,.0f} / $3,000 = {sum(combined_pls)/3000*100:.1f}%")


if __name__ == '__main__':
    np.random.seed(42)
    trades = backtest_gex_and_otm()
    analyze_correlation(trades)
