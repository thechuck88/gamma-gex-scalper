#!/usr/bin/env python3
"""
GEX + OTM BWIC Backtest (2026-01-16)

BWIC Strategy: Broken Wing Iron Condor with GEX Directional Bias
- If GEX pin ABOVE price: Bullish → Break CALL side (5-wide), keep PUT side wide (10-wide)
- If GEX pin BELOW price: Bearish → Break PUT side (5-wide), keep CALL side wide (10-wide)

Logic: Break the side MORE LIKELY to be breached to cap max loss

Improved Parameters:
1. Trailing activation: 30%
2. Emergency stop: 25%
3. Entry times: 10:00-11:30 only
4. Strike conflict detection
"""

import sqlite3
import datetime
import numpy as np
import json
import math
from collections import defaultdict

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

# OTM BWIC Strategy
OTM_MIN_PROBABILITY = 0.90
OTM_MIN_CREDIT_TOTAL = 0.30  # Reduced from 0.40 (BWIC has lower credit)
OTM_MIN_CREDIT_PER_SIDE = 0.10  # Reduced from 0.15
OTM_STD_DEV_MULTIPLIER = 0.75

# BWIC spread widths
OTM_BROKEN_WING_WIDTH = 5   # Narrow side (risky direction)
OTM_NORMAL_WING_WIDTH = 10  # Wide side (safe direction)

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


def find_otm_bwic_strikes(chain_data, underlying, vix, hours_remaining, pin_strike):
    """
    Find OTM BWIC strikes with GEX directional bias.

    BWIC Logic:
    - If pin ABOVE underlying (bullish): Break CALL side, wide PUT side
    - If pin BELOW underlying (bearish): Break PUT side, wide CALL side

    Returns: dict with call_spread, put_spread, bias info
    """
    if isinstance(chain_data, str):
        chain = json.loads(chain_data)
    else:
        chain = chain_data

    std_move = calculate_expected_move(underlying, vix, hours_remaining)
    target_distance = std_move * OTM_STD_DEV_MULTIPLIER

    calls = [opt for opt in chain if opt['option_type'] == 'call']
    puts = [opt for opt in chain if opt['option_type'] == 'put']

    # Determine directional bias from GEX pin
    if pin_strike > underlying:
        # Bullish bias - price likely to move UP toward pin
        # BREAK CALL SIDE (narrow) to cap upside loss
        call_width = OTM_BROKEN_WING_WIDTH
        put_width = OTM_NORMAL_WING_WIDTH
        bias = "BULLISH"
        broken_side = "CALL"
    else:
        # Bearish bias - price likely to move DOWN toward pin
        # BREAK PUT SIDE (narrow) to cap downside loss
        call_width = OTM_NORMAL_WING_WIDTH
        put_width = OTM_BROKEN_WING_WIDTH
        bias = "BEARISH"
        broken_side = "PUT"

    # Find call spread
    call_short_target = underlying + target_distance
    call_long_target = call_short_target + call_width

    call_short_strike = min(calls, key=lambda x: abs(x['strike'] - call_short_target))['strike']
    call_long_strike = min(calls, key=lambda x: abs(x['strike'] - call_long_target))['strike']

    # Find put spread
    put_short_target = underlying - target_distance
    put_long_target = put_short_target - put_width

    put_short_strike = min(puts, key=lambda x: abs(x['strike'] - put_short_target))['strike']
    put_long_strike = min(puts, key=lambda x: abs(x['strike'] - put_long_target))['strike']

    # Get quotes
    call_short = next((c for c in calls if c['strike'] == call_short_strike), None)
    call_long = next((c for c in calls if c['strike'] == call_long_strike), None)
    put_short = next((p for p in puts if p['strike'] == put_short_strike), None)
    put_long = next((p for p in puts if p['strike'] == put_long_strike), None)

    if not all([call_short, call_long, put_short, put_long]):
        return None

    # Calculate credits
    call_spread_credit = call_short['bid'] - call_long['ask']
    put_spread_credit = put_short['bid'] - put_long['ask']
    total_credit = call_spread_credit + put_spread_credit

    # Check minimum credits (relaxed for BWIC)
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
            'credit': call_spread_credit,
            'width': call_width
        },
        'put_spread': {
            'short': put_short_strike,
            'long': put_long_strike,
            'credit': put_spread_credit,
            'width': put_width
        },
        'total_credit': total_credit,
        'target_distance': target_distance,
        'std_move': std_move,
        'bias': bias,
        'broken_side': broken_side,
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


# Import simulation functions from original backtest
from backtest_gex_and_otm import simulate_gex_exit, simulate_otm_exit


def backtest_gex_and_otm_bwic():
    """Run backtest with GEX and OTM BWIC strategies."""

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

        # Parse time
        hour = int(time_et.split(':')[0])
        minute = int(time_et.split(':')[1])
        entry_time_str = f"{hour:02d}:{minute:02d}"

        # Only trade at scheduled times
        if entry_time_str not in ENTRY_TIMES_ET:
            continue

        # Only 1 trade per date + entry time
        trade_key = (date_et, entry_time_str)
        if trade_key in traded_times:
            continue

        # Apply filters
        if hour >= CUTOFF_HOUR:
            continue
        if vix >= VIX_MAX_THRESHOLD or vix < VIX_FLOOR:
            continue

        # Must have GEX pin for both strategies
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

        otm_setup = find_otm_bwic_strikes(chain_data, underlying, vix, hours_to_close, pin_strike)

        # Check for strike conflicts
        has_conflict = False
        if gex_setup and otm_setup:
            gex_strikes = [
                gex_setup['pin_strike'] - 5,
                gex_setup['pin_strike'],
                gex_setup['pin_strike'] + 5
            ]

            otm_strikes = [
                otm_setup['call_spread']['short'],
                otm_setup['call_spread']['long'],
                otm_setup['put_spread']['short'],
                otm_setup['put_spread']['long']
            ]

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
                'conflict_skipped': 'Yes' if has_conflict else 'No',
                'bias': 'N/A',
                'broken_side': 'N/A'
            })

        # Execute OTM BWIC trade
        if take_otm:
            entry_credit = otm_setup['total_credit']

            exit_result = simulate_otm_exit(
                entry_credit=entry_credit,
                underlying=underlying,
                strikes=otm_setup,
                vix=vix,
                entry_time=entry_datetime
            )

            pl = (entry_credit - exit_result['exit_credit']) * 100

            # Format strikes with widths
            call_width = otm_setup['call_spread']['width']
            put_width = otm_setup['put_spread']['width']
            strikes_str = (f"C:{otm_setup['call_spread']['short']:.0f}/{otm_setup['call_spread']['long']:.0f}({call_width}w) "
                          f"P:{otm_setup['put_spread']['short']:.0f}/{otm_setup['put_spread']['long']:.0f}({put_width}w)")

            trades.append({
                'strategy': 'BWIC',
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
                'conflict_skipped': 'No',
                'bias': otm_setup['bias'],
                'broken_side': otm_setup['broken_side']
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
    print("GEX + OTM BWIC STRATEGY: ALL TRADES")
    print("="*220)
    print("\nIMPROVEMENTS:")
    print("  • BWIC: Broken wing on side MORE LIKELY to be breached (GEX directional bias)")
    print("  • Trailing activation: 30% (hold winners longer)")
    print("  • Emergency stop: 25% (tighter risk control)")
    print("  • Entry times: 10:00-11:30 only")
    print("  • Strike conflict detection enabled")

    if not trades:
        print("\nNo trades found.")
        return

    # Overall stats
    total_pl = sum(t['pl'] for t in trades)
    winners = [t for t in trades if t['winner']]
    losers = [t for t in trades if not t['winner']]

    gex_trades = [t for t in trades if t['strategy'] == 'GEX']
    bwic_trades = [t for t in trades if t['strategy'] == 'BWIC']

    print(f"\n" + "="*220)
    print("SUMMARY")
    print("="*220)
    print(f"Total trades: {len(trades)} ({len(gex_trades)} GEX, {len(bwic_trades)} BWIC)")
    print(f"Winners: {len(winners)} ({len(winners)/len(trades)*100:.1f}%)")
    print(f"Losers: {len(losers)} ({len(losers)/len(trades)*100:.1f}%)")
    print(f"Total P/L: ${total_pl:,.0f}")
    print(f"Avg P/L/trade: ${total_pl/len(trades):,.0f}")

    total_wins = sum(t['pl'] for t in winners)
    total_losses = abs(sum(t['pl'] for t in losers))
    pf = total_wins / total_losses if total_losses > 0 else float('inf')
    print(f"Profit Factor: {pf:.2f}")

    # Conflict statistics
    gex_skipped = [t for t in gex_trades if t.get('conflict_skipped') == 'Yes']
    print(f"\nStrike Conflicts:")
    print(f"  GEX trades skipped due to BWIC overlap: {len(gex_skipped)}")

    # BWIC bias analysis
    if bwic_trades:
        bullish_bwic = [t for t in bwic_trades if t['bias'] == 'BULLISH']
        bearish_bwic = [t for t in bwic_trades if t['bias'] == 'BEARISH']
        print(f"\nBWIC Directional Bias:")
        print(f"  Bullish (call broken): {len(bullish_bwic)} trades")
        print(f"  Bearish (put broken): {len(bearish_bwic)} trades")

    # Print all trades
    print(f"\n" + "="*220)
    print("ALL TRADES")
    print("="*220)

    header = (
        f"{'#':<4} {'Strat':<6} {'Date':<10} {'Time':<8} {'SPX':<8} {'VIX':<5} "
        f"{'Strikes':<40} {'Entry':<6} {'Exit':<6} {'P/L':<7} {'Dur':<8} "
        f"{'Exit Reason':<35} {'W/L':<4} {'Bias':<8} {'Broken':<6}"
    )
    print(header)
    print("-"*220)

    for i, t in enumerate(trades, 1):
        duration = format_duration(t['duration_sec'])
        result = 'WIN' if t['winner'] else 'LOSS'

        row = (
            f"{i:<4} {t['strategy']:<6} {t['date']:<10} {t['time']:<8} "
            f"${t['underlying']:<7.2f} {t['vix']:<5.2f} {t['strikes']:<40} "
            f"${t['entry_credit']:<5.2f} ${t['exit_credit']:<5.2f} "
            f"${t['pl']:>6.0f} {duration:<8} {t['exit_reason']:<35} {result:<4} "
            f"{t['bias']:<8} {t['broken_side']:<6}"
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

    if bwic_trades:
        bwic_pl = sum(t['pl'] for t in bwic_trades)
        bwic_winners = [t for t in bwic_trades if t['winner']]
        bwic_losers = [t for t in bwic_trades if not t['winner']]

        print("\nOTM BWIC PERFORMANCE")
        print("-"*80)
        print(f"Trades: {len(bwic_trades)} | Win Rate: {len(bwic_winners)/len(bwic_trades)*100:.1f}% | Total P&L: ${bwic_pl:,.0f}")
        if bwic_winners:
            print(f"Avg Winner: ${sum([t['pl'] for t in bwic_winners])/len(bwic_winners):.0f}")
        if bwic_losers:
            print(f"Avg Loser: ${sum([t['pl'] for t in bwic_losers])/len(bwic_losers):.0f}")

        # Bias-specific performance
        if bullish_bwic:
            bull_pl = sum(t['pl'] for t in bullish_bwic)
            bull_wr = sum(1 for t in bullish_bwic if t['winner']) / len(bullish_bwic) * 100
            print(f"\n  Bullish BWIC (call broken): {len(bullish_bwic)} trades, {bull_wr:.1f}% WR, ${bull_pl:,.0f} P/L")

        if bearish_bwic:
            bear_pl = sum(t['pl'] for t in bearish_bwic)
            bear_wr = sum(1 for t in bearish_bwic if t['winner']) / len(bearish_bwic) * 100
            print(f"  Bearish BWIC (put broken): {len(bearish_bwic)} trades, {bear_wr:.1f}% WR, ${bear_pl:,.0f} P/L")


if __name__ == '__main__':
    np.random.seed(42)
    trades = backtest_gex_and_otm_bwic()
    print_horizontal_report(trades)

    # Save to file
    with open('/root/gamma/BACKTEST_GEX_BWIC_COMPLETE.txt', 'w') as f:
        import sys
        old_stdout = sys.stdout
        sys.stdout = f
        print_horizontal_report(trades)
        sys.stdout = old_stdout

    print("\n✓ Complete report saved to: /root/gamma/BACKTEST_GEX_BWIC_COMPLETE.txt")
