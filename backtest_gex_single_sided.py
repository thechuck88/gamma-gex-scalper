#!/usr/bin/env python3
"""
GEX + Single-Sided OTM Backtest (2026-01-16)

Single-Sided Strategy: Use GEX pin direction to pick ONE side only
- If GEX pin ABOVE price (bullish): Sell PUT spread (bet price won't fall)
- If GEX pin BELOW price (bearish): Sell CALL spread (bet price won't rise)

Benefits vs Iron Condor:
- Lower margin requirement (only 1 spread)
- Simpler management (only track 1 side)
- Clearer directional bet
- Higher probability on chosen side

Improved Parameters:
- Trailing activation: 30%
- Emergency stop: 25%
- Entry times: 10:00-11:30 only
- Strike conflict detection
"""

import sqlite3
import datetime
import numpy as np
import json
import math

DB_PATH = "/root/gamma/data/gex_blackbox.db"

# ============================================================================
# IMPROVED PARAMETERS
# ============================================================================

# Profit targets
PROFIT_TARGET_PCT = 0.50
PROFIT_TARGET_MEDIUM = 0.60

# Stop loss
STOP_LOSS_PCT = 0.15

# VIX filters
VIX_MAX_THRESHOLD = 20
VIX_FLOOR = 13.0

# Trailing stop (IMPROVED)
TRAILING_STOP_ENABLED = True
TRAILING_TRIGGER_PCT = 0.30
TRAILING_LOCK_IN_PCT = 0.20
TRAILING_DISTANCE_MIN = 0.10
TRAILING_TIGHTEN_RATE = 0.4

# Stop loss grace period (IMPROVED)
SL_GRACE_PERIOD_SEC = 540
SL_EMERGENCY_PCT = 0.25

# Progressive hold-to-expiration
PROGRESSIVE_HOLD_ENABLED = True
HOLD_PROFIT_THRESHOLD = 0.80
HOLD_VIX_MAX = 17
HOLD_MIN_TIME_LEFT_HOURS = 1.0
HOLD_MIN_ENTRY_DISTANCE = 8

# Single-Sided Strategy
OTM_MIN_PROBABILITY = 0.90
OTM_MIN_CREDIT = 0.20  # Minimum credit for single spread
OTM_STD_DEV_MULTIPLIER = 0.75  # Distance from price
OTM_SPREAD_WIDTH = 10  # Width of spread

# Progressive TP schedule
PROGRESSIVE_TP_SCHEDULE = [
    (0.0, 0.50), (0.5, 0.55), (1.0, 0.60),
    (2.0, 0.70), (3.0, 0.80), (4.0, 0.90),
]

# Entry times (IMPROVED)
ENTRY_TIMES_ET = ["10:00", "10:30", "11:00", "11:30"]
CUTOFF_HOUR = 12
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
    time_fraction = hours_remaining / (252 * 6.5)
    time_adjusted_vol = implied_vol * math.sqrt(time_fraction)
    expected_move = price * time_adjusted_vol
    return expected_move


def find_single_sided_spread(chain_data, underlying, vix, hours_remaining, pin_strike):
    """
    Find single-sided OTM spread based on GEX directional bias.

    Logic:
    - If pin ABOVE underlying (bullish): Sell PUT spread
    - If pin BELOW underlying (bearish): Sell CALL spread

    Returns: dict with spread info or None
    """
    if isinstance(chain_data, str):
        chain = json.loads(chain_data)
    else:
        chain = chain_data

    std_move = calculate_expected_move(underlying, vix, hours_remaining)
    target_distance = std_move * OTM_STD_DEV_MULTIPLIER

    calls = [opt for opt in chain if opt['option_type'] == 'call']
    puts = [opt for opt in chain if opt['option_type'] == 'put']

    # Determine direction from GEX pin
    if pin_strike > underlying:
        # Bullish: Price likely to move UP toward pin
        # Sell PUT spread (bet price won't fall)
        direction = "BULLISH"
        side = "PUT"

        put_short_target = underlying - target_distance
        put_long_target = put_short_target - OTM_SPREAD_WIDTH

        put_short_strike = min(puts, key=lambda x: abs(x['strike'] - put_short_target))['strike']
        put_long_strike = min(puts, key=lambda x: abs(x['strike'] - put_long_target))['strike']

        put_short = next((p for p in puts if p['strike'] == put_short_strike), None)
        put_long = next((p for p in puts if p['strike'] == put_long_strike), None)

        if not all([put_short, put_long]):
            return None

        credit = put_short['bid'] - put_long['ask']

        if credit < OTM_MIN_CREDIT:
            return None

        return {
            'side': side,
            'direction': direction,
            'short_strike': put_short_strike,
            'long_strike': put_long_strike,
            'credit': credit,
            'width': OTM_SPREAD_WIDTH,
            'distance_otm': underlying - put_short_strike,
            'pin_strike': pin_strike
        }

    else:
        # Bearish: Price likely to move DOWN toward pin
        # Sell CALL spread (bet price won't rise)
        direction = "BEARISH"
        side = "CALL"

        call_short_target = underlying + target_distance
        call_long_target = call_short_target + OTM_SPREAD_WIDTH

        call_short_strike = min(calls, key=lambda x: abs(x['strike'] - call_short_target))['strike']
        call_long_strike = min(calls, key=lambda x: abs(x['strike'] - call_long_target))['strike']

        call_short = next((c for c in calls if c['strike'] == call_short_strike), None)
        call_long = next((c for c in calls if c['strike'] == call_long_strike), None)

        if not all([call_short, call_long]):
            return None

        credit = call_short['bid'] - call_long['ask']

        if credit < OTM_MIN_CREDIT:
            return None

        return {
            'side': side,
            'direction': direction,
            'short_strike': call_short_strike,
            'long_strike': call_long_strike,
            'credit': credit,
            'width': OTM_SPREAD_WIDTH,
            'distance_otm': call_short_strike - underlying,
            'pin_strike': pin_strike
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


def simulate_single_sided_exit(entry_credit, underlying, spread_setup, vix, entry_time):
    """
    Simulate single-sided spread exit.

    Single spread behaves like half an iron condor - simpler to model.
    Uses same exit logic as OTM IC but only tracking one side.
    """
    spread_width = spread_setup['width']
    short_strike = spread_setup['short_strike']
    long_strike = spread_setup['long_strike']
    side = spread_setup['side']

    best_profit_pct = 0
    otm_lock_in_active = False

    elapsed_sec = 0
    check_interval_sec = 15

    # Track underlying price
    current_price = underlying

    # Determine if this will be a winner (probability-based)
    will_be_winner = np.random.random() < 0.90  # 90% probability OTM

    while elapsed_sec < 23400:
        elapsed_sec += check_interval_sec
        current_time_dt = entry_time + datetime.timedelta(seconds=elapsed_sec)
        hours_elapsed = elapsed_sec / 3600.0
        hours_remaining = 6.5 - hours_elapsed

        # Expiration check
        if current_time_dt.hour >= 16:
            if will_be_winner:
                return {
                    'exit_credit': 0.0,
                    'exit_reason': 'OTM Expiration: Worthless',
                    'is_winner': True,
                    'exit_time_sec': elapsed_sec
                }
            else:
                # Breached - calculate loss
                if side == 'CALL' and current_price > short_strike:
                    itm_amount = min(current_price - short_strike, long_strike - short_strike)
                    exit_value = entry_credit + (itm_amount * 100 / 100)
                elif side == 'PUT' and current_price < short_strike:
                    itm_amount = min(short_strike - current_price, short_strike - long_strike)
                    exit_value = entry_credit + (itm_amount * 100 / 100)
                else:
                    exit_value = entry_credit * 1.30

                return {
                    'exit_credit': exit_value,
                    'exit_reason': 'OTM Expire ITM',
                    'is_winner': False,
                    'exit_time_sec': elapsed_sec
                }

        # Simulate price movement
        if will_be_winner:
            # Small random walk away from short strike
            price_change = np.random.normal(0, 3.0)
            current_price += price_change
        else:
            # Move toward breach
            if side == 'CALL':
                target = short_strike + 10
            else:
                target = short_strike - 10
            direction = (target - current_price) * 0.15
            price_change = np.random.normal(direction, 5.0)
            current_price += price_change

        # Calculate distance from short strike
        if side == 'CALL':
            current_distance = short_strike - current_price
        else:
            current_distance = current_price - short_strike

        # Theta decay
        time_fraction_remaining = hours_remaining / 6.5
        theta_decay_pct = 1.0 - (time_fraction_remaining ** 2)

        # Delta effect
        if will_be_winner:
            delta_effect = 0.0
        else:
            if current_distance < 0:  # Breached
                breach_amount = abs(current_distance)
                intrinsic_value = min(breach_amount, spread_width)
                spread_value_increase_pct = intrinsic_value / entry_credit
                delta_effect = -spread_value_increase_pct
            else:
                threat_level = max(0, 30 - current_distance) / 30
                delta_effect = -threat_level * 0.20

        profit_pct = theta_decay_pct + delta_effect
        profit_pct += np.random.normal(0, 0.02)
        profit_pct = np.clip(profit_pct, -1.0, 0.95)

        mid_value, bid_value, ask_value = simulate_spread_quotes(entry_credit, profit_pct)
        profit_pct_mid = (entry_credit - mid_value) / entry_credit
        profit_pct_sl = (entry_credit - ask_value) / entry_credit

        if profit_pct_mid > best_profit_pct:
            best_profit_pct = profit_pct_mid

        # 50% lock-in
        if not otm_lock_in_active and profit_pct_mid >= 0.50:
            otm_lock_in_active = True

        # Exit logic (same as OTM IC)
        if profit_pct_mid >= 0.70:
            if profit_pct_sl <= -SL_EMERGENCY_PCT:
                return {
                    'exit_credit': ask_value,
                    'exit_reason': 'EMERGENCY Stop (from 70%+)',
                    'is_winner': False,
                    'exit_time_sec': elapsed_sec
                }

        elif otm_lock_in_active:
            if profit_pct_mid < 0.50:
                return {
                    'exit_credit': mid_value,
                    'exit_reason': f'50% Lock-In Stop (peak {best_profit_pct*100:.0f}%)',
                    'is_winner': True,
                    'exit_time_sec': elapsed_sec
                }
            elif profit_pct_sl <= -SL_EMERGENCY_PCT:
                return {
                    'exit_credit': ask_value,
                    'exit_reason': 'EMERGENCY Stop',
                    'is_winner': False,
                    'exit_time_sec': elapsed_sec
                }

        else:
            if profit_pct_sl <= -SL_EMERGENCY_PCT:
                return {
                    'exit_credit': ask_value,
                    'exit_reason': f'EMERGENCY Stop Loss ({profit_pct_sl*100:.0f}%)',
                    'is_winner': False,
                    'exit_time_sec': elapsed_sec
                }
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


# Import GEX simulation from original
from backtest_gex_and_otm import simulate_gex_exit


def backtest_gex_and_single_sided():
    """Run backtest with GEX and single-sided OTM spreads."""

    conn = get_optimized_connection()
    cursor = conn.cursor()

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
    traded_times = set()

    for snapshot in snapshots:
        timestamp, date_et, time_et, symbol, underlying, vix, chain_data, pin_strike, gex, distance = snapshot

        hour = int(time_et.split(':')[0])
        minute = int(time_et.split(':')[1])
        entry_time_str = f"{hour:02d}:{minute:02d}"

        if entry_time_str not in ENTRY_TIMES_ET:
            continue

        trade_key = (date_et, entry_time_str)
        if trade_key in traded_times:
            continue

        if hour >= CUTOFF_HOUR:
            continue
        if vix >= VIX_MAX_THRESHOLD or vix < VIX_FLOOR:
            continue

        if pin_strike is None or gex is None or gex == 0:
            continue

        entry_datetime = datetime.datetime.strptime(f"{date_et} {time_et}", '%Y-%m-%d %H:%M:%S')
        hours_to_close = 16 - hour - minute/60.0

        traded_times.add(trade_key)

        # Get both setups
        gex_setup = None
        entry_credit = estimate_entry_credit(pin_strike, vix, underlying)
        if entry_credit >= 0.50:
            gex_setup = {
                'pin_strike': pin_strike,
                'entry_credit': entry_credit
            }

        otm_setup = find_single_sided_spread(chain_data, underlying, vix, hours_to_close, pin_strike)

        # Check for strike conflicts
        has_conflict = False
        if gex_setup and otm_setup:
            gex_strikes = [
                gex_setup['pin_strike'] - 5,
                gex_setup['pin_strike'],
                gex_setup['pin_strike'] + 5
            ]

            otm_strikes = [otm_setup['short_strike'], otm_setup['long_strike']]
            has_conflict = any(strike in otm_strikes for strike in gex_strikes)

        # Decision logic
        take_gex = gex_setup is not None and (not has_conflict or otm_setup is None)
        take_otm = otm_setup is not None

        # Execute GEX trade
        if take_gex:
            exit_result = simulate_gex_exit(
                entry_credit=gex_setup['entry_credit'],
                underlying=underlying,
                pin_strike=gex_setup['pin_strike'],
                vix=vix,
                entry_time=entry_datetime
            )

            pl = (gex_setup['entry_credit'] - exit_result['exit_credit']) * 100

            trades.append({
                'strategy': 'GEX',
                'date': date_et,
                'time': time_et,
                'underlying': underlying,
                'vix': vix,
                'strikes': f"{gex_setup['pin_strike']:.0f}",
                'entry_credit': gex_setup['entry_credit'],
                'exit_credit': exit_result['exit_credit'],
                'exit_reason': exit_result['exit_reason'],
                'pl': pl,
                'winner': exit_result['is_winner'],
                'duration_sec': exit_result['exit_time_sec'],
                'direction': 'N/A',
                'side': 'N/A',
                'distance_otm': 0
            })

        # Execute single-sided OTM trade
        if take_otm:
            exit_result = simulate_single_sided_exit(
                entry_credit=otm_setup['credit'],
                underlying=underlying,
                spread_setup=otm_setup,
                vix=vix,
                entry_time=entry_datetime
            )

            pl = (otm_setup['credit'] - exit_result['exit_credit']) * 100

            strikes_str = f"{otm_setup['side']}: {otm_setup['short_strike']:.0f}/{otm_setup['long_strike']:.0f}"

            trades.append({
                'strategy': 'SS-OTM',
                'date': date_et,
                'time': time_et,
                'underlying': underlying,
                'vix': vix,
                'strikes': strikes_str,
                'entry_credit': otm_setup['credit'],
                'exit_credit': exit_result['exit_credit'],
                'exit_reason': exit_result['exit_reason'],
                'pl': pl,
                'winner': exit_result['is_winner'],
                'duration_sec': exit_result['exit_time_sec'],
                'direction': otm_setup['direction'],
                'side': otm_setup['side'],
                'distance_otm': otm_setup['distance_otm']
            })

    return trades


def format_duration(seconds):
    """Convert seconds to human-readable duration."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def print_horizontal_report(trades):
    """Print trades in horizontal table format."""

    print("\n" + "="*220)
    print("GEX + SINGLE-SIDED OTM STRATEGY: ALL TRADES")
    print("="*220)
    print("\nSTRATEGY:")
    print("  • Single-sided OTM: Sell PUT spread (bullish) OR CALL spread (bearish)")
    print("  • Direction from GEX pin: Pin above = bullish → PUT spread | Pin below = bearish → CALL spread")
    print("  • Lower margin than IC (only 1 spread)")
    print("  • Trailing activation: 30% | Emergency stop: 25%")
    print("  • Entry times: 10:00-11:30 only")

    if not trades:
        print("\nNo trades found.")
        return

    total_pl = sum(t['pl'] for t in trades)
    winners = [t for t in trades if t['winner']]
    losers = [t for t in trades if not t['winner']]

    gex_trades = [t for t in trades if t['strategy'] == 'GEX']
    otm_trades = [t for t in trades if t['strategy'] == 'SS-OTM']

    print(f"\n" + "="*220)
    print("SUMMARY")
    print("="*220)
    print(f"Total trades: {len(trades)} ({len(gex_trades)} GEX, {len(otm_trades)} Single-Sided OTM)")
    print(f"Winners: {len(winners)} ({len(winners)/len(trades)*100:.1f}%)")
    print(f"Losers: {len(losers)} ({len(losers)/len(trades)*100:.1f}%)")
    print(f"Total P/L: ${total_pl:,.0f}")
    print(f"Avg P/L/trade: ${total_pl/len(trades):,.0f}")

    total_wins = sum(t['pl'] for t in winners)
    total_losses = abs(sum(t['pl'] for t in losers))
    pf = total_wins / total_losses if total_losses > 0 else float('inf')
    print(f"Profit Factor: {pf:.2f}")

    # Directional analysis
    if otm_trades:
        bullish_otm = [t for t in otm_trades if t['direction'] == 'BULLISH']
        bearish_otm = [t for t in otm_trades if t['direction'] == 'BEARISH']
        print(f"\nDirectional Breakdown:")
        print(f"  Bullish (PUT spreads): {len(bullish_otm)} trades")
        print(f"  Bearish (CALL spreads): {len(bearish_otm)} trades")

    # Print all trades
    print(f"\n" + "="*220)
    print("ALL TRADES")
    print("="*220)

    header = (
        f"{'#':<4} {'Strat':<8} {'Date':<10} {'Time':<8} {'SPX':<8} {'VIX':<5} "
        f"{'Strikes':<25} {'Entry':<6} {'Exit':<6} {'P/L':<7} {'Dur':<8} "
        f"{'Exit Reason':<35} {'W/L':<4} {'Dir':<8} {'OTM':<6}"
    )
    print(header)
    print("-"*220)

    for i, t in enumerate(trades, 1):
        duration = format_duration(t['duration_sec'])
        result = 'WIN' if t['winner'] else 'LOSS'
        otm_dist = f"{t['distance_otm']:.0f}pt" if t['distance_otm'] > 0 else "N/A"

        row = (
            f"{i:<4} {t['strategy']:<8} {t['date']:<10} {t['time']:<8} "
            f"${t['underlying']:<7.2f} {t['vix']:<5.2f} {t['strikes']:<25} "
            f"${t['entry_credit']:<5.2f} ${t['exit_credit']:<5.2f} "
            f"${t['pl']:>6.0f} {duration:<8} {t['exit_reason']:<35} {result:<4} "
            f"{t['direction']:<8} {otm_dist:<6}"
        )
        print(row)

    print("="*220)

    # Strategy breakdown
    if gex_trades:
        gex_pl = sum(t['pl'] for t in gex_trades)
        gex_winners = [t for t in gex_trades if t['winner']]
        gex_losers = [t for t in gex_trades if not t['winner']]

        print("\nGEX PIN SPREAD PERFORMANCE")
        print("-"*80)
        print(f"Trades: {len(gex_trades)} | Win Rate: {len(gex_winners)/len(gex_trades)*100:.1f}% | Total P&L: ${gex_pl:,.0f}")
        if gex_winners:
            print(f"Avg Winner: ${sum([t['pl'] for t in gex_winners])/len(gex_winners):.0f}")
        if gex_losers:
            print(f"Avg Loser: ${sum([t['pl'] for t in gex_losers])/len(gex_losers):.0f}")

    if otm_trades:
        otm_pl = sum(t['pl'] for t in otm_trades)
        otm_winners = [t for t in otm_trades if t['winner']]
        otm_losers = [t for t in otm_trades if not t['winner']]

        print("\nSINGLE-SIDED OTM PERFORMANCE")
        print("-"*80)
        print(f"Trades: {len(otm_trades)} | Win Rate: {len(otm_winners)/len(otm_trades)*100:.1f}% | Total P&L: ${otm_pl:,.0f}")
        if otm_winners:
            print(f"Avg Winner: ${sum([t['pl'] for t in otm_winners])/len(otm_winners):.0f}")
        if otm_losers:
            print(f"Avg Loser: ${sum([t['pl'] for t in otm_losers])/len(otm_losers):.0f}")

        if bullish_otm:
            bull_pl = sum(t['pl'] for t in bullish_otm)
            bull_wr = sum(1 for t in bullish_otm if t['winner']) / len(bullish_otm) * 100
            print(f"\n  Bullish (PUT spreads): {len(bullish_otm)} trades, {bull_wr:.1f}% WR, ${bull_pl:,.0f} P/L")

        if bearish_otm:
            bear_pl = sum(t['pl'] for t in bearish_otm)
            bear_wr = sum(1 for t in bearish_otm if t['winner']) / len(bearish_otm) * 100
            print(f"  Bearish (CALL spreads): {len(bearish_otm)} trades, {bear_wr:.1f}% WR, ${bear_pl:,.0f} P/L")


if __name__ == '__main__':
    np.random.seed(42)
    trades = backtest_gex_and_single_sided()
    print_horizontal_report(trades)

    # Save to file
    with open('/root/gamma/BACKTEST_GEX_SINGLE_SIDED_COMPLETE.txt', 'w') as f:
        import sys
        old_stdout = sys.stdout
        sys.stdout = f
        print_horizontal_report(trades)
        sys.stdout = old_stdout

    print("\n✓ Complete report saved to: /root/gamma/BACKTEST_GEX_SINGLE_SIDED_COMPLETE.txt")
