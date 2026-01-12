#!/usr/bin/env python3
"""
GEX Black Box Service - Continuous data collection during market hours

Runs as systemd service with auto-restart.
Records SPX and NDX data every 5 minutes during market hours.

Usage:
    python3 gex_blackbox_service.py
"""

import sys
import time
from datetime import datetime, time as dt_time
import pytz

# Import the recorder function
sys.path.insert(0, '/root/gamma')

from gex_blackbox_recorder import record_snapshot, init_database
import os

# Configuration
SNAPSHOT_INTERVAL = 300  # 5 minutes (300 seconds)
DB_PATH = "/root/gamma/data/gex_blackbox.db"

# Market hours (ET)
MARKET_OPEN = dt_time(9, 30)   # 9:30 AM ET
MARKET_CLOSE = dt_time(16, 0)  # 4:00 PM ET

ET = pytz.timezone('America/New_York')


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
    # Check if trading day flag exists (set by check_trading_day.py)
    return os.path.exists('/etc/trading-day')


def main():
    """Main service loop - runs continuously."""
    print(f"GEX Black Box Service starting at {datetime.now()}")
    print(f"Snapshot interval: {SNAPSHOT_INTERVAL}s ({SNAPSHOT_INTERVAL/60:.0f} minutes)")

    # Initialize database if needed
    if not os.path.exists(DB_PATH):
        print("Initializing database...")
        init_database()

    # Track last snapshot times
    last_spx_snapshot = 0
    last_ndx_snapshot = 0

    print("Service loop starting...")

    while True:
        try:
            now = time.time()
            now_et = datetime.now(ET)

            # Check if trading day
            if not is_trading_day():
                # Not a trading day, sleep longer
                if now_et.hour < 8:
                    # Before 8 AM, sleep until 8 AM
                    print(f"[{now_et.strftime('%H:%M:%S')}] Not a trading day, sleeping until 8 AM ET...")
                    time.sleep(3600)  # 1 hour
                else:
                    # After 8 AM, check again in 10 minutes
                    print(f"[{now_et.strftime('%H:%M:%S')}] Not a trading day, rechecking in 10 min...")
                    time.sleep(600)  # 10 minutes
                continue

            # Check if market hours
            if not is_market_hours():
                # Outside market hours
                if now_et.time() < MARKET_OPEN:
                    # Before market open
                    seconds_until_open = (
                        datetime.combine(now_et.date(), MARKET_OPEN, tzinfo=ET) - now_et
                    ).total_seconds()
                    if seconds_until_open > 0:
                        print(f"[{now_et.strftime('%H:%M:%S')}] Market opens in {seconds_until_open/60:.0f} min, sleeping...")
                        time.sleep(min(seconds_until_open, 3600))  # Sleep max 1 hour
                else:
                    # After market close
                    print(f"[{now_et.strftime('%H:%M:%S')}] Market closed, sleeping until tomorrow...")
                    time.sleep(3600)  # 1 hour
                continue

            # Within market hours - record snapshots
            print(f"[{now_et.strftime('%H:%M:%S')}] Market hours - checking for snapshots...")

            # SPX snapshot
            if now - last_spx_snapshot >= SNAPSHOT_INTERVAL:
                print(f"[{now_et.strftime('%H:%M:%S')}] Recording SPX snapshot...")
                try:
                    success = record_snapshot('SPX')
                    if success:
                        last_spx_snapshot = now
                        print(f"[{now_et.strftime('%H:%M:%S')}] ✓ SPX snapshot recorded")
                    else:
                        print(f"[{now_et.strftime('%H:%M:%S')}] ✗ SPX snapshot failed")
                except Exception as e:
                    print(f"[{now_et.strftime('%H:%M:%S')}] ERROR recording SPX: {e}")

            # NDX snapshot
            if now - last_ndx_snapshot >= SNAPSHOT_INTERVAL:
                print(f"[{now_et.strftime('%H:%M:%S')}] Recording NDX snapshot...")
                try:
                    success = record_snapshot('NDX')
                    if success:
                        last_ndx_snapshot = now
                        print(f"[{now_et.strftime('%H:%M:%S')}] ✓ NDX snapshot recorded")
                    else:
                        print(f"[{now_et.strftime('%H:%M:%S')}] ✗ NDX snapshot failed")
                except Exception as e:
                    print(f"[{now_et.strftime('%H:%M:%S')}] ERROR recording NDX: {e}")

            # Sleep until next check (1 minute)
            print(f"[{now_et.strftime('%H:%M:%S')}] Sleeping 60s until next check...")
            time.sleep(60)

        except KeyboardInterrupt:
            print("\nService stopped by user")
            break
        except Exception as e:
            print(f"ERROR in main loop: {e}")
            print("Sleeping 60s before retry...")
            time.sleep(60)


if __name__ == '__main__':
    main()
