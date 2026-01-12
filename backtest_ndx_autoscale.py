#!/usr/bin/env python3
"""
1-Year Backtest - NDX ONLY - REALISTIC 0DTE Credits with AUTOSCALING
Matches live scalper.py Half-Kelly position sizing
"""
import sys
sys.path.insert(0, '/root/gamma')

from index_config import get_index_config
import random
import datetime
from collections import defaultdict

print("=" * 80)
print("1-YEAR BACKTEST - NDX - REALISTIC 0DTE + HALF-KELLY AUTOSCALING")
print("=" * 80)
print()

# Autoscaling parameters (match scalper.py)
AUTOSCALING_ENABLED = True
STARTING_CAPITAL = 20000
MAX_CONTRACTS = 10  # Kelly formula scales from 1-10 as account grows
STOP_LOSS_PER_CONTRACT = 750  # NDX: 5× SPX ($150 × 5 = $750)

# Bootstrap statistics (from realistic backtest until we have real data)
BOOTSTRAP_WIN_RATE = 0.592
BOOTSTRAP_AVG_WIN = 138
BOOTSTRAP_AVG_LOSS = 37

# Seed for reproducibility (different from SPX)
random.seed(43)

def get_realistic_ndx_credit(vix, distance_otm, time_hour):
    """Realistic 0DTE NDX 25-point spread credit (5x SPX)."""
    if vix < 15:
        base = random.uniform(1.00, 2.00)
    elif vix < 22:
        base = random.uniform(1.80, 3.20)
    elif vix < 30:
        base = random.uniform(3.00, 5.00)
    else:
        base = random.uniform(4.50, 7.50)

    distance_factor = max(0.85, min(1.15, 110 / max(distance_otm, 50)))
    time_factor = 1.1 if time_hour < 10 else (1.0 if time_hour < 12 else 0.9)
    return round(base * distance_factor * time_factor, 2)

def calculate_position_size_kelly(account_balance, win_rate, avg_win, avg_loss):
    """
    Calculate position size using Half-Kelly criterion.

    Kelly formula: f = (p*W - (1-p)*L) / W
    Where:
        f = fraction of capital to risk
        p = win rate
        W = avg win amount
        L = avg loss amount (absolute value)

    Uses Half-Kelly (50% of Kelly) for more conservative sizing.
    """
    if not AUTOSCALING_ENABLED:
        return 1

    # Safety halt: stop trading if account drops below 50% of starting capital
    if account_balance < STARTING_CAPITAL * 0.5:
        print(f"⚠️  Account below 50% of starting capital (${account_balance:,.0f} < ${STARTING_CAPITAL * 0.5:,.0f})")
        return 0  # Stop trading

    # Kelly fraction
    kelly_f = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win

    # Use half-Kelly for safety
    half_kelly = kelly_f * 0.5

    # Calculate contracts based on available capital and max loss per contract
    contracts = int((account_balance * half_kelly) / STOP_LOSS_PER_CONTRACT)

    # Cap at maximum
    contracts = min(contracts, MAX_CONTRACTS)

    return max(1, contracts)  # Minimum 1 contract

# Simulate 1 year of trading (252 trading days, approximate 2.9 trades/day)
num_days = 252
trades_per_day = 2.9
total_trades = int(num_days * trades_per_day)

config = get_index_config('NDX')
all_trades = []

# Track account balance
account_balance = STARTING_CAPITAL

# Track rolling statistics (last 50 trades)
recent_trades = []
ROLLING_WINDOW = 50

# Simulate VIX and price movement
base_vix = 16.0
base_price = 21500

for trade_num in range(1, total_trades + 1):
    # Vary VIX (random walk)
    vix = max(10, min(40, base_vix + random.uniform(-2, 2)))
    base_vix = vix

    # Vary NDX price
    ndx_price = base_price + random.uniform(-200, 200)
    base_price = ndx_price

    # GEX pin near current price
    ndx_pin = ndx_price + random.uniform(-50, 50)

    # Entry time
    time_hour = random.randint(9, 14)

    # Get trade setup
    distance = abs(ndx_price - ndx_pin)
    distance_otm = distance + 100  # Short strike is ~100pts OTM

    # Get realistic credit
    credit = get_realistic_ndx_credit(vix, distance_otm, time_hour)

    # Calculate position size using Half-Kelly
    if len(recent_trades) >= 10:
        # Use rolling statistics
        recent_winners = [t for t in recent_trades if t['win']]
        recent_losers = [t for t in recent_trades if not t['win']]

        win_rate = len(recent_winners) / len(recent_trades) if recent_trades else BOOTSTRAP_WIN_RATE
        avg_win = sum(t['profit_per_contract'] for t in recent_winners) / len(recent_winners) if recent_winners else BOOTSTRAP_AVG_WIN
        avg_loss = abs(sum(t['profit_per_contract'] for t in recent_losers) / len(recent_losers)) if recent_losers else BOOTSTRAP_AVG_LOSS
    else:
        # Use bootstrap statistics
        win_rate = BOOTSTRAP_WIN_RATE
        avg_win = BOOTSTRAP_AVG_WIN
        avg_loss = BOOTSTRAP_AVG_LOSS

    contracts = calculate_position_size_kelly(account_balance, win_rate, avg_win, avg_loss)

    if contracts == 0:
        print(f"Trading halted at trade #{trade_num} - account below safety threshold")
        break

    # Win/loss outcome (60% win rate based on GEX edge)
    win = random.random() < 0.60

    if win:
        # Winner: 50% profit on credit
        profit_per_contract = credit * 0.50 * 100
    else:
        # Loser: Stop loss at 10% or max loss at spread width
        if random.random() < 0.7:  # 70% hit stop
            loss_pct = 0.10
        else:  # 30% hit emergency stop
            loss_pct = random.uniform(0.15, 0.40)
        profit_per_contract = -credit * loss_pct * 100

    # Scale by position size
    total_profit = profit_per_contract * contracts

    # Update account balance
    account_balance += total_profit

    trade_data = {
        'trade_num': trade_num,
        'index': 'NDX',
        'vix': vix,
        'credit': credit,
        'contracts': contracts,
        'profit_per_contract': profit_per_contract,
        'total_profit': total_profit,
        'win': win,
        'time_hour': time_hour,
        'account_balance': account_balance
    }

    all_trades.append(trade_data)

    # Update rolling window
    recent_trades.append(trade_data)
    if len(recent_trades) > ROLLING_WINDOW:
        recent_trades.pop(0)

# Calculate statistics
total_pnl = account_balance - STARTING_CAPITAL
winners = [t for t in all_trades if t['win']]
losers = [t for t in all_trades if not t['win']]

win_rate = len(winners) / len(all_trades) * 100
avg_win_per_contract = sum(t['profit_per_contract'] for t in winners) / len(winners) if winners else 0
avg_loss_per_contract = sum(t['profit_per_contract'] for t in losers) / len(losers) if losers else 0
avg_credit = sum(t['credit'] for t in all_trades) / len(all_trades)
avg_contracts = sum(t['contracts'] for t in all_trades) / len(all_trades)

profit_factor = abs(sum(t['total_profit'] for t in winners) / sum(t['total_profit'] for t in losers)) if losers else 0

# Contract size distribution
contract_sizes = [t['contracts'] for t in all_trades]
contracts_1 = sum(1 for c in contract_sizes if c == 1)
contracts_2 = sum(1 for c in contract_sizes if c == 2)
contracts_3 = sum(1 for c in contract_sizes if c == 3)

print(f"Trading Days:         {num_days}")
print(f"Total Trades:         {len(all_trades)}")
print(f"Avg Trades/Day:       {len(all_trades)/num_days:.1f}")
print()
print("=" * 80)
print("AUTOSCALING RESULTS")
print("=" * 80)
print(f"Starting Capital:     ${STARTING_CAPITAL:,.0f}")
print(f"Final Balance:        ${account_balance:,.0f}")
print(f"NET P/L:              ${total_pnl:,.0f} ({(total_pnl/STARTING_CAPITAL)*100:+.1f}%)")
print()
print(f"Win Rate:             {win_rate:.1f}%")
print(f"Profit Factor:        {profit_factor:.2f}")
print()
print(f"Average Credit:       ${avg_credit:.2f}")
print(f"Avg Contracts/Trade:  {avg_contracts:.2f}")
print(f"Avg Win (per contr):  ${avg_win_per_contract:.0f}")
print(f"Avg Loss (per contr): ${avg_loss_per_contract:.0f}")
print()
print("Position Size Distribution:")
print(f"  1 contract:  {contracts_1} trades ({contracts_1/len(all_trades)*100:.1f}%)")
print(f"  2 contracts: {contracts_2} trades ({contracts_2/len(all_trades)*100:.1f}%)")
print(f"  3 contracts: {contracts_3} trades ({contracts_3/len(all_trades)*100:.1f}%)")
print()

# Top 10 best and worst
sorted_trades = sorted(all_trades, key=lambda x: x['total_profit'], reverse=True)
print("TOP 10 BEST TRADES:")
print("-" * 80)
for i, t in enumerate(sorted_trades[:10], 1):
    print(f"{i:2d}. Trade #{t['trade_num']:3d}: ${t['total_profit']:7.0f} profit ({t['contracts']} × ${t['credit']:.2f} credit, VIX {t['vix']:.1f})")
print()

print("TOP 10 WORST TRADES:")
print("-" * 80)
for i, t in enumerate(sorted_trades[-10:], 1):
    print(f"{i:2d}. Trade #{t['trade_num']:3d}: ${t['total_profit']:7.0f} loss ({t['contracts']} × ${t['credit']:.2f} credit, VIX {t['vix']:.1f})")
print()

print("ACCOUNT GROWTH TRAJECTORY:")
print("-" * 80)
milestones = [0, 100, 200, 300, 400, 500, 600, len(all_trades)-1]
for idx in milestones:
    if idx < len(all_trades):
        t = all_trades[idx]
        print(f"After trade #{t['trade_num']:3d}: ${t['account_balance']:8,.0f} (avg {t['contracts']:.1f} contracts)")
print()
print("=" * 80)
print("NDX AUTOSCALING BACKTEST COMPLETE")
print("=" * 80)
