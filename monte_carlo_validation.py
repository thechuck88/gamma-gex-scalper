#!/usr/bin/env python3
"""
Monte Carlo Validation for GEX + OTM Strategy Backtest

Runs 10,000 simulations by randomly resampling trades from the backtest
to validate strategy robustness and generate distribution of outcomes.

This answers: "What's the range of possible outcomes if we traded this
strategy for 1 year with different trade sequences?"
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import json

# Simulation parameters
NUM_SIMULATIONS = 10000
STARTING_CAPITAL = 20000
MAX_CONTRACTS = 3

# Load backtest trade data
print("Loading backtest data...")
trades_df = pd.read_csv('/root/gamma/BACKTEST_1YEAR_SIMULATION.csv')

# Extract per-contract P/L for resampling
trades_pnl_per_contract = trades_df['pl_per_contract'].values
total_backtest_trades = len(trades_pnl_per_contract)

print(f"Loaded {total_backtest_trades} trades from backtest")
print(f"Win rate: {(trades_pnl_per_contract > 0).mean()*100:.1f}%")
print(f"Avg winner: ${trades_pnl_per_contract[trades_pnl_per_contract > 0].mean():.2f}")
print(f"Avg loser: ${trades_pnl_per_contract[trades_pnl_per_contract <= 0].mean():.2f}")
print()

# Half-Kelly position sizing function
def calculate_position_size(balance, trade_history, max_risk_per_contract=800):
    """Calculate position size using Half-Kelly formula."""
    # Safety halt
    if balance < STARTING_CAPITAL * 0.5:
        return 0

    # Bootstrap phase
    if len(trade_history) < 10:
        return 1

    # Use last 50 trades
    recent_trades = trade_history[-50:]
    winners = [t for t in recent_trades if t > 0]
    losers = [t for t in recent_trades if t <= 0]

    if not winners or not losers:
        return 1

    # Calculate Kelly
    win_rate = len(winners) / len(recent_trades)
    loss_rate = len(losers) / len(recent_trades)
    avg_win = np.mean(winners)
    avg_loss = abs(np.mean(losers))

    kelly_pct = (win_rate * avg_win - loss_rate * avg_loss) / avg_win
    half_kelly_pct = kelly_pct / 2

    if half_kelly_pct > 0:
        contracts = int((balance * half_kelly_pct) / max_risk_per_contract)
        contracts = max(1, min(contracts, MAX_CONTRACTS))
    else:
        contracts = 1

    return contracts


def run_simulation(sim_num):
    """Run single Monte Carlo simulation by resampling trades."""
    balance = STARTING_CAPITAL
    trade_history = []
    peak_balance = STARTING_CAPITAL
    max_drawdown = 0

    # Randomly resample trades (with replacement)
    num_trades = total_backtest_trades
    resampled_trades = np.random.choice(trades_pnl_per_contract, size=num_trades, replace=True)

    # Track equity curve
    equity_curve = [balance]

    for pl_per_contract in resampled_trades:
        # Determine max risk based on trade type
        # GEX: ~60% of trades, $250 max risk
        # OTM: ~40% of trades, $900 max risk
        if np.random.random() < 0.60:
            max_risk = 250  # GEX
        else:
            max_risk = 900  # OTM

        # Calculate position size
        position_size = calculate_position_size(balance, trade_history, max_risk)

        # Safety halt check
        if position_size == 0:
            break

        # Scale P/L by position size
        total_pl = pl_per_contract * position_size

        # Update balance
        balance += total_pl
        trade_history.append(pl_per_contract)

        # Track drawdown
        if balance > peak_balance:
            peak_balance = balance

        current_drawdown = peak_balance - balance
        if current_drawdown > max_drawdown:
            max_drawdown = current_drawdown

        equity_curve.append(balance)

    # Calculate metrics
    total_trades = len(trade_history)
    winners = sum(1 for t in trade_history if t > 0)
    win_rate = (winners / total_trades * 100) if total_trades > 0 else 0
    total_return = ((balance - STARTING_CAPITAL) / STARTING_CAPITAL * 100)
    max_dd_pct = (max_drawdown / peak_balance * 100) if peak_balance > 0 else 0

    return {
        'sim_num': sim_num,
        'ending_balance': balance,
        'total_return': total_return,
        'total_trades': total_trades,
        'win_rate': win_rate,
        'max_drawdown_dollars': max_drawdown,
        'max_drawdown_pct': max_dd_pct,
        'equity_curve': equity_curve
    }


print(f"Running {NUM_SIMULATIONS:,} Monte Carlo simulations...")
print("This may take 1-2 minutes...")
print()

# Run simulations
results = []
for i in range(NUM_SIMULATIONS):
    if (i + 1) % 1000 == 0:
        print(f"  Completed {i + 1:,} / {NUM_SIMULATIONS:,} simulations...")

    result = run_simulation(i)
    results.append(result)

results_df = pd.DataFrame(results)

print()
print("=" * 100)
print("MONTE CARLO VALIDATION RESULTS (10,000 SIMULATIONS)")
print("=" * 100)
print()

# Summary statistics
print("ENDING BALANCE DISTRIBUTION:")
print("-" * 60)
percentiles = [1, 5, 10, 25, 50, 75, 90, 95, 99]
for p in percentiles:
    value = np.percentile(results_df['ending_balance'], p)
    pnl = value - STARTING_CAPITAL
    ret = (pnl / STARTING_CAPITAL * 100)
    print(f"  {p:2d}th percentile: ${value:>9,.0f} (P/L: ${pnl:>+8,.0f}, Return: {ret:>+6.1f}%)")

print()
print(f"  Mean:           ${results_df['ending_balance'].mean():>9,.0f}")
print(f"  Std Dev:        ${results_df['ending_balance'].std():>9,.0f}")
print(f"  Min:            ${results_df['ending_balance'].min():>9,.0f}")
print(f"  Max:            ${results_df['ending_balance'].max():>9,.0f}")
print()

# Probability analysis
print("PROBABILITY ANALYSIS:")
print("-" * 60)
prob_profit = (results_df['ending_balance'] > STARTING_CAPITAL).mean() * 100
prob_double = (results_df['ending_balance'] > STARTING_CAPITAL * 2).mean() * 100
prob_triple = (results_df['ending_balance'] > STARTING_CAPITAL * 3).mean() * 100
prob_10x = (results_df['ending_balance'] > STARTING_CAPITAL * 10).mean() * 100
prob_loss = (results_df['ending_balance'] < STARTING_CAPITAL).mean() * 100
prob_ruin = (results_df['ending_balance'] < STARTING_CAPITAL * 0.5).mean() * 100

print(f"  Probability of profit (>$20k):        {prob_profit:>6.2f}%")
print(f"  Probability of 2x return (>$40k):     {prob_double:>6.2f}%")
print(f"  Probability of 3x return (>$60k):     {prob_triple:>6.2f}%")
print(f"  Probability of 10x return (>$200k):   {prob_10x:>6.2f}%")
print(f"  Probability of loss (<$20k):          {prob_loss:>6.2f}%")
print(f"  Probability of ruin (<$10k):          {prob_ruin:>6.2f}%")
print()

# Return distribution
print("RETURN DISTRIBUTION:")
print("-" * 60)
for p in percentiles:
    value = np.percentile(results_df['total_return'], p)
    print(f"  {p:2d}th percentile: {value:>+7.1f}%")
print()

# Drawdown analysis
print("DRAWDOWN ANALYSIS:")
print("-" * 60)
print(f"  Mean max drawdown:     ${results_df['max_drawdown_dollars'].mean():>8,.0f} ({results_df['max_drawdown_pct'].mean():>5.1f}%)")
print(f"  Median max drawdown:   ${results_df['max_drawdown_dollars'].median():>8,.0f} ({results_df['max_drawdown_pct'].median():>5.1f}%)")
print(f"  95th percentile DD:    ${np.percentile(results_df['max_drawdown_dollars'], 95):>8,.0f} ({np.percentile(results_df['max_drawdown_pct'], 95):>5.1f}%)")
print(f"  Worst drawdown:        ${results_df['max_drawdown_dollars'].max():>8,.0f} ({results_df['max_drawdown_pct'].max():>5.1f}%)")
print()

# Win rate distribution
print("WIN RATE DISTRIBUTION:")
print("-" * 60)
for p in percentiles:
    value = np.percentile(results_df['win_rate'], p)
    print(f"  {p:2d}th percentile: {value:>5.1f}%")
print()

# Risk of ruin analysis
print("RISK ANALYSIS:")
print("-" * 60)
worst_case = results_df['ending_balance'].min()
worst_dd = results_df['max_drawdown_dollars'].max()
print(f"  Worst case scenario (1 in 10,000):    ${worst_case:,.0f}")
print(f"  Worst drawdown (1 in 10,000):         ${worst_dd:,.0f}")
print(f"  95% confidence interval:              ${np.percentile(results_df['ending_balance'], 2.5):,.0f} - ${np.percentile(results_df['ending_balance'], 97.5):,.0f}")
print()

# Compare to actual backtest
print("COMPARISON TO ACTUAL BACKTEST:")
print("-" * 60)
backtest_balance = trades_df.iloc[-1]['balance']
backtest_return = (backtest_balance - STARTING_CAPITAL) / STARTING_CAPITAL * 100
percentile_rank = (results_df['ending_balance'] < backtest_balance).mean() * 100

print(f"  Backtest ending balance:   ${backtest_balance:,.0f}")
print(f"  Backtest return:           {backtest_return:+.1f}%")
print(f"  Percentile rank:           {percentile_rank:.1f}th (better than {percentile_rank:.1f}% of simulations)")
print()

# Save results
output_file = '/root/gamma/MONTE_CARLO_RESULTS.json'
summary = {
    'num_simulations': NUM_SIMULATIONS,
    'starting_capital': STARTING_CAPITAL,
    'percentiles': {
        '1': float(np.percentile(results_df['ending_balance'], 1)),
        '5': float(np.percentile(results_df['ending_balance'], 5)),
        '10': float(np.percentile(results_df['ending_balance'], 10)),
        '25': float(np.percentile(results_df['ending_balance'], 25)),
        '50': float(np.percentile(results_df['ending_balance'], 50)),
        '75': float(np.percentile(results_df['ending_balance'], 75)),
        '90': float(np.percentile(results_df['ending_balance'], 90)),
        '95': float(np.percentile(results_df['ending_balance'], 95)),
        '99': float(np.percentile(results_df['ending_balance'], 99))
    },
    'probabilities': {
        'profit': float(prob_profit),
        'double': float(prob_double),
        'triple': float(prob_triple),
        'loss': float(prob_loss),
        'ruin': float(prob_ruin)
    },
    'drawdown': {
        'mean': float(results_df['max_drawdown_dollars'].mean()),
        'median': float(results_df['max_drawdown_dollars'].median()),
        'p95': float(np.percentile(results_df['max_drawdown_dollars'], 95)),
        'worst': float(results_df['max_drawdown_dollars'].max())
    },
    'backtest_comparison': {
        'backtest_balance': float(backtest_balance),
        'percentile_rank': float(percentile_rank)
    }
}

with open(output_file, 'w') as f:
    json.dump(summary, f, indent=2)

print(f"Results saved to: {output_file}")
print()

# Generate histogram
print("Generating distribution chart...")
plt.figure(figsize=(12, 8))

# Plot 1: Ending balance distribution
plt.subplot(2, 2, 1)
plt.hist(results_df['ending_balance'], bins=100, alpha=0.7, edgecolor='black')
plt.axvline(backtest_balance, color='red', linestyle='--', linewidth=2, label=f'Actual Backtest: ${backtest_balance:,.0f}')
plt.axvline(STARTING_CAPITAL, color='gray', linestyle='-', linewidth=1, label=f'Starting: ${STARTING_CAPITAL:,.0f}')
plt.xlabel('Ending Balance ($)')
plt.ylabel('Frequency')
plt.title('Ending Balance Distribution (10,000 Simulations)')
plt.legend()
plt.grid(alpha=0.3)

# Plot 2: Return distribution
plt.subplot(2, 2, 2)
plt.hist(results_df['total_return'], bins=100, alpha=0.7, edgecolor='black', color='green')
plt.axvline(backtest_return, color='red', linestyle='--', linewidth=2, label=f'Actual: {backtest_return:+.1f}%')
plt.axvline(0, color='gray', linestyle='-', linewidth=1)
plt.xlabel('Total Return (%)')
plt.ylabel('Frequency')
plt.title('Return Distribution')
plt.legend()
plt.grid(alpha=0.3)

# Plot 3: Drawdown distribution
plt.subplot(2, 2, 3)
plt.hist(results_df['max_drawdown_dollars'], bins=100, alpha=0.7, edgecolor='black', color='orange')
plt.xlabel('Max Drawdown ($)')
plt.ylabel('Frequency')
plt.title('Maximum Drawdown Distribution')
plt.grid(alpha=0.3)

# Plot 4: Win rate distribution
plt.subplot(2, 2, 4)
plt.hist(results_df['win_rate'], bins=100, alpha=0.7, edgecolor='black', color='purple')
backtest_wr = (trades_df['wl'] == 'WIN').mean() * 100
plt.axvline(backtest_wr, color='red', linestyle='--', linewidth=2, label=f'Actual: {backtest_wr:.1f}%')
plt.xlabel('Win Rate (%)')
plt.ylabel('Frequency')
plt.title('Win Rate Distribution')
plt.legend()
plt.grid(alpha=0.3)

plt.tight_layout()
chart_file = '/root/gamma/MONTE_CARLO_DISTRIBUTION.png'
plt.savefig(chart_file, dpi=150)
print(f"Chart saved to: {chart_file}")
print()

print("=" * 100)
print("MONTE CARLO VALIDATION COMPLETE")
print("=" * 100)
