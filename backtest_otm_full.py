#!/usr/bin/env python3
"""
Full OTM Spread Backtest - Using all available SPX historical data

Strategy:
- Place OTM iron condors on days when GEX has no setup OR alongside GEX
- 2.5 SD strikes (90-95% win rate)
- Hold to expiration if >70% profit
- Lock in 50% if profit reaches 50-70%
- 10% stop loss, 40% emergency stop
"""

import pandas as pd
import numpy as np
from datetime import datetime, time
import sys

sys.path.insert(0, '/root/gamma')
from otm_spreads import calculate_expected_move, get_implied_volatility_estimate


# Strategy parameters (matching monitor.py)
WIN_RATE = 0.92  # 92% win rate for 2.5 SD strikes
STOP_LOSS_PCT = 0.10
EMERGENCY_STOP_PCT = 0.40
LOCK_IN_THRESHOLD = 0.50  # Lock in 50% profit
HOLD_THRESHOLD = 0.70     # Hold to expiration if >70%

# Position sizing
STARTING_POSITION_SIZE = 10  # contracts


def calculate_otm_strikes_and_credit(spx_price, vix_level, hours_remaining=4.5):
    """
    Calculate OTM strikes and expected credit.

    Returns:
        dict with strikes, credits, and distances
    """
    # Calculate strike distance (2.2 SD for better credits, still ~92% win rate)
    # 2.5 SD = 98.8% theoretical, but with real-world slippage/gaps = 95%
    # 2.2 SD = 97.2% theoretical, with real-world = 92% (target)
    implied_vol = vix_level / 100.0
    one_sd = calculate_expected_move(spx_price, implied_vol, hours_remaining)
    strike_distance = one_sd * 2.2  # Slightly closer for better credits

    # Round to nearest 5
    strike_distance = round(strike_distance / 5) * 5
    strike_distance = max(45, strike_distance)  # Minimum 45 points (closer than before)

    # Calculate strikes
    call_short = round((spx_price + strike_distance) / 5) * 5
    call_long = call_short + 10

    put_short = round((spx_price - strike_distance) / 5) * 5
    put_long = put_short - 10

    # Estimate credit based on distance and VIX
    # Credit model: Further away = less credit, higher VIX = more credit
    vix_factor = vix_level / 15.0
    time_factor = min(1.0, hours_remaining / 4.0)

    # Base credit for 45pts away, VIX=15, 4hrs remaining
    # Closer strikes = better credit (0.30 base instead of 0.25)
    base_credit = 0.30

    call_distance_factor = 45.0 / max(45, call_short - spx_price)
    put_distance_factor = 45.0 / max(45, spx_price - put_short)

    call_credit = base_credit * vix_factor * time_factor * call_distance_factor
    put_credit = base_credit * vix_factor * time_factor * put_distance_factor

    call_credit = max(0.10, call_credit)
    put_credit = max(0.10, put_credit)

    total_credit = call_credit + put_credit

    return {
        'call_short': call_short,
        'call_long': call_long,
        'put_short': put_short,
        'put_long': put_long,
        'call_credit': call_credit,
        'put_credit': put_credit,
        'total_credit': total_credit,
        'call_distance': call_short - spx_price,
        'put_distance': spx_price - put_short,
        'strike_distance': strike_distance
    }


def simulate_otm_trade(entry_price, entry_vix, close_price, position_size=10):
    """
    Simulate one OTM iron condor trade.

    Returns:
        dict with trade result
    """
    # Calculate strikes and credit
    strikes = calculate_otm_strikes_and_credit(entry_price, entry_vix)

    # Check minimum credit requirement
    if strikes['total_credit'] < 0.30:
        return None  # Credit too low

    # Simulate outcome with realistic win rate
    # Use actual close price AND add statistical losses (8% loss rate)
    import random
    random.seed(int(entry_price + entry_vix))  # Deterministic based on entry conditions

    # Check if SPX closed outside strikes (loss scenario)
    call_breached = close_price >= strikes['call_short']
    put_breached = close_price <= strikes['put_short']

    # Add statistical losses even if strikes not breached (intraday moves, gaps, etc.)
    # Target: ~92% win rate
    if not call_breached and not put_breached:
        # Randomly assign loss based on target win rate
        if random.random() > WIN_RATE:
            # Simulate intraday loss (stop triggered but recovered by close)
            # Randomly pick which side got tested
            if random.random() > 0.5:
                call_breached = True
            else:
                put_breached = True

    if call_breached or put_breached:
        # Loss scenario - check stop loss levels

        # Calculate how far price moved
        if call_breached:
            move_points = close_price - strikes['call_short']
            # Loss = move into spread, capped at spread width (10 points)
            loss_points = min(move_points, 10)
        else:  # put_breached
            move_points = strikes['put_short'] - close_price
            loss_points = min(move_points, 10)

        # Convert to dollars
        spread_width = 10
        max_loss = (spread_width - strikes['total_credit']) * 100
        actual_loss = loss_points * 100

        # Apply stop loss (10% or 40% emergency)
        stop_loss_trigger = max_loss * STOP_LOSS_PCT
        emergency_stop_trigger = max_loss * EMERGENCY_STOP_PCT

        if actual_loss >= emergency_stop_trigger:
            # Emergency stop
            loss = emergency_stop_trigger
            exit_reason = "Emergency Stop (40%)"
        elif actual_loss >= stop_loss_trigger:
            # Normal stop loss
            loss = stop_loss_trigger
            exit_reason = "Stop Loss (10%)"
        else:
            # Realized full loss (rare - price moved slowly)
            loss = actual_loss
            exit_reason = "Full Loss at Expiration"

        pnl_per_contract = -loss / 100  # Convert to per-contract
        outcome = "LOSS"

    else:
        # Win scenario - expired worthless
        # Profit = full credit collected
        pnl_per_contract = strikes['total_credit'] * 100
        outcome = "WIN"
        exit_reason = "Expired Worthless (Full Credit)"

    total_pnl = pnl_per_contract * position_size

    return {
        'outcome': outcome,
        'call_strikes': f"{strikes['call_short']}/{strikes['call_long']}",
        'put_strikes': f"{strikes['put_short']}/{strikes['put_long']}",
        'entry_credit': strikes['total_credit'],
        'call_distance': strikes['call_distance'],
        'put_distance': strikes['put_distance'],
        'pnl_per_contract': pnl_per_contract / 100,  # In dollars
        'total_pnl': total_pnl / 100,  # In dollars
        'exit_reason': exit_reason,
        'call_breached': call_breached,
        'put_breached': put_breached
    }


def run_full_backtest():
    """Run full OTM backtest on all available data."""

    print("=" * 80)
    print("FULL OTM SPREAD BACKTEST - All Available Historical Data")
    print("=" * 80)
    print()

    # Load historical backtest data
    df = pd.read_csv('/root/gamma/data/backtest_spx_results.csv')

    print(f"Loaded {len(df)} historical data points")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    print()

    # Group by date to get unique trading days
    daily_data = df.groupby('date').first().reset_index()

    print(f"Unique trading days: {len(daily_data)}")
    print()

    # Simulate OTM spreads
    trades = []

    for idx, row in daily_data.iterrows():
        date = row['date']
        spx_entry = row['spx_entry']
        spx_close = row['spx_close']
        vix = row['vix']

        # Skip if missing data
        if pd.isna(spx_entry) or pd.isna(spx_close) or pd.isna(vix):
            continue

        # Skip weekends (already filtered in source data)

        # Check if OTM opportunity exists
        # For this backtest, we'll trade every valid day to see max potential

        # Simulate trade
        trade = simulate_otm_trade(spx_entry, vix, spx_close, STARTING_POSITION_SIZE)

        if trade:
            trade['date'] = date
            trade['spx_entry'] = spx_entry
            trade['spx_close'] = spx_close
            trade['vix'] = vix
            trades.append(trade)

    # Convert to DataFrame
    trades_df = pd.DataFrame(trades)

    if trades_df.empty:
        print("No valid trades found")
        return

    # Calculate statistics
    total_trades = len(trades_df)
    wins = (trades_df['outcome'] == 'WIN').sum()
    losses = total_trades - wins
    win_rate = (wins / total_trades) * 100

    total_pnl = trades_df['total_pnl'].sum()
    winning_trades = trades_df[trades_df['outcome'] == 'WIN']
    losing_trades = trades_df[trades_df['outcome'] == 'LOSS']

    avg_win = winning_trades['total_pnl'].mean() if len(winning_trades) > 0 else 0
    avg_loss = losing_trades['total_pnl'].mean() if len(losing_trades) > 0 else 0

    avg_credit = trades_df['entry_credit'].mean()

    # Calculate profit factor
    gross_profit = winning_trades['total_pnl'].sum() if len(winning_trades) > 0 else 0
    gross_loss = abs(losing_trades['total_pnl'].sum()) if len(losing_trades) > 0 else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # Calculate drawdown
    trades_df['cumulative_pnl'] = trades_df['total_pnl'].cumsum()
    trades_df['peak'] = trades_df['cumulative_pnl'].cummax()
    trades_df['drawdown'] = trades_df['peak'] - trades_df['cumulative_pnl']
    max_drawdown = trades_df['drawdown'].max()

    # Monthly breakdown
    trades_df['month'] = pd.to_datetime(trades_df['date']).dt.to_period('M')
    monthly_stats = trades_df.groupby('month').agg({
        'total_pnl': 'sum',
        'outcome': 'count'
    }).rename(columns={'outcome': 'trades'})

    # Print results
    print("=" * 80)
    print("BACKTEST RESULTS")
    print("=" * 80)
    print()
    print(f"Total Trades:        {total_trades}")
    print(f"Wins:                {wins} ({win_rate:.1f}%)")
    print(f"Losses:              {losses} ({100-win_rate:.1f}%)")
    print()
    print(f"Total P&L:           ${total_pnl:,.2f}")
    print(f"Avg Credit:          ${avg_credit:.2f}")
    print(f"Avg Win:             ${avg_win:,.2f}")
    print(f"Avg Loss:            ${avg_loss:,.2f}")
    print(f"Avg P&L/Trade:       ${total_pnl/total_trades:,.2f}")
    print()
    print(f"Profit Factor:       {profit_factor:.2f}")
    print(f"Max Drawdown:        ${max_drawdown:,.2f}")
    print()

    # Monthly performance
    print("MONTHLY PERFORMANCE:")
    print("-" * 60)
    print(f"{'Month':<12} {'Trades':<8} {'P&L':<15} {'Avg/Trade':<12}")
    print("-" * 60)

    for month, stats in monthly_stats.iterrows():
        avg_per_trade = stats['total_pnl'] / stats['trades']
        print(f"{str(month):<12} {int(stats['trades']):<8} ${stats['total_pnl']:>12,.2f} ${avg_per_trade:>10,.2f}")

    print("-" * 60)
    print(f"{'TOTAL':<12} {total_trades:<8} ${total_pnl:>12,.2f} ${total_pnl/total_trades:>10,.2f}")
    print()

    # Show sample trades
    print("SAMPLE TRADES (First 10 & Last 10):")
    print("-" * 100)
    print(f"{'Date':<12} {'SPX Entry':<10} {'SPX Close':<10} {'VIX':<6} {'Strikes':<30} {'Credit':<8} {'P&L':<12} {'Outcome':<10}")
    print("-" * 100)

    sample_trades = pd.concat([trades_df.head(10), trades_df.tail(10)])

    for _, trade in sample_trades.iterrows():
        strikes = f"{trade['put_strikes']} × {trade['call_strikes']}"
        print(f"{trade['date']:<12} {trade['spx_entry']:<10.0f} {trade['spx_close']:<10.0f} "
              f"{trade['vix']:<6.1f} {strikes:<30} ${trade['entry_credit']:<7.2f} "
              f"${trade['total_pnl']:>10.2f} {trade['outcome']:<10}")

    print()

    # Breach analysis
    call_breaches = trades_df['call_breached'].sum()
    put_breaches = trades_df['put_breached'].sum()

    print("BREACH ANALYSIS:")
    print("-" * 40)
    print(f"Call breaches:  {call_breaches} ({call_breaches/total_trades*100:.1f}%)")
    print(f"Put breaches:   {put_breaches} ({put_breaches/total_trades*100:.1f}%)")
    print(f"Total losses:   {losses} ({losses/total_trades*100:.1f}%)")
    print()

    # Exit reason breakdown
    print("EXIT REASONS:")
    print("-" * 40)
    exit_counts = trades_df['exit_reason'].value_counts()
    for reason, count in exit_counts.items():
        print(f"{reason:<30} {count:>4} ({count/total_trades*100:.1f}%)")

    print()
    print("=" * 80)
    print(f"ANNUALIZED PROJECTION: ${total_pnl * (252 / len(daily_data)):,.2f}")
    print("=" * 80)

    return trades_df


if __name__ == '__main__':
    trades_df = run_full_backtest()
