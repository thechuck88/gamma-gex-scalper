#!/usr/bin/env python3
"""
1-Year Simulated Backtest for GEX + Single-Sided OTM Strategy

Simulates 252 trading days with:
- Realistic SPX price movements (trending + ranging periods)
- VIX regime changes (low vol / high vol)
- GEX pin levels based on SPX
- Entry signals at 10:00, 10:30, 11:00, 11:30 ET
- Both GEX PIN spreads and Single-Sided OTM spreads
- 70% hold-to-expiration logic
- 50% lock-in protection
- Autoscaling position sizing (Half-Kelly)
"""

import random
import numpy as np
from datetime import datetime, timedelta
import pandas as pd

# Strategy parameters (from optimizations)
ENTRY_TIMES_ET = ['10:00', '10:30', '11:00', '11:30']
CUTOFF_HOUR = 13  # No trades after 1 PM
VIX_FLOOR = 12.0
VIX_MAX_THRESHOLD = 20.0

# Exit parameters
STOP_LOSS_PCT = 0.10
SL_EMERGENCY_PCT = 0.25
SL_GRACE_PERIOD_SEC = 540

# Position sizing (autoscaling)
STARTING_CAPITAL = 20000
MAX_CONTRACTS = 3  # Conservative limit

# Simulation parameters
TRADING_DAYS = 252  # 1 year
START_DATE = datetime(2025, 1, 16)


def simulate_market_conditions():
    """Generate 1 year of market data with realistic regimes."""
    np.random.seed(42)  # Reproducible results

    dates = []
    spx_prices = []
    vix_levels = []

    current_date = START_DATE
    spx_price = 6900.0
    vix = 15.0

    # Market regimes (alternating trending/ranging)
    regimes = [
        {'type': 'trending_up', 'days': 40, 'spx_drift': 1.5, 'vix_mean': 13.0},
        {'type': 'ranging', 'days': 30, 'spx_drift': 0.0, 'vix_mean': 16.0},
        {'type': 'trending_up', 'days': 50, 'spx_drift': 1.2, 'vix_mean': 14.0},
        {'type': 'volatile', 'days': 20, 'spx_drift': -2.0, 'vix_mean': 22.0},
        {'type': 'recovery', 'days': 35, 'spx_drift': 2.0, 'vix_mean': 18.0},
        {'type': 'ranging', 'days': 40, 'spx_drift': 0.0, 'vix_mean': 15.0},
        {'type': 'trending_down', 'days': 15, 'spx_drift': -1.5, 'vix_mean': 19.0},
        {'type': 'recovery', 'days': 22, 'spx_drift': 1.8, 'vix_mean': 16.0},
    ]

    for regime in regimes:
        for _ in range(regime['days']):
            # Skip weekends
            while current_date.weekday() >= 5:
                current_date += timedelta(days=1)

            # SPX movement
            daily_return = np.random.normal(regime['spx_drift'] / 252, 0.012)
            spx_price *= (1 + daily_return)

            # VIX movement (mean-reverting)
            vix_drift = (regime['vix_mean'] - vix) * 0.1
            vix_change = vix_drift + np.random.normal(0, 1.0)
            vix = max(10.0, min(40.0, vix + vix_change))

            dates.append(current_date)
            spx_prices.append(spx_price)
            vix_levels.append(vix)

            current_date += timedelta(days=1)

    # Trim to exactly 252 days
    dates = dates[:TRADING_DAYS]
    spx_prices = spx_prices[:TRADING_DAYS]
    vix_levels = vix_levels[:TRADING_DAYS]

    return pd.DataFrame({
        'date': dates,
        'spx': spx_prices,
        'vix': vix_levels
    })


def calculate_gex_pin(spx_price):
    """Simulate GEX pin location based on SPX."""
    # Typically pins at round strikes near current price
    # 60% chance above (bullish bias), 40% below
    if random.random() < 0.60:
        # Pin above (bullish)
        offset = random.choice([25, 50, 75, 100])
    else:
        # Pin below (bearish)
        offset = -random.choice([25, 50, 75, 100])

    pin = round(spx_price / 5) * 5 + offset
    return pin


def simulate_gex_trade(entry_credit, spx_price, vix):
    """Simulate GEX PIN spread exit."""
    # GEX typically has shorter duration, moderate win rate
    will_win = random.random() < 0.67  # 67% win rate from live data

    if will_win:
        # Winner: Trailing stop exit
        profit_pct = random.uniform(0.12, 0.40)
        exit_credit = entry_credit * (1 - profit_pct)
        duration_min = random.randint(5, 60)
        reason = f"Trailing Stop ({profit_pct*100:.0f}%)"
    else:
        # Loser: Stop loss
        loss_pct = random.uniform(0.10, 0.25)
        exit_credit = entry_credit * (1 + loss_pct)
        duration_min = random.randint(3, 30)
        reason = f"Stop Loss (-{loss_pct*100:.0f}%)"

    pl = (entry_credit - exit_credit) * 100
    return exit_credit, pl, duration_min, reason, will_win


def simulate_single_sided_trade(entry_credit, distance_otm, vix):
    """Simulate single-sided OTM spread exit with 70% hold logic."""
    # High win rate (87.5% from backtest)
    will_win = random.random() < 0.875

    if will_win:
        # Simulate profit progression
        peak_profit_pct = random.uniform(0.50, 0.85)

        if peak_profit_pct >= 0.70:
            # Qualifies for 70% hold-to-expiration
            exit_credit = 0.0  # Expires worthless
            pl = entry_credit * 100
            duration_min = random.randint(60, 360)
            reason = "OTM Hold-to-Expiry: Full Credit Collected"
        elif peak_profit_pct >= 0.50:
            # 50% lock-in triggered, held to ~50%
            profit_pct = random.uniform(0.48, 0.54)
            exit_credit = entry_credit * (1 - profit_pct)
            pl = (entry_credit - exit_credit) * 100
            duration_min = random.randint(60, 180)
            reason = f"OTM 50% Lock-In Stop (peak {peak_profit_pct*100:.0f}%)"
        else:
            # Normal profit target
            profit_pct = random.uniform(0.40, 0.50)
            exit_credit = entry_credit * (1 - profit_pct)
            pl = (entry_credit - exit_credit) * 100
            duration_min = random.randint(30, 120)
            reason = f"Profit Target ({profit_pct*100:.0f}%)"
    else:
        # Loser (12.5% of trades)
        if random.random() < 0.3:
            # Emergency stop (rare)
            exit_credit = entry_credit * 1.25
            duration_min = random.randint(3, 10)
            reason = "EMERGENCY Stop Loss (-25%)"
        else:
            # Regular stop loss
            loss_pct = random.uniform(0.10, 0.20)
            exit_credit = entry_credit * (1 + loss_pct)
            duration_min = random.randint(5, 30)
            reason = f"Stop Loss (-{loss_pct*100:.0f}%)"

        pl = (entry_credit - exit_credit) * 100

    return exit_credit, pl, duration_min, reason, will_win


def calculate_position_size(account_balance, trades_history, max_risk_per_contract=800):
    """
    Calculate position size using Half-Kelly formula.

    Half-Kelly Formula:
        Kelly% = (Win_Rate * Avg_Win - Loss_Rate * Avg_Loss) / Avg_Win
        Half_Kelly% = Kelly% / 2
        Position_Size = (Account_Balance * Half_Kelly%) / Max_Risk_Per_Contract

    Args:
        account_balance: Current account value
        trades_history: List of past trades with P/L data
        max_risk_per_contract: Maximum loss per contract (spread_width - credit) * 100

    Returns:
        Number of contracts to trade (1-MAX_CONTRACTS)
    """
    # Safety halt: Stop trading if account drops below 50%
    if account_balance < STARTING_CAPITAL * 0.5:
        return 0

    # Bootstrap phase: Use 1 contract until we have 10 trades
    if len(trades_history) < 10:
        return 1

    # Use last 50 trades for rolling statistics
    recent_trades = trades_history[-50:]
    winners = [t['pl'] for t in recent_trades if t['pl'] > 0]
    losers = [t['pl'] for t in recent_trades if t['pl'] <= 0]

    # Safety check: Need both winners and losers
    if not winners or not losers:
        return 1

    # Calculate statistics
    total_trades = len(recent_trades)
    win_rate = len(winners) / total_trades
    loss_rate = len(losers) / total_trades
    avg_win = np.mean(winners)
    avg_loss = abs(np.mean(losers))

    # Kelly% = (p * W - q * L) / W
    # where p = win rate, W = avg win, q = loss rate, L = avg loss
    kelly_pct = (win_rate * avg_win - loss_rate * avg_loss) / avg_win

    # Half-Kelly for conservative sizing
    half_kelly_pct = kelly_pct / 2

    # Calculate position size based on max risk
    # Position Size = (Account * Half_Kelly%) / Max_Risk_Per_Contract
    if half_kelly_pct > 0:
        contracts = (account_balance * half_kelly_pct) / max_risk_per_contract
        contracts = int(contracts)
        contracts = max(1, contracts)  # Always trade at least 1 contract
        contracts = min(contracts, MAX_CONTRACTS)  # Cap at maximum
    else:
        contracts = 1  # Default to 1 if Kelly is negative

    return contracts


def run_simulation():
    """Run full 1-year backtest simulation."""
    print("Generating 1-year market data...")
    market_data = simulate_market_conditions()

    print(f"Simulating {TRADING_DAYS} trading days...")
    print()

    trades = []
    account_balance = STARTING_CAPITAL
    trades_history = []

    trade_id = 1

    for idx, row in market_data.iterrows():
        date = row['date']
        spx = row['spx']
        vix = row['vix']

        # Check VIX filter
        if vix >= VIX_MAX_THRESHOLD or vix < VIX_FLOOR:
            continue

        # Calculate GEX pin
        gex_pin = calculate_gex_pin(spx)

        # Decide how many entry times to use (1-3 per day)
        num_entries = random.choice([1, 1, 2, 2, 3])  # Bias toward 1-2 entries
        entry_times = random.sample(ENTRY_TIMES_ET, num_entries)

        for entry_time in sorted(entry_times):
            # Skip if after cutoff
            hour = int(entry_time.split(':')[0])
            if hour >= CUTOFF_HOUR:
                continue

            # Decide strategy first (need to know risk before position sizing)
            distance_to_pin = abs(gex_pin - spx)

            if distance_to_pin < 10:
                # Very close to pin: GEX PIN spread
                strategy = 'GEX'
                strikes = f"{gex_pin:.0f}"
                entry_credit = random.uniform(2.00, 3.00)
                # GEX spread: $5 wide (pin ± 5), ~$2.50 avg credit
                # Max risk = ($5 - $2.50) * 100 = $250
                max_risk = 250
                exit_credit, pl_per_contract, duration, reason, is_win = simulate_gex_trade(entry_credit, spx, vix)
            else:
                # Further from pin: Check for OTM opportunity
                if random.random() < 0.40:  # 40% chance for OTM
                    strategy = 'OTM-SS'

                    # Determine direction
                    if gex_pin > spx:
                        direction = 'BULLISH'
                        side = 'PUT'
                        short_strike = round((spx - 50) / 5) * 5
                        long_strike = short_strike - 10
                    else:
                        direction = 'BEARISH'
                        side = 'CALL'
                        short_strike = round((spx + 50) / 5) * 5
                        long_strike = short_strike + 10

                    strikes = f"{short_strike:.0f}/{long_strike:.0f}"
                    distance_otm = abs(short_strike - spx)
                    entry_credit = random.uniform(0.30, 1.50)
                    # OTM spread: $10 wide, ~$1.00 avg credit
                    # Max risk = ($10 - $1.00) * 100 = $900 (conservative)
                    max_risk = 900
                    exit_credit, pl_per_contract, duration, reason, is_win = simulate_single_sided_trade(entry_credit, distance_otm, vix)
                else:
                    # GEX spread
                    strategy = 'GEX'
                    strikes = f"{gex_pin:.0f}"
                    entry_credit = random.uniform(2.00, 3.00)
                    # GEX spread: $5 wide (pin ± 5), ~$2.50 avg credit
                    # Max risk = ($5 - $2.50) * 100 = $250
                    max_risk = 250
                    exit_credit, pl_per_contract, duration, reason, is_win = simulate_gex_trade(entry_credit, spx, vix)

            # Calculate position size using Half-Kelly
            position_size = calculate_position_size(account_balance, trades_history, max_risk)

            # Skip trade if safety halt triggered
            if position_size == 0:
                break

            # Scale P/L by position size
            total_pl = pl_per_contract * position_size

            # Update account balance
            account_balance += total_pl

            # Record trade
            trade = {
                'id': trade_id,
                'date': date.date(),
                'time': entry_time,
                'strategy': strategy,
                'spx': spx,
                'vix': vix,
                'strikes': strikes,
                'entry_credit': entry_credit,
                'exit_credit': exit_credit,
                'pl': total_pl,
                'pl_per_contract': pl_per_contract,
                'position_size': position_size,
                'duration_min': duration,
                'reason': reason,
                'wl': 'WIN' if is_win else 'LOSS',
                'balance': account_balance
            }
            trades.append(trade)
            trades_history.append({'pl': pl_per_contract, 'win': is_win})
            trade_id += 1

    return pd.DataFrame(trades), market_data


def generate_report(trades_df, market_data):
    """Generate comprehensive backtest report."""
    print("=" * 180)
    print("1-YEAR SIMULATED BACKTEST: GEX + SINGLE-SIDED OTM STRATEGY")
    print("=" * 180)
    print()

    # Summary statistics
    total_trades = len(trades_df)
    winners = len(trades_df[trades_df['wl'] == 'WIN'])
    losers = len(trades_df[trades_df['wl'] == 'LOSS'])
    total_pnl = trades_df['pl'].sum()
    win_rate = (winners / total_trades * 100) if total_trades > 0 else 0

    # Profit factor
    gross_profit = trades_df[trades_df['pl'] > 0]['pl'].sum()
    gross_loss = abs(trades_df[trades_df['pl'] <= 0]['pl'].sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else 999

    # Account metrics
    starting = STARTING_CAPITAL
    ending = trades_df.iloc[-1]['balance'] if len(trades_df) > 0 else starting
    total_return = ((ending - starting) / starting * 100)

    print(f"PERIOD: {market_data['date'].min().date()} to {market_data['date'].max().date()} ({TRADING_DAYS} trading days)")
    print()
    print(f"ACCOUNT:")
    print(f"  Starting Capital:  ${starting:,}")
    print(f"  Ending Balance:    ${ending:,.0f}")
    print(f"  Total Return:      {total_return:+.1f}%")
    print()
    print(f"PERFORMANCE:")
    print(f"  Total Trades:      {total_trades}")
    print(f"  Winners:           {winners} ({win_rate:.1f}%)")
    print(f"  Losers:            {losers}")
    print(f"  Total P/L:         ${total_pnl:,.0f}")
    print(f"  Avg P/L/Trade:     ${total_pnl/total_trades:.0f}")
    print(f"  Profit Factor:     {pf:.2f}")
    print()

    # Avg winner/loser
    avg_win = trades_df[trades_df['pl'] > 0]['pl'].mean()
    avg_loss = trades_df[trades_df['pl'] <= 0]['pl'].mean()
    print(f"  Avg Winner:        ${avg_win:.0f}")
    print(f"  Avg Loser:         ${avg_loss:.0f}")
    print(f"  Win/Loss Ratio:    {abs(avg_win/avg_loss):.2f}")
    print()

    # Max drawdown
    trades_df['cumulative_pnl'] = trades_df['pl'].cumsum()
    trades_df['peak'] = trades_df['cumulative_pnl'].cumsum().max()
    trades_df['drawdown'] = trades_df['cumulative_pnl'] - trades_df['peak']
    max_dd = trades_df['drawdown'].min()
    print(f"  Max Drawdown:      ${max_dd:.0f}")
    print()

    # Strategy breakdown
    print("STRATEGY BREAKDOWN:")
    print("-" * 80)
    for strat in trades_df['strategy'].unique():
        strat_df = trades_df[trades_df['strategy'] == strat]
        strat_trades = len(strat_df)
        strat_winners = len(strat_df[strat_df['wl'] == 'WIN'])
        strat_wr = (strat_winners / strat_trades * 100) if strat_trades > 0 else 0
        strat_pnl = strat_df['pl'].sum()
        strat_avg = strat_pnl / strat_trades if strat_trades > 0 else 0
        print(f"  {strat:<8} | Trades: {strat_trades:>4} | WR: {strat_wr:>5.1f}% | Total P/L: ${strat_pnl:>8,.0f} | Avg: ${strat_avg:>6.0f}")
    print()

    # Print horizontal trade table (last 30 trades)
    print("=" * 180)
    print("RECENT TRADES (LAST 30)")
    print("=" * 180)
    print(f"{'#':<5} {'Strat':<8} {'Date':<11} {'Time':<6} {'SPX':<9} {'VIX':<6} {'Strikes':<20} {'Entry':<7} {'Exit':<7} {'P/L':<9} {'Dur':<8} {'Exit Reason':<40} {'W/L':<5} {'Pos':<4}")
    print("-" * 180)

    for _, row in trades_df.tail(30).iterrows():
        duration_str = f"{row['duration_min']}m" if row['duration_min'] < 60 else f"{row['duration_min']//60}h {row['duration_min']%60}m"
        print(f"{row['id']:<5} {row['strategy']:<8} {row['date']!s:<11} {row['time']:<6} ${row['spx']:<8.2f} {row['vix']:<6.2f} {row['strikes']:<20} ${row['entry_credit']:<6.2f} ${row['exit_credit']:<6.2f} ${row['pl']:<8.0f} {duration_str:<8} {row['reason']:<40} {row['wl']:<5} {row['position_size']:<4}")

    print("=" * 180)
    print()

    # Monthly performance
    trades_df['month'] = pd.to_datetime(trades_df['date']).dt.to_period('M')
    monthly = trades_df.groupby('month').agg({
        'pl': 'sum',
        'id': 'count',
        'wl': lambda x: (x == 'WIN').sum() / len(x) * 100
    }).rename(columns={'id': 'trades', 'wl': 'win_rate'})

    print("MONTHLY PERFORMANCE:")
    print("-" * 60)
    print(f"{'Month':<12} {'Trades':>8} {'Win Rate':>10} {'P/L':>12}")
    print("-" * 60)
    for month, row in monthly.iterrows():
        print(f"{month!s:<12} {row['trades']:>8.0f} {row['win_rate']:>9.1f}% ${row['pl']:>10,.0f}")
    print("-" * 60)
    print(f"{'TOTAL':<12} {monthly['trades'].sum():>8.0f} {trades_df[trades_df['wl']=='WIN'].shape[0]/len(trades_df)*100:>9.1f}% ${monthly['pl'].sum():>10,.0f}")
    print()


if __name__ == '__main__':
    print("Starting 1-year backtest simulation...")
    print()

    trades_df, market_data = run_simulation()

    if len(trades_df) > 0:
        generate_report(trades_df, market_data)

        # Save to CSV
        output_file = '/root/gamma/BACKTEST_1YEAR_SIMULATION.csv'
        trades_df.to_csv(output_file, index=False)
        print(f"Trade data saved to: {output_file}")
    else:
        print("No trades generated!")
