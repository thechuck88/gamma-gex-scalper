#!/usr/bin/env python3
"""Run parallel backtests on SPX and NDX with realistic parameters."""

import sys
sys.path.insert(0, '/root/gamma')

from backtest_realistic_intraday import *
import multiprocessing as mp
from datetime import datetime

def run_spx_backtest():
    """Run SPX backtest with standard parameters."""
    print("\n" + "="*80)
    print("SPX BACKTEST STARTING")
    print("="*80 + "\n")

    # Monkey-patch to use SPX parameters
    original_run = run_backtest

    def spx_backtest():
        # Set seed for reproducibility
        random.seed(42)
        np.random.seed(42)

        # Run with SPX defaults (already configured)
        return original_run()

    return spx_backtest()

def run_ndx_backtest():
    """Run NDX backtest with adjusted parameters."""
    print("\n" + "="*80)
    print("NDX BACKTEST STARTING")
    print("="*80 + "\n")

    # Monkey-patch the backtest to use NDX parameters
    original_run_backtest = run_backtest

    def ndx_backtest():
        # Set seed for reproducibility (same as SPX for fair comparison)
        random.seed(42)
        np.random.seed(42)

        # Track stats
        account_balance = STARTING_CAPITAL
        all_trades = []
        recent_trades = []
        ROLLING_WINDOW = 50

        # Bootstrap stats (NDX typically has better performance)
        BOOTSTRAP_WIN_RATE = 0.629
        BOOTSTRAP_AVG_WIN = 30
        BOOTSTRAP_AVG_LOSS = 9

        # Entry times (7 optimal windows - 1:00 PM removed due to poor performance)
        ENTRY_TIMES = [
            ('9:36', 0.1),
            ('10:00', 0.5),
            ('10:30', 1.0),
            ('11:00', 1.5),
            ('11:30', 2.0),
            ('12:00', 2.5),
            ('12:30', 3.0),
        ]

        # Simulate 252 trading days
        num_days = 252
        base_vix = 20.0  # NDX volatility typically ~25% higher than SPX
        base_price = 16000  # NDX ~2.6x SPX price

        print(f"Trading Days:         {num_days}")
        print(f"Total Setups:         ~{num_days * len(ENTRY_TIMES)}")
        print()
        print("="*80)
        print("RUNNING NDX SIMULATION")
        print("="*80)

        for day_num in range(num_days):
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
                    'entry_time': entry_label,
                    'spx_price': ndx_price,
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
                recent_trades.append(trade_data)
                if len(recent_trades) > ROLLING_WINDOW:
                    recent_trades.pop(0)

        # Calculate statistics
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

        # Print results
        print()
        print("="*80)
        print("NDX RESULTS")
        print("="*80)
        print(f"Starting Capital:     ${STARTING_CAPITAL:,.0f}")
        print(f"Final Balance:        ${account_balance:,.0f}")
        print(f"NET P/L:              ${total_pnl:,.0f} ({(total_pnl/STARTING_CAPITAL)*100:+.1f}%)")
        print()
        print(f"Total Trades:         {len(all_trades)}")
        print(f"Win Rate:             {win_rate:.1f}%")
        print(f"Profit Factor:        {profit_factor:.2f}")
        print()
        print(f"Average Credit:       ${avg_credit:.2f}")
        print(f"Avg Contracts/Trade:  {avg_contracts:.2f}")
        print(f"Avg Win (per contr):  ${avg_win_per_contract:.0f}")
        print(f"Avg Loss (per contr): ${avg_loss_per_contract:.0f}")
        print()
        print(f"Hold-to-Expiry:       {len(held_trades)} trades ({len(held_trades)/len(all_trades)*100:.1f}%)")
        print(f"Hold P/L:             ${sum(t['total_profit'] for t in held_trades) if held_trades else 0:.0f}")
        print("="*80)

        # Return summary stats
        return {
            'win_rate': win_rate / 100.0,
            'profit_factor': profit_factor,
            'net_pl': total_pnl,
            'final_balance': account_balance,
            'total_trades': len(all_trades),
            'hold_count': len(held_trades),
            'hold_pl': sum(t['total_profit'] for t in held_trades) if held_trades else 0,
            'avg_credit': avg_credit,
            'avg_contracts': avg_contracts,
            'avg_win': avg_win_per_contract,
            'avg_loss': avg_loss_per_contract
        }

    return ndx_backtest()

if __name__ == "__main__":
    print("\n" + "="*80)
    print("SPX vs NDX PARALLEL BACKTEST")
    print("="*80)
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)

    # Run both backtests in parallel
    with mp.Pool(2) as pool:
        spx_future = pool.apply_async(run_spx_backtest)
        ndx_future = pool.apply_async(run_ndx_backtest)

        spx_results = spx_future.get()
        ndx_results = ndx_future.get()

    # Print comparison
    print("\n" + "="*80)
    print("SPX vs NDX COMPARISON")
    print("="*80)
    print()
    print(f"{'Metric':<25} | {'SPX':>15} | {'NDX':>15} | {'Difference':>15}")
    print("-" * 80)
    print(f"{'Win Rate':<25} | {spx_results['win_rate']*100:>14.1f}% | {ndx_results['win_rate']*100:>14.1f}% | {(ndx_results['win_rate']-spx_results['win_rate'])*100:>+14.1f}%")
    print(f"{'Profit Factor':<25} | {spx_results['profit_factor']:>15.2f} | {ndx_results['profit_factor']:>15.2f} | {ndx_results['profit_factor']-spx_results['profit_factor']:>+15.2f}")
    print(f"{'Net P/L':<25} | ${spx_results['net_pl']:>14,.0f} | ${ndx_results['net_pl']:>14,.0f} | ${ndx_results['net_pl']-spx_results['net_pl']:>+14,.0f}")
    print(f"{'Return %':<25} | {spx_results['net_pl']/STARTING_CAPITAL*100:>14.1f}% | {ndx_results['net_pl']/STARTING_CAPITAL*100:>14.1f}% | {(ndx_results['net_pl']-spx_results['net_pl'])/STARTING_CAPITAL*100:>+14.1f}%")
    print(f"{'Total Trades':<25} | {spx_results['total_trades']:>15,} | {ndx_results['total_trades']:>15,} | {ndx_results['total_trades']-spx_results['total_trades']:>+15,}")
    print(f"{'Avg Credit':<25} | ${spx_results['avg_credit']:>14.2f} | ${ndx_results['avg_credit']:>14.2f} | ${ndx_results['avg_credit']-spx_results['avg_credit']:>+14.2f}")
    print(f"{'Avg Contracts':<25} | {spx_results['avg_contracts']:>15.2f} | {ndx_results['avg_contracts']:>15.2f} | {ndx_results['avg_contracts']-spx_results['avg_contracts']:>+15.2f}")
    print(f"{'Avg Win (per contr)':<25} | ${spx_results['avg_win']:>14.0f} | ${ndx_results['avg_win']:>14.0f} | ${ndx_results['avg_win']-spx_results['avg_win']:>+14.0f}")
    print(f"{'Avg Loss (per contr)':<25} | ${spx_results['avg_loss']:>14.0f} | ${ndx_results['avg_loss']:>14.0f} | ${ndx_results['avg_loss']-spx_results['avg_loss']:>+14.0f}")
    print(f"{'Hold-to-Expiry Count':<25} | {spx_results['hold_count']:>15} | {ndx_results['hold_count']:>15} | {ndx_results['hold_count']-spx_results['hold_count']:>+15}")
    print(f"{'Hold P/L':<25} | ${spx_results['hold_pl']:>14,.0f} | ${ndx_results['hold_pl']:>14,.0f} | ${ndx_results['hold_pl']-spx_results['hold_pl']:>+14,.0f}")
    print()
    print("="*80)
    print("KEY INSIGHTS")
    print("="*80)

    # Calculate key metrics
    ndx_advantage = ndx_results['net_pl'] - spx_results['net_pl']
    ndx_advantage_pct = (ndx_advantage / spx_results['net_pl']) * 100 if spx_results['net_pl'] > 0 else 0

    print(f"\n1. Performance:")
    if ndx_advantage > 0:
        print(f"   NDX outperforms SPX by ${ndx_advantage:,.0f} ({ndx_advantage_pct:+.1f}%)")
    else:
        print(f"   SPX outperforms NDX by ${-ndx_advantage:,.0f} ({-ndx_advantage_pct:+.1f}%)")

    print(f"\n2. Credit Collection:")
    credit_diff = ndx_results['avg_credit'] - spx_results['avg_credit']
    credit_diff_pct = (credit_diff / spx_results['avg_credit']) * 100
    print(f"   NDX credits {credit_diff_pct:+.1f}% higher (${ndx_results['avg_credit']:.2f} vs ${spx_results['avg_credit']:.2f})")

    print(f"\n3. Risk Profile:")
    print(f"   SPX Avg Loss: ${spx_results['avg_loss']:.0f} per contract")
    print(f"   NDX Avg Loss: ${ndx_results['avg_loss']:.0f} per contract")
    loss_diff = ndx_results['avg_loss'] - spx_results['avg_loss']
    if loss_diff < 0:
        print(f"   NDX has {abs(loss_diff)/spx_results['avg_loss']*100:.1f}% larger average losses")
    else:
        print(f"   NDX has {loss_diff/spx_results['avg_loss']*100:.1f}% smaller average losses")

    print(f"\n4. Win Rate:")
    wr_diff = (ndx_results['win_rate'] - spx_results['win_rate']) * 100
    print(f"   SPX: {spx_results['win_rate']*100:.1f}%")
    print(f"   NDX: {ndx_results['win_rate']*100:.1f}%")
    print(f"   Difference: {wr_diff:+.1f}%")

    print("\n" + "="*80)
    print(f"End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80 + "\n")
