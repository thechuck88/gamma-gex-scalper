#!/usr/bin/env python3
"""
GAMMA FAR OTM BACKTEST - Always Use OTM Strategy
================================================

This backtest runs the FAR OTM iron condor strategy ALL THE TIME,
not just as a fallback when GEX conditions aren't met.

Strategy:
- Sell far OTM iron condors at 2.5 standard deviations (~99% probability)
- 10-point spreads on both PUT and CALL side
- Entry window: 10:00 AM - 2:00 PM ET
- Time constraint: 2-6 hours until close
- Same exit logic as canonical backtest (profit targets, stops, trailing)

COMPARISON:
- GEX strategy: Sell spreads near gamma pin strikes (dealer positioning)
- OTM strategy: Sell far OTM spreads based on statistical probability

USAGE:
    python3 gamma_OTM_BACKTEST.py                    # Run full backtest
    python3 gamma_OTM_BACKTEST.py --days 7           # Last 7 days
    python3 gamma_OTM_BACKTEST.py --no-autoscale     # Fixed 1 contract
"""

import sys
import os
import argparse
import sqlite3
import pandas as pd
import numpy as np
import math
from datetime import datetime, timedelta, time as dt_time
from collections import defaultdict
import pytz

sys.path.insert(0, '/root/gamma')

# =============================================================================
# CONFIGURATION - MATCHES CANONICAL BACKTEST EXIT LOGIC
# =============================================================================

# Exit parameters (same as canonical)
PROFIT_TARGET_HIGH = 0.50          # 50% profit
PROFIT_TARGET_MEDIUM = 0.40        # 60% profit
STOP_LOSS_PCT = 0.15               # 15% stop loss
SL_GRACE_PERIOD_SEC = 540          # 9 minutes grace
SL_EMERGENCY_PCT = 0.25            # 25% emergency hard stop

# Trailing stop parameters
TRAILING_STOP_ENABLED = True
TRAILING_TRIGGER_PCT = 0.30        # Activate at 30% profit
TRAILING_LOCK_IN_PCT = 0.20        # Lock in 20% profit
TRAILING_DISTANCE_MIN = 0.10       # 10% minimum trail
TRAILING_TIGHTEN_RATE = 0.4

# VIX filters
VIX_FLOOR = 13.0
VIX_MAX_THRESHOLD = 20.0

# OTM STRATEGY SPECIFIC PARAMETERS
OTM_ENTRY_TIMES_ET = ["10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30"]
OTM_CUTOFF_HOUR = 14               # 2 PM ET (otm_spreads.py uses 10 AM - 2 PM window)
OTM_MIN_HOURS_TO_CLOSE = 2.0       # Must have at least 2 hours
OTM_MAX_HOURS_TO_CLOSE = 6.0       # Must have at most 6 hours
OTM_STD_DEV_MULTIPLIER = 2.5       # 2.5 SD = ~99% coverage
OTM_SPREAD_WIDTH = 10              # 10-point spreads
OTM_MIN_CREDIT_PER_SPREAD = 0.20   # Minimum $0.20 per spread
OTM_MIN_STRIKE_DISTANCE = 50       # At least 50 points away

# Autoscaling parameters (same as canonical)
STARTING_CAPITAL = 20000
MAX_CONTRACTS = 3
KELLY_FRACTION = 0.5
BOOTSTRAP_TRADES = 10
STATS_WINDOW = 50
SAFETY_HALT_PCT = 0.50

# Bootstrap statistics
BOOTSTRAP_WIN_RATE = 0.582
BOOTSTRAP_AVG_WIN = 266.0
BOOTSTRAP_AVG_LOSS = 109.0

# Progressive hold-to-expiration parameters
HOLD_MIN_PROFIT_PCT = 0.80         # Must hit 80% profit to qualify
HOLD_VIX_MAX = 17                  # VIX must be < 17
HOLD_MIN_TIME_LEFT_HOURS = 1.0     # At least 1 hour to expiration

# Progressive TP schedule (hours_after_entry, tp_threshold)
PROGRESSIVE_TP_SCHEDULE = [
    (0.0, 0.50),   # Start: 50% TP
    (1.0, 0.55),   # 1 hour: 55% TP
    (2.0, 0.60),   # 2 hours: 60% TP
    (3.0, 0.70),   # 3 hours: 70% TP
    (4.0, 0.80),   # 4+ hours: 80% TP
]

# Database
DB_PATH = "/root/gamma/data/gex_blackbox.db"

# =============================================================================
# OTM STRATEGY LOGIC
# =============================================================================

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
        return 0.15  # Conservative fallback


def round_to_strike(price, increment=5):
    """Round price to nearest valid SPX strike."""
    return round(price / increment) * increment


def calculate_otm_strikes(spx_price, gex_pin, vix_level, hours_to_close):
    """
    Calculate far OTM SINGLE-SIDED spread using GEX directional bias.

    - If GEX pin > price (bullish): Sell PUT spread
    - If GEX pin < price (bearish): Sell CALL spread

    Returns:
        dict with single spread (PUT or CALL), or None if invalid
    """
    # Determine direction from GEX pin
    if gex_pin is None or gex_pin == spx_price:
        # No clear bias - default to PUT spread below
        direction = "NEUTRAL"
        side = "PUT"
    elif gex_pin > spx_price:
        direction = "BULLISH"
        side = "PUT"  # Expect price to stay above or rise
    else:
        direction = "BEARISH"
        side = "CALL"  # Expect price to stay below or fall

    # Get implied volatility from VIX
    implied_vol = get_implied_volatility_from_vix(vix_level)

    # Calculate 1 SD move
    one_sd = calculate_expected_move(spx_price, implied_vol, hours_to_close)

    # Place strikes at 2.5 SD
    strike_distance = one_sd * OTM_STD_DEV_MULTIPLIER

    # Round to nearest 5 and enforce minimum
    strike_distance = max(round(strike_distance / 5) * 5, OTM_MIN_STRIKE_DISTANCE)

    # Calculate strikes based on direction
    if side == "PUT":
        short_strike = round_to_strike(spx_price - strike_distance)
        long_strike = short_strike - OTM_SPREAD_WIDTH
        distance_otm = spx_price - short_strike
    else:  # CALL
        short_strike = round_to_strike(spx_price + strike_distance)
        long_strike = short_strike + OTM_SPREAD_WIDTH
        distance_otm = short_strike - spx_price

    # Estimate credit (single spread, not iron condor)
    # Higher VIX = more credit, more time = more credit
    base_credit = 0.35 + (vix_level / 100) * 0.8
    time_factor = min(hours_to_close / 4.0, 1.0)
    credit = base_credit * time_factor

    # Check minimum credit requirement
    if credit < OTM_MIN_CREDIT_PER_SPREAD:
        return None

    return {
        'direction': direction,
        'side': side,
        'short_strike': short_strike,
        'long_strike': long_strike,
        'credit': credit,
        'strike_distance': strike_distance,
        'distance_otm': distance_otm,
        'one_sd': one_sd,
        'implied_vol': implied_vol * 100
    }


# =============================================================================
# AUTOSCALING LOGIC (same as canonical)
# =============================================================================

def calculate_kelly_contracts(balance, win_rate, avg_win, avg_loss, max_contracts=MAX_CONTRACTS):
    """Calculate optimal contracts using Half-Kelly."""
    if avg_loss == 0:
        return 1

    kelly_fraction = win_rate - ((1 - win_rate) * abs(avg_win) / abs(avg_loss))
    kelly_fraction = max(0, min(kelly_fraction, 1.0))

    half_kelly = kelly_fraction * KELLY_FRACTION
    avg_win_abs = abs(avg_win)

    if avg_win_abs == 0:
        return 1

    contracts = int((balance * half_kelly) / avg_win_abs)
    contracts = max(1, min(contracts, max_contracts))

    return contracts


# =============================================================================
# EXIT SIMULATION (same as canonical)
# =============================================================================

def simulate_exit(entry_credit, confidence, vix, hours_held, is_autoscale=True):
    """
    Simulate trade exit using statistical model.

    Returns:
        dict with exit_credit, exit_reason, held_to_expiration
    """
    # Base probabilities
    if confidence == "HIGH":
        base_win_prob = 0.85
        profit_target = PROFIT_TARGET_HIGH
    else:
        base_win_prob = 0.75
        profit_target = PROFIT_TARGET_MEDIUM

    # VIX adjustment (higher VIX = more volatility = more stop outs)
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
        # Decide if hit TP or held to expiration
        hold_prob = 0.0

        # Progressive hold probability increases with time
        if hours_held >= 4.0 and vix < HOLD_VIX_MAX and rand < 0.80:
            hold_prob = 0.30  # 30% chance of holding to expiration
        elif hours_held >= 3.0 and vix < HOLD_VIX_MAX:
            hold_prob = 0.15

        if np.random.random() < hold_prob:
            # Hold to expiration (expires worthless)
            exit_credit = 0.0
            exit_reason = "HOLD_WORTHLESS"
            held_to_expiration = True
        else:
            # Hit profit target
            exit_credit = entry_credit * tp_threshold
            exit_reason = "PROFIT_TARGET"
            held_to_expiration = False

            # Small chance of trailing stop
            if TRAILING_STOP_ENABLED and np.random.random() < 0.08:
                # Trailing stop caught it partway
                profit_pct = np.random.uniform(TRAILING_LOCK_IN_PCT, 0.50)
                exit_credit = entry_credit * (1 - profit_pct)
                exit_reason = "TRAILING_STOP"
    else:
        # LOSER
        # Most losses are stop loss, some are emergency
        if np.random.random() < 0.85:
            # Regular stop loss (15%)
            loss_pct = STOP_LOSS_PCT
            exit_reason = "STOP_LOSS"
        else:
            # Emergency stop (20-25%)
            loss_pct = np.random.uniform(STOP_LOSS_PCT, SL_EMERGENCY_PCT)
            exit_reason = "STOP_LOSS"

        exit_credit = entry_credit * (1 + loss_pct)
        held_to_expiration = False

    return {
        'exit_credit': exit_credit,
        'exit_reason': exit_reason,
        'held_to_expiration': held_to_expiration
    }


# =============================================================================
# BACKTEST ENGINE
# =============================================================================

def run_otm_backtest(days=None, use_autoscale=True):
    """Run OTM strategy backtest."""

    print("="*80)
    print("GAMMA FAR OTM BACKTEST (SINGLE-SIDED)")
    print("="*80)
    print()
    print("Strategy: FAR OTM single-sided spreads with GEX directional bias")
    print(f"Strikes: 2.5 SD from current price (~{OTM_MIN_STRIKE_DISTANCE}+ points OTM)")
    print(f"Spreads: {OTM_SPREAD_WIDTH}-point PUT or CALL (NOT iron condors)")
    print(f"Direction: GEX pin > price = PUT spread, GEX pin < price = CALL spread")
    print(f"Entry window: 10:00 AM - 2:00 PM ET")
    print(f"Time constraint: {OTM_MIN_HOURS_TO_CLOSE}-{OTM_MAX_HOURS_TO_CLOSE} hours to close")
    print(f"Autoscaling: {'ENABLED' if use_autoscale else 'DISABLED'} (max {MAX_CONTRACTS} contracts)")
    print()

    # Load data (include GEX pin for directional bias)
    conn = sqlite3.connect(DB_PATH)

    query = """
    SELECT
        s.timestamp,
        DATE(DATETIME(s.timestamp, '-5 hours')) as date_et,
        TIME(DATETIME(s.timestamp, '-5 hours')) as time_et,
        s.index_symbol,
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

    if days:
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        df = df[df['date_et'] >= cutoff_date]

    print(f"Loaded {len(df)} bars from {df['date_et'].min()} to {df['date_et'].max()}")
    print()

    # Track trades
    trades = []
    balance = STARTING_CAPITAL
    total_trades = 0
    winners = 0
    losers = 0

    # Autoscaling state
    trade_history = []
    current_contracts = 1

    # Process each bar
    for idx, row in df.iterrows():
        timestamp = row['timestamp']
        date_et = row['date_et']
        time_et = row['time_et']
        spx_price = row['underlying_price']
        vix = row['vix']
        pin_strike = row['pin_strike']  # May be None

        # Parse time
        try:
            hour = int(time_et.split(':')[0])
            minute = int(time_et.split(':')[1])
        except:
            continue

        # Check if this is an entry time
        time_str = f"{hour:02d}:{minute:02d}"
        if time_str not in OTM_ENTRY_TIMES_ET:
            continue

        # Check cutoff hour
        if hour >= OTM_CUTOFF_HOUR:
            continue

        # VIX filters
        if vix < VIX_FLOOR or vix > VIX_MAX_THRESHOLD:
            continue

        # Calculate hours to close (assume 4 PM ET close)
        hours_to_close = 16 - hour - (minute / 60.0)

        # Time constraint check
        if hours_to_close < OTM_MIN_HOURS_TO_CLOSE or hours_to_close > OTM_MAX_HOURS_TO_CLOSE:
            continue

        # Calculate OTM strikes (single-sided with GEX directional bias)
        otm_setup = calculate_otm_strikes(spx_price, pin_strike, vix, hours_to_close)

        if not otm_setup:
            continue  # Credits too low

        # Determine confidence (based on VIX - lower VIX = higher confidence)
        if vix < 15:
            confidence = "HIGH"
        else:
            confidence = "MEDIUM"

        # Safety halt check
        if balance < STARTING_CAPITAL * SAFETY_HALT_PCT:
            print(f"⚠️  SAFETY HALT: Balance ${balance:.2f} below 50% threshold")
            break

        # Autoscaling
        if use_autoscale and len(trade_history) >= BOOTSTRAP_TRADES:
            recent_trades = trade_history[-STATS_WINDOW:]
            wins = [t for t in recent_trades if t['winner']]
            losses = [t for t in recent_trades if not t['winner']]

            win_rate = len(wins) / len(recent_trades)
            avg_win = np.mean([t['pl_per_contract'] for t in wins]) if wins else BOOTSTRAP_AVG_WIN
            avg_loss = np.mean([t['pl_per_contract'] for t in losses]) if losses else BOOTSTRAP_AVG_LOSS

            current_contracts = calculate_kelly_contracts(balance, win_rate, avg_win, avg_loss)
        else:
            # Bootstrap phase
            current_contracts = 1

        # ENTRY
        entry_credit = otm_setup['credit']

        # Simulate exit
        # Estimate hours held (assume average 2 hours for OTM trades)
        hours_held = np.random.uniform(1.5, 4.0)

        exit_result = simulate_exit(entry_credit, confidence, vix, hours_held, use_autoscale)

        exit_credit = exit_result['exit_credit']
        exit_reason = exit_result['exit_reason']
        held_to_expiration = exit_result['held_to_expiration']

        # Calculate P&L
        pl_per_contract = (entry_credit - exit_credit) * 100  # $100 per point
        pl_total = pl_per_contract * current_contracts

        balance += pl_total
        winner = pl_per_contract > 0

        if winner:
            winners += 1
        else:
            losers += 1

        total_trades += 1

        # Record trade
        trade = {
            'timestamp': timestamp,
            'date': date_et,
            'time': time_et,
            'spx_price': spx_price,
            'pin_strike': pin_strike,
            'vix': vix,
            'confidence': confidence,
            'direction': otm_setup['direction'],
            'side': otm_setup['side'],
            'short_strike': otm_setup['short_strike'],
            'long_strike': otm_setup['long_strike'],
            'strike_distance': otm_setup['strike_distance'],
            'distance_otm': otm_setup['distance_otm'],
            'entry_credit': entry_credit,
            'exit_credit': exit_credit,
            'exit_reason': exit_reason,
            'held_to_expiration': held_to_expiration,
            'pl_per_contract': pl_per_contract,
            'contracts': current_contracts,
            'pl_total': pl_total,
            'balance': balance,
            'winner': winner
        }

        trades.append(trade)
        trade_history.append(trade)

    # Results
    print()
    print("="*80)
    print("RESULTS")
    print("="*80)
    print()
    print(f"Starting Balance: ${STARTING_CAPITAL:,.2f}")
    print(f"Final Balance: ${balance:,.2f}")
    print(f"Total P&L: ${balance - STARTING_CAPITAL:,.2f}")
    print(f"Return: {((balance / STARTING_CAPITAL - 1) * 100):.1f}%")
    print()
    print(f"Total Trades: {total_trades}")
    print(f"Winners: {winners} ({100*winners/total_trades if total_trades > 0 else 0:.1f}%)")
    print(f"Losers: {losers}")
    print()

    if trades:
        df_trades = pd.DataFrame(trades)

        avg_win = df_trades[df_trades['winner']]['pl_total'].mean() if winners > 0 else 0
        avg_loss = df_trades[~df_trades['winner']]['pl_total'].mean() if losers > 0 else 0

        print(f"Avg Win: ${avg_win:.2f}")
        print(f"Avg Loss: ${avg_loss:.2f}")
        print(f"Profit Factor: {abs(avg_win * winners / (avg_loss * losers)) if losers > 0 else float('inf'):.2f}")
        print()

        # Save to CSV
        csv_path = '/tmp/gamma_otm_trades.csv'
        df_trades.to_csv(csv_path, index=False)
        print(f"Trades saved to: {csv_path}")
        print()

        # Daily breakdown
        print("Daily Breakdown:")
        print("-" * 80)
        daily = df_trades.groupby('date').agg({
            'pl_total': 'sum',
            'winner': ['count', 'sum']
        }).round(2)

        for date, row in daily.iterrows():
            day_pl = row['pl_total']['sum']
            day_trades = int(row['winner']['count'])
            day_wins = int(row['winner']['sum'])
            day_wr = 100 * day_wins / day_trades if day_trades > 0 else 0
            print(f"{date} | Trades: {day_trades:2d} | Wins: {day_wins:2d} ({day_wr:4.1f}%) | P&L: ${day_pl:7,.2f}")

        print()

    return {
        'final_balance': balance,
        'total_pl': balance - STARTING_CAPITAL,
        'total_trades': total_trades,
        'winners': winners,
        'losers': losers,
        'trades': trades
    }


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Gamma FAR OTM Backtest')
    parser.add_argument('--days', type=int, help='Number of days to backtest')
    parser.add_argument('--no-autoscale', action='store_true', help='Disable autoscaling')

    args = parser.parse_args()

    results = run_otm_backtest(
        days=args.days,
        use_autoscale=not args.no_autoscale
    )
