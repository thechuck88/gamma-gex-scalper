#!/usr/bin/env python3
"""
GEX Black Box Service v2 - Dual recording schedules

1. GEX Peaks: Records at bot's entry check times only (9:36, 10:00, 10:30, etc.)
2. Live Pricing: Records every 30 seconds for strikes within ±60pts of pin

Purpose: Enable accurate stop loss backtesting with granular pricing data

Usage:
    python3 gex_blackbox_service_v2.py
"""

import sys
import time
from datetime import datetime, time as dt_time
import pytz
import sqlite3
import threading

# Import the recorder function
sys.path.insert(0, '/root/gamma')

from gex_blackbox_recorder import record_snapshot, init_database, get_price, get_options_chain, cleanup_old_data, get_optimized_connection
import os

# Configuration
GEX_CHECK_TIMES = [
    dt_time(9, 36),   # First check (after market open)
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
    dt_time(15, 0),   # Last check
]

PRICE_MONITOR_INTERVAL = 30  # 30 seconds
PRICE_BUFFER_POINTS = 250    # ±250 points from pin (for credit spreads)

DB_PATH = "/gamma-scalper/data/gex_blackbox.db"

# Market hours (ET)
MARKET_OPEN = dt_time(9, 30)   # 9:30 AM ET
MARKET_CLOSE = dt_time(16, 0)  # 4:00 PM ET

ET = pytz.timezone('America/New_York')


def init_live_pricing_table():
    """Add live pricing table for 30-second snapshots."""
    conn = get_optimized_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS options_prices_live (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL,
            index_symbol TEXT NOT NULL,
            strike REAL NOT NULL,
            option_type TEXT NOT NULL,
            bid REAL,
            ask REAL,
            mid REAL,
            last REAL,
            volume INTEGER,
            open_interest INTEGER
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prices_time ON options_prices_live(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prices_symbol ON options_prices_live(index_symbol)")

    conn.commit()
    conn.close()
    print("✅ Live pricing table initialized")


def get_latest_pin(index_symbol):
    """Get the most recent GEX pin for an index."""
    conn = get_optimized_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT strike
        FROM gex_peaks
        WHERE index_symbol = ? AND peak_rank = 1
        ORDER BY timestamp DESC
        LIMIT 1
    """, (index_symbol,))

    row = cursor.fetchone()
    conn.close()

    if row:
        return row[0]
    return None


def record_live_pricing(index_symbol, pin_strike, expiration):
    """
    Record live pricing for strikes within ±250pts of pin.

    This range supports:
    - Put credit spreads: 100pt wide (e.g., sell 5950P, buy 5850P)
    - Call credit spreads: 100pt wide (e.g., sell 6050C, buy 6150C)
    - Iron condors: Both wings covered
    - Flexibility for wider spreads

    Args:
        index_symbol: 'SPX' or 'NDX'
        pin_strike: Current GEX pin
        expiration: 0DTE expiration date (YYYY-MM-DD)
    """
    if pin_strike is None:
        print(f"[{datetime.now(ET).strftime('%H:%M:%S')}] No pin available for {index_symbol}, skipping price recording")
        return False

    # Fetch options chain
    chain = get_options_chain(index_symbol, expiration)
    if not chain:
        return False

    # Filter to strikes within ±250pts of pin (for credit spreads)
    min_strike = pin_strike - PRICE_BUFFER_POINTS
    max_strike = pin_strike + PRICE_BUFFER_POINTS

    nearby_options = [opt for opt in chain if min_strike <= opt['strike'] <= max_strike]

    if not nearby_options:
        print(f"[{datetime.now(ET).strftime('%H:%M:%S')}] No options found near pin {pin_strike}")
        return False

    # Store to database
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_optimized_connection()
    cursor = conn.cursor()

    try:
        for opt in nearby_options:
            mid = None
            if opt['bid'] and opt['ask']:
                mid = (opt['bid'] + opt['ask']) / 2

            cursor.execute("""
                INSERT INTO options_prices_live
                (timestamp, index_symbol, strike, option_type, bid, ask, mid, last, volume, open_interest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                timestamp,
                index_symbol,
                opt['strike'],
                opt['option_type'],
                opt['bid'],
                opt['ask'],
                mid,
                opt['last'],
                opt['volume'],
                opt['open_interest']
            ))

        conn.commit()
        print(f"[{datetime.now(ET).strftime('%H:%M:%S')}] ✓ {index_symbol} live pricing: {len(nearby_options)} options near {pin_strike}")
        return True

    except Exception as e:
        print(f"[{datetime.now(ET).strftime('%H:%M:%S')}] ERROR storing prices: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def is_market_hours():
    """Check if currently within market hours (9:30 AM - 4:00 PM ET, Mon-Fri)."""
    now_et = datetime.now(ET)

    # Check if weekend
    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    # Check if within market hours
    current_time = now_et.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def is_trading_day():
    """Check if today is a trading day (market open flag exists)."""
    return os.path.exists('/etc/trading-day')


def is_gex_check_time():
    """Check if current time matches a GEX check time (within 1 minute)."""
    now_et = datetime.now(ET)
    current_time = now_et.time()

    for check_time in GEX_CHECK_TIMES:
        # Within 1 minute of check time
        check_minutes = check_time.hour * 60 + check_time.minute
        current_minutes = current_time.hour * 60 + current_time.minute

        if abs(current_minutes - check_minutes) <= 1:
            return True

    return False


def gex_recorder_thread():
    """Thread for GEX peak recording at specific times."""
    print("[GEX] GEX recorder thread starting...")
    last_recorded = {}  # Track last recorded time per index

    while True:
        try:
            if not is_trading_day() or not is_market_hours():
                time.sleep(60)
                continue

            if is_gex_check_time():
                now_et = datetime.now(ET)
                current_minute = now_et.strftime("%H:%M")

                # Record both indices
                for index_symbol in ['SPX', 'NDX']:
                    # Avoid duplicate recording in same minute
                    if last_recorded.get(index_symbol) == current_minute:
                        continue

                    print(f"[GEX] [{now_et.strftime('%H:%M:%S')}] Recording {index_symbol} GEX peaks...")
                    try:
                        success = record_snapshot(index_symbol)
                        if success:
                            last_recorded[index_symbol] = current_minute
                            print(f"[GEX] [{now_et.strftime('%H:%M:%S')}] ✓ {index_symbol} GEX recorded")
                        else:
                            print(f"[GEX] [{now_et.strftime('%H:%M:%S')}] ✗ {index_symbol} GEX failed")
                    except Exception as e:
                        print(f"[GEX] [{now_et.strftime('%H:%M:%S')}] ERROR recording {index_symbol}: {e}")

                # Sleep until next minute to avoid duplicate recording
                time.sleep(60)
            else:
                # Not a check time, sleep briefly
                time.sleep(30)

        except Exception as e:
            print(f"[GEX] ERROR in GEX thread: {e}")
            time.sleep(60)


def price_monitor_thread():
    """Thread for live pricing every 30 seconds."""
    print("[PRICE] Price monitor thread starting...")

    while True:
        try:
            if not is_trading_day() or not is_market_hours():
                time.sleep(60)
                continue

            now_et = datetime.now(ET)
            from datetime import date
            today = date.today().strftime("%Y-%m-%d")

            # Record pricing for both indices
            for index_symbol in ['SPX', 'NDX']:
                pin = get_latest_pin(index_symbol)
                if pin:
                    record_live_pricing(index_symbol, pin, today)
                else:
                    print(f"[PRICE] [{now_et.strftime('%H:%M:%S')}] No pin yet for {index_symbol}, waiting...")

            # Sleep 30 seconds
            time.sleep(PRICE_MONITOR_INTERVAL)

        except Exception as e:
            print(f"[PRICE] ERROR in price thread: {e}")
            time.sleep(60)


def cleanup_thread():
    """Thread for daily data cleanup at 6 AM ET."""
    print("[CLEANUP] Cleanup thread starting...")
    last_cleanup_date = None

    while True:
        try:
            now_et = datetime.now(ET)
            current_date = now_et.date()
            current_time = now_et.time()

            # Run cleanup once per day at 6:00 AM ET (before market opens)
            if current_time >= dt_time(6, 0) and current_time < dt_time(6, 5):
                if last_cleanup_date != current_date:
                    print(f"[CLEANUP] [{now_et.strftime('%Y-%m-%d %H:%M:%S')}] Running daily cleanup...")
                    success = cleanup_old_data(retention_days=365)
                    if success:
                        last_cleanup_date = current_date
                        print(f"[CLEANUP] ✓ Daily cleanup completed")
                    else:
                        print(f"[CLEANUP] ✗ Daily cleanup failed")

                    # Sleep 10 minutes to avoid running multiple times
                    time.sleep(600)
            else:
                # Check every hour
                time.sleep(3600)

        except Exception as e:
            print(f"[CLEANUP] ERROR in cleanup thread: {e}")
            time.sleep(3600)


def main():
    """Main service - runs three threads."""
    print(f"GEX Black Box Service v2 starting at {datetime.now()}")
    print(f"GEX recording times: {len(GEX_CHECK_TIMES)} checks per day")
    print(f"Price monitoring: Every {PRICE_MONITOR_INTERVAL}s")
    print(f"Daily cleanup: 6:00 AM ET (1-year data retention)")

    # Initialize database
    if not os.path.exists(DB_PATH):
        print("Initializing database...")
        init_database()

    # Add live pricing table
    init_live_pricing_table()

    # Start threads
    gex_thread = threading.Thread(target=gex_recorder_thread, daemon=True)
    price_thread = threading.Thread(target=price_monitor_thread, daemon=True)
    cleanup_thread_obj = threading.Thread(target=cleanup_thread, daemon=True)

    gex_thread.start()
    price_thread.start()
    cleanup_thread_obj.start()

    print("Service threads started...")

    # Keep main thread alive
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nService stopped by user")


if __name__ == '__main__':
    main()
