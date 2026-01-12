#!/usr/bin/env python3
"""
Live Data Backtest - Use real black box recorded data

Uses the options_prices_live and gex_peaks tables to backtest with actual market data.

Usage:
    python3 backtest_live_data.py                    # Today, SPX only
    python3 backtest_live_data.py 2026-01-12         # Specific date, SPX
    python3 backtest_live_data.py 2026-01-12 NDX     # Specific date, NDX
    python3 backtest_live_data.py 2026-01-12 ALL     # Specific date, both SPX and NDX
    python3 backtest_live_data.py --all              # All available dates, SPX
    python3 backtest_live_data.py --all ALL          # All available dates, both indices

Note: SPX uses $5 strike increments, NDX uses $10 strike increments
"""

import sys
import sqlite3
from datetime import datetime, date, time as dt_time, timedelta
from collections import defaultdict
import pytz

sys.path.insert(0, '/root/gamma')
from gex_blackbox_recorder import get_optimized_connection

DB_PATH = "/root/gamma/data/gex_blackbox.db"
ET = pytz.timezone('America/New_York')

# Entry check times (same as bot)
ENTRY_TIMES = [
    dt_time(9, 36),
    dt_time(10, 0),
    dt_time(10, 30),
    dt_time(11, 0),
    dt_time(11, 30),
    dt_time(12, 0),
    dt_time(12, 30),
    dt_time(13, 0),
    dt_time(13, 30),
    dt_time(14, 0),
    dt_time(14, 30),
    dt_time(15, 0),
]

# Strategy params (from config)
HARD_STOP_PCT = 0.10
PROFIT_TARGET_HIGH = 0.50  # 50% profit for HIGH confidence
PROFIT_TARGET_MED = 0.60   # 60% profit for MEDIUM confidence
TRAILING_TRIGGER = 0.20    # Activate at 20% profit
GRACE_PERIOD_SEC = 300     # 5 min grace before stop loss


def get_gex_peaks_for_time(index_symbol, timestamp):
    """Get GEX peaks at specific time (within ±2 minutes)."""
    conn = get_optimized_connection()
    cursor = conn.cursor()

    # Get peaks within ±2 minutes of timestamp
    start_time = (timestamp - timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M:%S')
    end_time = (timestamp + timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute("""
        SELECT peak_rank, strike, gex, distance_from_price, timestamp
        FROM gex_peaks
        WHERE index_symbol = ?
            AND timestamp >= ?
            AND timestamp <= ?
        ORDER BY timestamp DESC, peak_rank ASC
        LIMIT 3
    """, (index_symbol, start_time, end_time))

    peaks = []
    for row in cursor.fetchall():
        rank, strike, gex, distance, ts = row
        peaks.append({
            'rank': rank,
            'strike': strike,
            'gex': gex,
            'distance': distance,
            'timestamp': ts
        })

    conn.close()
    return peaks


def get_live_prices(index_symbol, start_time, end_time):
    """Get 30-second live pricing data for time range."""
    conn = get_optimized_connection()
    cursor = conn.cursor()

    start_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
    end_str = end_time.strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute("""
        SELECT timestamp, strike, option_type, bid, ask, mid, last
        FROM options_prices_live
        WHERE index_symbol = ?
            AND timestamp >= ?
            AND timestamp <= ?
        ORDER BY timestamp ASC, strike ASC
    """, (index_symbol, start_str, end_str))

    prices = []
    for row in cursor.fetchall():
        ts, strike, opt_type, bid, ask, mid, last = row
        prices.append({
            'timestamp': datetime.strptime(ts, '%Y-%m-%d %H:%M:%S'),
            'strike': strike,
            'option_type': opt_type,
            'bid': bid,
            'ask': ask,
            'mid': mid,
            'last': last
        })

    conn.close()
    return prices


def get_index_price_at_time(prices, timestamp):
    """Estimate index price from option strikes at given time."""
    # Get all prices at this exact timestamp
    at_time = [p for p in prices if p['timestamp'] == timestamp]

    if not at_time:
        return None

    # Estimate from mid-point of strikes
    strikes = [p['strike'] for p in at_time]
    if strikes:
        return sum(strikes) / len(strikes)

    return None


def calculate_spread_value(prices, short_strike, long_strike, option_type, timestamp):
    """Calculate spread value at specific time."""
    at_time = [p for p in prices
               if p['timestamp'] == timestamp
               and p['option_type'] == option_type]

    short_option = next((p for p in at_time if p['strike'] == short_strike), None)
    long_option = next((p for p in at_time if p['strike'] == long_strike), None)

    if not short_option or not long_option:
        return None

    # Credit spread: we sell short, buy long
    # Value = (short_mid - long_mid)
    short_val = short_option['mid'] or short_option['last'] or 0
    long_val = long_option['mid'] or long_option['last'] or 0

    return short_val - long_val


def determine_strategy(pin_strike, current_price, index_symbol='SPX', confidence='HIGH'):
    """Determine strategy and strikes based on pin and price."""
    distance = current_price - pin_strike

    # Strike increments differ by index
    # SPX: $5 increments
    # NDX: $10 increments
    increment = 10 if index_symbol == 'NDX' else 5

    def round_strike(strike):
        return round(strike / increment) * increment

    # For demo, use simple logic:
    # If above pin, sell call spreads (bearish)
    # If below pin, sell put spreads (bullish)

    if abs(distance) < 5:
        # Very close to pin - skip (competing peaks scenario)
        return None

    # Spread width: 10pts for SPX, 20pts for NDX (proportional to price)
    spread_width = 20 if index_symbol == 'NDX' else 10

    if distance > 0:
        # Above pin - sell call spread
        short_strike = round_strike(current_price + spread_width)
        long_strike = short_strike + spread_width
        option_type = 'call'
        direction = 'BEARISH_CALL'
    else:
        # Below pin - sell put spread
        short_strike = round_strike(current_price - spread_width)
        long_strike = short_strike - spread_width
        option_type = 'put'
        direction = 'BULLISH_PUT'

    return {
        'direction': direction,
        'option_type': option_type,
        'short_strike': short_strike,
        'long_strike': long_strike,
        'confidence': confidence
    }


def simulate_trade(entry_time, prices, strategy, index_symbol):
    """Simulate a single trade using live pricing data."""

    # Get entry credit
    entry_credit = calculate_spread_value(
        prices,
        strategy['short_strike'],
        strategy['long_strike'],
        strategy['option_type'],
        entry_time
    )

    if not entry_credit or entry_credit <= 0:
        print(f"  ❌ No valid entry credit (got {entry_credit})")
        # Debug: check what prices are available
        at_time = [p for p in prices if p['timestamp'] == entry_time and p['option_type'] == strategy['option_type']]
        print(f"  Debug: Found {len(at_time)} {strategy['option_type']} options at {entry_time}")
        if len(at_time) > 0:
            strikes_available = sorted(set(p['strike'] for p in at_time))
            print(f"  Debug: Available strikes: {strikes_available[:10]}...{strikes_available[-10:]}")
            print(f"  Debug: Looking for strikes: {strategy['short_strike']}, {strategy['long_strike']}")
        return None  # Invalid trade

    # Profit target
    if strategy['confidence'] == 'HIGH':
        tp_value = entry_credit * (1 - PROFIT_TARGET_HIGH)
    else:
        tp_value = entry_credit * (1 - PROFIT_TARGET_MED)

    # Stop loss
    sl_value = entry_credit * (1 + HARD_STOP_PCT)

    # Track trade through time (check every 30 seconds)
    trade_start = entry_time
    grace_end = datetime.combine(entry_time.date(), entry_time.time()) + \
                timedelta(seconds=GRACE_PERIOD_SEC)

    # Get all timestamps after entry
    future_times = sorted(set(p['timestamp'] for p in prices if p['timestamp'] > entry_time))

    exit_reason = None
    exit_time = None
    exit_value = None
    best_profit_pct = 0
    trailing_active = False

    for check_time in future_times:
        # Calculate current spread value
        current_value = calculate_spread_value(
            prices,
            strategy['short_strike'],
            strategy['long_strike'],
            strategy['option_type'],
            check_time
        )

        if current_value is None:
            continue

        # Calculate P&L
        pnl_dollars = (entry_credit - current_value) * 100  # $100 per point
        profit_pct = (entry_credit - current_value) / entry_credit

        # Track best profit for trailing stop
        if profit_pct > best_profit_pct:
            best_profit_pct = profit_pct

        # Check profit target
        if current_value <= tp_value:
            exit_reason = 'PROFIT_TARGET'
            exit_time = check_time
            exit_value = current_value
            break

        # Check trailing stop (after trigger)
        if profit_pct >= TRAILING_TRIGGER:
            trailing_active = True
            # Simplified trailing logic
            trail_level = best_profit_pct - 0.12  # Lock in 12%
            if profit_pct < trail_level:
                exit_reason = 'TRAILING_STOP'
                exit_time = check_time
                exit_value = current_value
                break

        # Check stop loss (after grace period)
        if check_time > grace_end and current_value >= sl_value:
            exit_reason = 'STOP_LOSS'
            exit_time = check_time
            exit_value = current_value
            break

        # Check EOD (3:30 PM ET) - MUST convert from UTC to ET
        check_time_utc = pytz.UTC.localize(check_time)
        check_time_et = check_time_utc.astimezone(ET)
        if check_time_et.time() >= dt_time(15, 30):
            exit_reason = 'EOD_CLOSE'
            exit_time = check_time
            exit_value = current_value
            break

    # If no exit found, assume EOD close at last price
    if not exit_time and future_times:
        exit_time = future_times[-1]
        exit_value = calculate_spread_value(
            prices,
            strategy['short_strike'],
            strategy['long_strike'],
            strategy['option_type'],
            exit_time
        )
        exit_reason = 'EOD_CLOSE'

    if not exit_value:
        return None

    # Calculate final P&L
    pnl_dollars = (entry_credit - exit_value) * 100
    pnl_pct = (entry_credit - exit_value) / entry_credit * 100
    duration_min = (exit_time - entry_time).total_seconds() / 60

    return {
        'entry_time': entry_time,
        'exit_time': exit_time,
        'duration_min': duration_min,
        'strategy': strategy['direction'],
        'strikes': f"{strategy['short_strike']}/{strategy['long_strike']}{strategy['option_type'][0].upper()}",
        'entry_credit': entry_credit,
        'exit_value': exit_value,
        'pnl_dollars': pnl_dollars,
        'pnl_pct': pnl_pct,
        'exit_reason': exit_reason,
        'best_profit_pct': best_profit_pct * 100
    }


def run_backtest_for_date(test_date, index_symbol='SPX'):
    """Run backtest for a specific date."""

    print(f"\n{'='*70}")
    print(f"LIVE DATA BACKTEST - {index_symbol} - {test_date}")
    print(f"{'='*70}")

    # Load all prices for the day (database is in UTC)
    # Convert ET times to UTC for database query
    start_time_et = ET.localize(datetime.combine(test_date, dt_time(9, 30)))
    end_time_et = ET.localize(datetime.combine(test_date, dt_time(16, 0)))

    start_time_utc = start_time_et.astimezone(pytz.UTC)
    end_time_utc = end_time_et.astimezone(pytz.UTC)

    print(f"\n📊 Loading live pricing data...")
    print(f"Time range: {start_time_et.strftime('%H:%M %Z')} to {end_time_et.strftime('%H:%M %Z')}")
    prices = get_live_prices(index_symbol, start_time_utc, end_time_utc)

    if not prices:
        print(f"❌ No pricing data found for {test_date}")
        return

    print(f"✓ Loaded {len(prices):,} price records")

    # Get unique timestamps
    timestamps = sorted(set(p['timestamp'] for p in prices))
    print(f"✓ {len(timestamps)} unique timestamps (30-sec intervals)")

    trades = []

    # Check each entry time
    for entry_time_obj in ENTRY_TIMES:
        # Create ET datetime and convert to UTC
        entry_dt_et = ET.localize(datetime.combine(test_date, entry_time_obj))
        entry_dt_utc = entry_dt_et.astimezone(pytz.UTC).replace(tzinfo=None)

        # Find closest timestamp in data
        closest_ts = min(timestamps, key=lambda t: abs((t - entry_dt_utc).total_seconds()))

        if abs((closest_ts - entry_dt_utc).total_seconds()) > 120:  # More than 2 min away
            continue

        print(f"\n🔍 Checking entry at {entry_dt_et.strftime('%H:%M ET')} (closest data: {closest_ts})")

        # Get GEX peak at this time
        peaks = get_gex_peaks_for_time(index_symbol, closest_ts)

        if not peaks or len(peaks) == 0:
            print(f"  ❌ No GEX peaks found")
            continue

        pin_strike = peaks[0]['strike']
        print(f"  ✓ GEX pin: {pin_strike}")

        # Estimate current price
        current_price = get_index_price_at_time(prices, closest_ts)

        if not current_price:
            print(f"  ❌ No price data at this time")
            continue

        print(f"  ✓ {index_symbol} price: {current_price:.0f} (distance from pin: {current_price - pin_strike:+.0f})")

        # Determine strategy
        strategy = determine_strategy(pin_strike, current_price, index_symbol)

        if not strategy:
            print(f"  ⚠️  Too close to pin (no trade)")
            continue

        print(f"  ✓ Strategy: {strategy['direction']} at {strategy['short_strike']}/{strategy['long_strike']}")

        # Simulate trade
        trade = simulate_trade(closest_ts, prices, strategy, index_symbol)

        if trade:
            trades.append(trade)
            print(f"\n✓ Trade #{len(trades)}: {trade['entry_time'].strftime('%H:%M')}")
            print(f"  Strategy: {trade['strategy']}")
            print(f"  Strikes: {trade['strikes']}")
            print(f"  Entry: ${trade['entry_credit']:.2f} → Exit: ${trade['exit_value']:.2f}")
            print(f"  P&L: ${trade['pnl_dollars']:+.0f} ({trade['pnl_pct']:+.0f}%)")
            print(f"  Duration: {trade['duration_min']:.0f} min")
            print(f"  Exit: {trade['exit_reason']}")

    # Summary
    if trades:
        print(f"\n{'='*70}")
        print("RESULTS")
        print(f"{'='*70}")

        total_pnl = sum(t['pnl_dollars'] for t in trades)
        winners = [t for t in trades if t['pnl_dollars'] > 0]
        losers = [t for t in trades if t['pnl_dollars'] <= 0]

        print(f"Total Trades: {len(trades)}")
        print(f"Winners: {len(winners)} ({len(winners)/len(trades)*100:.1f}%)")
        print(f"Losers: {len(losers)}")
        print(f"Total P&L: ${total_pnl:+,.0f}")

        if winners:
            avg_win = sum(t['pnl_dollars'] for t in winners) / len(winners)
            print(f"Avg Winner: ${avg_win:+.0f}")

        if losers:
            avg_loss = sum(t['pnl_dollars'] for t in losers) / len(losers)
            print(f"Avg Loser: ${avg_loss:+.0f}")
    else:
        print(f"\n⚠️  No valid trades found for {test_date}")


def main():
    # Parse arguments: [date|--all] [SPX|NDX|ALL]
    test_date = date.today()
    index_symbols = ['SPX']

    if len(sys.argv) > 1:
        if sys.argv[1] == '--all':
            # Get all available dates
            conn = get_optimized_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT DATE(timestamp) as trade_date
                FROM options_prices_live
                ORDER BY trade_date ASC
            """)
            dates = [datetime.strptime(row[0], '%Y-%m-%d').date() for row in cursor.fetchall()]
            conn.close()
        else:
            # Specific date
            dates = [datetime.strptime(sys.argv[1], '%Y-%m-%d').date()]

        # Check for index symbol argument
        if len(sys.argv) > 2:
            if sys.argv[2].upper() == 'ALL':
                index_symbols = ['SPX', 'NDX']
            else:
                index_symbols = [sys.argv[2].upper()]
    else:
        dates = [test_date]

    # Run backtest for each date and index
    for test_date in dates:
        for index_symbol in index_symbols:
            run_backtest_for_date(test_date, index_symbol)


if __name__ == '__main__':
    main()
