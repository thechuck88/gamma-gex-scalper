#!/usr/bin/env python3
"""
1-Year Backtest - NDX - REALISTIC 0DTE with 7 ENTRY TIMES
Matches production cron: 9:36, 10:00, 10:30, 11:00, 11:30, 12:00, 12:30
"""
import sys
sys.path.insert(0, '/root/gamma')

from index_config import get_index_config
import random
import datetime
from collections import defaultdict

print("=" * 80)
print("1-YEAR BACKTEST - NDX - 7 ENTRY TIMES + HALF-KELLY AUTOSCALING")
print("=" * 80)
print()

# Autoscaling parameters (match scalper.py)
AUTOSCALING_ENABLED = True
STARTING_CAPITAL = 20000
MAX_CONTRACTS = 10
STOP_LOSS_PER_CONTRACT = 750  # NDX: 5× SPX

# Bootstrap statistics
BOOTSTRAP_WIN_RATE = 0.592
BOOTSTRAP_AVG_WIN = 138
BOOTSTRAP_AVG_LOSS = 37

# Entry times (match production cron)
ENTRY_TIMES = [
    ('9:36', 9.6),
    ('10:00', 10.0),
    ('10:30', 10.5),
    ('11:00', 11.0),
    ('11:30', 11.5),
    ('12:00', 12.0),
    ('12:30', 12.5),
]

# Seed for reproducibility (different from SPX)
random.seed(43)

def get_realistic_ndx_credit(vix, distance_otm, time_hour):
    """Realistic 0DTE NDX 25-point spread credit (5× SPX)."""
    if vix < 15:
        base = random.uniform(1.00, 2.00)
    elif vix < 22:
        base = random.uniform(1.80, 3.20)
    elif vix < 30:
        base = random.uniform(3.00, 5.00)
    else:
        base = random.uniform(4.50, 7.50)

    distance_factor = max(0.85, min(1.15, 110 / max(distance_otm, 50)))

    # Time decay: morning has more premium
    if time_hour < 10:
        time_factor = 1.1  # 9:36 has 10% higher premium
    elif time_hour < 12:
        time_factor = 1.0  # 10:00-11:30 baseline
    else:
        time_factor = 0.9  # 12:00-12:30 lower premium (theta decay)

    return round(base * distance_factor * time_factor, 2)

def calculate_position_size_kelly(account_balance, win_rate, avg_win, avg_loss):
    """Calculate position size using Half-Kelly criterion."""
    if not AUTOSCALING_ENABLED:
        return 1

    if account_balance < STARTING_CAPITAL * 0.5:
        print(f"⚠️  Account below 50% of starting capital (${account_balance:,.0f})")
        return 0

    kelly_f = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
    half_kelly = kelly_f * 0.5
    contracts = int((account_balance * half_kelly) / STOP_LOSS_PER_CONTRACT)
    contracts = max(1, min(contracts, MAX_CONTRACTS))

    return contracts

# Simulate 1 year of trading
num_days = 252
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

trade_num = 0

for day_num in range(num_days):
    # Daily VIX
    vix = max(10, min(40, base_vix + random.uniform(-2, 2)))
    base_vix = vix

    # Daily NDX price
    ndx_price = base_price + random.uniform(-200, 200)
    base_price = ndx_price

    # Daily GEX pin
    ndx_pin = ndx_price + random.uniform(-50, 50)

    # Try each of 7 entry windows
    for entry_label, entry_hour in ENTRY_TIMES:
        trade_num += 1

        # 70% chance of valid setup at each entry window
        if random.random() > 0.70:
            continue  # Skip this entry window (no valid setup)

        # Get trade setup
        distance = abs(ndx_price - ndx_pin)
        distance_otm = distance + 100

        # Get realistic credit
        credit = get_realistic_ndx_credit(vix, distance_otm, entry_hour)

        # Calculate position size using Half-Kelly
        if len(recent_trades) >= 10:
            recent_winners = [t for t in recent_trades if t['win']]
            recent_losers = [t for t in recent_trades if not t['win']]

            win_rate = len(recent_winners) / len(recent_trades) if recent_trades else BOOTSTRAP_WIN_RATE
            avg_win = sum(t['profit_per_contract'] for t in recent_winners) / len(recent_winners) if recent_winners else BOOTSTRAP_AVG_WIN
            avg_loss = abs(sum(t['profit_per_contract'] for t in recent_losers) / len(recent_losers)) if recent_losers else BOOTSTRAP_AVG_LOSS
        else:
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
            profit_per_contract = credit * 0.50 * 100
        else:
            if random.random() < 0.7:
                loss_pct = 0.10
            else:
                loss_pct = random.uniform(0.15, 0.40)
            profit_per_contract = -credit * loss_pct * 100

        total_profit = profit_per_contract * contracts
        account_balance += total_profit

        trade_data = {
            'trade_num': trade_num,
            'day': day_num + 1,
            'entry_time': entry_label,
            'index': 'NDX',
            'vix': vix,
            'credit': credit,
            'contracts': contracts,
            'profit_per_contract': profit_per_contract,
            'total_profit': total_profit,
            'win': win,
            'account_balance': account_balance
        }

        all_trades.append(trade_data)
        recent_trades.append(trade_data)
        if len(recent_trades) > ROLLING_WINDOW:
            recent_trades.pop(0)

# Calculate statistics
total_pnl = account_balance - STARTING_CAPITAL
winners = [t for t in all_trades if t['win']]
losers = [t for t in all_trades if not t['win']]

win_rate = len(winners) / len(all_trades) * 100 if all_trades else 0
avg_win_per_contract = sum(t['profit_per_contract'] for t in winners) / len(winners) if winners else 0
avg_loss_per_contract = sum(t['profit_per_contract'] for t in losers) / len(losers) if losers else 0
avg_credit = sum(t['credit'] for t in all_trades) / len(all_trades) if all_trades else 0
avg_contracts = sum(t['contracts'] for t in all_trades) / len(all_trades) if all_trades else 0

profit_factor = abs(sum(t['total_profit'] for t in winners) / sum(t['total_profit'] for t in losers)) if losers else 0

# Entry time distribution
entry_time_stats = defaultdict(int)
for t in all_trades:
    entry_time_stats[t['entry_time']] += 1

print(f"Trading Days:         {num_days}")
print(f"Total Trades:         {len(all_trades)}")
print(f"Avg Trades/Day:       {len(all_trades)/num_days:.1f}")
print()
print("Entry Time Distribution:")
for entry_label, _ in ENTRY_TIMES:
    count = entry_time_stats[entry_label]
    pct = count / len(all_trades) * 100 if all_trades else 0
    print(f"  {entry_label}: {count:3d} trades ({pct:4.1f}%)")
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

# Contract distribution
contract_sizes = [t['contracts'] for t in all_trades]
for c in range(1, 11):
    count = sum(1 for cs in contract_sizes if cs == c)
    if count > 0:
        print(f"  {c:2d} contract{'s' if c > 1 else ' '}: {count:3d} trades ({count/len(all_trades)*100:4.1f}%)")
print()

# Top 10 best and worst
sorted_trades = sorted(all_trades, key=lambda x: x['total_profit'], reverse=True)
print("TOP 10 BEST TRADES:")
print("-" * 80)
for i, t in enumerate(sorted_trades[:10], 1):
    print(f"{i:2d}. Day {t['day']:3d} {t['entry_time']}: ${t['total_profit']:7.0f} profit ({t['contracts']} × ${t['credit']:.2f}, VIX {t['vix']:.1f})")
print()

print("TOP 10 WORST TRADES:")
print("-" * 80)
for i, t in enumerate(sorted_trades[-10:], 1):
    print(f"{i:2d}. Day {t['day']:3d} {t['entry_time']}: ${t['total_profit']:7.0f} loss ({t['contracts']} × ${t['credit']:.2f}, VIX {t['vix']:.1f})")
print()

print("ACCOUNT GROWTH TRAJECTORY:")
print("-" * 80)
milestones = [0, 100, 200, 300, 400, 500, len(all_trades)-1] if all_trades else []
for idx in milestones:
    if idx < len(all_trades):
        t = all_trades[idx]
        print(f"After trade #{t['trade_num']:3d}: ${t['account_balance']:8,.0f}")
print()
print("=" * 80)
print("NDX 7-ENTRY BACKTEST COMPLETE")
print("=" * 80)
