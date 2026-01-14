#!/usr/bin/env python3
"""
download_databento_ndx.py — Download NDX Options Data from Databento

Downloads historical NDX (Nasdaq-100 Index) options data from Databento
using their Python API client.

Usage:
  python3 download_databento_ndx.py --date 2026-01-10
  python3 download_databento_ndx.py --start 2026-01-01 --end 2026-01-10

Author: Claude Code (2026-01-10)
"""

import os
import sys
import argparse
import datetime
import pandas as pd
import sqlite3
from pathlib import Path

try:
    import databento as db
except ImportError:
    print("❌ databento not installed. Install with: pip install databento")
    sys.exit(1)

# Configuration
DATABENTO_API_KEY = os.environ.get('DATABENTO_API_KEY', 'db-piX4qSRjXE3frsr6Dd4EbRG6VXuKW')
DB_PATH = Path("/root/gamma/market_data.db")  # Centralized market data database (backed up by restic)
DOWNLOAD_DIR = Path(__file__).parent / "databento_data"

def download_ndx_options(start_date, end_date, save_to_db=True):
    """
    Download NDX options data from Databento.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        save_to_db: Whether to save to database (default: True)

    Returns: DataFrame with options data
    """
    print(f"\n{'='*70}")
    print(f"DATABENTO NDX OPTIONS DOWNLOAD")
    print(f"{'='*70}\n")

    print(f"Date Range: {start_date} to {end_date}")
    print(f"API Key: {DATABENTO_API_KEY[:10]}...")
    print()

    # Create Databento client
    client = db.Historical(DATABENTO_API_KEY)

    try:
        # Download NDX options data
        # Dataset: OPRA (Options Price Reporting Authority)
        # Schema: tbbo (top of book quotes - bid/ask)
        # Symbols: Use NDX or I:NDX for index options

        print("Downloading NDX options data from Databento...")
        print("  Dataset: OPRA.PILLAR")
        print("  Schema: tbbo (top of book bid/ask)")
        print("  Symbol: I:NDX (Nasdaq-100 Index)")
        print()

        data = client.timeseries.get_range(
            dataset='OPRA.PILLAR',
            symbols=['I:NDX'],  # NDX index options
            schema='tbbo',  # Top of book (best bid/ask)
            start=start_date,
            end=end_date,
            stype_in='parent'  # Get all option contracts for NDX
        )

        print(f"✓ Downloaded {len(data)} records")

        # Convert to DataFrame
        df = data.to_df()

        print(f"  DataFrame shape: {df.shape}")
        print(f"  Columns: {list(df.columns)}")

        if len(df) > 0:
            print(f"\nSample data:")
            print(df.head())

            # Save to CSV
            DOWNLOAD_DIR.mkdir(exist_ok=True)
            csv_file = DOWNLOAD_DIR / f"ndx_options_{start_date}_{end_date}.csv"
            df.to_csv(csv_file, index=False)
            print(f"\n✓ Saved to: {csv_file}")

            # Save to database
            if save_to_db:
                save_to_database(df)

        return df

    except Exception as e:
        print(f"\n❌ Error downloading data: {e}")
        print(f"\nTroubleshooting:")
        print(f"  1. Check API key is valid")
        print(f"  2. Verify you have access to OPRA dataset")
        print(f"  3. Check date range (data may not be available for future dates)")
        print(f"  4. Try with smaller date range")
        return None

def download_batch_file(job_id):
    """
    Download a specific batch job by ID.

    The FTP path /VLV7KEPX/OPRA-20260110-VNGJGNEUVK suggests a batch job.
    VLV7KEPX = dataset ID
    OPRA-20260110-VNGJGNEUVK = job ID

    Args:
        job_id: Batch job ID (e.g., 'OPRA-20260110-VNGJGNEUVK')
    """
    print(f"\n{'='*70}")
    print(f"DOWNLOADING BATCH FILE")
    print(f"{'='*70}\n")

    print(f"Job ID: {job_id}")

    client = db.Historical(DATABENTO_API_KEY)

    try:
        # Download batch file
        print("Downloading batch file...")

        batch_data = client.batch.download(
            output_dir=str(DOWNLOAD_DIR),
            job_id=job_id
        )

        print(f"✓ Downloaded batch file to: {DOWNLOAD_DIR}")

        return batch_data

    except Exception as e:
        print(f"❌ Error downloading batch: {e}")
        return None

def save_to_database(df):
    """Save options data to SQLite database."""
    print(f"\nSaving to database: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)

    # Create table if needed (using existing schema)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS option_bars_1min (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            datetime TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            bid REAL,
            ask REAL,
            mid REAL,
            iv REAL,
            delta REAL,
            gamma REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, datetime)
        )
    """)

    # Transform Databento data to our schema
    # Note: Databento columns may differ, adjust as needed
    records_added = 0

    for _, row in df.iterrows():
        try:
            # Extract fields (adjust based on actual Databento schema)
            symbol = row.get('symbol', '')
            ts = row.get('ts_event', row.get('timestamp', ''))

            # Convert timestamp to datetime string
            if isinstance(ts, int):
                dt = pd.to_datetime(ts, unit='ns')
            else:
                dt = pd.to_datetime(ts)

            datetime_str = dt.strftime('%Y-%m-%d %H:%M:%S')

            bid_price = row.get('bid_px', None)
            ask_price = row.get('ask_px', None)
            mid_price = (bid_price + ask_price) / 2 if bid_price and ask_price else None

            # Insert into database
            conn.execute("""
                INSERT OR REPLACE INTO option_bars_1min
                (symbol, datetime, bid, ask, mid)
                VALUES (?, ?, ?, ?, ?)
            """, (symbol, datetime_str, bid_price, ask_price, mid_price))

            records_added += 1

        except Exception as e:
            print(f"  Warning: Skipped row due to error: {e}")
            continue

    conn.commit()
    conn.close()

    print(f"✓ Saved {records_added} records to database")

def main():
    parser = argparse.ArgumentParser(description='Download NDX Options from Databento')
    parser.add_argument('--date', type=str, help='Single date (YYYY-MM-DD)')
    parser.add_argument('--start', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--batch-id', type=str, help='Download specific batch job ID')
    parser.add_argument('--no-db', action='store_true', help='Skip database save')

    args = parser.parse_args()

    # Handle batch download
    if args.batch_id:
        download_batch_file(args.batch_id)
        return

    # Determine date range
    if args.date:
        start_date = args.date
        end_date = args.date
    elif args.start and args.end:
        start_date = args.start
        end_date = args.end
    else:
        # Default: yesterday
        yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        start_date = yesterday
        end_date = yesterday
        print(f"No date specified, using yesterday: {yesterday}")

    # Download data
    save_to_db = not args.no_db
    df = download_ndx_options(start_date, end_date, save_to_db)

    if df is not None:
        print(f"\n{'='*70}")
        print(f"DOWNLOAD COMPLETE")
        print(f"{'='*70}\n")
        print(f"Records: {len(df)}")
        print(f"Saved to: {DOWNLOAD_DIR}")
        if save_to_db:
            print(f"Database: {DB_PATH}")
    else:
        print("\n❌ Download failed")
        sys.exit(1)

if __name__ == '__main__':
    main()
