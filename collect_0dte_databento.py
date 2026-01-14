#!/usr/bin/env python3
"""
collect_0dte_databento.py - Collect 0DTE NDX/SPX Options from Databento

Queries Databento API day-by-day for options that expire on the same day (0DTE).
This approach gets around the batch download limitation that excludes expiration day.

Usage:
  python3 collect_0dte_databento.py --symbol NDX --year 2025
  python3 collect_0dte_databento.py --symbol SPX --year 2025 --start-date 2025-01-01 --end-date 2025-06-30

Author: Claude Code (2026-01-10)
"""

import os
import sys
import argparse
import sqlite3
import databento as db
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import time

# Configuration
DB_PATH = Path("/root/gamma/market_data.db")  # Centralized market data database (backed up by restic)
DATABENTO_API_KEY = os.environ.get('DATABENTO_API_KEY')

if not DATABENTO_API_KEY:
    print("ERROR: DATABENTO_API_KEY not found in environment")
    sys.exit(1)

# ============================================================================
#                    DATABASE SETUP
# ============================================================================

def setup_database():
    """Create 0DTE option table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create separate table for 0DTE data
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS option_bars_0dte (
            symbol TEXT,
            datetime TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            expiration_date TEXT,
            trade_date TEXT,
            UNIQUE(symbol, datetime)
        )
    """)

    # Create index for fast queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_0dte_symbol_datetime
        ON option_bars_0dte(symbol, datetime)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_0dte_trade_date
        ON option_bars_0dte(trade_date)
    """)

    conn.commit()
    conn.close()
    print("✓ Database setup complete")

# ============================================================================
#                    TRADING DAYS GENERATOR
# ============================================================================

def get_trading_days(start_date, end_date):
    """Generate list of trading days (Mon-Fri) in date range."""
    trading_days = []
    current = start_date

    while current <= end_date:
        # Skip weekends (0=Monday, 6=Sunday)
        if current.weekday() < 5:
            trading_days.append(current)
        current += timedelta(days=1)

    return trading_days

# ============================================================================
#                    DATABENTO API QUERIES
# ============================================================================

def query_0dte_for_day(client, symbol_root, trade_date):
    """
    Query 0DTE options for a specific trading day.

    For 0DTE, we want options where expiration_date = trade_date.
    Symbol format: NDX250110C20500000 = NDX Jan 10, 2025 Call $20,500
    """
    # Format expiration date (YYMMDD)
    exp_str = trade_date.strftime('%y%m%d')

    # Query all options for this expiration on this date
    # Use wildcard pattern to match all strikes for this expiration
    try:
        print(f"\n  Querying {symbol_root} 0DTE for {trade_date.strftime('%Y-%m-%d')}...")

        # Get data for market hours (9:30 AM - 4:00 PM ET)
        start_time = f"{trade_date.strftime('%Y-%m-%d')}T09:30"
        end_time = f"{trade_date.strftime('%Y-%m-%d')}T16:00"

        # Use parent symbol to get all options for the underlying
        # Format: NDX.OPT gets all NDX options
        # Then filter by expiration date after receiving data
        parent_symbol = f'{symbol_root}.OPT'

        data = client.timeseries.get_range(
            dataset='OPRA.PILLAR',
            symbols=[parent_symbol],
            schema='ohlcv-1m',  # 1-minute bars
            start=start_time,
            end=end_time,
            stype_in='parent'  # Parent symbol gets all options for underlying
        )

        if data is None:
            print(f"  ⚠️  No data returned for {trade_date.strftime('%Y-%m-%d')}")
            return pd.DataFrame()

        # Convert to DataFrame
        df = data.to_df()

        if df is None or df.empty:
            print(f"  ⚠️  Empty dataframe for {trade_date.strftime('%Y-%m-%d')}")
            return pd.DataFrame()

        # Filter for 0DTE: symbol contains expiration date matching trade date
        # Symbol format from Databento API: "NDX   250117P19525000" (with spaces)
        # Extract YYMMDD (positions 6-12, after the spaces)
        # First strip spaces and rebuild to find expiration
        df['symbol_clean'] = df['symbol'].str.replace(' ', '')
        # Now format is: NDX250117P19525000
        # Extract YYMMDD (positions 3-9)
        df['exp_from_symbol'] = df['symbol_clean'].str[3:9]
        df_0dte = df[df['exp_from_symbol'] == exp_str].copy()

        if df_0dte.empty:
            # Show what expirations we actually got
            unique_exps = df['exp_from_symbol'].unique()
            exp_counts = df['exp_from_symbol'].value_counts()
            print(f"  ⚠️  No 0DTE options found (checked {len(df)} total options)")
            print(f"      Looking for expiration: {exp_str}")
            print(f"      Found expirations: {sorted(unique_exps)[:10]}")
            # Show sample symbols to debug format
            sample_symbols = df['symbol'].head(5).tolist()
            print(f"      Sample symbols: {sample_symbols[:3]}")
            if len(unique_exps) > 0:
                top_exp = exp_counts.head(1)
                print(f"      Most common: {top_exp.index[0]} ({top_exp.values[0]} bars)")
            return pd.DataFrame()

        print(f"  ✓ Found {len(df_0dte)} 0DTE bars ({len(df_0dte['symbol'].unique())} unique contracts)")

        return df_0dte

    except Exception as e:
        if "No data found" in str(e):
            print(f"  ⚠️  No data available for {trade_date.strftime('%Y-%m-%d')}")
            return pd.DataFrame()
        else:
            print(f"  ❌ Error querying {trade_date.strftime('%Y-%m-%d')}: {e}")
            return pd.DataFrame()

# ============================================================================
#                    DATA PROCESSING
# ============================================================================

def process_and_store(df, trade_date):
    """Process 0DTE data and store in database."""
    if df.empty:
        return 0

    # Prepare data for insertion
    df['trade_date'] = trade_date.strftime('%Y-%m-%d')
    df['expiration_date'] = trade_date.strftime('%Y-%m-%d')  # 0DTE = same day
    df['datetime'] = pd.to_datetime(df.index).strftime('%Y-%m-%d %H:%M:%S')

    # Use cleaned symbol (without spaces) to match database format
    if 'symbol_clean' in df.columns:
        df['symbol'] = df['symbol_clean']

    # Reset index to make datetime a column
    df_insert = df.reset_index(drop=True)

    # Select columns for database
    columns = ['symbol', 'datetime', 'open', 'high', 'low', 'close', 'volume',
               'expiration_date', 'trade_date']
    df_insert = df_insert[columns]

    # Insert into database
    conn = sqlite3.connect(DB_PATH)

    inserted = 0
    for _, row in df_insert.iterrows():
        try:
            conn.execute("""
                INSERT OR REPLACE INTO option_bars_0dte
                (symbol, datetime, open, high, low, close, volume, expiration_date, trade_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row['symbol'],
                row['datetime'],
                row['open'],
                row['high'],
                row['low'],
                row['close'],
                row['volume'],
                row['expiration_date'],
                row['trade_date']
            ))
            inserted += 1
        except sqlite3.IntegrityError:
            pass  # Already exists

    conn.commit()
    conn.close()

    return inserted

# ============================================================================
#                    MAIN COLLECTION LOOP
# ============================================================================

def collect_0dte_data(symbol_root, start_date, end_date, delay=1.0):
    """
    Collect 0DTE data for date range.

    Args:
        symbol_root: 'NDX' or 'SPX'
        start_date: datetime object
        end_date: datetime object
        delay: seconds to wait between API calls (rate limiting)
    """
    print(f"\n{'='*70}")
    print(f"COLLECTING 0DTE DATA: {symbol_root}")
    print(f"{'='*70}\n")

    print(f"Date Range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")

    # Get trading days
    trading_days = get_trading_days(start_date, end_date)
    print(f"Trading Days: {len(trading_days)}\n")

    # Setup database
    setup_database()

    # Initialize Databento client
    client = db.Historical(DATABENTO_API_KEY)

    # Statistics
    total_bars = 0
    days_with_data = 0
    days_no_data = 0

    # Collect data day by day
    for i, trade_date in enumerate(trading_days, 1):
        print(f"[{i}/{len(trading_days)}] {trade_date.strftime('%Y-%m-%d')} ({trade_date.strftime('%A')})")

        # Query 0DTE data for this day
        df = query_0dte_for_day(client, symbol_root, trade_date)

        if not df.empty:
            # Store in database
            inserted = process_and_store(df, trade_date)
            total_bars += inserted
            days_with_data += 1
            print(f"  → Inserted {inserted} bars into database")
        else:
            days_no_data += 1

        # Rate limiting
        if i < len(trading_days):
            time.sleep(delay)

    # Summary
    print(f"\n{'='*70}")
    print("COLLECTION COMPLETE")
    print(f"{'='*70}\n")
    print(f"Trading Days Processed: {len(trading_days)}")
    print(f"Days with 0DTE Data:    {days_with_data}")
    print(f"Days without Data:      {days_no_data}")
    print(f"Total Bars Inserted:    {total_bars:,}")
    print(f"\nData stored in: {DB_PATH}")
    print(f"Table: option_bars_0dte\n")

    # Show database stats
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM option_bars_0dte")
    total_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT symbol) FROM option_bars_0dte")
    unique_symbols = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT trade_date) FROM option_bars_0dte")
    unique_dates = cursor.fetchone()[0]
    conn.close()

    print(f"Database Total:")
    print(f"  Total 0DTE Bars:     {total_count:,}")
    print(f"  Unique Contracts:    {unique_symbols:,}")
    print(f"  Trading Days:        {unique_dates}")
    print()

# ============================================================================
#                    MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Collect 0DTE options data from Databento API'
    )
    parser.add_argument(
        '--symbol',
        type=str,
        required=True,
        choices=['NDX', 'SPX'],
        help='Option symbol root (NDX or SPX)'
    )
    parser.add_argument(
        '--year',
        type=int,
        help='Year to collect (e.g., 2025)'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        help='Start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        help='End date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=1.0,
        help='Delay between API calls in seconds (default: 1.0)'
    )

    args = parser.parse_args()

    # Determine date range
    if args.year:
        start_date = datetime(args.year, 1, 1)
        end_date = datetime(args.year, 12, 31)
    elif args.start_date and args.end_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
    else:
        print("ERROR: Must specify either --year or both --start-date and --end-date")
        sys.exit(1)

    # Collect data
    collect_0dte_data(args.symbol, start_date, end_date, args.delay)

if __name__ == '__main__':
    main()
