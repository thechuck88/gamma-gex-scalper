#!/usr/bin/env python3
"""
GEX + OTM Backtest: Complete Strategy Test (2026-01-16)

Tests BOTH strategies at each entry time:
1. GEX PIN spread (primary strategy)
2. OTM iron condor (fallback when GEX too far)

Uses EXACT exit logic from monitor.py for both strategies.

Usage:
  python backtest_gex_and_otm.py
"""

import sqlite3
import datetime
import numpy as np
import pandas as pd
import json
import math
from collections import defaultdict

DB_PATH = "/root/gamma/data/gex_blackbox.db"

# ============================================================================
# STRATEGY PARAMETERS (EXACT MATCH TO monitor.py)
# ============================================================================

# GEX Strategy
PROFIT_TARGET_PCT = 0.50
PROFIT_TARGET_MEDIUM = 0.60
STOP_LOSS_PCT = 0.15
VIX_MAX_THRESHOLD = 20
VIX_FLOOR = 13.0

# Trailing stop
TRAILING_STOP_ENABLED = True
TRAILING_TRIGGER_PCT = 0.20
TRAILING_LOCK_IN_PCT = 0.12
TRAILING_DISTANCE_MIN = 0.08
TRAILING_TIGHTEN_RATE = 0.4

# Stop loss grace period
SL_GRACE_PERIOD_SEC = 540
SL_EMERGENCY_PCT = 0.40

# Progressive hold-to-expiration
PROGRESSIVE_HOLD_ENABLED = True
HOLD_PROFIT_THRESHOLD = 0.80
HOLD_VIX_MAX = 17
HOLD_MIN_TIME_LEFT_HOURS = 1.0
HOLD_MIN_ENTRY_DISTANCE = 8

# OTM Strategy (adjusted for 0DTE reality)
OTM_MIN_PROBABILITY = 0.90
OTM_MIN_CREDIT_TOTAL = 0.40  # Min $0.40 for iron condor
OTM_MIN_CREDIT_PER_SIDE = 0.15  # Min $0.15 per call/put spread
OTM_STD_DEV_MULTIPLIER = 0.75  # ADJUSTED: 0.75 std dev for 0DTE (~50-60 pts)
OTM_SPREAD_WIDTH = 10  # $10 wide spreads

# Progressive TP schedule
PROGRESSIVE_TP_SCHEDULE = [
    (0.0, 0.50), (0.5, 0.55), (1.0, 0.60),
    (2.0, 0.70), (3.0, 0.80), (4.0, 0.90),
]

# Entry times and auto-close
ENTRY_TIMES_ET = [
    "09:36", "10:00", "10:30", "11:00",
    "11:30", "12:00", "12:30", "13:00"
]
CUTOFF_HOUR = 13
AUTO_CLOSE_HOUR = 15
AUTO_CLOSE_MINUTE = 30


def get_optimized_connection():
    """Get database connection with optimizations."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def estimate_entry_credit(pin_strike, vix, underlying):
    """Estimate GEX PIN entry credit."""
    iv = vix / 100.0
    distance_pct = abs(pin_strike - underlying) / underlying

    if distance_pct < 0.005:
        credit = underlying * iv * 0.05
    elif distance_pct < 0.01:
        credit = underlying * iv * 0.03
    else:
        credit = underlying * iv * 0.02

    return max(0.50, min(credit, 2.50))


def calculate_expected_move(price, vix, hours_remaining):
    """Calculate expected price move for OTM strike selection."""
    implied_vol = vix / 100.0
    time_fraction = hours_remaining / (252 * 6.5)  # Trading hours in a year
    time_adjusted_vol = implied_vol * math.sqrt(time_fraction)
    expected_move = price * time_adjusted_vol
    return expected_move


def find_otm_strikes(chain_data, underlying, vix, hours_remaining):
    """
    Find OTM iron condor strikes from option chain.

    Returns: dict with call_spread and put_spread or None
    """
    # Parse chain data
    if isinstance(chain_data, str):
        chain = json.loads(chain_data)
    else:
        chain = chain_data

    # Calculate expected move (2.5 standard deviations)
    std_move = calculate_expected_move(underlying, vix, hours_remaining)
    target_distance = std_move * OTM_STD_DEV_MULTIPLIER

    # Separate calls and puts
    calls = [opt for opt in chain if opt['option_type'] == 'call']
    puts = [opt for opt in chain if opt['option_type'] == 'put']

    # Find call spread (above current price)
    call_short_target = underlying + target_distance
    call_long_target = call_short_target + OTM_SPREAD_WIDTH

    # Find closest strikes to targets
    call_short_strike = min(calls, key=lambda x: abs(x['strike'] - call_short_target))['strike']
    call_long_strike = min(calls, key=lambda x: abs(x['strike'] - call_long_target))['strike']

    # Find put spread (below current price)
    put_short_target = underlying - target_distance
    put_long_target = put_short_target - OTM_SPREAD_WIDTH

    put_short_strike = min(puts, key=lambda x: abs(x['strike'] - put_short_target))['strike']
    put_long_strike = min(puts, key=lambda x: abs(x['strike'] - put_long_target))['strike']

    # Get quotes for each leg
    call_short = next((c for c in calls if c['strike'] == call_short_strike), None)
    call_long = next((c for c in calls if c['strike'] == call_long_strike), None)
    put_short = next((p for p in puts if p['strike'] == put_short_strike), None)
    put_long = next((p for p in puts if p['strike'] == put_long_strike), None)

    if not all([call_short, call_long, put_short, put_long]):
        return None

    # Calculate credits (sell short, buy long)
    call_spread_credit = call_short['bid'] - call_long['ask']
    put_spread_credit = put_short['bid'] - put_long['ask']
    total_credit = call_spread_credit + put_spread_credit

    # Check minimum credits
    if total_credit < OTM_MIN_CREDIT_TOTAL:
        return None
    if call_spread_credit < OTM_MIN_CREDIT_PER_SIDE:
        return None
    if put_spread_credit < OTM_MIN_CREDIT_PER_SIDE:
        return None

    return {
        'call_spread': {
            'short': call_short_strike,
            'long': call_long_strike,
            'credit': call_spread_credit
        },
        'put_spread': {
            'short': put_short_strike,
            'long': put_long_strike,
            'credit': put_spread_credit
        },
        'total_credit': total_credit,
        'target_distance': target_distance,
        'std_move': std_move
    }


def simulate_spread_quotes(entry_credit, profit_pct):
    """Simulate realistic bid/ask spread."""
    mid_value = entry_credit * (1 - profit_pct)

    if mid_value < 0.50:
        spread = 0.05
    elif mid_value < 1.00:
        spread = 0.10
    else:
        spread = 0.15

    bid_value = max(0, mid_value - spread/2)
    ask_value = mid_value + spread/2

    return round(mid_value, 2), round(bid_value, 2), round(ask_value, 2)


def simulate_gex_exit(entry_credit, underlying, pin_strike, vix, entry_time, strategy='GEX'):
    """Simulate GEX PIN spread exit using monitor.py logic."""
    spread_width = 5.0
    confidence = 'HIGH' if vix < 18 else 'MEDIUM'
    profit_target = PROFIT_TARGET_PCT if confidence == 'HIGH' else PROFIT_TARGET_MEDIUM
    entry_distance = abs(pin_strike - underlying)

    best_profit_pct = 0
    trailing_active = False
    hold_qualified = False

    elapsed_sec = 0
    check_interval_sec = 15

    # Simulate market behavior (PIN pull + random walk)
    distance_from_pin = underlying - pin_strike
    pin_pull_strength = 0.3

    while elapsed_sec < 23400:  # Max 6.5 hours
        elapsed_sec += check_interval_sec
        current_time_dt = entry_time + datetime.timedelta(seconds=elapsed_sec)
        hours_elapsed = elapsed_sec / 3600.0

        # Auto-close check
        if current_time_dt.hour >= AUTO_CLOSE_HOUR:
            if current_time_dt.hour > AUTO_CLOSE_HOUR or current_time_dt.minute >= AUTO_CLOSE_MINUTE:
                if not hold_qualified:
                    profit_pct = np.random.uniform(0.30, 0.70)
                    mid_value, _, _ = simulate_spread_quotes(entry_credit, profit_pct)
                    return {
                        'exit_credit': mid_value,
                        'exit_reason': 'Auto-close 3:30 PM',
                        'is_winner': True,
                        'exit_time_sec': elapsed_sec
                    }

        # Expiration check
        if current_time_dt.hour >= 16:
            if hold_qualified or np.random.random() < 0.85:
                return {
                    'exit_credit': 0.0,
                    'exit_reason': 'Hold-to-Expiry: Worthless' if hold_qualified else '0DTE Expiration',
                    'is_winner': True,
                    'exit_time_sec': elapsed_sec
                }
            else:
                loss_pct = np.random.uniform(0.20, 0.50)
                mid_value = entry_credit * (1 + loss_pct)
                return {
                    'exit_credit': mid_value,
                    'exit_reason': 'Expire ITM',
                    'is_winner': False,
                    'exit_time_sec': elapsed_sec
                }

        # Simulate price movement
        volatility_per_hour = vix * 0.5
        random_move = np.random.normal(0, volatility_per_hour / np.sqrt(252 * 6.5))
        pin_pull = -distance_from_pin * pin_pull_strength * (check_interval_sec / 3600.0)
        distance_from_pin += random_move + pin_pull

        # Calculate profit
        initial_distance = abs(underlying - pin_strike)
        current_distance = abs(distance_from_pin)
        if initial_distance > 0:
            distance_improvement = (initial_distance - current_distance) / initial_distance
            profit_pct = distance_improvement * 0.8
        else:
            profit_pct = 0.0

        profit_pct += np.random.normal(0, 0.05)
        profit_pct = np.clip(profit_pct, -1.0, 0.95)

        mid_value, bid_value, ask_value = simulate_spread_quotes(entry_credit, profit_pct)
        profit_pct_mid = (entry_credit - mid_value) / entry_credit
        profit_pct_sl = (entry_credit - ask_value) / entry_credit

        if profit_pct_mid > best_profit_pct:
            best_profit_pct = profit_pct_mid

        # Trailing stop
        if TRAILING_STOP_ENABLED and not trailing_active and profit_pct_mid >= TRAILING_TRIGGER_PCT:
            trailing_active = True

        if trailing_active:
            initial_trail_distance = TRAILING_TRIGGER_PCT - TRAILING_LOCK_IN_PCT
            profit_above_trigger = best_profit_pct - TRAILING_TRIGGER_PCT
            trail_distance = initial_trail_distance - (profit_above_trigger * TRAILING_TIGHTEN_RATE)
            trail_distance = max(trail_distance, TRAILING_DISTANCE_MIN)
            trailing_stop_level = best_profit_pct - trail_distance

            if profit_pct_mid <= trailing_stop_level:
                return {
                    'exit_credit': mid_value,
                    'exit_reason': f'Trailing Stop ({trailing_stop_level*100:.0f}%)',
                    'is_winner': profit_pct_mid > 0,
                    'exit_time_sec': elapsed_sec
                }

        # Progressive TP
        schedule_times = [t for t, _ in PROGRESSIVE_TP_SCHEDULE]
        schedule_tps = [tp for _, tp in PROGRESSIVE_TP_SCHEDULE]
        progressive_tp_pct = np.interp(hours_elapsed, schedule_times, schedule_tps)

        # Hold qualification
        if PROGRESSIVE_HOLD_ENABLED and not hold_qualified and profit_pct_mid >= HOLD_PROFIT_THRESHOLD:
            hours_to_expiry = (16 - current_time_dt.hour) + (0 - current_time_dt.minute) / 60.0
            if (vix < HOLD_VIX_MAX and hours_to_expiry >= HOLD_MIN_TIME_LEFT_HOURS and
                entry_distance >= HOLD_MIN_ENTRY_DISTANCE):
                hold_qualified = True

        # Profit target
        if profit_pct_mid >= progressive_tp_pct and not hold_qualified:
            return {
                'exit_credit': mid_value,
                'exit_reason': f'Profit Target ({progressive_tp_pct*100:.0f}%)',
                'is_winner': True,
                'exit_time_sec': elapsed_sec
            }

        # Stop losses
        if not trailing_active and not hold_qualified:
            if profit_pct_sl <= -SL_EMERGENCY_PCT:
                return {
                    'exit_credit': ask_value,
                    'exit_reason': f'EMERGENCY Stop Loss ({profit_pct_sl*100:.0f}%)',
                    'is_winner': False,
                    'exit_time_sec': elapsed_sec
                }

            if profit_pct_sl <= -STOP_LOSS_PCT and elapsed_sec >= SL_GRACE_PERIOD_SEC:
                return {
                    'exit_credit': ask_value,
                    'exit_reason': f'Stop Loss ({profit_pct_sl*100:.0f}%)',
                    'is_winner': False,
                    'exit_time_sec': elapsed_sec
                }

    return {
        'exit_credit': 0.0,
        'exit_reason': 'Simulation Timeout',
        'is_winner': True,
        'exit_time_sec': elapsed_sec
    }


def simulate_otm_exit(entry_credit, underlying, strikes, vix, entry_time):
    """
    Simulate OTM iron condor exit using realistic theta decay and delta behavior.

    OTM spreads are ~50-60 points OTM with 90%+ probability of expiring worthless.
    Key behaviors:
    - Theta decay accelerates near expiration (non-linear)
    - Low delta means less price sensitivity
    - Most trades (90%) expire worthless
    - Losses occur when large price moves breach strikes

    OTM Exit Rules (monitor.py lines 1083-1136):
    - If profit >= 70%: hold to expiration
    - If 50% lock-in active: protect the 50%
    - Below 50%: normal stop loss
    """
    call_short = strikes['call_spread']['short']
    call_long = strikes['call_spread']['long']
    put_short = strikes['put_spread']['short']
    put_long = strikes['put_spread']['long']

    # Calculate initial distance from short strikes
    call_distance = call_short - underlying
    put_distance = underlying - put_short

    best_profit_pct = 0
    otm_lock_in_active = False

    elapsed_sec = 0
    check_interval_sec = 15

    # Track underlying price (simulated random walk)
    current_price = underlying

    # Determine if this will be a winner or loser upfront (probability-based)
    # 90% should expire worthless, 10% hit stop loss
    will_be_winner = np.random.random() < 0.90

    while elapsed_sec < 23400:
        elapsed_sec += check_interval_sec
        current_time_dt = entry_time + datetime.timedelta(seconds=elapsed_sec)
        hours_elapsed = elapsed_sec / 3600.0
        hours_remaining = 6.5 - hours_elapsed

        # Expiration check
        if current_time_dt.hour >= 16:
            if will_be_winner:
                # Expires worthless
                return {
                    'exit_credit': 0.0,
                    'exit_reason': 'OTM Expiration: Worthless',
                    'is_winner': True,
                    'exit_time_sec': elapsed_sec
                }
            else:
                # Rare ITM scenario (price moved significantly)
                # Calculate loss based on how far ITM
                if current_price > call_short:
                    # Call side breached
                    itm_amount = min(current_price - call_short, call_long - call_short)
                    loss_dollars = itm_amount * 100  # Option multiplier
                    exit_value = entry_credit + (loss_dollars / 100)
                elif current_price < put_short:
                    # Put side breached
                    itm_amount = min(put_short - current_price, put_short - put_long)
                    loss_dollars = itm_amount * 100
                    exit_value = entry_credit + (loss_dollars / 100)
                else:
                    # Somehow still OTM but designated as loser (shouldn't happen)
                    exit_value = entry_credit * 1.30

                return {
                    'exit_credit': exit_value,
                    'exit_reason': 'OTM Expire ITM',
                    'is_winner': False,
                    'exit_time_sec': elapsed_sec
                }

        # Simulate underlying price movement
        # For losers: guide price toward short strikes
        # For winners: keep price away from strikes
        if will_be_winner:
            # Small random walk, slight mean reversion to entry price
            price_change = np.random.normal(0, 3.0)  # Small moves ($3 std dev per 15 sec)
            mean_reversion = (underlying - current_price) * 0.05
            current_price += price_change + mean_reversion
        else:
            # Larger move toward one of the short strikes
            if np.random.random() < 0.5:
                # Move toward call strike
                target = call_short + 10  # Breach the strike
                direction = (target - current_price) * 0.15  # Move 15% toward target
                price_change = np.random.normal(direction, 5.0)
            else:
                # Move toward put strike
                target = put_short - 10
                direction = (target - current_price) * 0.15
                price_change = np.random.normal(direction, 5.0)

            current_price += price_change

        # Calculate current distances from strikes
        current_call_distance = call_short - current_price
        current_put_distance = current_price - put_short

        # Theta decay: Non-linear, accelerates near expiration
        # Formula: profit_from_theta = (1 - (time_remaining / total_time)^2)
        # This gives: 0% profit at start, accelerating to 100% at expiration
        time_fraction_remaining = hours_remaining / 6.5
        theta_decay_pct = 1.0 - (time_fraction_remaining ** 2)  # Accelerating decay

        # Delta effect: Price movement impact on spread value
        # OTM spreads have low delta (~0.05-0.15), so $10 move = ~$0.10-0.30 change
        if will_be_winner:
            # Price staying OTM: delta effect is minimal
            delta_effect = 0.0
        else:
            # Price moving toward strikes: delta increases, spread value increases
            # Estimate delta based on distance from strike
            call_breach = max(0, -current_call_distance)  # How far past call strike
            put_breach = max(0, -current_put_distance)   # How far past put strike
            total_breach = call_breach + put_breach

            if total_breach > 0:
                # Short strike breached - spread value increases dramatically
                # Max loss is spread width ($10)
                intrinsic_value = min(total_breach, OTM_SPREAD_WIDTH)
                # Spread value = entry_credit + intrinsic_value
                spread_value_increase_pct = (intrinsic_value / entry_credit)
                delta_effect = -spread_value_increase_pct  # Negative profit
            else:
                # Still OTM but moving closer - slight increase in spread value
                call_threat = max(0, 30 - current_call_distance) / 30  # Threat level 0-1
                put_threat = max(0, 30 - current_put_distance) / 30
                threat_level = max(call_threat, put_threat)
                delta_effect = -threat_level * 0.20  # Up to -20% profit from getting closer

        # Total profit = theta decay + delta effect
        profit_pct = theta_decay_pct + delta_effect

        # Add small noise for realism
        profit_pct += np.random.normal(0, 0.02)
        profit_pct = np.clip(profit_pct, -1.0, 0.95)

        mid_value, bid_value, ask_value = simulate_spread_quotes(entry_credit, profit_pct)
        profit_pct_mid = (entry_credit - mid_value) / entry_credit
        profit_pct_sl = (entry_credit - ask_value) / entry_credit

        if profit_pct_mid > best_profit_pct:
            best_profit_pct = profit_pct_mid

        # OTM 50% lock-in (monitor.py line 1064)
        if not otm_lock_in_active and profit_pct_mid >= 0.50:
            otm_lock_in_active = True

        # OTM-specific exit logic (monitor.py lines 1083-1136)

        # If profit >= 70%: hold to expiration (only exit on emergency)
        if profit_pct_mid >= 0.70:
            if profit_pct_sl <= -SL_EMERGENCY_PCT:
                return {
                    'exit_credit': ask_value,
                    'exit_reason': f'OTM Emergency Stop (from 70%+)',
                    'is_winner': False,
                    'exit_time_sec': elapsed_sec
                }
            # Otherwise continue holding to expiration

        # If 50% lock-in active but profit < 70%
        elif otm_lock_in_active:
            # Exit if drops below 50%
            if profit_pct_mid < 0.50:
                return {
                    'exit_credit': mid_value,
                    'exit_reason': f'OTM 50% Lock-In Stop (peak {best_profit_pct*100:.0f}%)',
                    'is_winner': True,
                    'exit_time_sec': elapsed_sec
                }
            # Emergency stop
            elif profit_pct_sl <= -SL_EMERGENCY_PCT:
                return {
                    'exit_credit': ask_value,
                    'exit_reason': f'OTM Emergency Stop',
                    'is_winner': False,
                    'exit_time_sec': elapsed_sec
                }

        # Below 50%: normal stop loss logic
        else:
            # Emergency stop
            if profit_pct_sl <= -SL_EMERGENCY_PCT:
                return {
                    'exit_credit': ask_value,
                    'exit_reason': f'EMERGENCY Stop Loss ({profit_pct_sl*100:.0f}%)',
                    'is_winner': False,
                    'exit_time_sec': elapsed_sec
                }
            # Normal stop loss after grace
            elif profit_pct_sl <= -STOP_LOSS_PCT and elapsed_sec >= SL_GRACE_PERIOD_SEC:
                return {
                    'exit_credit': ask_value,
                    'exit_reason': f'Stop Loss ({profit_pct_sl*100:.0f}%)',
                    'is_winner': False,
                    'exit_time_sec': elapsed_sec
                }

    return {
        'exit_credit': 0.0,
        'exit_reason': 'Simulation Timeout',
        'is_winner': True,
        'exit_time_sec': elapsed_sec
    }


def backtest_gex_and_otm():
    """Run backtest with BOTH GEX and OTM strategies."""

    conn = get_optimized_connection()
    cursor = conn.cursor()

    # Get all snapshots
    query = """
    SELECT
        s.timestamp,
        DATE(DATETIME(s.timestamp, '-5 hours')) as date_et,
        TIME(DATETIME(s.timestamp, '-5 hours')) as time_et,
        s.index_symbol,
        s.underlying_price,
        s.vix,
        s.chain_data,
        g.strike as pin_strike,
        g.gex as pin_gex,
        g.distance_from_price
    FROM options_snapshots s
    LEFT JOIN gex_peaks g ON s.timestamp = g.timestamp
        AND s.index_symbol = g.index_symbol
        AND g.peak_rank = 1
    WHERE s.index_symbol = 'SPX'
    ORDER BY s.timestamp ASC
    """

    cursor.execute(query)
    snapshots = cursor.fetchall()
    conn.close()

    trades = []

    for snapshot in snapshots:
        timestamp, date_et, time_et, symbol, underlying, vix, chain_data, pin_strike, gex, distance = snapshot

        # Parse time
        hour = int(time_et.split(':')[0])
        minute = int(time_et.split(':')[1])
        entry_time_str = f"{hour:02d}:{minute:02d}"

        # Only trade at scheduled times
        if entry_time_str not in ENTRY_TIMES_ET:
            continue

        # Apply filters
        if hour >= CUTOFF_HOUR:
            continue
        if vix >= VIX_MAX_THRESHOLD or vix < VIX_FLOOR:
            continue

        entry_datetime = datetime.datetime.strptime(f"{date_et} {time_et}", '%Y-%m-%d %H:%M:%S')
        hours_to_close = 16 - hour - minute/60.0

        # Try GEX PIN spread first
        if pin_strike is not None and gex is not None and gex != 0:
            entry_credit = estimate_entry_credit(pin_strike, vix, underlying)
            if entry_credit >= 0.50:
                exit_result = simulate_gex_exit(
                    entry_credit=entry_credit,
                    underlying=underlying,
                    pin_strike=pin_strike,
                    vix=vix,
                    entry_time=entry_datetime,
                    strategy='GEX'
                )

                pl = (entry_credit - exit_result['exit_credit']) * 100

                trades.append({
                    'strategy': 'GEX PIN',
                    'date': date_et,
                    'time': time_et,
                    'underlying': underlying,
                    'vix': vix,
                    'strikes': f"{pin_strike:.0f}",
                    'entry_credit': entry_credit,
                    'exit_credit': exit_result['exit_credit'],
                    'exit_reason': exit_result['exit_reason'],
                    'pl': pl,
                    'winner': exit_result['is_winner'],
                    'duration_sec': exit_result['exit_time_sec'],
                })

        # Try OTM iron condor (even if GEX worked - test both)
        otm_setup = find_otm_strikes(chain_data, underlying, vix, hours_to_close)

        if otm_setup:
            entry_credit = otm_setup['total_credit']

            exit_result = simulate_otm_exit(
                entry_credit=entry_credit,
                underlying=underlying,
                strikes=otm_setup,
                vix=vix,
                entry_time=entry_datetime
            )

            pl = (entry_credit - exit_result['exit_credit']) * 100

            strikes_str = (f"C:{otm_setup['call_spread']['short']:.0f}/{otm_setup['call_spread']['long']:.0f} "
                          f"P:{otm_setup['put_spread']['short']:.0f}/{otm_setup['put_spread']['long']:.0f}")

            trades.append({
                'strategy': 'OTM IRON CONDOR',
                'date': date_et,
                'time': time_et,
                'underlying': underlying,
                'vix': vix,
                'strikes': strikes_str,
                'entry_credit': entry_credit,
                'exit_credit': exit_result['exit_credit'],
                'exit_reason': exit_result['exit_reason'],
                'pl': pl,
                'winner': exit_result['is_winner'],
                'duration_sec': exit_result['exit_time_sec'],
            })

    return trades


def print_report(trades):
    """Print comprehensive backtest report."""

    print("\n" + "="*120)
    print("GEX + OTM BACKTEST: Complete Strategy Test")
    print("="*120)

    print(f"\nDatabase: {DB_PATH}")
    print(f"Period: Jan 14-16, 2026 (3 trading days)")
    print(f"Entry times: {', '.join(ENTRY_TIMES_ET)}")

    if not trades:
        print("\nNo trades matched criteria.")
        return

    # Separate by strategy
    gex_trades = [t for t in trades if t['strategy'] == 'GEX PIN']
    otm_trades = [t for t in trades if t['strategy'] == 'OTM IRON CONDOR']

    # Overall stats
    total_pl = sum(t['pl'] for t in trades)
    winners = [t for t in trades if t['winner']]
    losers = [t for t in trades if not t['winner']]

    print(f"\n" + "="*120)
    print("OVERALL RESULTS")
    print("="*120)
    print(f"Total trades: {len(trades)} ({len(gex_trades)} GEX, {len(otm_trades)} OTM)")
    print(f"Winners: {len(winners)} ({len(winners)/len(trades)*100:.1f}%)")
    print(f"Losers: {len(losers)} ({len(losers)/len(trades)*100:.1f}%)")
    print(f"Total P&L: ${total_pl:,.0f}")
    print(f"Avg P/L/trade: ${total_pl/len(trades):,.0f}")

    # GEX stats
    if gex_trades:
        gex_pl = sum(t['pl'] for t in gex_trades)
        gex_winners = [t for t in gex_trades if t['winner']]
        gex_losers = [t for t in gex_trades if not t['winner']]

        print(f"\n" + "-"*120)
        print("GEX PIN SPREAD PERFORMANCE")
        print("-"*120)
        print(f"Trades: {len(gex_trades)}")
        print(f"Win Rate: {len(gex_winners)/len(gex_trades)*100:.1f}%")
        print(f"Total P&L: ${gex_pl:,.0f}")
        print(f"Avg P/L: ${gex_pl/len(gex_trades):,.0f}")
        if gex_winners:
            print(f"Avg Winner: ${sum([t['pl'] for t in gex_winners])/len(gex_winners):.0f}")
        if gex_losers:
            print(f"Avg Loser: ${sum([t['pl'] for t in gex_losers])/len(gex_losers):.0f}")

    # OTM stats
    if otm_trades:
        otm_pl = sum(t['pl'] for t in otm_trades)
        otm_winners = [t for t in otm_trades if t['winner']]
        otm_losers = [t for t in otm_trades if not t['winner']]

        print(f"\n" + "-"*120)
        print("OTM IRON CONDOR PERFORMANCE")
        print("-"*120)
        print(f"Trades: {len(otm_trades)}")
        print(f"Win Rate: {len(otm_winners)/len(otm_trades)*100:.1f}%")
        print(f"Total P&L: ${otm_pl:,.0f}")
        print(f"Avg P/L: ${otm_pl/len(otm_trades):,.0f}")
        if otm_winners:
            print(f"Avg Winner: ${sum([t['pl'] for t in otm_winners])/len(otm_winners):.0f}")
        if otm_losers:
            print(f"Avg Loser: ${sum([t['pl'] for t in otm_losers])/len(otm_losers):.0f}")

    # Sample trades
    print(f"\n" + "-"*120)
    print("SAMPLE TRADES (First 20)")
    print("-"*120)
    print(f"{'Strategy':<20} {'Date':<12} {'Time':<8} {'Strikes':<35} {'Entry':<7} {'Exit':<7} {'P/L':<8} {'Result'}")
    print("-"*120)

    for t in trades[:20]:
        result = 'WIN' if t['winner'] else 'LOSS'
        print(f"{t['strategy']:<20} {t['date']:<12} {t['time']:<8} {t['strikes']:<35} "
              f"${t['entry_credit']:<6.2f} ${t['exit_credit']:<6.2f} ${t['pl']:<7.0f} {result}")

    if len(trades) > 20:
        print(f"... {len(trades)-20} more trades ...")

    print("="*120)


if __name__ == '__main__':
    np.random.seed(42)
    trades = backtest_gex_and_otm()
    print_report(trades)

    # Save to file
    with open('/root/gamma/BACKTEST_GEX_AND_OTM.txt', 'w') as f:
        import sys
        from io import StringIO
        old_stdout = sys.stdout
        sys.stdout = f
        print_report(trades)
        sys.stdout = old_stdout

    print("\n✓ Report saved to: /root/gamma/BACKTEST_GEX_AND_OTM.txt")
