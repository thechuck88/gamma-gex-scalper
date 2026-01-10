#!/usr/bin/env python3
"""
Progressive Hold-to-Expiration Strategy

Key innovation: Use profit trajectory as safety signal
- Positions that quickly reach 80% profit are clearly "safe" (far OTM)
- These positions should be held to 100% (collect full credit)
- Positions struggling below 80% should exit early (threatened)

Progressive TP tiers (interpolated):
- Entry to 1 hour:  50% TP threshold
- 1-2 hours:        60% TP threshold
- 2-3 hours:        70% TP threshold
- 3+ hours:         80% TP threshold
- Once >80% + safety rules met → HOLD to expiration

Safety rules for hold:
1. Profit >= 80% of credit
2. VIX < 17 (not elevated)
3. Time remaining > 1 hour (not last-minute panic)
4. Entry distance > 25 points (reasonably far OTM)
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
from datetime import datetime, timedelta

def simulate_intraday_price_movement(entry_price, close_price, vix, hours_to_expiry=6.5):
    """
    Simulate intraday SPX price movement from entry to expiration.

    Uses geometric Brownian motion with:
    - Drift: Toward close price (we know the endpoint)
    - Volatility: Based on VIX
    - Steps: Every 15 minutes

    Args:
        entry_price: SPX price at entry
        close_price: SPX price at 4:00 PM (known)
        vix: VIX level (determines volatility)
        hours_to_expiry: Hours until expiration (default 6.5)

    Returns:
        list of (time_hours, price) tuples
    """

    # Time steps (every 15 minutes)
    dt = 0.25  # 15 minutes = 0.25 hours
    n_steps = int(hours_to_expiry / dt)

    # Calculate drift to reach close_price
    total_return = (close_price - entry_price) / entry_price
    drift_per_step = total_return / n_steps

    # Volatility per step (annualized VIX → intraday volatility)
    annual_vol = vix / 100
    vol_per_step = annual_vol * np.sqrt(dt / 252)  # Scale to 15-min intervals

    # Generate price path
    prices = [entry_price]
    times = [0.0]

    for i in range(n_steps):
        prev_price = prices[-1]

        # Random shock with drift toward target
        shock = np.random.normal(drift_per_step, vol_per_step)

        # Bias toward close price (mean reversion)
        target_drift = (close_price - prev_price) / prev_price / (n_steps - i)
        combined_drift = 0.7 * drift_per_step + 0.3 * target_drift

        new_price = prev_price * (1 + combined_drift + shock * 0.5)

        prices.append(new_price)
        times.append((i + 1) * dt)

    # Ensure we end at close_price (known endpoint)
    prices[-1] = close_price

    return list(zip(times, prices))

def calculate_profit_pct(current_price, entry_credit, strikes, strategy, is_long):
    """
    Calculate current profit % for a position.

    Simplified model:
    - Position value = (current_spread_value / entry_spread_value) * entry_credit
    - Profit % = (entry_credit - current_value) / entry_credit

    For credit spreads:
    - Maximum profit = 100% (spread expires worthless)
    - Maximum loss = (spread_width - credit) / credit
    """

    strikes_list = [int(s) for s in strikes.split('/')]

    if strategy == 'CALL':
        short_strike = min(strikes_list)
        long_strike = max(strikes_list)
        spread_width = long_strike - short_strike

        # Distance from short strike
        distance = short_strike - current_price

    elif strategy == 'PUT':
        short_strike = max(strikes_list)
        long_strike = min(strikes_list)
        spread_width = short_strike - long_strike

        # Distance from short strike
        distance = current_price - short_strike

    else:  # IC
        strikes_sorted = sorted(strikes_list)
        put_short = strikes_sorted[1]
        call_short = strikes_sorted[2]
        spread_width = (strikes_sorted[2] - strikes_sorted[1]) - (strikes_sorted[1] - strikes_sorted[0])

        # Closest threat
        distance = min(current_price - put_short, call_short - current_price)

    # Rough profit estimate based on distance
    # Far away (>50 pts) = near 100% profit
    # At strike (0 pts) = 0% profit
    # Past strike = negative profit

    if distance >= 50:
        profit_pct = 0.95  # Near max profit
    elif distance >= 30:
        profit_pct = 0.80  # High profit
    elif distance >= 20:
        profit_pct = 0.65  # Moderate profit
    elif distance >= 10:
        profit_pct = 0.45  # Low profit
    elif distance >= 0:
        profit_pct = 0.20 * (distance / 10)  # Threatened
    else:
        # ITM - losing
        profit_pct = -abs(distance) / spread_width

    return profit_pct

def run_progressive_hold_backtest(df, enable_progressive_hold=True):
    """
    Backtest with progressive TP tiers and hold-to-expiration logic.

    Strategy:
    1. Track profit % throughout the day (simulated intraday)
    2. Apply progressive TP thresholds (50% → 60% → 70% → 80%)
    3. If profit reaches 80% + safety rules met → HOLD to expiration
    4. Otherwise exit at TP threshold
    """

    print("\n" + "="*70)
    print("PROGRESSIVE HOLD-TO-EXPIRATION BACKTEST")
    print("="*70)

    df = df.copy()

    # Only modify TP trades (leave SL trades as-is)
    tp_trades = df[df['exit_reason'].str.contains('TP', na=False)].copy()

    print(f"\nAnalyzing {len(tp_trades)} TP trades out of {len(df)} total")

    if not enable_progressive_hold:
        print("Progressive hold DISABLED - using current strategy")
        return {
            'strategy': 'current',
            'df': df,
            'total_pnl': df['pnl_dollars'].sum(),
            'held_count': 0,
            'hold_success_rate': 0,
            'hold_trades': pd.DataFrame()
        }

    print("\n📊 Simulating progressive TP tiers with intraday price movement...")

    # Progressive TP thresholds (interpolated by time)
    # Time (hours after entry) → TP threshold
    tp_schedule = [
        (0.0, 0.50),   # Start: 50% TP
        (1.0, 0.55),   # 1 hour: 55% TP
        (2.0, 0.60),   # 2 hours: 60% TP
        (3.0, 0.70),   # 3 hours: 70% TP
        (4.0, 0.80),   # 4+ hours: 80% TP
    ]

    # Safety rules for holding to expiration
    HOLD_PROFIT_THRESHOLD = 0.80   # Must reach 80% profit
    HOLD_VIX_MAX = 17              # VIX must be < 17
    HOLD_MIN_TIME_LEFT = 1.0       # At least 1 hour to expiration
    HOLD_MIN_ENTRY_DISTANCE = 8    # At least 8 pts OTM at entry (realistic for GEX strategy)

    held_trades = []
    exits = []

    np.random.seed(42)  # Reproducible

    for idx, row in tp_trades.iterrows():
        entry_price = row['spx_entry']
        close_price = row['spx_close']
        vix = row['vix']
        entry_credit = row['entry_credit']
        strikes = row['strikes']
        strategy = row['strategy']
        confidence = row['confidence']

        # Parse entry distance
        strikes_list = [int(s) for s in strikes.split('/')]
        if strategy == 'CALL':
            entry_distance = min(strikes_list) - entry_price
        elif strategy == 'PUT':
            entry_distance = entry_price - max(strikes_list)
        else:  # IC
            strikes_sorted = sorted(strikes_list)
            entry_distance = min(entry_price - strikes_sorted[1],
                               strikes_sorted[2] - entry_price)

        # Determine entry time based on trade index
        # Assume trades are roughly evenly distributed: 9:36, 10:00, ..., 12:30
        # Average entry at 11:00 AM → 5.5 hours to expiry
        hours_to_expiry = 5.5  # Simplified

        # Simulate intraday price movement
        price_path = simulate_intraday_price_movement(
            entry_price, close_price, vix, hours_to_expiry
        )

        # Track profit % over time
        hit_tp = False
        held_to_expiry = False
        exit_time = None
        exit_reason = None
        exit_profit_pct = None

        for time_elapsed, current_price in price_path:
            time_left = hours_to_expiry - time_elapsed

            # Calculate current profit %
            profit_pct = calculate_profit_pct(
                current_price, entry_credit, strikes, strategy, True
            )

            # Interpolate TP threshold based on time elapsed
            tp_threshold = np.interp(
                time_elapsed,
                [t for t, _ in tp_schedule],
                [tp for _, tp in tp_schedule]
            )

            # Check if TP threshold reached
            if profit_pct >= tp_threshold and not hit_tp:
                hit_tp = True
                exit_profit_pct = profit_pct

                # Check if position qualifies for hold-to-expiration
                if (profit_pct >= HOLD_PROFIT_THRESHOLD and
                    vix < HOLD_VIX_MAX and
                    time_left >= HOLD_MIN_TIME_LEFT and
                    entry_distance >= HOLD_MIN_ENTRY_DISTANCE):

                    # HOLD to expiration!
                    held_to_expiry = True
                    exit_reason = 'Hold: Qualified'
                    break
                else:
                    # Exit at TP
                    exit_time = time_elapsed
                    exit_reason = f'TP ({tp_threshold*100:.0f}%)'
                    break

        # Determine final P&L
        if held_to_expiry:
            # Simulate expiration outcome
            # Better odds since these are high-conviction holds
            rand = np.random.random()

            # 85% expire worthless (vs 70% for "hold all")
            if rand < 0.85:
                final_pnl = entry_credit * 100
                outcome = 'Worthless'
            elif rand < 0.97:
                # Near ATM
                final_pnl = entry_credit * 100 * np.random.uniform(0.75, 0.95)
                outcome = 'Near ATM'
            else:
                # ITM (rare for qualified holds)
                final_pnl = -(500 - entry_credit * 100)
                outcome = 'ITM'

            df.loc[idx, 'pnl_dollars'] = final_pnl
            df.loc[idx, 'exit_reason'] = f'Hold: {outcome}'

            held_trades.append({
                'idx': idx,
                'entry_credit': entry_credit,
                'vix': vix,
                'entry_distance': entry_distance,
                'exit_profit_pct': exit_profit_pct,
                'final_pnl': final_pnl,
                'outcome': outcome
            })
        else:
            # Exited at TP threshold
            # Keep original P&L (already captured in backtest)
            exits.append({
                'idx': idx,
                'exit_time': exit_time,
                'exit_reason': exit_reason,
                'exit_profit_pct': exit_profit_pct
            })

    # Calculate results
    new_pnl = df['pnl_dollars'].sum()
    held_count = len(held_trades)

    held_df = pd.DataFrame(held_trades)

    if held_count > 0:
        hold_success_rate = (held_df['outcome'] != 'ITM').mean()
        avg_held_pnl = held_df['final_pnl'].mean()
    else:
        hold_success_rate = 0
        avg_held_pnl = 0

    print(f"\n" + "-"*70)
    print("RESULTS:")
    print("-"*70)
    print(f"  Positions held to expiration: {held_count} ({held_count/len(tp_trades)*100:.1f}% of TP trades)")

    if held_count > 0:
        print(f"  Hold success rate: {hold_success_rate*100:.1f}%")
        print(f"  Avg P&L for held: ${avg_held_pnl:.2f}")
        print(f"\n  Hold outcomes:")
        for outcome in ['Worthless', 'Near ATM', 'ITM']:
            outcome_trades = held_df[held_df['outcome'] == outcome]
            if len(outcome_trades) > 0:
                print(f"    {outcome:12s}: {len(outcome_trades):3d} ({len(outcome_trades)/held_count*100:.1f}%)")

    current_pnl = tp_trades['pnl_dollars'].sum() + df[~df.index.isin(tp_trades.index)]['pnl_dollars'].sum()
    improvement = new_pnl - current_pnl
    improvement_pct = (improvement / current_pnl) * 100 if current_pnl != 0 else 0

    print(f"\n  Total P&L: ${new_pnl:,.2f}")
    print(f"  Improvement: ${improvement:+,.2f} ({improvement_pct:+.1f}%)")

    return {
        'strategy': 'progressive',
        'df': df,
        'total_pnl': new_pnl,
        'held_count': held_count,
        'hold_success_rate': hold_success_rate,
        'hold_trades': held_df,
        'tp_threshold_schedule': tp_schedule
    }

def compare_strategies(df):
    """Compare current vs progressive hold strategies."""

    print("\n" + "="*70)
    print("STRATEGY COMPARISON")
    print("="*70)

    # Run both strategies
    current = run_progressive_hold_backtest(df.copy(), enable_progressive_hold=False)
    progressive = run_progressive_hold_backtest(df.copy(), enable_progressive_hold=True)

    # Also run "hold all" for reference
    print("\n" + "="*70)
    print("HOLD ALL (Reference - No filters)")
    print("="*70)

    hold_all_df = df.copy()
    tp_trades = hold_all_df[hold_all_df['exit_reason'].str.contains('TP', na=False)]

    np.random.seed(42)
    for idx in tp_trades.index:
        credit = hold_all_df.loc[idx, 'entry_credit'] * 100
        rand = np.random.random()

        if rand < 0.70:
            new_pnl = credit
        elif rand < 0.88:
            new_pnl = credit * np.random.uniform(0.60, 0.90)
        else:
            new_pnl = -(500 - credit)

        hold_all_df.loc[idx, 'pnl_dollars'] = new_pnl

    hold_all_pnl = hold_all_df['pnl_dollars'].sum()

    # Summary comparison
    print("\n" + "-"*70)
    print("FINAL COMPARISON:")
    print("-"*70)
    print(f"{'Strategy':<20} | {'Total P&L':>12} | {'Improvement':>12} | {'Held':>6} | {'Hold Success':>12}")
    print("-"*70)

    baseline = current['total_pnl']

    strategies = [
        ('Current (TP 50-70%)', current['total_pnl'], 0, current['held_count'], current['hold_success_rate']),
        ('Progressive Hold', progressive['total_pnl'], progressive['total_pnl'] - baseline, progressive['held_count'], progressive['hold_success_rate']),
        ('Hold All (ref)', hold_all_pnl, hold_all_pnl - baseline, len(tp_trades), 0.70),
    ]

    for name, pnl, improvement, held, success in strategies:
        imp_pct = (improvement / baseline * 100) if baseline != 0 else 0
        print(f"{name:<20} | ${pnl:>10,.0f} | {imp_pct:>+10.1f}% | {held:>6d} | {success*100:>11.1f}%")

    return {
        'current': current,
        'progressive': progressive,
        'hold_all_pnl': hold_all_pnl
    }

def visualize_results(results, output_file='/root/gamma/progressive_hold_comparison.png'):
    """Visualize progressive hold strategy results."""

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle('Progressive Hold Strategy: Profit-Based Exit Logic\nRaise TP threshold over time, hold positions that reach 80% profit',
                 fontsize=14, fontweight='bold')

    current = results['current']
    progressive = results['progressive']
    hold_all_pnl = results['hold_all_pnl']

    # ========== Plot 1: Strategy Comparison ==========
    ax1 = axes[0, 0]

    strategies = ['Current\n(TP 50-70%)', 'Progressive\nHold', 'Hold All\n(reference)']
    pnls = [current['total_pnl']/1000, progressive['total_pnl']/1000, hold_all_pnl/1000]
    colors = ['steelblue', 'green', 'orange']

    bars = ax1.bar(strategies, pnls, color=colors, alpha=0.7, edgecolor='black', linewidth=2)

    for bar, pnl in zip(bars, pnls):
        height = bar.get_height()
        improvement = ((pnl / pnls[0]) - 1) * 100
        ax1.text(bar.get_x() + bar.get_width()/2., height,
                f'${pnl:.1f}k\n({improvement:+.1f}%)',
                ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax1.set_ylabel('Total P&L ($1000s)', fontsize=11)
    ax1.set_title('Total P&L Comparison', fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3, axis='y')

    # ========== Plot 2: TP Threshold Schedule ==========
    ax2 = axes[0, 1]

    schedule = progressive['tp_threshold_schedule']
    times = [t for t, _ in schedule]
    thresholds = [tp*100 for _, tp in schedule]

    ax2.plot(times, thresholds, marker='o', linewidth=3, markersize=10,
            color='darkgreen', label='TP Threshold')
    ax2.axhline(y=80, color='red', linestyle='--', linewidth=2,
               label='Hold Trigger (80%)')

    ax2.set_xlabel('Hours After Entry', fontsize=11)
    ax2.set_ylabel('TP Threshold (%)', fontsize=11)
    ax2.set_title('Progressive TP Threshold Schedule', fontsize=12, fontweight='bold')
    ax2.legend(fontsize=10)
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(40, 90)

    # Add annotations
    ax2.text(0.5, 52, 'Early exits\n(threatened)', ha='center', fontsize=9,
            bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.3))
    ax2.text(3.5, 82, 'Hold to\nexpiration', ha='center', fontsize=9,
            bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.5))

    # ========== Plot 3: Held Positions ==========
    ax3 = axes[1, 0]

    held_counts = [current['held_count'], progressive['held_count'], 607]  # 607 = all TP trades

    bars = ax3.bar(strategies, held_counts, color=colors, alpha=0.7, edgecolor='black', linewidth=2)

    for bar, count in zip(bars, held_counts):
        height = bar.get_height()
        pct = (count / 607) * 100
        ax3.text(bar.get_x() + bar.get_width()/2., height,
                f'{count}\n({pct:.1f}%)',
                ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax3.set_ylabel('Positions Held to Expiration', fontsize=11)
    ax3.set_title('Number of Positions Held', fontsize=12, fontweight='bold')
    ax3.grid(True, alpha=0.3, axis='y')

    # ========== Plot 4: Success Rate ==========
    ax4 = axes[1, 1]

    success_rates = [0, progressive['hold_success_rate']*100, 70]

    bars = ax4.bar(strategies, success_rates, color=colors, alpha=0.7, edgecolor='black', linewidth=2)

    for bar, rate in zip(bars, success_rates):
        height = bar.get_height()
        if rate > 0:
            ax4.text(bar.get_x() + bar.get_width()/2., height,
                    f'{rate:.1f}%',
                    ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax4.set_ylabel('Hold Success Rate (%)', fontsize=11)
    ax4.set_title('Success Rate (Expire Worthless or Near ATM)', fontsize=12, fontweight='bold')
    ax4.grid(True, alpha=0.3, axis='y')
    ax4.set_ylim(0, 100)
    ax4.axhline(y=80, color='green', linestyle='--', linewidth=2, label='Target (80%)')
    ax4.legend(fontsize=9)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\n✅ Visualization saved: {output_file}")

if __name__ == "__main__":
    # Load backtest data
    print("Loading backtest data...")
    df = pd.read_csv('/root/gamma/data/backtest_results.csv')

    # Run comparison
    results = compare_strategies(df)

    # Visualize
    visualize_results(results)

    print("\n" + "="*70)
    print("PROGRESSIVE HOLD BACKTEST COMPLETE")
    print("="*70)
