#!/usr/bin/env python3
"""
Stop Loss Optimization Script for GEX Scalper

Tests various stop loss strategies:
1. Fixed percentage stops (5% to 30%)
2. ATR-based stops (volatility-adjusted)
3. Time-based stops (different grace periods)
4. VIX-based stops (regime-dependent)

Goal: Find optimal stop loss that maximizes:
- Net P/L
- Profit factor
- Risk-adjusted returns (Sharpe/Sortino)
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pytz
import multiprocessing as mp
from functools import partial

# ============================================================================
#                           CONFIGURATION
# ============================================================================

# Backtest period
LOOKBACK_DAYS = 750  # ~3 years

# Stop loss test ranges
FIXED_STOP_TESTS = [0.05, 0.075, 0.10, 0.125, 0.15, 0.175, 0.20, 0.25, 0.30]
GRACE_PERIOD_TESTS = [0, 120, 180, 240, 300, 360, 420, 480]  # seconds
ATR_MULTIPLIER_TESTS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]

# Progressive hold parameters (from production)
PROGRESSIVE_HOLD_PROFIT_PCT = 0.80
PROGRESSIVE_HOLD_VIX_MAX = 17.0
PROGRESSIVE_HOLD_MIN_TIME_LEFT_HOURS = 1.0
PROGRESSIVE_HOLD_OTM_POINTS = 8

# Entry parameters (from production)
ENTRY_TIMES = ['09:36', '10:00', '11:00', '12:00']
VIX_MAX = 20
MIN_CREDIT = 1.00
PROFIT_TARGET_HIGH = 0.50
PROFIT_TARGET_MEDIUM = 0.60

# Realistic adjustments
SLIPPAGE_PER_TRADE = 6.03
COMMISSION_PER_TRADE = 1.32
GAP_RISK_RATE = 0.02
GAP_LOSS = -500

# Autoscaling
STARTING_CAPITAL = 25000
MAX_CONTRACTS = 10
STOP_LOSS_PER_CONTRACT = 150

# ============================================================================
#                           HELPER FUNCTIONS
# ============================================================================

def calculate_atr(df, period=14):
    """Calculate Average True Range"""
    high = df['High']
    low = df['Low']
    close = df['SPX'].shift(1)  # Use SPX column

    tr1 = high - low
    tr2 = abs(high - close)
    tr3 = abs(low - close)

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()

    return atr

def calculate_ivr(vix_series):
    """Calculate Implied Volatility Rank (0-100)"""
    rolling_252 = vix_series.rolling(window=252, min_periods=50)
    vix_min = rolling_252.min()
    vix_max = rolling_252.max()

    ivr = 100 * (vix_series - vix_min) / (vix_max - vix_min + 0.0001)
    return ivr.fillna(0)

def get_gex_setup(row):
    """Determine GEX-based setup (CALL/PUT/IC)"""
    spx = row['SPX']
    ivr = row['IVR']

    # High IVR → Iron Condor
    if ivr >= 40:
        return 'IC', 'HIGH'

    # Medium IVR → Directional spreads
    elif ivr >= 20:
        # Simplified: alternate CALL/PUT based on day
        return np.random.choice(['CALL', 'PUT']), 'MEDIUM'

    # Low IVR → Directional spreads
    else:
        return np.random.choice(['CALL', 'PUT']), 'MEDIUM'

def simulate_trade_outcome(entry_credit, strategy, confidence, stop_loss_pct, grace_period_sec,
                          atr=None, atr_multiplier=None, vix=None):
    """
    Simulate a single trade outcome with given stop loss parameters

    Returns: (exit_reason, profit_pct, time_in_trade_min)
    """

    # Determine stop loss trigger level
    if atr is not None and atr_multiplier is not None:
        # ATR-based stop loss
        # Convert ATR to percentage of entry credit
        # ATR is in SPX points, we need to convert to option value change
        # Rough estimate: 1 SPX point ≈ $0.50 option value change for 10-point spreads
        atr_in_dollars = atr * 0.50
        stop_loss_pct_actual = min(0.40, atr_in_dollars / entry_credit * atr_multiplier)
    else:
        # Fixed percentage stop loss
        stop_loss_pct_actual = stop_loss_pct

    # Simulate trade path (simplified Monte Carlo)
    # Based on historical data: 58.2% win rate

    is_winner = np.random.random() < 0.582

    if is_winner:
        # Winner - check for progressive hold
        peak_profit_pct = np.random.uniform(0.40, 0.95)

        # Progressive hold criteria
        progressive_hold = (
            peak_profit_pct >= PROGRESSIVE_HOLD_PROFIT_PCT and
            vix < PROGRESSIVE_HOLD_VIX_MAX and
            np.random.random() < 0.30  # Simplified time/OTM check
        )

        if progressive_hold:
            # Hold to expiration
            final_profit_pct = 1.0  # 100% profit (worthless)
            exit_reason = 'Hold: Worthless'
            time_in_trade = np.random.uniform(180, 390)  # 3-6.5 hours
        else:
            # Hit profit target
            target = PROFIT_TARGET_HIGH if confidence == 'HIGH' else PROFIT_TARGET_MEDIUM
            final_profit_pct = min(peak_profit_pct, target)
            exit_reason = f'TP ({final_profit_pct*100:.0f}%)'
            time_in_trade = np.random.uniform(30, 240)  # 0.5-4 hours

    else:
        # Loser - check for stop loss
        worst_loss_pct = np.random.uniform(-0.05, -0.50)

        # Emergency stop (40%) always triggers immediately
        if worst_loss_pct <= -0.40:
            final_profit_pct = -0.40
            exit_reason = 'Emergency SL'
            time_in_trade = np.random.uniform(5, 60)  # 5-60 min

        # Check if stop loss triggered
        elif worst_loss_pct <= -stop_loss_pct_actual:
            # Check grace period
            trade_age_sec = np.random.uniform(0, 300)

            if trade_age_sec < grace_period_sec:
                # In grace period - let it ride
                # Sometimes it recovers, sometimes it gets worse
                if np.random.random() < 0.30:
                    # Recovered
                    final_profit_pct = np.random.uniform(-0.05, 0.20)
                    exit_reason = 'Recovered (grace)'
                    time_in_trade = grace_period_sec / 60 + np.random.uniform(30, 120)
                else:
                    # Got worse
                    final_profit_pct = worst_loss_pct
                    exit_reason = f'SL (after grace)'
                    time_in_trade = grace_period_sec / 60 + np.random.uniform(10, 60)
            else:
                # Stop loss hit after grace period
                final_profit_pct = -stop_loss_pct_actual
                exit_reason = f'SL ({stop_loss_pct_actual*100:.0f}%)'
                time_in_trade = grace_period_sec / 60 + np.random.uniform(5, 30)

        else:
            # Small loss, held to expiration or closed at loss
            final_profit_pct = worst_loss_pct
            exit_reason = 'Hold: ITM'
            time_in_trade = np.random.uniform(180, 390)

    return exit_reason, final_profit_pct, time_in_trade

def run_backtest_with_stop_loss(df, stop_loss_pct, grace_period_sec=300,
                                 atr_based=False, atr_multiplier=None,
                                 vix_based=False):
    """
    Run backtest with specific stop loss parameters

    Returns: dict with performance metrics
    """

    trades = []

    for idx, row in df.iterrows():
        date = row['Date']
        spx = row['SPX']
        vix = row['VIX']
        ivr = row['IVR']
        atr = row.get('ATR', None)

        # Skip weekends
        if date.weekday() >= 5:
            continue

        # Skip high VIX days
        if vix >= VIX_MAX:
            continue

        # Entry times
        for entry_time in ENTRY_TIMES:
            # Get GEX setup
            strategy, confidence = get_gex_setup(row)

            # Simulate entry credit (based on historical avg)
            if strategy == 'IC':
                entry_credit = np.random.uniform(5.00, 8.00)
            else:
                entry_credit = np.random.uniform(2.00, 4.00)

            # Skip if below minimum credit
            if entry_credit < MIN_CREDIT:
                continue

            # VIX-based stop loss adjustment
            if vix_based:
                if vix < 15:
                    stop_loss_pct_adj = stop_loss_pct * 0.8  # Tighter in low VIX
                elif vix > 18:
                    stop_loss_pct_adj = stop_loss_pct * 1.2  # Wider in high VIX
                else:
                    stop_loss_pct_adj = stop_loss_pct
            else:
                stop_loss_pct_adj = stop_loss_pct

            # Simulate trade
            exit_reason, profit_pct, time_in_trade = simulate_trade_outcome(
                entry_credit, strategy, confidence, stop_loss_pct_adj, grace_period_sec,
                atr=atr if atr_based else None,
                atr_multiplier=atr_multiplier,
                vix=vix
            )

            # Calculate P/L
            pnl_per_contract = entry_credit * profit_pct * 100

            # Slippage and commissions
            pnl_per_contract -= (SLIPPAGE_PER_TRADE + COMMISSION_PER_TRADE)

            trades.append({
                'date': date,
                'entry_time': entry_time,
                'strategy': strategy,
                'confidence': confidence,
                'vix': vix,
                'ivr': ivr,
                'entry_credit': entry_credit,
                'exit_reason': exit_reason,
                'profit_pct': profit_pct,
                'pnl_per_contract': pnl_per_contract,
                'time_in_trade': time_in_trade,
                'stop_loss_pct': stop_loss_pct_adj
            })

    # Convert to DataFrame
    trades_df = pd.DataFrame(trades)

    if len(trades_df) == 0:
        return None

    # Apply gap risk (2% catastrophic)
    gap_mask = np.random.random(len(trades_df)) < GAP_RISK_RATE
    trades_df.loc[gap_mask, 'pnl_per_contract'] = GAP_LOSS
    trades_df.loc[gap_mask, 'exit_reason'] = 'Gap (realistic)'

    # Calculate metrics
    total_trades = len(trades_df)
    winners = trades_df[trades_df['pnl_per_contract'] > 0]
    losers = trades_df[trades_df['pnl_per_contract'] <= 0]

    win_rate = len(winners) / total_trades if total_trades > 0 else 0
    avg_win = winners['pnl_per_contract'].mean() if len(winners) > 0 else 0
    avg_loss = losers['pnl_per_contract'].mean() if len(losers) > 0 else 0

    total_pnl = trades_df['pnl_per_contract'].sum()

    # Profit factor
    total_wins = winners['pnl_per_contract'].sum() if len(winners) > 0 else 0
    total_losses = abs(losers['pnl_per_contract'].sum()) if len(losers) > 0 else 1
    profit_factor = total_wins / total_losses if total_losses > 0 else 0

    # Max drawdown
    cumulative_pnl = trades_df['pnl_per_contract'].cumsum()
    running_max = cumulative_pnl.expanding().max()
    drawdown = cumulative_pnl - running_max
    max_drawdown = drawdown.min()

    # Sharpe/Sortino
    returns = trades_df['pnl_per_contract']
    sharpe = returns.mean() / returns.std() if returns.std() > 0 else 0
    downside_returns = returns[returns < 0]
    sortino = returns.mean() / downside_returns.std() if len(downside_returns) > 0 and downside_returns.std() > 0 else 0

    # Stop loss hit rate
    sl_trades = trades_df[trades_df['exit_reason'].str.contains('SL', na=False)]
    sl_rate = len(sl_trades) / total_trades if total_trades > 0 else 0

    return {
        'stop_loss_pct': stop_loss_pct,
        'grace_period_sec': grace_period_sec,
        'atr_based': atr_based,
        'atr_multiplier': atr_multiplier,
        'vix_based': vix_based,
        'total_trades': total_trades,
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'total_pnl': total_pnl,
        'profit_factor': profit_factor,
        'sharpe': sharpe,
        'sortino': sortino,
        'max_drawdown': max_drawdown,
        'sl_hit_rate': sl_rate,
        'avg_time_in_trade': trades_df['time_in_trade'].mean()
    }

# ============================================================================
#                           MAIN OPTIMIZATION
# ============================================================================

def test_stop_loss_config(args):
    """Wrapper for parallel processing"""
    df, config = args
    return run_backtest_with_stop_loss(df, **config)

def main():
    print("=" * 70)
    print("STOP LOSS OPTIMIZATION FOR GEX SCALPER")
    print("=" * 70)
    print()

    # Fetch data
    print("Fetching historical data...")
    end_date = datetime.now()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)

    spy = yf.download("SPY", start=start_date, end=end_date, progress=False, auto_adjust=True)
    vix = yf.download("^VIX", start=start_date, end=end_date, progress=False, auto_adjust=True)

    # Build DataFrame
    df = pd.DataFrame({
        'Date': spy.index,
        'SPX': spy['Close'].values.flatten() * 10,  # SPY → SPX approximation
        'High': spy['High'].values.flatten() * 10,
        'Low': spy['Low'].values.flatten() * 10,
        'VIX': vix['Close'].values.flatten()
    }).dropna()

    df['ATR'] = calculate_atr(df, period=14)
    df['IVR'] = calculate_ivr(df['VIX'])

    df = df.dropna().reset_index(drop=True)

    print(f"Loaded {len(df)} trading days")
    print(f"Date range: {df['Date'].min().date()} to {df['Date'].max().date()}")
    print(f"SPX range: {df['SPX'].min():.0f} - {df['SPX'].max():.0f}")
    print(f"VIX range: {df['VIX'].min():.1f} - {df['VIX'].max():.1f}")
    print()

    # Test configurations
    configs = []

    # 1. Fixed percentage stops (baseline)
    print("Building test configurations...")
    for stop_pct in FIXED_STOP_TESTS:
        for grace in [300]:  # Use production grace period
            configs.append({
                'stop_loss_pct': stop_pct,
                'grace_period_sec': grace,
                'atr_based': False,
                'atr_multiplier': None,
                'vix_based': False
            })

    # 2. ATR-based stops
    for atr_mult in ATR_MULTIPLIER_TESTS:
        configs.append({
            'stop_loss_pct': 0.10,  # Baseline
            'grace_period_sec': 300,
            'atr_based': True,
            'atr_multiplier': atr_mult,
            'vix_based': False
        })

    # 3. VIX-based stops (regime-dependent)
    for stop_pct in [0.075, 0.10, 0.125, 0.15]:
        configs.append({
            'stop_loss_pct': stop_pct,
            'grace_period_sec': 300,
            'atr_based': False,
            'atr_multiplier': None,
            'vix_based': True
        })

    # 4. Grace period variations (using current 10% stop)
    for grace in GRACE_PERIOD_TESTS:
        configs.append({
            'stop_loss_pct': 0.10,
            'grace_period_sec': grace,
            'atr_based': False,
            'atr_multiplier': None,
            'vix_based': False
        })

    print(f"Testing {len(configs)} configurations...")
    print()

    # Run in parallel
    with mp.Pool(processes=min(mp.cpu_count(), 30)) as pool:
        results = pool.map(test_stop_loss_config, [(df, config) for config in configs])

    # Filter out None results
    results = [r for r in results if r is not None]

    # Convert to DataFrame
    results_df = pd.DataFrame(results)

    # Sort by total P/L
    results_df = results_df.sort_values('total_pnl', ascending=False)

    # Display results
    print("=" * 70)
    print("OPTIMIZATION RESULTS - TOP 20 CONFIGURATIONS")
    print("=" * 70)
    print()

    print(f"{'Rank':<5} {'Type':<12} {'Stop%':<7} {'Grace':<7} {'ATR':<6} {'VIX':<5} "
          f"{'P/L':<10} {'PF':<6} {'WR%':<6} {'SL%':<6} {'Sortino':<8}")
    print("-" * 120)

    for idx, row in results_df.head(20).iterrows():
        config_type = 'ATR-based' if row['atr_based'] else ('VIX-based' if row['vix_based'] else 'Fixed')
        stop_display = f"{row['stop_loss_pct']*100:.1f}%" if not row['atr_based'] else f"ATR×{row['atr_multiplier']:.1f}"
        grace_display = f"{row['grace_period_sec']:.0f}s"
        atr_display = f"{row['atr_multiplier']:.2f}" if row['atr_based'] else "-"
        vix_display = "Yes" if row['vix_based'] else "No"

        print(f"{len(results_df) - idx:<5} {config_type:<12} {stop_display:<7} {grace_display:<7} {atr_display:<6} {vix_display:<5} "
              f"${row['total_pnl']:>9,.0f} {row['profit_factor']:>5.2f} {row['win_rate']*100:>5.1f} "
              f"{row['sl_hit_rate']*100:>5.1f} {row['sortino']:>7.2f}")

    print()

    # Best configuration
    best = results_df.iloc[0]

    print("=" * 70)
    print("BEST CONFIGURATION DETAILS")
    print("=" * 70)
    print()

    if best['atr_based']:
        print(f"Type:                ATR-Based Stop Loss")
        print(f"ATR Multiplier:      {best['atr_multiplier']:.2f}×")
    elif best['vix_based']:
        print(f"Type:                VIX-Based Stop Loss (Regime-Dependent)")
        print(f"Base Stop Loss:      {best['stop_loss_pct']*100:.1f}%")
    else:
        print(f"Type:                Fixed Percentage")
        print(f"Stop Loss:           {best['stop_loss_pct']*100:.1f}%")

    print(f"Grace Period:        {best['grace_period_sec']:.0f} seconds")
    print()
    print(f"Total Trades:        {best['total_trades']:,}")
    print(f"Win Rate:            {best['win_rate']*100:.1f}%")
    print(f"Avg Winner:          ${best['avg_win']:.2f}")
    print(f"Avg Loser:           ${best['avg_loss']:.2f}")
    print()
    print(f"Total P/L:           ${best['total_pnl']:,.0f}")
    print(f"Profit Factor:       {best['profit_factor']:.2f}")
    print(f"Sharpe Ratio:        {best['sharpe']:.2f}")
    print(f"Sortino Ratio:       {best['sortino']:.2f}")
    print(f"Max Drawdown:        ${best['max_drawdown']:,.0f}")
    print()
    print(f"Stop Loss Hit Rate:  {best['sl_hit_rate']*100:.1f}%")
    print(f"Avg Time in Trade:   {best['avg_time_in_trade']:.0f} minutes")
    print()

    # Compare to current production (10% stop, 300s grace)
    current = results_df[
        (results_df['stop_loss_pct'] == 0.10) &
        (results_df['grace_period_sec'] == 300) &
        (~results_df['atr_based']) &
        (~results_df['vix_based'])
    ]

    if len(current) > 0:
        current = current.iloc[0]
        print("=" * 70)
        print("COMPARISON TO CURRENT PRODUCTION (10% stop, 300s grace)")
        print("=" * 70)
        print()

        improvement_pnl = ((best['total_pnl'] - current['total_pnl']) / abs(current['total_pnl']) * 100)
        improvement_pf = ((best['profit_factor'] - current['profit_factor']) / current['profit_factor'] * 100)

        print(f"Current P/L:         ${current['total_pnl']:,.0f}")
        print(f"Best P/L:            ${best['total_pnl']:,.0f}")
        print(f"Improvement:         {improvement_pnl:+.1f}%")
        print()
        print(f"Current PF:          {current['profit_factor']:.2f}")
        print(f"Best PF:             {best['profit_factor']:.2f}")
        print(f"Improvement:         {improvement_pf:+.1f}%")
        print()
        print(f"Current SL Rate:     {current['sl_hit_rate']*100:.1f}%")
        print(f"Best SL Rate:        {best['sl_hit_rate']*100:.1f}%")
        print(f"Change:              {(best['sl_hit_rate'] - current['sl_hit_rate'])*100:+.1f}pp")

    print()
    print("=" * 70)
    print("OPTIMIZATION COMPLETE")
    print("=" * 70)

    # Save results
    results_df.to_csv('/root/gamma/data/stop_loss_optimization_results.csv', index=False)
    print()
    print("Results saved to: /root/gamma/data/stop_loss_optimization_results.csv")

if __name__ == '__main__':
    main()
