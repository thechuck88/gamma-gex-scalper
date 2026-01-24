#!/usr/bin/env python3
"""
OTM Strike Optimization - Find optimal parameters for OTM strategy

Tests combinations of:
- Strike distance (1.0 - 3.0 standard deviations)
- Spread width (5, 10, 15, 20 points)
- Minimum credit threshold ($0.20 - $0.60)

Goal: Maximize P&L while maintaining acceptable win rate
"""

import sys
import sqlite3
import pandas as pd
import numpy as np
import math
from datetime import datetime, timedelta
from itertools import product

sys.path.insert(0, '/root/gamma')

# Constants
DB_PATH = "/root/gamma/data/gex_blackbox.db"
STARTING_CAPITAL = 20000
VIX_FLOOR = 13.0
VIX_MAX_THRESHOLD = 20.0
OTM_ENTRY_TIMES_ET = ["10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30"]
OTM_CUTOFF_HOUR = 14
OTM_MIN_HOURS_TO_CLOSE = 2.0
OTM_MAX_HOURS_TO_CLOSE = 6.0

# Progressive hold parameters
HOLD_VIX_MAX = 17
PROGRESSIVE_TP_SCHEDULE = [
    (0.0, 0.50), (1.0, 0.55), (2.0, 0.60), (3.0, 0.70), (4.0, 0.80)
]

# Exit parameters
PROFIT_TARGET_HIGH = 0.50
PROFIT_TARGET_MEDIUM = 0.40
STOP_LOSS_PCT = 0.15
SL_GRACE_PERIOD_SEC = 540
SL_EMERGENCY_PCT = 0.25
TRAILING_STOP_ENABLED = True
TRAILING_TRIGGER_PCT = 0.30
TRAILING_LOCK_IN_PCT = 0.20
TRAILING_DISTANCE_MIN = 0.10
TRAILING_TIGHTEN_RATE = 0.4

# Test parameters
STRIKE_DISTANCES = [1.0, 1.5, 2.0, 2.5, 3.0]  # Standard deviations
SPREAD_WIDTHS = [5, 10, 15, 20]  # Point widths
MIN_CREDITS = [0.20, 0.30, 0.40, 0.50, 0.60]  # Minimum credit per spread


def calculate_expected_move(price, implied_vol_annual, hours_remaining):
    """Calculate expected price move using Black-Scholes volatility scaling."""
    time_fraction = hours_remaining / (252 * 24)
    time_adjusted_vol = implied_vol_annual * math.sqrt(time_fraction)
    expected_move = price * time_adjusted_vol
    return expected_move


def get_implied_volatility_from_vix(vix_level):
    """Convert VIX to annual implied volatility."""
    if vix_level and vix_level > 0:
        return vix_level / 100.0
    else:
        return 0.15


def round_to_strike(price, increment=5):
    """Round price to nearest valid SPX strike."""
    return round(price / increment) * increment


def calculate_otm_strikes(spx_price, gex_pin, vix_level, hours_to_close,
                          std_dev_mult, spread_width, min_credit):
    """
    Calculate far OTM single-sided spread.

    Args:
        std_dev_mult: How many standard deviations away to place strikes
        spread_width: Width of the spread in points
        min_credit: Minimum acceptable credit
    """
    # Determine direction
    if gex_pin is None or gex_pin == spx_price:
        direction = "NEUTRAL"
        side = "PUT"
    elif gex_pin > spx_price:
        direction = "BULLISH"
        side = "PUT"
    else:
        direction = "BEARISH"
        side = "CALL"

    # Get implied volatility
    implied_vol = get_implied_volatility_from_vix(vix_level)

    # Calculate 1 SD move
    one_sd = calculate_expected_move(spx_price, implied_vol, hours_to_close)

    # Place strikes at specified SD
    strike_distance = one_sd * std_dev_mult

    # Round to nearest 5 and enforce minimum of 50
    strike_distance = max(round(strike_distance / 5) * 5, 50)

    # Calculate strikes
    if side == "PUT":
        short_strike = round_to_strike(spx_price - strike_distance)
        long_strike = short_strike - spread_width
        distance_otm = spx_price - short_strike
    else:  # CALL
        short_strike = round_to_strike(spx_price + strike_distance)
        long_strike = short_strike + spread_width
        distance_otm = short_strike - spx_price

    # Estimate credit based on:
    # - VIX (higher = more credit)
    # - Time to expiration (more time = more credit)
    # - Spread width (wider = more credit but also more risk)
    # - Distance OTM (farther = less credit)

    # Base credit increases with spread width
    base_credit_per_point = 0.035  # $0.035 per point of width
    base_credit = base_credit_per_point * spread_width

    # VIX multiplier (higher VIX = higher premiums)
    vix_multiplier = 1.0 + (vix_level / 100) * 2.0

    # Time multiplier (more time = more theta to collect)
    time_multiplier = min(hours_to_close / 4.0, 1.0)

    # Distance penalty (farther OTM = less credit)
    # At 1 SD = 100% credit, at 3 SD = ~30% credit
    distance_penalty = 1.0 / (std_dev_mult ** 0.8)

    credit = base_credit * vix_multiplier * time_multiplier * distance_penalty

    # Check minimum credit
    if credit < min_credit:
        return None

    return {
        'direction': direction,
        'side': side,
        'short_strike': short_strike,
        'long_strike': long_strike,
        'spread_width': spread_width,
        'credit': credit,
        'strike_distance': strike_distance,
        'distance_otm': distance_otm,
        'one_sd': one_sd,
        'std_dev_mult': std_dev_mult
    }


def simulate_exit(entry_credit, confidence, vix, hours_held):
    """Simulate trade exit."""
    # Base probabilities
    if confidence == "HIGH":
        base_win_prob = 0.85
        profit_target = PROFIT_TARGET_HIGH
    else:
        base_win_prob = 0.75
        profit_target = PROFIT_TARGET_MEDIUM

    # VIX adjustment
    vix_adjustment = (vix - 15) * 0.02
    win_prob = max(0.5, min(0.95, base_win_prob - vix_adjustment))

    # Determine outcome
    rand = np.random.random()

    # Progressive TP threshold
    tp_threshold = profit_target
    for hours, threshold in PROGRESSIVE_TP_SCHEDULE:
        if hours_held >= hours:
            tp_threshold = threshold

    if rand < win_prob:
        # WINNER
        hold_prob = 0.0
        if hours_held >= 4.0 and vix < HOLD_VIX_MAX and rand < 0.80:
            hold_prob = 0.30
        elif hours_held >= 3.0 and vix < HOLD_VIX_MAX:
            hold_prob = 0.15

        if np.random.random() < hold_prob:
            exit_credit = 0.0
            exit_reason = "HOLD_WORTHLESS"
        else:
            exit_credit = entry_credit * tp_threshold
            exit_reason = "PROFIT_TARGET"

            if TRAILING_STOP_ENABLED and np.random.random() < 0.08:
                profit_pct = np.random.uniform(TRAILING_LOCK_IN_PCT, 0.50)
                exit_credit = entry_credit * (1 - profit_pct)
                exit_reason = "TRAILING_STOP"
    else:
        # LOSER
        if np.random.random() < 0.85:
            loss_pct = STOP_LOSS_PCT
        else:
            loss_pct = np.random.uniform(STOP_LOSS_PCT, SL_EMERGENCY_PCT)

        exit_credit = entry_credit * (1 + loss_pct)
        exit_reason = "STOP_LOSS"

    return {
        'exit_credit': exit_credit,
        'exit_reason': exit_reason
    }


def run_otm_test(df, std_dev_mult, spread_width, min_credit):
    """Run backtest with specific parameters."""
    balance = STARTING_CAPITAL
    trades = []

    for idx, row in df.iterrows():
        spx_price = row['underlying_price']
        vix = row['vix']
        pin_strike = row['pin_strike']

        # Parse time
        try:
            time_et = row['time_et']
            hour = int(time_et.split(':')[0])
            minute = int(time_et.split(':')[1])
            time_str = f"{hour:02d}:{minute:02d}"
        except:
            continue

        # Entry filters
        if time_str not in OTM_ENTRY_TIMES_ET:
            continue
        if hour >= OTM_CUTOFF_HOUR:
            continue
        if vix < VIX_FLOOR or vix > VIX_MAX_THRESHOLD:
            continue

        # Hours to close
        hours_to_close = 16 - hour - (minute / 60.0)
        if hours_to_close < OTM_MIN_HOURS_TO_CLOSE or hours_to_close > OTM_MAX_HOURS_TO_CLOSE:
            continue

        # Calculate strikes
        otm_setup = calculate_otm_strikes(
            spx_price, pin_strike, vix, hours_to_close,
            std_dev_mult, spread_width, min_credit
        )

        if not otm_setup:
            continue

        # Determine confidence
        confidence = "HIGH" if vix < 15 else "MEDIUM"

        # Entry
        entry_credit = otm_setup['credit']

        # Simulate exit
        hours_held = np.random.uniform(1.5, 4.0)
        exit_result = simulate_exit(entry_credit, confidence, vix, hours_held)

        # Calculate P&L (fixed 1 contract for fair comparison)
        pl_per_contract = (entry_credit - exit_result['exit_credit']) * 100

        balance += pl_per_contract

        trades.append({
            'pl': pl_per_contract,
            'winner': pl_per_contract > 0,
            'credit': entry_credit,
            'exit_reason': exit_result['exit_reason']
        })

    if len(trades) == 0:
        return None

    # Calculate stats
    df_trades = pd.DataFrame(trades)
    winners = df_trades[df_trades['winner']]
    losers = df_trades[~df_trades['winner']]

    total_pl = balance - STARTING_CAPITAL
    win_rate = len(winners) / len(trades) if len(trades) > 0 else 0
    avg_win = winners['pl'].mean() if len(winners) > 0 else 0
    avg_loss = losers['pl'].mean() if len(losers) > 0 else 0
    avg_credit = df_trades['credit'].mean()

    return {
        'std_dev': std_dev_mult,
        'width': spread_width,
        'min_credit': min_credit,
        'total_pl': total_pl,
        'trades': len(trades),
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'avg_credit': avg_credit,
        'return_pct': (total_pl / STARTING_CAPITAL) * 100
    }


def main():
    print("="*80)
    print("OTM STRIKE OPTIMIZATION")
    print("="*80)
    print()
    print("Testing combinations of:")
    print(f"  Strike distance: {STRIKE_DISTANCES} standard deviations")
    print(f"  Spread width: {SPREAD_WIDTHS} points")
    print(f"  Min credit: ${MIN_CREDITS}")
    print()
    print(f"Total combinations: {len(STRIKE_DISTANCES) * len(SPREAD_WIDTHS) * len(MIN_CREDITS)}")
    print()

    # Load data
    conn = sqlite3.connect(DB_PATH)
    query = """
    SELECT
        s.timestamp,
        DATE(DATETIME(s.timestamp, '-5 hours')) as date_et,
        TIME(DATETIME(s.timestamp, '-5 hours')) as time_et,
        s.underlying_price,
        s.vix,
        g.strike AS pin_strike
    FROM market_context s
    LEFT JOIN gex_peaks g ON s.timestamp = g.timestamp
        AND s.index_symbol = g.index_symbol
        AND g.peak_rank = 1
    WHERE s.index_symbol = 'SPX'
    ORDER BY s.timestamp ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    print(f"Loaded {len(df)} bars from {df['date_et'].min()} to {df['date_et'].max()}")
    print()
    print("Running optimization...")
    print()

    # Test all combinations
    results = []
    total_tests = len(STRIKE_DISTANCES) * len(SPREAD_WIDTHS) * len(MIN_CREDITS)
    test_num = 0

    for std_dev, width, min_cred in product(STRIKE_DISTANCES, SPREAD_WIDTHS, MIN_CREDITS):
        test_num += 1
        result = run_otm_test(df, std_dev, width, min_cred)

        if result:
            results.append(result)

            if test_num % 10 == 0:
                print(f"Progress: {test_num}/{total_tests} ({100*test_num/total_tests:.0f}%)")

    print()
    print("="*80)
    print("RESULTS")
    print("="*80)
    print()

    # Sort by total P&L
    df_results = pd.DataFrame(results)
    df_results = df_results.sort_values('total_pl', ascending=False)

    print("Top 10 Configurations by Total P&L:")
    print("-" * 120)
    print(f"{'Rank':<5} {'SD':<6} {'Width':<7} {'MinCr':<7} {'Trades':<7} {'WinRate':<9} {'AvgWin':<9} {'AvgLoss':<10} {'AvgCr':<8} {'TotalP&L':<12} {'Return%':<8}")
    print("-" * 120)

    for idx, row in df_results.head(10).iterrows():
        print(f"{idx+1:<5} "
              f"{row['std_dev']:<6.1f} "
              f"{int(row['width']):<7} "
              f"${row['min_credit']:<6.2f} "
              f"{int(row['trades']):<7} "
              f"{row['win_rate']*100:<8.1f}% "
              f"${row['avg_win']:<8.2f} "
              f"${row['avg_loss']:<9.2f} "
              f"${row['avg_credit']:<7.2f} "
              f"${row['total_pl']:<11,.2f} "
              f"{row['return_pct']:<7.1f}%")

    print()
    print("-" * 120)
    print()

    # Best by P&L
    best = df_results.iloc[0]
    print("BEST CONFIGURATION:")
    print(f"  Strike Distance: {best['std_dev']:.1f} SD")
    print(f"  Spread Width: {int(best['width'])} points")
    print(f"  Min Credit: ${best['min_credit']:.2f}")
    print()
    print(f"  Total Trades: {int(best['trades'])}")
    print(f"  Win Rate: {best['win_rate']*100:.1f}%")
    print(f"  Avg Win: ${best['avg_win']:.2f}")
    print(f"  Avg Loss: ${best['avg_loss']:.2f}")
    print(f"  Avg Credit: ${best['avg_credit']:.2f}")
    print(f"  Total P&L: ${best['total_pl']:,.2f}")
    print(f"  Return: {best['return_pct']:.1f}%")
    print()

    # Compare to baseline (2.5 SD, 10 pt, $0.20 min)
    baseline = df_results[
        (df_results['std_dev'] == 2.5) &
        (df_results['width'] == 10) &
        (df_results['min_credit'] == 0.20)
    ]

    if len(baseline) > 0:
        baseline = baseline.iloc[0]
        improvement = ((best['total_pl'] - baseline['total_pl']) / baseline['total_pl']) * 100
        print(f"IMPROVEMENT vs BASELINE (2.5 SD, 10pt, $0.20):")
        print(f"  Baseline P&L: ${baseline['total_pl']:,.2f}")
        print(f"  Best P&L: ${best['total_pl']:,.2f}")
        print(f"  Improvement: {improvement:+.1f}%")
        print()

    # Save results
    csv_path = '/tmp/otm_optimization_results.csv'
    df_results.to_csv(csv_path, index=False)
    print(f"Full results saved to: {csv_path}")
    print()


if __name__ == '__main__':
    main()
