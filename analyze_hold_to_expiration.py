#!/usr/bin/env python3
"""
Analyze which positions could have been held to expiration for 100% credit.

Current strategy: Take profit at 50-70% of credit
Proposed: Identify positions safe to hold to expiration (100% credit)

Potential gain: If 30-40% of positions can be held safely, could increase
returns by 15-30%.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')

def analyze_hold_opportunities(df):
    """
    Analyze which trades could have been held to expiration for full credit.

    A position is "safe to hold" if:
    1. SPX stays far from strikes (never threatened)
    2. Price moves away from strikes over time (getting safer)
    3. VIX stays low or drops (reducing risk)
    """

    print("\n" + "="*70)
    print("ANALYZING HOLD-TO-EXPIRATION OPPORTUNITIES")
    print("="*70)

    # Load data
    print(f"\nLoaded {len(df)} trades")
    print(f"Current strategy: TP at 50% (HIGH) or 70% (MEDIUM confidence)")

    # Parse strikes
    df['strikes_list'] = df['strikes'].str.split('/')

    def parse_strike_distance(row):
        """Calculate how far SPX is from nearest strike."""
        try:
            strikes = [int(s) for s in row['strikes_list']]
            spx_entry = row['spx_entry']
            spx_close = row['spx_close']

            if row['strategy'] == 'CALL':
                # CALL spread: short strike is lower (closer to ATM)
                short_strike = min(strikes)
                long_strike = max(strikes)
                # Risk if SPX goes UP through short strike
                entry_distance = short_strike - spx_entry
                close_distance = short_strike - spx_close

            elif row['strategy'] == 'PUT':
                # PUT spread: short strike is higher (closer to ATM)
                short_strike = max(strikes)
                long_strike = min(strikes)
                # Risk if SPX goes DOWN through short strike
                entry_distance = spx_entry - short_strike
                close_distance = spx_close - short_strike

            else:  # IC
                # Iron Condor: both sides
                strikes_sorted = sorted(strikes)
                put_short = strikes_sorted[1]
                call_short = strikes_sorted[2]

                # Distance to nearest threat
                entry_distance = min(spx_entry - put_short, call_short - spx_entry)
                close_distance = min(spx_close - put_short, call_short - spx_close)

            return entry_distance, close_distance
        except:
            return None, None

    df[['entry_distance', 'close_distance']] = df.apply(
        parse_strike_distance, axis=1, result_type='expand'
    )

    # Remove rows where parsing failed
    df = df.dropna(subset=['entry_distance', 'close_distance'])

    print(f"\nParsed {len(df)} trades successfully")

    # Current profit distribution
    print("\n" + "-"*70)
    print("CURRENT STRATEGY PERFORMANCE:")
    print("-"*70)

    current_pnl = df['pnl_dollars'].sum()
    current_avg = df['pnl_dollars'].mean()

    print(f"Total P&L: ${current_pnl:,.2f}")
    print(f"Avg per trade: ${current_avg:.2f}")
    print(f"Win rate: {(df['pnl_dollars'] > 0).mean() * 100:.1f}%")

    # Exit reasons
    print("\nExit reasons:")
    exit_counts = df['exit_reason'].value_counts()
    for reason, count in exit_counts.items():
        pct = count / len(df) * 100
        avg_pnl = df[df['exit_reason'] == reason]['pnl_dollars'].mean()
        print(f"  {reason:20s}: {count:4d} ({pct:5.1f}%)  Avg P&L: ${avg_pnl:+7.2f}")

    # Analyze TP trades - could these have been held?
    print("\n" + "-"*70)
    print("ANALYZING TP TRADES (Could they have been held to expiration?):")
    print("-"*70)

    tp_trades = df[df['exit_reason'].str.contains('TP', na=False)].copy()
    print(f"\nTotal TP trades: {len(tp_trades)}")

    # Calculate how much credit was left on table
    tp_trades['captured_profit_pct'] = tp_trades['pnl_dollars'] / (tp_trades['entry_credit'] * 100)
    tp_trades['remaining_credit'] = tp_trades['entry_credit'] * 100 - tp_trades['pnl_dollars']

    total_remaining = tp_trades['remaining_credit'].sum()
    print(f"Total credit left on table: ${total_remaining:,.2f}")
    print(f"Average per TP trade: ${tp_trades['remaining_credit'].mean():.2f}")

    # Identify "safe" TP trades (those that expired worthless if held)
    # "Safe" = close_distance > 20 points (far from strikes at close)
    safe_threshold = 20  # points
    tp_trades['safe_to_hold'] = tp_trades['close_distance'] > safe_threshold

    safe_tp = tp_trades[tp_trades['safe_to_hold']]
    unsafe_tp = tp_trades[~tp_trades['safe_to_hold']]

    print(f"\nTP trades by safety at expiration:")
    print(f"  Safe to hold (>{safe_threshold} pts from strikes): {len(safe_tp)} ({len(safe_tp)/len(tp_trades)*100:.1f}%)")
    print(f"  Unsafe (≤{safe_threshold} pts from strikes):        {len(unsafe_tp)} ({len(unsafe_tp)/len(tp_trades)*100:.1f}%)")

    # Calculate potential gains from holding safe trades
    safe_tp_remaining = safe_tp['remaining_credit'].sum()
    print(f"\nPotential additional profit from holding safe trades: ${safe_tp_remaining:,.2f}")
    print(f"This is {safe_tp_remaining / current_pnl * 100:.1f}% more than current strategy")

    # Characteristics of safe vs unsafe TP trades
    print("\n" + "-"*70)
    print("CHARACTERISTICS OF SAFE VS UNSAFE TP TRADES:")
    print("-"*70)

    for name, subset in [("Safe", safe_tp), ("Unsafe", unsafe_tp)]:
        if len(subset) > 0:
            print(f"\n{name} TP trades ({len(subset)} trades):")
            print(f"  Avg entry distance: {subset['entry_distance'].mean():.1f} pts")
            print(f"  Avg close distance: {subset['close_distance'].mean():.1f} pts")
            print(f"  Avg VIX: {subset['vix'].mean():.1f}")
            print(f"  Avg credit: ${subset['entry_credit'].mean():.2f}")
            print(f"  Avg captured: ${subset['pnl_dollars'].mean():.2f} ({subset['captured_profit_pct'].mean()*100:.1f}% of credit)")
            print(f"  Avg remaining: ${subset['remaining_credit'].mean():.2f}")

    # Identify factors that predict "safe to hold"
    print("\n" + "-"*70)
    print("PREDICTIVE FACTORS FOR 'SAFE TO HOLD':")
    print("-"*70)

    # Entry distance threshold
    for threshold in [30, 40, 50, 60]:
        far_at_entry = tp_trades[tp_trades['entry_distance'] > threshold]
        if len(far_at_entry) > 0:
            safe_pct = (far_at_entry['safe_to_hold']).mean() * 100
            remaining = far_at_entry['remaining_credit'].sum()
            print(f"  Entry distance > {threshold} pts: {len(far_at_entry):3d} trades, {safe_pct:5.1f}% safe, ${remaining:8,.0f} potential gain")

    # VIX threshold
    print("\n  VIX level:")
    for threshold in [14, 16, 18]:
        low_vix = tp_trades[tp_trades['vix'] < threshold]
        if len(low_vix) > 0:
            safe_pct = (low_vix['safe_to_hold']).mean() * 100
            remaining = low_vix['remaining_credit'].sum()
            print(f"    VIX < {threshold}: {len(low_vix):3d} trades, {safe_pct:5.1f}% safe, ${remaining:8,.0f} potential gain")

    # Credit size
    print("\n  Credit size:")
    for threshold in [2.0, 2.5, 3.0, 3.5]:
        high_credit = tp_trades[tp_trades['entry_credit'] > threshold]
        if len(high_credit) > 0:
            safe_pct = (high_credit['safe_to_hold']).mean() * 100
            remaining = high_credit['remaining_credit'].sum()
            print(f"    Credit > ${threshold}: {len(high_credit):3d} trades, {safe_pct:5.1f}% safe, ${remaining:8,.0f} potential gain")

    # Combined filter (best prediction)
    print("\n" + "-"*70)
    print("OPTIMAL 'HOLD TO EXPIRATION' FILTER:")
    print("-"*70)

    # Test various combinations
    best_filters = []

    for entry_dist in [40, 50, 60]:
        for vix_max in [15, 16, 17]:
            for credit_min in [2.5, 3.0]:
                filter_mask = (
                    (tp_trades['entry_distance'] > entry_dist) &
                    (tp_trades['vix'] < vix_max) &
                    (tp_trades['entry_credit'] > credit_min)
                )
                filtered = tp_trades[filter_mask]

                if len(filtered) > 10:  # Need reasonable sample size
                    safe_pct = (filtered['safe_to_hold']).mean() * 100
                    remaining = filtered['remaining_credit'].sum()

                    best_filters.append({
                        'entry_dist': entry_dist,
                        'vix_max': vix_max,
                        'credit_min': credit_min,
                        'count': len(filtered),
                        'safe_pct': safe_pct,
                        'remaining': remaining,
                        'avg_remaining': filtered['remaining_credit'].mean()
                    })

    # Sort by safe_pct * count (maximize both safety and volume)
    best_filters.sort(key=lambda x: x['safe_pct'] * x['count'], reverse=True)

    print("\nTop 5 filter combinations:")
    print(f"{'Entry Dist':>11} | {'VIX':>5} | {'Credit':>7} | {'Count':>5} | {'Safe%':>6} | {'Total Gain':>11} | {'Avg Gain':>9}")
    print("-" * 80)

    for f in best_filters[:5]:
        print(f"    >{f['entry_dist']:2d} pts | <{f['vix_max']:4.1f} | >${f['credit_min']:4.2f} | {f['count']:5d} | {f['safe_pct']:5.1f}% | ${f['remaining']:9,.0f} | ${f['avg_remaining']:7.2f}")

    # Select best filter
    best = best_filters[0]
    print(f"\n✅ RECOMMENDED FILTER:")
    print(f"   Entry distance > {best['entry_dist']} points")
    print(f"   VIX < {best['vix_max']}")
    print(f"   Credit > ${best['credit_min']}")
    print(f"\n   Identifies {best['count']} trades ({best['count']/len(tp_trades)*100:.1f}% of TP trades)")
    print(f"   {best['safe_pct']:.1f}% would have expired worthless")
    print(f"   Potential gain: ${best['remaining']:,.0f} (+{best['remaining']/current_pnl*100:.1f}% vs current)")

    return {
        'df': df,
        'tp_trades': tp_trades,
        'safe_tp': safe_tp,
        'best_filter': best,
        'current_pnl': current_pnl
    }

def visualize_hold_analysis(results, output_file='/root/gamma/hold_to_expiration_analysis.png'):
    """Create visualization of hold-to-expiration analysis."""

    df = results['df']
    tp_trades = results['tp_trades']

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle('Hold-to-Expiration Analysis\nCan we identify positions safe to hold for 100% credit?',
                 fontsize=16, fontweight='bold')

    # ========== Plot 1: Entry Distance vs Safety ==========
    ax1 = axes[0, 0]

    safe = tp_trades[tp_trades['safe_to_hold']]
    unsafe = tp_trades[~tp_trades['safe_to_hold']]

    ax1.scatter(unsafe['entry_distance'], unsafe['close_distance'],
               alpha=0.5, c='red', s=30, label=f'Unsafe ({len(unsafe)})')
    ax1.scatter(safe['entry_distance'], safe['close_distance'],
               alpha=0.5, c='green', s=30, label=f'Safe ({len(safe)})')

    ax1.axhline(y=20, color='orange', linestyle='--', linewidth=2, label='Safe threshold (20 pts)')
    ax1.axvline(x=50, color='blue', linestyle='--', linewidth=2, label='Recommended filter (50 pts)')

    ax1.set_xlabel('Entry Distance (points from strike)', fontsize=11)
    ax1.set_ylabel('Close Distance (points from strike)', fontsize=11)
    ax1.set_title('Position Safety: Entry vs Close Distance', fontsize=12, fontweight='bold')
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)

    # ========== Plot 2: Credit Left on Table ==========
    ax2 = axes[0, 1]

    bins = np.arange(0, 350, 10)
    ax2.hist(tp_trades['remaining_credit'], bins=bins, alpha=0.7, color='steelblue', edgecolor='black')

    mean_remaining = tp_trades['remaining_credit'].mean()
    ax2.axvline(mean_remaining, color='red', linestyle='--', linewidth=2,
               label=f'Mean: ${mean_remaining:.2f}')

    ax2.set_xlabel('Credit Left on Table ($)', fontsize=11)
    ax2.set_ylabel('Frequency', fontsize=11)
    ax2.set_title('How Much Credit Was Left Uncaptured?', fontsize=12, fontweight='bold')
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)

    total_remaining = tp_trades['remaining_credit'].sum()
    text = f"Total: ${total_remaining:,.0f}\n{len(tp_trades)} TP trades"
    ax2.text(0.98, 0.97, text, transform=ax2.transAxes, fontsize=10,
            verticalalignment='top', horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    # ========== Plot 3: VIX vs Safety ==========
    ax3 = axes[1, 0]

    vix_bins = np.arange(12, 21, 1)
    safe_by_vix = []
    vix_centers = []

    for i in range(len(vix_bins)-1):
        vix_range = tp_trades[(tp_trades['vix'] >= vix_bins[i]) &
                              (tp_trades['vix'] < vix_bins[i+1])]
        if len(vix_range) > 0:
            safe_pct = (vix_range['safe_to_hold']).mean() * 100
            safe_by_vix.append(safe_pct)
            vix_centers.append((vix_bins[i] + vix_bins[i+1]) / 2)

    ax3.bar(vix_centers, safe_by_vix, width=0.8, alpha=0.7, color='coral', edgecolor='black')
    ax3.axhline(y=50, color='green', linestyle='--', linewidth=2, label='50% threshold')

    ax3.set_xlabel('VIX Level', fontsize=11)
    ax3.set_ylabel('% Safe to Hold', fontsize=11)
    ax3.set_title('Lower VIX = Safer to Hold', fontsize=12, fontweight='bold')
    ax3.legend(fontsize=9)
    ax3.grid(True, alpha=0.3)
    ax3.set_ylim(0, 100)

    # ========== Plot 4: Potential Gain by Strategy ==========
    ax4 = axes[1, 1]

    strategies = ['Current\n(TP at 50-70%)', 'Hold Safe\n(filter)', 'Hold All\n(risky)']

    current = results['current_pnl']
    best = results['best_filter']
    hold_safe_gain = best['remaining']
    hold_all_gain = tp_trades['remaining_credit'].sum()

    # Estimate risk for "hold all"
    # Unsafe trades: assume 50% would lose vs expire worthless
    unsafe_count = len(tp_trades[~tp_trades['safe_to_hold']])
    unsafe_avg_credit = tp_trades[~tp_trades['safe_to_hold']]['entry_credit'].mean() * 100
    hold_all_risk = unsafe_count * unsafe_avg_credit * 0.5  # 50% lose

    pnls = [
        current / 1000,  # Current
        (current + hold_safe_gain) / 1000,  # Hold safe
        (current + hold_all_gain - hold_all_risk) / 1000  # Hold all (adjusted for risk)
    ]

    colors = ['steelblue', 'green', 'orange']
    bars = ax4.bar(strategies, pnls, color=colors, alpha=0.7, edgecolor='black', linewidth=2)

    # Add value labels on bars
    for bar, pnl in zip(bars, pnls):
        height = bar.get_height()
        ax4.text(bar.get_x() + bar.get_width()/2., height,
                f'${pnl:.0f}k\n(+{(pnl/pnls[0]-1)*100:.0f}%)',
                ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax4.set_ylabel('Total P&L ($1000s)', fontsize=11)
    ax4.set_title('Strategy Comparison', fontsize=12, fontweight='bold')
    ax4.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\n✅ Visualization saved: {output_file}")

if __name__ == "__main__":
    # Load backtest results
    print("Loading backtest data...")
    df = pd.read_csv('/root/gamma/data/backtest_results.csv')

    # Run analysis
    results = analyze_hold_opportunities(df)

    # Create visualization
    visualize_hold_analysis(results)

    print("\n" + "="*70)
    print("ANALYSIS COMPLETE")
    print("="*70)
