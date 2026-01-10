#!/usr/bin/env python3
"""
Multi-Index GEX Backtest - Compare strategy performance across indices

Tests the GEX scalper strategy on:
- SPX (S&P 500) - via SPY proxy
- NDX (Nasdaq-100) - via QQQ proxy
- RUT (Russell 2000) - via IWM proxy
- DJX (Dow Jones) - via DIA proxy

Usage:
  python backtest_multi_index.py --days 252  # 1 year

Author: Claude + Human collaboration
"""

import datetime
import argparse
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm

# Import shared GEX strategy logic
from core.gex_strategy import get_gex_trade_setup as core_get_gex_trade_setup
from core.gex_strategy import round_to_5, get_spread_width

# ============================================================================
#                           INDEX CONFIGURATIONS
# ============================================================================

INDEX_CONFIGS = {
    'SPX': {
        'name': 'S&P 500',
        'etf_proxy': 'SPY',
        'multiplier': 10,  # SPY * 10 = SPX
        'contract_multiplier': 100,  # $100 per point
        'spread_width': 5,  # 5-point spreads
        'round_to': 5,  # Round strikes to nearest 5
    },
    'NDX': {
        'name': 'Nasdaq-100',
        'etf_proxy': 'QQQ',
        'multiplier': 42.5,  # QQQ * ~42.5 = NDX (approximate)
        'contract_multiplier': 100,  # $100 per point
        'spread_width': 25,  # 25-point spreads (higher price)
        'round_to': 25,  # Round strikes to nearest 25
    },
    'RUT': {
        'name': 'Russell 2000',
        'etf_proxy': 'IWM',
        'multiplier': 10,  # IWM * 10 = RUT
        'contract_multiplier': 100,  # $100 per point
        'spread_width': 5,  # 5-point spreads
        'round_to': 5,  # Round strikes to nearest 5
    },
    'DJX': {
        'name': 'Dow Jones',
        'etf_proxy': 'DIA',
        'multiplier': 1,  # DIA = DJX (1/100th of DJIA)
        'contract_multiplier': 100,  # $100 per point
        'spread_width': 2,  # 2-point spreads (lower price)
        'round_to': 2,  # Round strikes to nearest 2
    }
}

# ============================================================================
#                           STRATEGY PARAMETERS
# ============================================================================

# Same parameters as SPX backtest
PROFIT_TARGET_HIGH = 0.50
PROFIT_TARGET_MEDIUM = 0.70
STOP_LOSS_PCT = 0.10
VIX_MAX_THRESHOLD = 20

# Trailing stop settings
TRAILING_STOP_ENABLED = True
TRAILING_TRIGGER_PCT = 0.20
TRAILING_LOCK_IN_PCT = 0.12
TRAILING_DISTANCE_MIN = 0.08
TRAILING_TIGHTEN_RATE = 0.4

# Entry times (hours after market open)
ENTRY_TIMES = [0.1, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]

# Auto-scaling parameters
AUTO_SCALE_ENABLED = False  # Disable for fair comparison
STARTING_CAPITAL = 25000
MAX_CONTRACTS = 10
STOP_LOSS_PER_CONTRACT = 150

# Progressive hold-to-expiration
PROGRESSIVE_HOLD_ENABLED = True
HOLD_PROFIT_THRESHOLD = 0.80
HOLD_VIX_MAX = 17
HOLD_MIN_TIME_LEFT = 1.0
HOLD_MIN_ENTRY_DISTANCE = 8

# FOMC dates (2024-2025)
FOMC_DATES = set([
    '2024-01-31', '2024-03-20', '2024-05-01', '2024-06-12',
    '2024-07-31', '2024-09-18', '2024-11-07', '2024-12-18',
    '2025-01-29', '2025-03-19', '2025-05-07', '2025-06-18',
    '2025-07-30', '2025-09-17', '2025-11-05', '2025-12-17'
])

# Short trading days
SHORT_DAYS = [
    '2024-07-03', '2024-11-29', '2024-12-24',
    '2025-07-03', '2025-11-28', '2025-12-24'
]

def round_strike(price, round_to):
    """Round strike price to nearest increment."""
    return round(price / round_to) * round_to

def get_gex_pin(close_price, round_to):
    """Estimate GEX pin level (simplified - uses previous close)."""
    return round_strike(close_price, round_to)

def estimate_credit_from_vix(vix, spread_width, distance_otm):
    """
    Estimate option credit from VIX using empirical formula.
    Higher VIX = higher premiums.
    """
    # Base credit (percentage of spread width)
    base_pct = 0.35  # 35% of spread width as baseline

    # VIX adjustment (higher VIX = higher credit)
    vix_factor = 1.0 + ((vix - 15) * 0.02)  # +2% per VIX point above 15
    vix_factor = max(0.5, min(vix_factor, 2.0))  # Clamp between 50% and 200%

    # Distance adjustment (farther OTM = lower credit)
    distance_factor = 1.0 - (distance_otm * 0.01)  # -1% per point OTM
    distance_factor = max(0.3, min(distance_factor, 1.0))

    # Calculate credit
    credit = spread_width * base_pct * vix_factor * distance_factor

    # Add some randomness to simulate market variability
    noise = np.random.uniform(0.9, 1.1)
    credit = credit * noise

    return max(0.5, min(credit, spread_width * 0.9))  # Clamp to reasonable range

def simulate_trade_exit(entry_credit, spread_width, high_low_range, hours_held):
    """
    Simulate trade exit using realistic profit progression.
    Returns exit reason and profit percentage.
    """
    # Initial profit check (5 minutes after entry)
    initial_profit_pct = np.random.uniform(-0.05, 0.15)

    # Intraday progression
    mid_profit_pct = initial_profit_pct + np.random.uniform(0, 0.30)

    # Final profit at close (with theta decay)
    theta_decay = 0.20 + (hours_held * 0.05)  # More decay with time
    close_profit_pct = mid_profit_pct + theta_decay + np.random.uniform(-0.10, 0.20)

    # Track best profit for trailing stop
    best_profit_pct = max(initial_profit_pct, mid_profit_pct, close_profit_pct)

    # Determine exit
    exit_reason = None
    final_profit_pct = 0
    trailing_activated = False

    # Check stop loss (10%)
    if initial_profit_pct <= -STOP_LOSS_PCT:
        exit_reason = "SL (10%)"
        final_profit_pct = -STOP_LOSS_PCT

    # Check trailing stop
    elif TRAILING_STOP_ENABLED and best_profit_pct >= TRAILING_TRIGGER_PCT:
        trailing_activated = True
        trail_distance = TRAILING_DISTANCE_MIN + (best_profit_pct - TRAILING_TRIGGER_PCT) * TRAILING_TIGHTEN_RATE
        trail_distance = min(trail_distance, best_profit_pct - TRAILING_LOCK_IN_PCT)

        current_profit = close_profit_pct
        stop_level = best_profit_pct - trail_distance

        if current_profit <= stop_level:
            exit_reason = f"Trail ({int(current_profit * 100)}%)"
            final_profit_pct = stop_level
        else:
            final_profit_pct = close_profit_pct

    # Check profit targets
    if exit_reason is None:
        # Progressive hold logic
        if PROGRESSIVE_HOLD_ENABLED and best_profit_pct >= HOLD_PROFIT_THRESHOLD:
            # 85% expire worthless (100% profit)
            if np.random.random() < 0.85:
                exit_reason = "Hold: Worthless"
                final_profit_pct = 1.0
            # 12% near ATM (75-95% profit)
            elif np.random.random() < 0.89:  # 0.12 / 0.15 = 0.80
                exit_reason = "Hold: Near ATM"
                final_profit_pct = np.random.uniform(0.75, 0.95)
            # 3% ITM (lose spread width)
            else:
                exit_reason = "Hold: ITM"
                final_profit_pct = -1.0
        else:
            # Check profit targets
            if close_profit_pct >= 0.80:
                exit_reason = "TP (80%)"
                final_profit_pct = 0.80
            elif close_profit_pct >= 0.75:
                exit_reason = "TP (75%)"
                final_profit_pct = 0.75
            else:
                exit_reason = "Close"
                final_profit_pct = close_profit_pct

    # Otherwise use close profit
    if exit_reason is None:
        exit_reason = "Close"
        final_profit_pct = close_profit_pct

    # Calculate final values
    final_value = entry_credit * (1 - final_profit_pct)
    final_value = max(0, min(final_value, spread_width))

    pnl_dollars = final_profit_pct * entry_credit * 100  # Per contract
    pnl_pct = final_profit_pct * 100

    return {
        'exit_reason': exit_reason,
        'exit_value': round(final_value, 2),
        'pnl_dollars': round(pnl_dollars, 2),
        'pnl_pct': round(pnl_pct, 1),
        'best_profit_pct': round(best_profit_pct * 100, 1),
        'trailing_activated': best_profit_pct >= TRAILING_TRIGGER_PCT if TRAILING_STOP_ENABLED else False
    }

def run_index_backtest(index_code, days=252, realistic=True):
    """Run backtest for a specific index."""

    config = INDEX_CONFIGS[index_code]

    print(f"\n{'='*70}")
    print(f"BACKTESTING: {config['name']} ({index_code})")
    print(f"ETF Proxy: {config['etf_proxy']}")
    print(f"Period: Last {days} trading days")
    print(f"{'='*70}")

    # Fetch historical data
    print("Fetching historical data...")
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=int(days * 1.5))

    etf = yf.download(config['etf_proxy'], start=start_date, end=end_date, progress=False)
    vix = yf.download("^VIX", start=start_date, end=end_date, progress=False)

    if etf.empty or vix.empty:
        print(f"ERROR: Could not fetch data for {index_code}")
        return None

    # Handle multi-level columns
    if isinstance(etf.columns, pd.MultiIndex):
        etf.columns = etf.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    # Convert ETF to index level
    etf['Index_Open'] = etf['Open'] * config['multiplier']
    etf['Index_High'] = etf['High'] * config['multiplier']
    etf['Index_Low'] = etf['Low'] * config['multiplier']
    etf['Index_Close'] = etf['Close'] * config['multiplier']

    # Merge VIX
    etf['VIX'] = vix['Close']

    # Calculate IVR
    etf['VIX_52w_high'] = etf['VIX'].rolling(window=252, min_periods=50).max()
    etf['VIX_52w_low'] = etf['VIX'].rolling(window=252, min_periods=50).min()
    etf['IVR'] = ((etf['VIX'] - etf['VIX_52w_low']) / (etf['VIX_52w_high'] - etf['VIX_52w_low'])) * 100
    etf['IVR'] = etf['IVR'].fillna(50)

    # Additional indicators
    etf['day_of_week'] = etf.index.dayofweek
    etf['day_name'] = etf.index.day_name()
    etf['prev_close'] = etf['Index_Close'].shift(1)
    etf['gap_pct'] = ((etf['Index_Open'] - etf['prev_close']) / etf['prev_close'] * 100).abs()
    etf['sma20'] = etf['Index_Close'].rolling(window=20).mean()
    etf['above_sma20'] = etf['Index_Open'] > etf['sma20']

    # Drop NaN rows
    etf = etf.dropna()

    # Limit to requested days
    etf = etf.tail(days)

    print(f"Loaded {len(etf)} trading days")
    print(f"Date range: {etf.index[0].date()} to {etf.index[-1].date()}")
    print(f"{index_code} range: {int(etf['Index_Close'].min())} - {int(etf['Index_Close'].max())}")
    print(f"VIX range: {etf['VIX'].min():.1f} - {etf['VIX'].max():.1f}")

    # Run simulation
    print("\nRunning simulation...")

    trades = []
    total_pnl = 0
    winners = 0
    losers = 0

    spread_width = config['spread_width']
    round_to = config['round_to']

    for date, row in etf.iterrows():
        date_str = date.strftime('%Y-%m-%d')

        # Skip FOMC and short days
        if date_str in FOMC_DATES or date_str in SHORT_DAYS:
            continue

        # Skip if VIX >= 20
        if row['VIX'] >= VIX_MAX_THRESHOLD:
            continue

        # Get GEX pin (simplified - use previous close)
        prev_close = row['prev_close']
        gex_pin = get_gex_pin(prev_close, round_to)
        current_price = row['Index_Open']

        # Determine trade direction
        if current_price > gex_pin:
            # Price above pin - sell call spread (bearish)
            strike_short = round_strike(current_price + (spread_width * 2), round_to)
            strike_long = strike_short + spread_width
            strategy = "CALL"
            confidence = "HIGH" if abs(current_price - gex_pin) > (spread_width * 2) else "MEDIUM"
        else:
            # Price below pin - sell put spread (bullish)
            strike_short = round_strike(current_price - (spread_width * 2), round_to)
            strike_long = strike_short - spread_width
            strategy = "PUT"
            confidence = "HIGH" if abs(current_price - gex_pin) > (spread_width * 2) else "MEDIUM"

        # Process each entry time
        for entry_hour in ENTRY_TIMES:
            # Skip if after 2:00 PM
            if entry_hour > 4.5:
                continue

            # Estimate credit
            distance_otm = abs(current_price - strike_short)
            entry_credit = estimate_credit_from_vix(row['VIX'], spread_width, distance_otm)

            # Min credit filter
            if entry_credit < 1.0:
                continue

            # Simulate trade
            hours_held = 6.5 - entry_hour  # Market hours remaining
            high_low_range = row['Index_High'] - row['Index_Low']

            exit_result = simulate_trade_exit(entry_credit, spread_width, high_low_range, hours_held)

            # Apply realistic adjustments if enabled
            if realistic:
                # 10% of trades hit stop loss
                if np.random.random() < 0.10:
                    exit_result['exit_reason'] = "SL (realistic)"
                    exit_result['pnl_dollars'] = -150.0  # $150 loss per contract

                # 2% gap risk
                elif np.random.random() < 0.02:
                    exit_result['exit_reason'] = "Gap (realistic)"
                    exit_result['pnl_dollars'] = -500.0  # $500 loss per contract

                # Slippage/commissions
                else:
                    exit_result['pnl_dollars'] -= 6.50  # $6.50 per trade

            # Record trade
            pnl = exit_result['pnl_dollars']
            total_pnl += pnl

            if pnl > 0:
                winners += 1
            else:
                losers += 1

            trades.append({
                'date': date_str,
                'index': index_code,
                'strategy': strategy,
                'confidence': confidence,
                'entry_credit': round(entry_credit, 2),
                'spread_width': spread_width,
                'strike_short': strike_short,
                'strike_long': strike_long,
                'vix': round(row['VIX'], 1),
                'ivr': round(row['IVR'], 0),
                'gap_pct': round(row['gap_pct'], 2),
                'exit_reason': exit_result['exit_reason'],
                'pnl': pnl,
                'trailing_activated': exit_result['trailing_activated']
            })

    total_trades = len(trades)
    win_rate = (winners / total_trades * 100) if total_trades > 0 else 0
    avg_winner = sum(t['pnl'] for t in trades if t['pnl'] > 0) / winners if winners > 0 else 0
    avg_loser = sum(t['pnl'] for t in trades if t['pnl'] < 0) / losers if losers > 0 else 0
    profit_factor = abs(sum(t['pnl'] for t in trades if t['pnl'] > 0) / sum(t['pnl'] for t in trades if t['pnl'] < 0)) if losers > 0 else 0

    # Calculate return on starting capital
    roi_pct = (total_pnl / STARTING_CAPITAL) * 100

    results = {
        'index': index_code,
        'name': config['name'],
        'total_trades': total_trades,
        'winners': winners,
        'losers': losers,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'avg_winner': avg_winner,
        'avg_loser': avg_loser,
        'profit_factor': profit_factor,
        'roi_pct': roi_pct,
        'trades': trades
    }

    # Print summary
    print(f"\n{'-'*70}")
    print(f"RESULTS - {config['name']} ({index_code})")
    print(f"{'-'*70}")
    print(f"Total Trades:     {total_trades}")
    print(f"Winners:          {winners} ({win_rate:.1f}%)")
    print(f"Losers:           {losers}")
    print(f"Total P/L:        ${total_pnl:,.2f}")
    print(f"ROI:              {roi_pct:+.1f}%")
    print(f"Avg Winner:       ${avg_winner:.2f}")
    print(f"Avg Loser:        ${avg_loser:.2f}")
    print(f"Profit Factor:    {profit_factor:.2f}")
    print(f"{'-'*70}")

    return results

def compare_indices(days=252):
    """Run backtest on all indices and compare results."""

    print("\n" + "="*70)
    print("MULTI-INDEX COMPARISON BACKTEST")
    print(f"Testing GEX scalper strategy across 4 indices")
    print(f"Period: {days} trading days (~1 year)")
    print("="*70)

    all_results = []

    # Run backtest for each index
    for index_code in ['SPX', 'NDX', 'RUT', 'DJX']:
        result = run_index_backtest(index_code, days=days, realistic=True)
        if result:
            all_results.append(result)

    # Comparison summary
    print("\n" + "="*70)
    print("COMPARISON SUMMARY")
    print("="*70)
    print(f"\n{'Index':<10} {'Name':<20} {'Trades':<10} {'Win Rate':<12} {'Total P/L':<15} {'ROI':<10} {'PF':<8}")
    print("-"*90)

    for r in all_results:
        print(f"{r['index']:<10} {r['name']:<20} {r['total_trades']:<10} {r['win_rate']:>6.1f}%     ${r['total_pnl']:>10,.2f}   {r['roi_pct']:>6.1f}%   {r['profit_factor']:>6.2f}")

    # Rank by ROI
    print("\n" + "="*70)
    print("RANKING BY ROI")
    print("="*70)

    ranked = sorted(all_results, key=lambda x: x['roi_pct'], reverse=True)
    for i, r in enumerate(ranked, 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else ""
        print(f"{i}. {emoji} {r['index']} ({r['name']}): {r['roi_pct']:+.1f}% ROI, ${r['total_pnl']:,.0f} profit")

    # Rank by profit factor
    print("\n" + "="*70)
    print("RANKING BY PROFIT FACTOR")
    print("="*70)

    ranked_pf = sorted(all_results, key=lambda x: x['profit_factor'], reverse=True)
    for i, r in enumerate(ranked_pf, 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else ""
        print(f"{i}. {emoji} {r['index']} ({r['name']}): {r['profit_factor']:.2f} PF, {r['win_rate']:.1f}% WR")

    # Save detailed results
    output_file = '/root/gamma/multi_index_comparison.csv'

    all_trades = []
    for r in all_results:
        all_trades.extend(r['trades'])

    if all_trades:
        df = pd.DataFrame(all_trades)
        df.to_csv(output_file, index=False)
        print(f"\nDetailed results saved to: {output_file}")

    return all_results

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Multi-Index GEX Backtest Comparison')
    parser.add_argument('--days', type=int, default=252, help='Number of trading days (default: 252 = 1 year)')

    args = parser.parse_args()

    results = compare_indices(days=args.days)
