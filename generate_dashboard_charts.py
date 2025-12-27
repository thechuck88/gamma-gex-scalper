#!/usr/bin/env python3
"""
Generate comprehensive dashboard charts for Gamma GEX Scalper
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
import os

# Set style
sns.set_style("whitegrid")
plt.rcParams['figure.dpi'] = 300
plt.rcParams['savefig.dpi'] = 300
plt.rcParams['font.size'] = 10

# Paths
DATA_FILE = '/root/gamma/data/backtest_results.csv'
OUTPUT_DIR = '/var/www/mnqprimo/downloads/dashboard/gamma/report_2025-12-27/'

# Create output directory
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Load data
print("Loading backtest data...")
df = pd.read_csv(DATA_FILE)
df['date'] = pd.to_datetime(df['date'])

# Calculate metrics
total_trades = len(df)
total_pnl = df['pnl_dollars'].sum()
win_rate = (df['pnl_dollars'] > 0).sum() / total_trades * 100
avg_win = df[df['pnl_dollars'] > 0]['pnl_dollars'].mean()
avg_loss = df[df['pnl_dollars'] < 0]['pnl_dollars'].mean()
max_drawdown = df['drawdown'].min()
profit_factor = df[df['pnl_dollars'] > 0]['pnl_dollars'].sum() / abs(df[df['pnl_dollars'] < 0]['pnl_dollars'].sum())

# Strategy breakdown
strategy_counts = df['strategy'].value_counts()
strategy_pnl = df.groupby('strategy')['pnl_dollars'].sum()

print(f"\nKey Metrics:")
print(f"Total Trades: {total_trades}")
print(f"Total P&L: ${total_pnl:,.2f}")
print(f"Win Rate: {win_rate:.1f}%")
print(f"Profit Factor: {profit_factor:.2f}")
print(f"Max Drawdown: ${max_drawdown:,.2f}")

# ========================================
# Chart 1: Equity Curve
# ========================================
print("\nGenerating Chart 1: Equity Curve...")
fig, ax = plt.subplots(figsize=(14, 7))
ax.plot(df['date'], df['cumulative_pnl'], color='#8b5cf6', linewidth=2.5, label='Cumulative P&L')
ax.fill_between(df['date'], 0, df['cumulative_pnl'], alpha=0.3, color='#8b5cf6')
ax.axhline(y=0, color='gray', linestyle='--', linewidth=1, alpha=0.5)
ax.set_title('Equity Curve - Cumulative P&L Over Time', fontsize=16, fontweight='bold', pad=20)
ax.set_xlabel('Date', fontsize=12, fontweight='bold')
ax.set_ylabel('Cumulative P&L ($)', fontsize=12, fontweight='bold')
ax.grid(True, alpha=0.3)
ax.legend(fontsize=11, loc='upper left')
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig(f'{OUTPUT_DIR}/1_equity_curve.png', bbox_inches='tight')
plt.close()

# ========================================
# Chart 2: Drawdown Analysis
# ========================================
print("Generating Chart 2: Drawdown Analysis...")
fig, ax = plt.subplots(figsize=(14, 7))
ax.fill_between(df['date'], 0, df['drawdown'], color='#ef4444', alpha=0.4, label='Drawdown')
ax.plot(df['date'], df['drawdown'], color='#dc2626', linewidth=2)
ax.set_title('Drawdown Analysis', fontsize=16, fontweight='bold', pad=20)
ax.set_xlabel('Date', fontsize=12, fontweight='bold')
ax.set_ylabel('Drawdown ($)', fontsize=12, fontweight='bold')
ax.grid(True, alpha=0.3)
ax.legend(fontsize=11)
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig(f'{OUTPUT_DIR}/2_drawdown_chart.png', bbox_inches='tight')
plt.close()

# ========================================
# Chart 3: P&L Distribution
# ========================================
print("Generating Chart 3: P&L Distribution...")
fig, ax = plt.subplots(figsize=(12, 7))
bins = np.linspace(df['pnl_dollars'].min(), df['pnl_dollars'].max(), 40)
colors = ['#ef4444' if x < 0 else '#10b981' for x in df['pnl_dollars']]
ax.hist(df['pnl_dollars'], bins=bins, color='#8b5cf6', alpha=0.7, edgecolor='black', linewidth=1.5)
ax.axvline(x=0, color='gray', linestyle='--', linewidth=2, alpha=0.7)
ax.axvline(x=df['pnl_dollars'].mean(), color='orange', linestyle='--', linewidth=2,
           label=f'Mean: ${df["pnl_dollars"].mean():.2f}')
ax.set_title('P&L Distribution Per Trade', fontsize=16, fontweight='bold', pad=20)
ax.set_xlabel('P&L ($)', fontsize=12, fontweight='bold')
ax.set_ylabel('Frequency', fontsize=12, fontweight='bold')
ax.grid(True, alpha=0.3, axis='y')
ax.legend(fontsize=11)
plt.tight_layout()
plt.savefig(f'{OUTPUT_DIR}/3_pnl_distribution.png', bbox_inches='tight')
plt.close()

# ========================================
# Chart 4: Win/Loss Analysis
# ========================================
print("Generating Chart 4: Win/Loss Analysis...")
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

# Win rate pie chart
wins = (df['pnl_dollars'] > 0).sum()
losses = (df['pnl_dollars'] < 0).sum()
labels = [f'Wins\n{wins} ({win_rate:.1f}%)', f'Losses\n{losses} ({100-win_rate:.1f}%)']
colors_pie = ['#10b981', '#ef4444']
explode = (0.05, 0)
ax1.pie([wins, losses], labels=labels, colors=colors_pie, autopct='%1.1f%%',
        startangle=90, explode=explode, textprops={'fontsize': 12, 'fontweight': 'bold'},
        wedgeprops={'edgecolor': 'white', 'linewidth': 3})
ax1.set_title('Win Rate', fontsize=14, fontweight='bold', pad=15)

# Avg win vs avg loss
x = np.arange(2)
bars = ax2.bar(x, [avg_win, abs(avg_loss)], color=['#10b981', '#ef4444'],
               alpha=0.8, edgecolor='black', linewidth=2)
ax2.set_xticks(x)
ax2.set_xticklabels(['Avg Win', 'Avg Loss'], fontsize=12, fontweight='bold')
ax2.set_ylabel('Amount ($)', fontsize=12, fontweight='bold')
ax2.set_title('Average Win vs Loss', fontsize=14, fontweight='bold', pad=15)
ax2.grid(True, alpha=0.3, axis='y')
for i, bar in enumerate(bars):
    height = bar.get_height()
    ax2.text(bar.get_x() + bar.get_width()/2., height,
            f'${height:.2f}', ha='center', va='bottom', fontsize=11, fontweight='bold')

plt.tight_layout()
plt.savefig(f'{OUTPUT_DIR}/4_win_loss_analysis.png', bbox_inches='tight')
plt.close()

# ========================================
# Chart 5: Strategy Performance
# ========================================
print("Generating Chart 5: Strategy Performance...")
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

# Strategy P&L
strategies = strategy_pnl.index
x_pos = np.arange(len(strategies))
colors_strat = ['#10b981' if val > 0 else '#ef4444' for val in strategy_pnl.values]
bars = ax1.bar(x_pos, strategy_pnl.values, color=colors_strat, alpha=0.8,
               edgecolor='black', linewidth=2)
ax1.set_xticks(x_pos)
ax1.set_xticklabels(strategies, fontsize=11, fontweight='bold')
ax1.set_ylabel('Total P&L ($)', fontsize=12, fontweight='bold')
ax1.set_title('P&L by Strategy Type', fontsize=14, fontweight='bold', pad=15)
ax1.grid(True, alpha=0.3, axis='y')
ax1.axhline(y=0, color='black', linestyle='-', linewidth=1)
for bar in bars:
    height = bar.get_height()
    ax1.text(bar.get_x() + bar.get_width()/2., height,
            f'${height:.0f}', ha='center', va='bottom' if height > 0 else 'top',
            fontsize=10, fontweight='bold')

# Strategy trade count
bars2 = ax2.bar(x_pos, strategy_counts.values, color='#8b5cf6', alpha=0.8,
                edgecolor='black', linewidth=2)
ax2.set_xticks(x_pos)
ax2.set_xticklabels(strategies, fontsize=11, fontweight='bold')
ax2.set_ylabel('Number of Trades', fontsize=12, fontweight='bold')
ax2.set_title('Trade Count by Strategy', fontsize=14, fontweight='bold', pad=15)
ax2.grid(True, alpha=0.3, axis='y')
for bar in bars2:
    height = bar.get_height()
    ax2.text(bar.get_x() + bar.get_width()/2., height,
            f'{int(height)}', ha='center', va='bottom', fontsize=10, fontweight='bold')

plt.tight_layout()
plt.savefig(f'{OUTPUT_DIR}/5_strategy_performance.png', bbox_inches='tight')
plt.close()

# ========================================
# Chart 6: Monthly Returns
# ========================================
print("Generating Chart 6: Monthly Returns...")
df['month'] = df['date'].dt.to_period('M')
monthly = df.groupby('month').agg({
    'pnl_dollars': 'sum',
    'date': 'count'
}).rename(columns={'date': 'trades'})

fig, ax = plt.subplots(figsize=(12, 7))
colors_monthly = ['#10b981' if val > 0 else '#ef4444' for val in monthly['pnl_dollars'].values]
bars = ax.bar(range(len(monthly)), monthly['pnl_dollars'].values, color=colors_monthly,
              alpha=0.8, edgecolor='black', linewidth=2)
ax.set_xticks(range(len(monthly)))
ax.set_xticklabels([str(m) for m in monthly.index], rotation=45, fontsize=10)
ax.set_ylabel('Monthly P&L ($)', fontsize=12, fontweight='bold')
ax.set_title('Monthly P&L Performance', fontsize=16, fontweight='bold', pad=20)
ax.grid(True, alpha=0.3, axis='y')
ax.axhline(y=0, color='black', linestyle='-', linewidth=1)
for i, bar in enumerate(bars):
    height = bar.get_height()
    ax.text(bar.get_x() + bar.get_width()/2., height,
           f'${height:.0f}\n({monthly.iloc[i]["trades"]} trades)',
           ha='center', va='bottom' if height > 0 else 'top',
           fontsize=8, fontweight='bold')

plt.tight_layout()
plt.savefig(f'{OUTPUT_DIR}/6_monthly_returns.png', bbox_inches='tight')
plt.close()

# ========================================
# Chart 7: Exit Reason Analysis
# ========================================
print("Generating Chart 7: Exit Reason Analysis...")
exit_reasons = df['exit_reason'].value_counts()

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

# Exit reason counts
colors_exit = ['#10b981', '#f59e0b', '#ef4444'][:len(exit_reasons)]
bars = ax1.bar(range(len(exit_reasons)), exit_reasons.values, color=colors_exit,
               alpha=0.8, edgecolor='black', linewidth=2)
ax1.set_xticks(range(len(exit_reasons)))
ax1.set_xticklabels(exit_reasons.index, rotation=45, ha='right', fontsize=10)
ax1.set_ylabel('Number of Trades', fontsize=12, fontweight='bold')
ax1.set_title('Exit Reason Distribution', fontsize=14, fontweight='bold', pad=15)
ax1.grid(True, alpha=0.3, axis='y')
for bar in bars:
    height = bar.get_height()
    ax1.text(bar.get_x() + bar.get_width()/2., height,
            f'{int(height)}', ha='center', va='bottom', fontsize=10, fontweight='bold')

# Exit reason P&L
exit_pnl = df.groupby('exit_reason')['pnl_dollars'].sum()
colors_exit_pnl = ['#10b981' if val > 0 else '#ef4444' for val in exit_pnl.values]
bars2 = ax2.bar(range(len(exit_pnl)), exit_pnl.values, color=colors_exit_pnl,
                alpha=0.8, edgecolor='black', linewidth=2)
ax2.set_xticks(range(len(exit_pnl)))
ax2.set_xticklabels(exit_pnl.index, rotation=45, ha='right', fontsize=10)
ax2.set_ylabel('Total P&L ($)', fontsize=12, fontweight='bold')
ax2.set_title('P&L by Exit Reason', fontsize=14, fontweight='bold', pad=15)
ax2.grid(True, alpha=0.3, axis='y')
ax2.axhline(y=0, color='black', linestyle='-', linewidth=1)
for bar in bars2:
    height = bar.get_height()
    ax2.text(bar.get_x() + bar.get_width()/2., height,
            f'${height:.0f}', ha='center', va='bottom' if height > 0 else 'top',
            fontsize=9, fontweight='bold')

plt.tight_layout()
plt.savefig(f'{OUTPUT_DIR}/7_exit_reason_analysis.png', bbox_inches='tight')
plt.close()

print(f"\n✅ All charts generated successfully in {OUTPUT_DIR}")
print(f"\nGenerated files:")
for i in range(1, 8):
    print(f"  - {i}_*.png")
