#!/usr/bin/env python3
"""
GEX BlackBox Continuous Collector - Collect every 30 seconds during market hours

Runs as systemd service and collects SPX and NDX GEX peaks continuously.
Market hours: 9:30 AM - 4:00 PM ET (Mon-Fri)

Usage:
  python3 gex_blackbox_continuous_collector.py SPX
  python3 gex_blackbox_continuous_collector.py NDX
"""

import sys
import time
import subprocess
from datetime import datetime, time as dt_time
import pytz

sys.path.insert(0, '/root/gamma')

# Market hours in ET
MARKET_OPEN = dt_time(9, 30)   # 9:30 AM ET
MARKET_CLOSE = dt_time(16, 0)  # 4:00 PM ET
ET = pytz.timezone('America/New_York')

COLLECTION_INTERVAL = 30  # seconds

def is_market_open():
    """Check if market is currently open."""
    now_et = datetime.now(ET)

    # Check if it's a trading day (Mon-Fri)
    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    # Check if it's within market hours
    current_time = now_et.time()
    return MARKET_OPEN <= current_time < MARKET_CLOSE

def collect_snapshot(index_symbol):
    """Collect a single snapshot."""
    try:
        result = subprocess.run(
            ['python3', '/root/gamma/gex_blackbox_recorder.py', index_symbol],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            # Extract key info from output
            if '✅ Snapshot saved' in result.stdout:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open('/var/log/gex_blackbox_collector.log', 'a') as f:
                    f.write(f"[{now}] {index_symbol} ✅ Collection successful\n")
                return True
        else:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open('/var/log/gex_blackbox_collector.log', 'a') as f:
                f.write(f"[{now}] {index_symbol} ❌ Collection failed (exit {result.returncode})\n")
            return False

    except subprocess.TimeoutExpired:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open('/var/log/gex_blackbox_collector.log', 'a') as f:
            f.write(f"[{now}] {index_symbol} ❌ Collection timeout\n")
        return False
    except Exception as e:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open('/var/log/gex_blackbox_collector.log', 'a') as f:
            f.write(f"[{now}] {index_symbol} ❌ Error: {e}\n")
        return False

def main(index_symbol):
    """Main loop - collect every 30 seconds during market hours."""

    # Validate input
    if index_symbol.upper() not in ['SPX', 'NDX']:
        print(f"Invalid index symbol: {index_symbol}")
        print("Must be SPX or NDX")
        sys.exit(1)

    index_symbol = index_symbol.upper()

    print(f"GEX BlackBox Continuous Collector - {index_symbol}")
    print(f"Collection interval: {COLLECTION_INTERVAL} seconds")
    print(f"Market hours: {MARKET_OPEN.strftime('%H:%M')} - {MARKET_CLOSE.strftime('%H:%M')} ET (Mon-Fri)")
    print("Starting collection loop...")

    # Log startup
    with open('/var/log/gex_blackbox_collector.log', 'a') as f:
        f.write(f"\n{'='*70}\n")
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting {index_symbol} collector\n")
        f.write(f"{'='*70}\n")

    collection_count = 0
    error_count = 0
    last_market_status = None

    try:
        while True:
            # Check market status
            market_open = is_market_open()

            if market_open != last_market_status:
                status_str = "🟢 OPEN" if market_open else "🔴 CLOSED"
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open('/var/log/gex_blackbox_collector.log', 'a') as f:
                    f.write(f"[{now}] Market status: {status_str}\n")
                last_market_status = market_open

            # Only collect during market hours
            if market_open:
                if collect_snapshot(index_symbol):
                    collection_count += 1
                else:
                    error_count += 1

            # Wait for next collection
            time.sleep(COLLECTION_INTERVAL)

    except KeyboardInterrupt:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open('/var/log/gex_blackbox_collector.log', 'a') as f:
            f.write(f"[{now}] Collector stopped (SIGINT)\n")
            f.write(f"Total collections: {collection_count}, Errors: {error_count}\n")
        print(f"\nCollector stopped. Total: {collection_count}, Errors: {error_count}")
        sys.exit(0)
    except Exception as e:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open('/var/log/gex_blackbox_collector.log', 'a') as f:
            f.write(f"[{now}] Fatal error: {e}\n")
        print(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 gex_blackbox_continuous_collector.py <SPX|NDX>")
        sys.exit(1)

    main(sys.argv[1])
