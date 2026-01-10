#!/usr/bin/env python3
"""
Visualize Monte Carlo equity curves for gamma scalper with auto-scaling.

Shows distribution of outcomes across simulations.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend

# Import from backtest
import sys
sys.path.insert(0, '/root/gamma')
from backtest import (
    STARTING_CAPITAL, MAX_CONTRACTS, STOP_LOSS_PER_CONTRACT,
    calculate_position_size_kelly
)

def run_monte_carlo_with_curves(df, simulations=100, periods=252):
    """
    Run Monte Carlo and return equity curves for visualization.

    Args:
        df: Backtest results DataFrame with pnl_per_contract column
        simulations: Number of simulations to run
        periods: Trading days to simulate

    Returns:
        dict with equity_curves, final_balances, statistics
    """
    print(f"\nRunning {simulations} Monte Carlo simulations for visualization...")

    # Get trade P/L distribution (per-contract)
    trade_pnls = df['pnl_per_contract'].values if 'pnl_per_contract' in df.columns else df['pnl_dollars'].values
    trades_per_day = len(df) / df['date'].nunique()

    equity_curves = []
    final_balances = []
    max_drawdowns = []

    for sim_idx in range(simulations):
        if (sim_idx + 1) % 20 == 0:
            print(f"  Simulation {sim_idx + 1}/{simulations}...")

        # Sample trades for N trading days
        n_trades = int(trades_per_day * periods)
        sampled_pnls = np.random.choice(trade_pnls, size=n_trades, replace=True)

        # Simulate with dynamic position sizing
        account = STARTING_CAPITAL
        equity_curve = [account]
        rolling_wins = []
        rolling_losses = []
        position_sizes = []

        for trade_pnl in sampled_pnls:
            # Calculate position size using Half-Kelly
            if len(rolling_wins) >= 10 and len(rolling_losses) >= 5:
                win_rate = len(rolling_wins) / (len(rolling_wins) + len(rolling_losses))
                avg_win = np.mean(rolling_wins[-50:])
                avg_loss = np.mean(rolling_losses[-50:])
            else:
                # Bootstrap with baseline stats
                win_rate = 0.588
                avg_win = 223
                avg_loss = 103

            position_size = calculate_position_size_kelly(account, win_rate, avg_win, avg_loss)

            if position_size == 0:
                # Account dropped below 50% - stop trading
                break

            position_sizes.append(position_size)

            # Scale P&L by position size
            scaled_pnl = trade_pnl * position_size

            # Update rolling stats
            if trade_pnl > 0:
                rolling_wins.append(trade_pnl)
            else:
                rolling_losses.append(abs(trade_pnl))

            # Update account
            account += scaled_pnl
            equity_curve.append(account)

        # Calculate max drawdown
        equity_arr = np.array(equity_curve)
        peak = np.maximum.accumulate(equity_arr)
        drawdown = equity_arr - peak

        equity_curves.append(equity_curve)
        final_balances.append(account)
        max_drawdowns.append(drawdown.min())

    return {
        'equity_curves': equity_curves,
        'final_balances': np.array(final_balances),
        'max_drawdowns': np.array(max_drawdowns),
        'trades_per_curve': [len(curve) - 1 for curve in equity_curves]
    }

def plot_equity_curves(results, output_file='/root/gamma/monte_carlo_curves.png'):
    """Create comprehensive visualization of Monte Carlo results."""

    equity_curves = results['equity_curves']
    final_balances = results['final_balances']
    max_drawdowns = results['max_drawdowns']

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle('Monte Carlo Simulation: Half-Kelly Auto-Scaling\n$25k Starting Capital, 252 Trading Days',
                 fontsize=16, fontweight='bold')

    # ========== Plot 1: Sample Equity Curves ==========
    ax1 = axes[0, 0]

    # Plot 50 random equity curves (semi-transparent)
    sample_indices = np.random.choice(len(equity_curves), size=min(50, len(equity_curves)), replace=False)
    for idx in sample_indices:
        curve = equity_curves[idx]
        ax1.plot(curve, alpha=0.15, color='blue', linewidth=0.8)

    # Plot median curve (bold)
    median_idx = np.argsort(final_balances)[len(final_balances) // 2]
    median_curve = equity_curves[median_idx]
    ax1.plot(median_curve, color='red', linewidth=2.5, label=f'Median (${final_balances[median_idx]:,.0f})', zorder=10)

    # Plot 5th and 95th percentile curves
    p5_idx = np.argsort(final_balances)[int(len(final_balances) * 0.05)]
    p95_idx = np.argsort(final_balances)[int(len(final_balances) * 0.95)]
    ax1.plot(equity_curves[p5_idx], color='orange', linewidth=2, label=f'5th % (${final_balances[p5_idx]:,.0f})', linestyle='--', zorder=9)
    ax1.plot(equity_curves[p95_idx], color='green', linewidth=2, label=f'95th % (${final_balances[p95_idx]:,.0f})', linestyle='--', zorder=9)

    ax1.axhline(y=STARTING_CAPITAL, color='black', linestyle=':', linewidth=1, label='Starting Capital')
    ax1.set_xlabel('Trade Number', fontsize=11)
    ax1.set_ylabel('Account Balance ($)', fontsize=11)
    ax1.set_title('Sample Equity Curves (50 random + key percentiles)', fontsize=12, fontweight='bold')
    ax1.legend(loc='upper left', fontsize=9)
    ax1.grid(True, alpha=0.3)
    ax1.set_yscale('log')  # Log scale to see growth better

    # Format y-axis as currency
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))

    # ========== Plot 2: Final Balance Distribution ==========
    ax2 = axes[0, 1]

    n, bins, patches = ax2.hist(final_balances / 1000, bins=50, alpha=0.7, color='steelblue', edgecolor='black')

    # Add percentile lines
    percentiles = [5, 25, 50, 75, 95]
    colors = ['red', 'orange', 'green', 'orange', 'red']
    for p, color in zip(percentiles, colors):
        val = np.percentile(final_balances, p) / 1000
        ax2.axvline(val, color=color, linestyle='--', linewidth=2, label=f'{p}th %: ${val:.0f}k')

    ax2.set_xlabel('Final Balance ($1000s)', fontsize=11)
    ax2.set_ylabel('Frequency', fontsize=11)
    ax2.set_title('Final Balance Distribution', fontsize=12, fontweight='bold')
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)

    # Add statistics text
    stats_text = f"Mean: ${final_balances.mean()/1000:.0f}k\nStd: ${final_balances.std()/1000:.0f}k\nP(>$1M): {(final_balances > 1e6).mean()*100:.1f}%"
    ax2.text(0.98, 0.97, stats_text, transform=ax2.transAxes, fontsize=10,
             verticalalignment='top', horizontalalignment='right',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    # ========== Plot 3: Max Drawdown Distribution ==========
    ax3 = axes[1, 0]

    ax3.hist(max_drawdowns / 1000, bins=40, alpha=0.7, color='coral', edgecolor='black')

    # Add percentile lines
    for p in [5, 50, 95]:
        val = np.percentile(max_drawdowns, p) / 1000
        ax3.axvline(val, color='darkred', linestyle='--', linewidth=2, label=f'{p}th %: ${val:.1f}k')

    ax3.set_xlabel('Max Drawdown ($1000s)', fontsize=11)
    ax3.set_ylabel('Frequency', fontsize=11)
    ax3.set_title('Max Drawdown Distribution', fontsize=12, fontweight='bold')
    ax3.legend(fontsize=9)
    ax3.grid(True, alpha=0.3)

    # Add statistics text
    dd_text = f"Mean: ${max_drawdowns.mean()/1000:.1f}k\nWorst: ${max_drawdowns.min()/1000:.1f}k\nMedian: ${np.median(max_drawdowns)/1000:.1f}k"
    ax3.text(0.02, 0.97, dd_text, transform=ax3.transAxes, fontsize=10,
             verticalalignment='top', horizontalalignment='left',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    # ========== Plot 4: Return vs Drawdown Scatter ==========
    ax4 = axes[1, 1]

    returns = (final_balances - STARTING_CAPITAL) / STARTING_CAPITAL * 100
    drawdown_pct = abs(max_drawdowns) / final_balances * 100

    scatter = ax4.scatter(drawdown_pct, returns, alpha=0.5, c=final_balances,
                         cmap='viridis', s=30, edgecolors='black', linewidth=0.5)

    ax4.set_xlabel('Max Drawdown (% of Final Balance)', fontsize=11)
    ax4.set_ylabel('Total Return (%)', fontsize=11)
    ax4.set_title('Risk vs Return Profile', fontsize=12, fontweight='bold')
    ax4.grid(True, alpha=0.3)

    # Add colorbar
    cbar = plt.colorbar(scatter, ax=ax4)
    cbar.set_label('Final Balance ($)', fontsize=10)

    # Add reference lines
    ax4.axhline(y=returns.mean(), color='red', linestyle='--', linewidth=1, alpha=0.7, label=f'Mean Return: {returns.mean():.0f}%')
    ax4.axvline(x=drawdown_pct.mean(), color='blue', linestyle='--', linewidth=1, alpha=0.7, label=f'Mean DD: {drawdown_pct.mean():.1f}%')
    ax4.legend(fontsize=9)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\n✅ Visualization saved: {output_file}")

    return output_file

if __name__ == "__main__":
    # Load backtest results
    print("Loading backtest data...")
    df = pd.read_csv('/root/gamma/data/backtest_results.csv')

    print(f"Loaded {len(df)} trades from backtest")
    print(f"Average P&L per contract: ${df['pnl_per_contract'].mean():.2f}")
    print(f"Win rate: {(df['pnl_per_contract'] > 0).mean() * 100:.1f}%")

    # Run Monte Carlo with smaller sample for visualization
    results = run_monte_carlo_with_curves(df, simulations=200, periods=252)

    # Create visualization
    output_file = plot_equity_curves(results)

    print(f"\n📊 Monte Carlo Visualization Complete")
    print(f"   Simulations: {len(results['equity_curves'])}")
    print(f"   Median final balance: ${np.median(results['final_balances']):,.0f}")
    print(f"   5th percentile: ${np.percentile(results['final_balances'], 5):,.0f}")
    print(f"   95th percentile: ${np.percentile(results['final_balances'], 95):,.0f}")
