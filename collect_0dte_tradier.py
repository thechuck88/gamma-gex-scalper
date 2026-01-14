#!/usr/bin/env python3
"""
collect_0dte_tradier.py - Collect 0DTE SPX/NDX Options Data via Tradier API

Runs daily to collect options that expire TODAY (0DTE).
Stores in database for backtest validation.

Usage:
  python3 collect_0dte_tradier.py --symbol SPX
  python3 collect_0dte_tradier.py --symbol NDX --all-day
  python3 collect_0dte_tradier.py --symbol SPX --time 10:00

Cron (daily at 10 AM ET):
  0 15 * * 1-5 cd /root/gamma && /usr/bin/python3 collect_0dte_tradier.py --symbol SPX >> /var/log/0dte_collector.log 2>&1

Author: Claude Code (2026-01-10)
"""

import os
import sys
import argparse
import requests
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import time
import pytz

# Configuration
DB_PATH = "/root/gamma/market_data.db"  # Centralized market data database (backed up by restic)
TRADIER_API_KEY = os.environ.get('TRADIER_SANDBOX_KEY')  # Use sandbox for data collection
TRADIER_BASE_URL = "https://sandbox.tradier.com/v1"

if not TRADIER_API_KEY:
    print("ERROR: TRADIER_SANDBOX_KEY not found in environment")
    print("Run: source /etc/gamma.env")
    sys.exit(1)

# ============================================================================
#                    TRADIER API FUNCTIONS
# ============================================================================

def get_option_expirations(symbol):
    """Get list of option expiration dates for a symbol."""
    url = f"{TRADIER_BASE_URL}/markets/options/expirations"

    headers = {
        'Authorization': f'Bearer {TRADIER_API_KEY}',
        'Accept': 'application/json'
    }

    params = {
        'symbol': symbol,
        'includeAllRoots': 'true'
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        data = response.json()
        if 'expirations' in data and data['expirations'] and 'date' in data['expirations']:
            return data['expirations']['date']
        return []
    else:
        print(f"Error getting expirations: {response.status_code} - {response.text}")
        return []

def get_option_chain(symbol, expiration):
    """Get option chain for a specific expiration."""
    url = f"{TRADIER_BASE_URL}/markets/options/chains"

    headers = {
        'Authorization': f'Bearer {TRADIER_API_KEY}',
        'Accept': 'application/json'
    }

    params = {
        'symbol': symbol,
        'expiration': expiration,
        'greeks': 'false'  # Don't need greeks for now
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        data = response.json()
        if 'options' in data and data['options'] and 'option' in data['options']:
            return data['options']['option']
        return []
    else:
        print(f"Error getting option chain: {response.status_code} - {response.text}")
        return []

def get_option_quotes(symbols):
    """Get real-time quotes for multiple option symbols."""
    url = f"{TRADIER_BASE_URL}/markets/quotes"

    headers = {
        'Authorization': f'Bearer {TRADIER_API_KEY}',
        'Accept': 'application/json'
    }

    # Tradier allows up to 100 symbols per request
    all_quotes = []

    for i in range(0, len(symbols), 100):
        batch = symbols[i:i+100]
        params = {
            'symbols': ','.join(batch),
            'greeks': 'false'
        }

        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            data = response.json()
            if 'quotes' in data and data['quotes'] and 'quote' in data['quotes']:
                quotes = data['quotes']['quote']
                # Handle single quote (not in list)
                if isinstance(quotes, dict):
                    quotes = [quotes]
                all_quotes.extend(quotes)
        else:
            print(f"Error getting quotes: {response.status_code}")

        # Rate limiting
        if i + 100 < len(symbols):
            time.sleep(0.5)

    return all_quotes

# ============================================================================
#                    DATABASE FUNCTIONS
# ============================================================================

def setup_database():
    """Create 0DTE table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS option_bars_0dte (
            symbol TEXT,
            datetime TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            bid REAL,
            ask REAL,
            last REAL,
            expiration_date TEXT,
            trade_date TEXT,
            strike REAL,
            option_type TEXT,
            underlying_price REAL,
            UNIQUE(symbol, datetime)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_0dte_symbol_datetime
        ON option_bars_0dte(symbol, datetime)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_0dte_trade_date
        ON option_bars_0dte(trade_date)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_0dte_expiration
        ON option_bars_0dte(expiration_date)
    """)

    conn.commit()
    conn.close()

def store_0dte_data(quotes, expiration_date, underlying_price):
    """Store 0DTE option quotes in database."""
    if not quotes:
        return 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get current time in ET
    et_tz = pytz.timezone('US/Eastern')
    now_et = datetime.now(et_tz)
    datetime_str = now_et.strftime('%Y-%m-%d %H:%M:%S')
    trade_date = now_et.strftime('%Y-%m-%d')

    inserted = 0

    for quote in quotes:
        try:
            symbol = quote.get('symbol', '')
            if not symbol:
                continue

            # Extract strike and option type from symbol
            # Format: SPX260110C05900000
            option_type = quote.get('option_type', '')
            strike = quote.get('strike', 0.0)

            cursor.execute("""
                INSERT OR REPLACE INTO option_bars_0dte
                (symbol, datetime, open, high, low, close, volume,
                 bid, ask, last, expiration_date, trade_date,
                 strike, option_type, underlying_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol,
                datetime_str,
                quote.get('open', 0.0),
                quote.get('high', 0.0),
                quote.get('low', 0.0),
                quote.get('close', quote.get('last', 0.0)),  # Use last if no close
                quote.get('volume', 0),
                quote.get('bid', 0.0),
                quote.get('ask', 0.0),
                quote.get('last', 0.0),
                expiration_date,
                trade_date,
                strike,
                option_type,
                underlying_price
            ))

            inserted += 1

        except Exception as e:
            print(f"Error inserting {quote.get('symbol', 'unknown')}: {e}")
            continue

    conn.commit()
    conn.close()

    return inserted

# ============================================================================
#                    COLLECTION LOGIC
# ============================================================================

def collect_0dte_snapshot(symbol):
    """
    Collect a single snapshot of 0DTE options.

    This is meant to be run multiple times per day to build intraday data.
    """
    print(f"\n{'='*70}")
    print(f"COLLECTING 0DTE DATA: {symbol}")
    print(f"{'='*70}\n")

    et_tz = pytz.timezone('US/Eastern')
    now_et = datetime.now(et_tz)
    today = now_et.strftime('%Y-%m-%d')

    print(f"Collection Time: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Looking for: Options expiring TODAY ({today})\n")

    # Step 1: Get all expirations
    print("Step 1: Getting option expirations...")
    expirations = get_option_expirations(symbol)

    if not expirations:
        print("❌ No expirations found")
        return 0

    print(f"✓ Found {len(expirations)} expirations")

    # Step 2: Find today's expiration
    if today not in expirations:
        print(f"\n⚠️  No 0DTE expiration found for {today}")
        print(f"   Available expirations: {expirations[:5]}")
        print(f"   {symbol} may not have daily expirations")
        return 0

    print(f"✓ Found 0DTE expiration: {today}\n")

    # Step 3: Get option chain for 0DTE
    print(f"Step 2: Getting option chain for {today} expiration...")
    chain = get_option_chain(symbol, today)

    if not chain:
        print("❌ No options in chain")
        return 0

    print(f"✓ Found {len(chain)} options in chain")

    # Get underlying price
    underlying_price = 0.0
    if chain and 'underlying' in chain[0]:
        try:
            underlying_price = float(chain[0]['underlying'])
        except (ValueError, TypeError):
            underlying_price = 0.0

    print(f"   Underlying price: ${underlying_price:.2f}\n")

    # Step 3: Get real-time quotes
    print(f"Step 3: Getting real-time quotes for {len(chain)} options...")
    symbols = [opt['symbol'] for opt in chain if 'symbol' in opt]

    quotes = get_option_quotes(symbols)

    if not quotes:
        print("❌ No quotes received")
        return 0

    print(f"✓ Received {len(quotes)} quotes\n")

    # Step 4: Store in database
    print("Step 4: Storing in database...")
    setup_database()
    inserted = store_0dte_data(quotes, today, underlying_price)

    print(f"✓ Inserted {inserted} option quotes\n")

    # Summary
    print(f"{'='*70}")
    print("COLLECTION COMPLETE")
    print(f"{'='*70}\n")

    print(f"Symbol: {symbol}")
    print(f"Expiration: {today} (0DTE)")
    print(f"Options Collected: {inserted}")
    print(f"Underlying Price: ${underlying_price:.2f}")
    print(f"Collection Time: {now_et.strftime('%H:%M:%S %Z')}")
    print(f"Database: {DB_PATH}")
    print()

    return inserted

def collect_all_day(symbol, interval_minutes=30):
    """
    Collect 0DTE data throughout the trading day.

    Runs from 9:30 AM to 4:00 PM ET, collecting every interval_minutes.
    """
    et_tz = pytz.timezone('US/Eastern')

    print(f"\n{'='*70}")
    print(f"ALL-DAY 0DTE COLLECTION: {symbol}")
    print(f"{'='*70}\n")
    print(f"Interval: Every {interval_minutes} minutes")
    print(f"Market Hours: 9:30 AM - 4:00 PM ET")
    print()

    total_collected = 0
    collections = 0

    while True:
        now_et = datetime.now(et_tz)
        current_time = now_et.time()

        # Check if market is open (9:30 AM - 4:00 PM ET)
        market_open = current_time >= datetime.strptime('09:30', '%H:%M').time()
        market_close = current_time <= datetime.strptime('16:00', '%H:%M').time()

        if not (market_open and market_close):
            print(f"[{now_et.strftime('%H:%M:%S')}] Market closed. Exiting.")
            break

        # Collect snapshot
        collected = collect_0dte_snapshot(symbol)
        total_collected += collected
        collections += 1

        # Wait for next interval
        print(f"Waiting {interval_minutes} minutes until next collection...")
        time.sleep(interval_minutes * 60)

    print(f"\n{'='*70}")
    print("ALL-DAY COLLECTION COMPLETE")
    print(f"{'='*70}\n")
    print(f"Total Collections: {collections}")
    print(f"Total Options: {total_collected}")
    print()

# ============================================================================
#                    STATUS & STATS
# ============================================================================

def show_status():
    """Show current 0DTE data collection status."""
    conn = sqlite3.connect(DB_PATH)

    print(f"\n{'='*70}")
    print("0DTE DATA COLLECTION STATUS")
    print(f"{'='*70}\n")

    # Overall stats
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM option_bars_0dte")
    total_rows = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT symbol) FROM option_bars_0dte")
    unique_symbols = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT trade_date) FROM option_bars_0dte")
    unique_dates = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT expiration_date) FROM option_bars_0dte")
    unique_expirations = cursor.fetchone()[0]

    print(f"Database: {DB_PATH}")
    print(f"Table: option_bars_0dte\n")
    print(f"Total Snapshots: {total_rows:,}")
    print(f"Unique Options: {unique_symbols:,}")
    print(f"Trading Days: {unique_dates}")
    print(f"Expirations: {unique_expirations}\n")

    # Recent collections
    query = """
    SELECT
        trade_date,
        COUNT(*) as snapshots,
        COUNT(DISTINCT symbol) as options,
        MAX(datetime) as last_collection
    FROM option_bars_0dte
    GROUP BY trade_date
    ORDER BY trade_date DESC
    LIMIT 10
    """

    df = pd.read_sql_query(query, conn)

    if not df.empty:
        print("Recent Collections:\n")
        print(df.to_string(index=False))
    else:
        print("⚠️  No data collected yet")
        print("   Run: python3 collect_0dte_tradier.py --symbol SPX")

    conn.close()
    print()

# ============================================================================
#                    MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Collect 0DTE options data via Tradier API'
    )
    parser.add_argument(
        '--symbol',
        type=str,
        default='SPX',
        help='Underlying symbol (SPX or NDX)'
    )
    parser.add_argument(
        '--all-day',
        action='store_true',
        help='Collect throughout trading day (9:30 AM - 4:00 PM ET)'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=30,
        help='Collection interval in minutes (default: 30)'
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='Show collection status and stats'
    )

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.all_day:
        collect_all_day(args.symbol, args.interval)
    else:
        collect_0dte_snapshot(args.symbol)

if __name__ == '__main__':
    main()
