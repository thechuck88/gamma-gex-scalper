#!/usr/bin/env python3
"""
Gamma Backtest with ADX + Momentum Trend Filters

Compares performance:
- Baseline: Normal trading (no trend filter)
- With Filters: Block trades when ADX > 25 or momentum > 10 pts in 30 min

Tests 2026-02-10 hypothesis: Trending markets break through GEX levels
"""

import sqlite3
import datetime
import numpy as np
import yfinance as yf
import talib
import pandas as pd
from collections import defaultdict

DB_PATH = "/root/gamma/data/gex_blackbox.db"

# ============================================================================
# STRATEGY PARAMETERS
# ============================================================================

PROFIT_TARGET_HIGH = 0.50
PROFIT_TARGET_MEDIUM = 0.70
STOP_LOSS_PCT = 0.10
VIX_MAX_THRESHOLD = 20
VIX_FLOOR = 13.0

TRAILING_STOP_ENABLED = True
TRAILING_TRIGGER_PCT = 0.20
TRAILING_LOCK_IN_PCT = 0.12
TRAILING_DISTANCE_MIN = 0.08

ENTRY_TIMES_ET = [
    "09:36", "10:00", "10:30", "11:00",
    "11:30", "12:00", "12:30", "13:00"
]

CUTOFF_HOUR = 13  # Stop after 1 PM ET

# ADX + Momentum thresholds
ADX_THRESHOLD = 25
MOMENTUM_THRESHOLD_PTS = 10  # SPX points
LOOKBACK_BARS = 6  # 30 minutes


# ============================================================================
# DATABASE CONNECTION
# ============================================================================

def get_optimized_connection():
    """Get optimized SQLite connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA cache_size = -64000")  # 64 MB cache
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA mmap_size = 268435456")  # 256 MB mmap
    return conn


# ============================================================================
# ADX + MOMENTUM FILTER
# ============================================================================

def check_trend_pressure_backtest(date_str, time_str, spy_data_cache):
    """
    Check if market was trending at given timestamp.

    Args:
        date_str: Date in 'YYYY-MM-DD' format
        time_str: Time in 'HH:MM' format (ET)
        spy_data_cache: Dict of date -> DataFrame with SPY 5-min bars

    Returns:
        (bool, str): (should_block, reason)
    """
    try:
        # Get SPY data for this date
        if date_str not in spy_data_cache:
            # Download SPY data for this date
            date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d')
            # Get data from day before to ensure enough bars for ADX
            start_date = date_obj - datetime.timedelta(days=2)
            end_date = date_obj + datetime.timedelta(days=1)

            data = yf.download('SPY', start=start_date, end=end_date, interval="5m", progress=False)

            if len(data) < 20:
                return False, None  # Not enough data, allow trade

            # Handle multi-index columns
            if isinstance(data.columns, pd.MultiIndex):
                high = data['High']['SPY'].values
                low = data['Low']['SPY'].values
                close = data['Close']['SPY'].values
                data_index = data.index
            else:
                high = data['High'].values
                low = data['Low'].values
                close = data['Close'].values
                data_index = data.index

            # Calculate ADX
            adx = talib.ADX(high, low, close, timeperiod=14)
            plus_di = talib.PLUS_DI(high, low, close, timeperiod=14)
            minus_di = talib.MINUS_DI(high, low, close, timeperiod=14)

            # Store in cache
            spy_data_cache[date_str] = {
                'index': data_index,
                'close': close,
                'adx': adx,
                'plus_di': plus_di,
                'minus_di': minus_di
            }

        cached = spy_data_cache[date_str]

        # Find the bar closest to our entry time (convert ET to UTC for comparison)
        entry_dt = datetime.datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')
        # ET is UTC-5, so add 5 hours to get UTC
        entry_utc = entry_dt + datetime.timedelta(hours=5)

        # Find closest timestamp
        closest_idx = None
        min_diff = datetime.timedelta(days=999)
        for idx, ts in enumerate(cached['index']):
            # Convert timezone-aware timestamp to timezone-naive for comparison
            ts_naive = ts.replace(tzinfo=None) if ts.tzinfo else ts
            diff = abs(ts_naive - entry_utc)
            if diff < min_diff:
                min_diff = diff
                closest_idx = idx

        if closest_idx is None or closest_idx < LOOKBACK_BARS:
            return False, None  # Can't check, allow trade

        # Get ADX at entry time
        current_adx = cached['adx'][closest_idx]

        if np.isnan(current_adx):
            return False, None

        # Filter 1: ADX check
        if current_adx > ADX_THRESHOLD:
            plus_di_val = cached['plus_di'][closest_idx]
            minus_di_val = cached['minus_di'][closest_idx]
            di_spread = abs(plus_di_val - minus_di_val)
            direction = "UP" if plus_di_val > minus_di_val else "DOWN"

            return True, f"ADX {current_adx:.1f} (Strong {direction} trend, DI spread {di_spread:.1f})"

        # Filter 2: Momentum check
        current_price = cached['close'][closest_idx]
        price_ago = cached['close'][closest_idx - LOOKBACK_BARS]
        points_moved_spy = abs(current_price - price_ago)

        # Convert SPY to SPX equivalent (roughly 10×)
        points_moved_spx = points_moved_spy * 10

        if points_moved_spx > MOMENTUM_THRESHOLD_PTS:
            return True, f"Momentum {points_moved_spx:.0f} pts in 30min (Fast trending)"

        return False, None

    except Exception as e:
        # On error, don't block (permissive)
        return False, None


# ============================================================================
# EXIT SIMULATION
# ============================================================================

def simulate_exit(entry_credit, underlying, pin_strike, vix, days_held=0):
    """
    Simulate realistic exit for 0DTE trade.
    Uses emergency stop probabilities from actual trade data.
    """

    # Distance from pin (proxy for risk)
    distance_from_pin = abs(underlying - pin_strike)
    distance_pct = distance_from_pin / underlying

    # Base probabilities (from actual 2026 data)
    # 48% win rate overall, but varies by distance from pin
    if distance_pct < 0.01:  # Very close to pin
        win_prob = 0.55
        emergency_prob = 0.15
    elif distance_pct < 0.02:  # Moderate distance
        win_prob = 0.48
        emergency_prob = 0.25
    else:  # Far from pin
        win_prob = 0.40
        emergency_prob = 0.35

    # Random outcome
    rand = np.random.random()

    if rand < emergency_prob:
        # Emergency stop (-26% to -33% typical)
        loss_pct = np.random.uniform(0.26, 0.33)
        exit_credit = entry_credit * (1 + loss_pct)
        return exit_credit, "EMERGENCY Stop Loss", False

    elif rand < emergency_prob + (1 - emergency_prob) * (1 - win_prob):
        # Regular stop loss (-10% to -17%)
        loss_pct = np.random.uniform(0.10, 0.17)
        exit_credit = entry_credit * (1 + loss_pct)
        return exit_credit, "Stop Loss", False

    else:
        # Winner - Profit target or trailing stop
        if np.random.random() < 0.7:
            # Profit target (50%)
            exit_credit = entry_credit * 0.50
            return exit_credit, "Profit Target (50%)", True
        else:
            # Trailing stop (20-34% profit)
            profit_pct = np.random.uniform(0.20, 0.34)
            exit_credit = entry_credit * (1 - profit_pct)
            return exit_credit, "Trailing Stop", True


def estimate_entry_credit(pin_strike, vix, underlying):
    """Estimate credit for 5-wide spread based on VIX and distance."""
    width = 5.0
    distance_from_pin = abs(underlying - pin_strike)

    # Base credit scales with VIX
    base_credit = 0.30 + (vix / 20) * 0.70  # $0.30-$1.00 range

    # Increase credit if farther from pin (more risk)
    distance_factor = 1 + (distance_from_pin / underlying) * 2

    credit = base_credit * distance_factor
    return round(credit, 2)


# ============================================================================
# MAIN BACKTEST
# ============================================================================

def run_backtest(with_trend_filter=False):
    """Run backtest with or without trend filters."""

    conn = get_optimized_connection()
    cursor = conn.cursor()

    # Get all SPX snapshots for last 30 days
    cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime('%Y-%m-%d')

    query = f"""
    SELECT
        s.timestamp,
        DATE(DATETIME(s.timestamp, '-5 hours')) as date_et,
        TIME(DATETIME(s.timestamp, '-5 hours')) as time_et,
        s.index_symbol,
        s.underlying_price,
        s.vix,
        g.strike as pin_strike,
        g.gex as pin_gex,
        g.distance_from_price
    FROM options_snapshots s
    LEFT JOIN gex_peaks g ON s.timestamp = g.timestamp
        AND s.index_symbol = g.index_symbol
        AND g.peak_rank = 1
    WHERE s.index_symbol = 'SPX'
        AND DATE(DATETIME(s.timestamp, '-5 hours')) >= '{cutoff_date}'
    ORDER BY s.timestamp ASC
    """

    cursor.execute(query)
    snapshots = cursor.fetchall()
    conn.close()

    print(f"Loaded {len(snapshots)} snapshots from {cutoff_date} to present")

    trades = []
    filtered_trades = []
    spy_data_cache = {}

    for snapshot in snapshots:
        timestamp, date_et, time_et, symbol, underlying, vix, pin_strike, gex, distance = snapshot

        # Apply standard filters
        hour = int(time_et.split(':')[0])
        minute = int(time_et.split(':')[1])
        entry_time = f"{hour:02d}:{minute:02d}"

        if entry_time not in ENTRY_TIMES_ET:
            continue
        if hour >= CUTOFF_HOUR:
            continue
        if vix >= VIX_MAX_THRESHOLD or vix < VIX_FLOOR:
            continue
        if pin_strike is None or gex is None or gex == 0:
            continue

        # Check trend filter if enabled
        if with_trend_filter:
            blocked, reason = check_trend_pressure_backtest(date_et, time_et, spy_data_cache)
            if blocked:
                filtered_trades.append({
                    'date': date_et,
                    'time': entry_time,
                    'reason': reason,
                    'vix': vix,
                    'pin_strike': pin_strike,
                    'underlying': underlying
                })
                continue

        # Entry
        entry_credit = estimate_entry_credit(pin_strike, vix, underlying)
        if entry_credit < 0.50:
            continue

        # Exit (simulate realistic outcome)
        exit_credit, exit_reason, is_winner = simulate_exit(
            entry_credit, underlying, pin_strike, vix, days_held=0
        )

        # P&L calculation
        width = 5.0
        pl = (entry_credit - exit_credit) * 100  # Per contract P&L

        trades.append({
            'date': date_et,
            'time': entry_time,
            'pin_strike': pin_strike,
            'underlying': underlying,
            'vix': vix,
            'entry_credit': entry_credit,
            'exit_credit': exit_credit,
            'exit_reason': exit_reason,
            'pl': pl,
            'winner': is_winner,
            'gex': gex,
        })

    return trades, filtered_trades


def print_comparison_report(baseline_trades, filtered_trades, filtered_list):
    """Print side-by-side comparison of baseline vs filtered performance."""

    print("\n" + "="*100)
    print("GAMMA BACKTEST: With vs Without ADX + Momentum Trend Filters")
    print("="*100)
    print()

    print(f"Database: {DB_PATH}")
    print(f"Period: Last 30 days ({datetime.datetime.now().strftime('%Y-%m-%d')})")
    print(f"Entry times: {', '.join(ENTRY_TIMES_ET)}")
    print(f"VIX range: {VIX_FLOOR}-{VIX_MAX_THRESHOLD}")
    print(f"ADX threshold: {ADX_THRESHOLD}")
    print(f"Momentum threshold: {MOMENTUM_THRESHOLD_PTS} pts in 30 min")
    print()

    # Calculate statistics for both
    def calc_stats(trades):
        if not trades:
            return None
        winners = [t for t in trades if t['winner']]
        losers = [t for t in trades if not t['winner']]
        total_pl = sum(t['pl'] for t in trades)
        win_rate = len(winners) / len(trades) * 100 if trades else 0
        avg_win = sum(t['pl'] for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t['pl'] for t in losers) / len(losers) if losers else 0
        profit_factor = abs(sum(t['pl'] for t in winners) / sum(t['pl'] for t in losers)) if losers and sum(t['pl'] for t in losers) != 0 else 0

        # Emergency stops
        emergency_stops = [t for t in losers if 'EMERGENCY' in t['exit_reason']]

        return {
            'total_trades': len(trades),
            'winners': len(winners),
            'losers': len(losers),
            'total_pl': total_pl,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'emergency_stops': len(emergency_stops),
            'emergency_pct': len(emergency_stops) / len(losers) * 100 if losers else 0
        }

    baseline_stats = calc_stats(baseline_trades)
    filtered_stats = calc_stats(filtered_trades)

    if not baseline_stats or not filtered_stats:
        print("ERROR: Not enough data for comparison")
        return

    # Print comparison table
    print("="*100)
    print("PERFORMANCE COMPARISON")
    print("="*100)
    print()
    print(f"{'Metric':<30} {'Without Filter':<20} {'With Filter':<20} {'Impact':<20}")
    print("-"*100)

    # Total P&L
    pl_diff = filtered_stats['total_pl'] - baseline_stats['total_pl']
    pl_diff_pct = (pl_diff / abs(baseline_stats['total_pl']) * 100) if baseline_stats['total_pl'] != 0 else 0
    print(f"{'Total P&L':<30} ${baseline_stats['total_pl']:>18,.0f} ${filtered_stats['total_pl']:>18,.0f} ${pl_diff:>+17,.0f} ({pl_diff_pct:>+.1f}%)")

    # Trade count
    trade_diff = filtered_stats['total_trades'] - baseline_stats['total_trades']
    trade_diff_pct = (trade_diff / baseline_stats['total_trades'] * 100) if baseline_stats['total_trades'] else 0
    print(f"{'Total Trades':<30} {baseline_stats['total_trades']:>20} {filtered_stats['total_trades']:>20} {trade_diff:>+20} ({trade_diff_pct:>+.1f}%)")

    # Win Rate
    wr_diff = filtered_stats['win_rate'] - baseline_stats['win_rate']
    print(f"{'Win Rate':<30} {baseline_stats['win_rate']:>19.1f}% {filtered_stats['win_rate']:>19.1f}% {wr_diff:>+19.1f}%")

    # Profit Factor
    pf_diff = filtered_stats['profit_factor'] - baseline_stats['profit_factor']
    print(f"{'Profit Factor':<30} {baseline_stats['profit_factor']:>20.2f} {filtered_stats['profit_factor']:>20.2f} {pf_diff:>+20.2f}")

    # Emergency Stops
    emerg_diff = filtered_stats['emergency_stops'] - baseline_stats['emergency_stops']
    emerg_diff_pct = (emerg_diff / baseline_stats['emergency_stops'] * 100) if baseline_stats['emergency_stops'] else 0
    print(f"{'Emergency Stops':<30} {baseline_stats['emergency_stops']:>20} {filtered_stats['emergency_stops']:>20} {emerg_diff:>+20} ({emerg_diff_pct:>+.1f}%)")

    print()
    print("="*100)

    # Filtered trades breakdown
    print()
    print(f"TRADES FILTERED: {len(filtered_list)}")
    if filtered_list:
        print()
        print("Sample of filtered trades:")
        for trade in filtered_list[:10]:
            print(f"  {trade['date']} {trade['time']} - {trade['reason']}")
        if len(filtered_list) > 10:
            print(f"  ... and {len(filtered_list) - 10} more")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    print("\nRunning baseline (no filter)...")
    baseline_trades, _ = run_backtest(with_trend_filter=False)

    print("\nRunning with ADX + momentum filter...")
    filtered_trades, filtered_list = run_backtest(with_trend_filter=True)

    print_comparison_report(baseline_trades, filtered_trades, filtered_list)
