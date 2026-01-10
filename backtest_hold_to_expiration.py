#!/usr/bin/env python3
"""
Backtest: Hold-to-Expiration Strategy

Compare three exit strategies:
1. Current: TP at 50-70% profit
2. Smart Hold: Hold positions with high conviction (far OTM, low VIX)
3. Hold All: Hold everything to expiration (risky)

Key question: Can we collect more premium by holding to expiration?
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')

def simulate_hold_to_expiration(df, hold_strategy='all'):
    """
    Simulate holding positions to expiration for 100% credit.

    Args:
        df: Backtest results
        hold_strategy: 'all', 'smart', or 'current'

    Returns:
        dict with results
    """

    print("\n" + "="*70)
    print(f"SIMULATING: {hold_strategy.upper()} HOLD-TO-EXPIRATION STRATEGY")
    print("="*70)

    df = df.copy()

    # Current strategy results
    current_pnl = df['pnl_dollars'].sum()
    current_trades = len(df)
    current_winners = (df['pnl_dollars'] > 0).sum()
    current_win_rate = current_winners / current_trades

    print(f"\nBaseline (Current Strategy):")
    print(f"  Total P&L: ${current_pnl:,.2f}")
    print(f"  Trades: {current_trades}")
    print(f"  Win rate: {current_win_rate*100:.1f}%")
    print(f"  Avg per trade: ${df['pnl_dollars'].mean():.2f}")

    # Analyze TP trades
    tp_trades = df[df['exit_reason'].str.contains('TP', na=False)].copy()
    print(f"\n  TP trades: {len(tp_trades)} ({len(tp_trades)/current_trades*100:.1f}%)")

    # Calculate credit captured vs total credit
    tp_trades['captured_pct'] = tp_trades['pnl_dollars'] / (tp_trades['entry_credit'] * 100)
    avg_captured = tp_trades['captured_pct'].mean()
    print(f"  Avg captured: {avg_captured*100:.1f}% of credit")

    # Credit left on table (if we held to 100%)
    tp_trades['remaining_credit'] = tp_trades['entry_credit'] * 100 - tp_trades['pnl_dollars']
    total_remaining = tp_trades['remaining_credit'].sum()
    avg_remaining = tp_trades['remaining_credit'].mean()

    print(f"  Credit left on table: ${total_remaining:,.2f} (avg ${avg_remaining:.2f}/trade)")

    # ----- Simulate Hold-to-Expiration -----

    if hold_strategy == 'current':
        # Keep current results
        new_df = df.copy()
        hold_count = 0

    elif hold_strategy == 'all':
        # Hold ALL TP trades to expiration
        print(f"\n📊 Simulating: HOLD ALL TP TRADES to expiration")

        hold_count = len(tp_trades)

        # Assumptions for positions held to expiration:
        # - Some will expire worthless (100% profit)
        # - Some will expire ITM (loss)
        #
        # Based on GEX strategy characteristics:
        # - Strikes are NEAR pin (not far OTM)
        # - Pin effect pulls price toward strikes
        # - Higher risk of ITM expiration
        #
        # Estimate:
        # - 70% expire worthless (100% credit)
        # - 20% expire near ATM (50-80% credit - similar to current)
        # - 10% expire ITM (lose spread width - max loss)

        expire_worthless_pct = 0.70
        expire_near_atm_pct = 0.20
        expire_itm_pct = 0.10

        new_df = df.copy()

        # Simulate outcomes for TP trades
        np.random.seed(42)  # Reproducible
        tp_indices = tp_trades.index

        for idx in tp_indices:
            credit = new_df.loc[idx, 'entry_credit'] * 100
            current_pnl = new_df.loc[idx, 'pnl_dollars']

            rand = np.random.random()

            if rand < expire_worthless_pct:
                # Expire worthless - collect 100% credit
                new_pnl = credit
                outcome = 'Worthless'

            elif rand < (expire_worthless_pct + expire_near_atm_pct):
                # Expire near ATM - collect 60-90% credit (random)
                capture_pct = np.random.uniform(0.60, 0.90)
                new_pnl = credit * capture_pct
                outcome = 'Near ATM'

            else:
                # Expire ITM - lose spread width
                # Assume 5-point spreads, max loss = $500
                # But we collected premium, so net loss = $500 - credit
                max_loss = 500
                new_pnl = -(max_loss - credit)
                outcome = 'ITM (loss)'

            new_df.loc[idx, 'pnl_dollars'] = new_pnl
            new_df.loc[idx, 'exit_reason'] = f'Hold: {outcome}'

    elif hold_strategy == 'smart':
        # Hold ONLY high-confidence trades
        print(f"\n📊 Simulating: SMART HOLD (high conviction only)")

        # Criteria for "safe to hold":
        # 1. High credit (>$3.00) - further OTM
        # 2. Low VIX (<16) - lower volatility risk
        # 3. HIGH confidence level (strategy already identified it as strong)
        # 4. Not IC (IC has 2-sided risk)

        smart_hold_mask = (
            (tp_trades['entry_credit'] > 3.0) &
            (tp_trades['vix'] < 16) &
            (tp_trades['confidence'] == 'HIGH') &
            (tp_trades['strategy'] != 'IC')
        )

        smart_hold_trades = tp_trades[smart_hold_mask]
        hold_count = len(smart_hold_trades)

        print(f"  Identified {hold_count} trades meeting criteria:")
        print(f"    - Credit > $3.00")
        print(f"    - VIX < 16")
        print(f"    - HIGH confidence")
        print(f"    - Not Iron Condor")

        # Better odds for smart holds (more selective)
        expire_worthless_pct = 0.85  # Higher success rate
        expire_near_atm_pct = 0.12
        expire_itm_pct = 0.03  # Lower risk

        new_df = df.copy()
        np.random.seed(42)

        for idx in smart_hold_trades.index:
            credit = new_df.loc[idx, 'entry_credit'] * 100
            current_pnl = new_df.loc[idx, 'pnl_dollars']

            rand = np.random.random()

            if rand < expire_worthless_pct:
                new_pnl = credit
                outcome = 'Worthless'
            elif rand < (expire_worthless_pct + expire_near_atm_pct):
                capture_pct = np.random.uniform(0.70, 0.95)
                new_pnl = credit * capture_pct
                outcome = 'Near ATM'
            else:
                max_loss = 500
                new_pnl = -(max_loss - credit)
                outcome = 'ITM (loss)'

            new_df.loc[idx, 'pnl_dollars'] = new_pnl
            new_df.loc[idx, 'exit_reason'] = f'Hold: {outcome}'

    # Calculate new results
    new_pnl = new_df['pnl_dollars'].sum()
    new_winners = (new_df['pnl_dollars'] > 0).sum()
    new_win_rate = new_winners / current_trades
    new_avg = new_df['pnl_dollars'].mean()

    improvement_pct = (new_pnl - current_pnl) / current_pnl * 100

    print(f"\n" + "-"*70)
    print(f"RESULTS ({hold_strategy.upper()} strategy):")
    print("-"*70)
    print(f"  Total P&L: ${new_pnl:,.2f} ({improvement_pct:+.1f}% vs current)")
    print(f"  Win rate: {new_win_rate*100:.1f}% ({(new_win_rate-current_win_rate)*100:+.1f}%)")
    print(f"  Avg per trade: ${new_avg:.2f} ({new_avg - df['pnl_dollars'].mean():+.2f})")
    print(f"  Trades modified: {hold_count}")

    # Exit reason breakdown
    if hold_count > 0:
        print(f"\n  Hold outcomes:")
        held_trades = new_df[new_df['exit_reason'].str.contains('Hold:', na=False)]
        for outcome in ['Worthless', 'Near ATM', 'ITM']:
            outcome_trades = held_trades[held_trades['exit_reason'].str.contains(outcome, na=False)]
            if len(outcome_trades) > 0:
                pct = len(outcome_trades) / len(held_trades) * 100
                avg_pnl = outcome_trades['pnl_dollars'].mean()
                total_pnl = outcome_trades['pnl_dollars'].sum()
                print(f"    {outcome:15s}: {len(outcome_trades):3d} trades ({pct:5.1f}%)  Avg: ${avg_pnl:+7.2f}  Total: ${total_pnl:+9,.2f}")

    return {
        'strategy': hold_strategy,
        'df': new_df,
        'current_pnl': current_pnl,
        'new_pnl': new_pnl,
        'improvement': new_pnl - current_pnl,
        'improvement_pct': improvement_pct,
        'current_win_rate': current_win_rate,
        'new_win_rate': new_win_rate,
        'hold_count': hold_count
    }

def compare_strategies(df):
    """Compare all three strategies side-by-side."""

    print("\n" + "="*70)
    print("COMPARING ALL STRATEGIES")
    print("="*70)

    results = {}
    for strategy in ['current', 'smart', 'all']:
        results[strategy] = simulate_hold_to_expiration(df, strategy)

    # Summary table
    print("\n" + "-"*70)
    print("SUMMARY COMPARISON:")
    print("-"*70)
    print(f"{'Strategy':<15} | {'P&L':>12} | {'Improvement':>12} | {'Win Rate':>8} | {'Avg/Trade':>10} | {'Held':>6}")
    print("-"*70)

    for strategy in ['current', 'smart', 'all']:
        r = results[strategy]
        print(f"{strategy.capitalize():<15} | ${r['new_pnl']:>10,.0f} | {r['improvement_pct']:>+10.1f}% | {r['new_win_rate']*100:>7.1f}% | ${r['new_pnl']/1073:>8.2f} | {r['hold_count']:>6d}")

    return results

def visualize_comparison(results, output_file='/root/gamma/hold_strategy_comparison.png'):
    """Visualize strategy comparison."""

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle('Hold-to-Expiration Strategy Comparison\nCurrent vs Smart Hold vs Hold All',
                 fontsize=16, fontweight='bold')

    strategies = ['Current', 'Smart Hold', 'Hold All']
    colors = ['steelblue', 'green', 'orange']

    # ========== Plot 1: Total P&L ==========
    ax1 = axes[0, 0]

    pnls = [results['current']['new_pnl']/1000,
            results['smart']['new_pnl']/1000,
            results['all']['new_pnl']/1000]

    bars = ax1.bar(strategies, pnls, color=colors, alpha=0.7, edgecolor='black', linewidth=2)

    for bar, pnl, strat in zip(bars, pnls, ['current', 'smart', 'all']):
        height = bar.get_height()
        improvement = results[strat]['improvement_pct']
        ax1.text(bar.get_x() + bar.get_width()/2., height,
                f'${pnl:.1f}k\n({improvement:+.1f}%)',
                ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax1.set_ylabel('Total P&L ($1000s)', fontsize=11)
    ax1.set_title('Total P&L Comparison', fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3, axis='y')
    ax1.set_ylim(0, max(pnls) * 1.2)

    # ========== Plot 2: Win Rate ==========
    ax2 = axes[0, 1]

    win_rates = [results['current']['new_win_rate']*100,
                 results['smart']['new_win_rate']*100,
                 results['all']['new_win_rate']*100]

    bars = ax2.bar(strategies, win_rates, color=colors, alpha=0.7, edgecolor='black', linewidth=2)

    for bar, wr in zip(bars, win_rates):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{wr:.1f}%',
                ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax2.set_ylabel('Win Rate (%)', fontsize=11)
    ax2.set_title('Win Rate Comparison', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3, axis='y')
    ax2.set_ylim(0, 100)
    ax2.axhline(y=50, color='gray', linestyle='--', alpha=0.5)

    # ========== Plot 3: Avg P&L per Trade ==========
    ax3 = axes[1, 0]

    avg_pnls = [results['current']['new_pnl']/1073,
                results['smart']['new_pnl']/1073,
                results['all']['new_pnl']/1073]

    bars = ax3.bar(strategies, avg_pnls, color=colors, alpha=0.7, edgecolor='black', linewidth=2)

    for bar, avg in zip(bars, avg_pnls):
        height = bar.get_height()
        ax3.text(bar.get_x() + bar.get_width()/2., height,
                f'${avg:.2f}',
                ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax3.set_ylabel('Avg P&L per Trade ($)', fontsize=11)
    ax3.set_title('Average Profit per Trade', fontsize=12, fontweight='bold')
    ax3.grid(True, alpha=0.3, axis='y')
    ax3.set_ylim(0, max(avg_pnls) * 1.2)

    # ========== Plot 4: Trades Held ==========
    ax4 = axes[1, 1]

    held = [0,
            results['smart']['hold_count'],
            results['all']['hold_count']]

    bars = ax4.bar(strategies, held, color=colors, alpha=0.7, edgecolor='black', linewidth=2)

    for bar, h, strat in zip(bars, held, ['current', 'smart', 'all']):
        height = bar.get_height()
        pct = (h / 1073) * 100 if h > 0 else 0
        ax4.text(bar.get_x() + bar.get_width()/2., height,
                f'{h}\n({pct:.1f}%)',
                ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax4.set_ylabel('Trades Held to Expiration', fontsize=11)
    ax4.set_title('Number of Positions Held', fontsize=12, fontweight='bold')
    ax4.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\n✅ Visualization saved: {output_file}")

if __name__ == "__main__":
    # Load backtest data
    print("Loading backtest data...")
    df = pd.read_csv('/root/gamma/data/backtest_results.csv')

    # Compare strategies
    results = compare_strategies(df)

    # Visualize
    visualize_comparison(results)

    print("\n" + "="*70)
    print("HOLD-TO-EXPIRATION BACKTEST COMPLETE")
    print("="*70)
