#!/usr/bin/env python3
"""Run 3-year backtest on NDX with realistic parameters."""

import sys
sys.path.insert(0, '/root/gamma')

from backtest_realistic_intraday import *
from datetime import datetime

def run_ndx_3year_backtest():
    """Run NDX backtest with 3 years of trading."""

    print("\n" + "="*80)
    print("NDX 3-YEAR BACKTEST - 0DTE Options with Hold-to-Expiry")
    print("="*80)
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    print()

    # Set seed for reproducibility
    random.seed(42)
    np.random.seed(42)

    # Track stats
    account_balance = STARTING_CAPITAL
    all_trades = []
    recent_trades = []
    ROLLING_WINDOW = 50

    # Bootstrap stats
    BOOTSTRAP_WIN_RATE = 0.629
    BOOTSTRAP_AVG_WIN = 30
    BOOTSTRAP_AVG_LOSS = 9

    # Entry times (7 optimal windows)
    ENTRY_TIMES = [
        ('9:36', 0.1),
        ('10:00', 0.5),
        ('10:30', 1.0),
        ('11:00', 1.5),
        ('11:30', 2.0),
        ('12:00', 2.5),
        ('12:30', 3.0),
    ]

    # Simulate 3 YEARS = 756 trading days
    num_days = 252 * 3
    base_vix = 20.0  # NDX volatility typically ~25% higher than SPX
    base_price = 16000  # NDX ~2.6x SPX price

    print(f"Trading Days:         {num_days}")
    print(f"Trading Years:        3.0")
    print(f"Entry Windows/Day:    {len(ENTRY_TIMES)}")
    print(f"Max Possible Trades:  ~{num_days * len(ENTRY_TIMES)}")
    print()
    print("="*80)
    print("RUNNING 3-YEAR NDX SIMULATION")
    print("="*80)
    print()

    # Track yearly performance
    yearly_stats = {1: [], 2: [], 3: []}
    starting_balances = {1: STARTING_CAPITAL}

    for day_num in range(num_days):
        # Determine which year we're in
        year = (day_num // 252) + 1

        # Track starting balance for each year
        if year not in starting_balances:
            starting_balances[year] = account_balance

        # Daily VIX (NDX uses VXN, typically higher)
        vix = max(12, min(50, base_vix + random.uniform(-3, 3)))
        base_vix = vix

        # Daily NDX price
        ndx_price = base_price + random.uniform(-150, 150)  # Wider range for NDX
        base_price = ndx_price

        # GEX pin
        gex_pin = ndx_price + random.uniform(-25, 25)  # Wider pin range

        # Try each entry window
        for entry_label, entry_hour in ENTRY_TIMES:
            # 70% chance of valid setup
            if random.random() > 0.70:
                continue

            # Get realistic credit - NDX typically 20-30% higher than SPX
            # For a 10-point ($0.10) spread, credits should be 20-80% of width
            if vix < 18:
                credit = random.uniform(0.025, 0.045)  # Low vol: 25-45% of width
            elif vix < 25:
                credit = random.uniform(0.045, 0.070)  # Med vol: 45-70% of width
            elif vix < 35:
                credit = random.uniform(0.070, 0.090)  # High vol: 70-90% of width
            else:
                credit = random.uniform(0.080, 0.095)  # Very high vol: 80-95% of width

            # Calculate position size
            if len(recent_trades) >= 10:
                recent_winners = [t for t in recent_trades if t['profit_per_contract'] > 0]
                recent_losers = [t for t in recent_trades if t['profit_per_contract'] <= 0]

                win_rate = len(recent_winners) / len(recent_trades) if recent_trades else BOOTSTRAP_WIN_RATE
                avg_win = sum(t['profit_per_contract'] for t in recent_winners) / len(recent_winners) if recent_winners else BOOTSTRAP_AVG_WIN
                avg_loss = abs(sum(t['profit_per_contract'] for t in recent_losers) / len(recent_losers)) if recent_losers else BOOTSTRAP_AVG_LOSS
            else:
                win_rate = BOOTSTRAP_WIN_RATE
                avg_win = BOOTSTRAP_AVG_WIN
                avg_loss = BOOTSTRAP_AVG_LOSS

            contracts = calculate_position_size_kelly(account_balance, win_rate, avg_win, avg_loss)

            if contracts == 0:
                continue

            # Simulate trade
            trade_result = simulate_trade(entry_hour, ndx_price, gex_pin, vix, credit, contracts, account_balance)

            # Update balance
            account_balance += trade_result['total_profit']

            # Record trade
            trade_data = {
                'day': day_num + 1,
                'year': year,
                'entry_time': entry_label,
                'ndx_price': ndx_price,
                'gex_pin': gex_pin,
                'vix': vix,
                'credit': credit,
                'contracts': contracts,
                'profit_per_contract': trade_result['profit_per_contract'],
                'total_profit': trade_result['total_profit'],
                'account_balance': account_balance,
                'exit_reason': trade_result['exit_reason'],
                'hold_to_expiry': trade_result['hold_to_expiry'],
                'best_profit_pct': trade_result['best_profit_pct'],
                'minutes_held': trade_result['minutes_held']
            }

            all_trades.append(trade_data)
            yearly_stats[year].append(trade_data)
            recent_trades.append(trade_data)
            if len(recent_trades) > ROLLING_WINDOW:
                recent_trades.pop(0)

        # Print progress every 100 days
        if (day_num + 1) % 100 == 0:
            progress_pct = ((day_num + 1) / num_days) * 100
            print(f"Progress: Day {day_num + 1}/{num_days} ({progress_pct:.1f}%) - Balance: ${account_balance:,.0f}")

    # Calculate overall statistics
    total_pnl = account_balance - STARTING_CAPITAL
    winners = [t for t in all_trades if t['profit_per_contract'] > 0]
    losers = [t for t in all_trades if t['profit_per_contract'] <= 0]

    win_rate = len(winners) / len(all_trades) * 100 if all_trades else 0
    avg_win_per_contract = sum(t['profit_per_contract'] for t in winners) / len(winners) if winners else 0
    avg_loss_per_contract = sum(t['profit_per_contract'] for t in losers) / len(losers) if losers else 0
    avg_credit = sum(t['credit'] for t in all_trades) / len(all_trades) if all_trades else 0
    avg_contracts = sum(t['contracts'] for t in all_trades) / len(all_trades) if all_trades else 0

    profit_factor = abs(sum(t['total_profit'] for t in winners) / sum(t['total_profit'] for t in losers)) if losers else 0

    # Hold-to-expiry stats
    held_trades = [t for t in all_trades if t['hold_to_expiry']]

    # Print overall results
    print()
    print("="*80)
    print("3-YEAR NDX RESULTS")
    print("="*80)
    print(f"Starting Capital:     ${STARTING_CAPITAL:,.0f}")
    print(f"Final Balance:        ${account_balance:,.0f}")
    print(f"NET P/L:              ${total_pnl:,.0f} ({(total_pnl/STARTING_CAPITAL)*100:+.1f}%)")
    print(f"Annualized Return:    {(((account_balance/STARTING_CAPITAL)**(1/3))-1)*100:.1f}%")
    print()
    print(f"Total Trades:         {len(all_trades):,}")
    print(f"Avg Trades/Day:       {len(all_trades)/num_days:.1f}")
    print(f"Win Rate:             {win_rate:.1f}%")
    print(f"Profit Factor:        {profit_factor:.2f}")
    print()
    print(f"Average Credit:       ${avg_credit:.2f}")
    print(f"Avg Contracts/Trade:  {avg_contracts:.2f}")
    print(f"Avg Win (per contr):  ${avg_win_per_contract:.0f}")
    print(f"Avg Loss (per contr): ${avg_loss_per_contract:.0f}")
    print()
    print(f"Hold-to-Expiry:       {len(held_trades)} trades ({len(held_trades)/len(all_trades)*100:.1f}%)")
    print(f"Hold P/L:             ${sum(t['total_profit'] for t in held_trades) if held_trades else 0:,.0f}")
    print()

    # Print yearly breakdown
    print("="*80)
    print("YEAR-BY-YEAR BREAKDOWN")
    print("="*80)
    print()

    for year in [1, 2, 3]:
        year_trades = yearly_stats[year]
        if not year_trades:
            continue

        year_winners = [t for t in year_trades if t['profit_per_contract'] > 0]
        year_losers = [t for t in year_trades if t['profit_per_contract'] <= 0]

        year_start_balance = starting_balances[year]
        year_end_balance = year_trades[-1]['account_balance']
        year_pnl = year_end_balance - year_start_balance
        year_return = (year_pnl / year_start_balance) * 100

        year_win_rate = len(year_winners) / len(year_trades) * 100 if year_trades else 0
        year_pf = abs(sum(t['total_profit'] for t in year_winners) / sum(t['total_profit'] for t in year_losers)) if year_losers else 0

        print(f"YEAR {year}:")
        print(f"  Trades:         {len(year_trades):,}")
        print(f"  Starting:       ${year_start_balance:,.0f}")
        print(f"  Ending:         ${year_end_balance:,.0f}")
        print(f"  P/L:            ${year_pnl:,.0f} ({year_return:+.1f}%)")
        print(f"  Win Rate:       {year_win_rate:.1f}%")
        print(f"  Profit Factor:  {year_pf:.2f}")
        print()

    # Exit reason distribution
    exit_reasons = defaultdict(int)
    for t in all_trades:
        exit_reasons[t['exit_reason']] += 1

    print("="*80)
    print("EXIT REASON DISTRIBUTION (Top 20)")
    print("="*80)
    sorted_reasons = sorted(exit_reasons.items(), key=lambda x: x[1], reverse=True)
    for reason, count in sorted_reasons[:20]:
        pct = (count / len(all_trades)) * 100
        print(f"  {reason:<50}: {count:5,} ({pct:5.1f}%)")

    print()
    print("="*80)
    print(f"End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    print()

if __name__ == "__main__":
    run_ndx_3year_backtest()
