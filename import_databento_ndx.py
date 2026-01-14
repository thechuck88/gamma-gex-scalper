#!/usr/bin/env python3
"""
import_databento_ndx.py — Import Databento NDX Options Data to Database

Reads the downloaded CSV file, aggregates 1-second bars into 1-minute bars,
and imports into market_data.db.

Usage:
  python3 import_databento_ndx.py

Author: Claude Code (2026-01-10)
"""

import os
import sys
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime
import time

# Paths
CSV_FILE = Path(__file__).parent / "databento_data/OPRA-20260110-VNGJGNEUVK/opra-pillar-20210109-20260108.ohlcv-1s.csv"
DB_PATH = Path("/root/gamma/market_data.db")  # Centralized market data database (backed up by restic)

def aggregate_to_1min(df):
    """
    Aggregate 1-second bars into 1-minute bars.

    Args:
        df: DataFrame with 1-second bars

    Returns: DataFrame with 1-minute bars
    """
    print("Aggregating 1-second bars to 1-minute bars...")

    # Parse timestamp
    df['datetime'] = pd.to_datetime(df['ts_event'])

    # Round down to nearest minute
    df['minute'] = df['datetime'].dt.floor('1min')

    # Group by (symbol, minute) and aggregate
    agg_df = df.groupby(['symbol', 'minute']).agg({
        'open': 'first',    # First bar's open
        'high': 'max',      # Highest high
        'low': 'min',       # Lowest low
        'close': 'last',    # Last bar's close
        'volume': 'sum'     # Total volume
    }).reset_index()

    # Rename minute column to datetime
    agg_df.rename(columns={'minute': 'datetime'}, inplace=True)

    print(f"✓ Aggregated {len(df):,} 1-second bars → {len(agg_df):,} 1-minute bars")

    return agg_df

def clean_symbol(symbol):
    """Clean up symbol format (remove extra spaces)."""
    # "NDX   211217C15900000" → "NDX211217C15900000"
    return symbol.replace(' ', '')

def import_to_database(df, batch_size=10000):
    """
    Import DataFrame to database in batches.

    Args:
        df: DataFrame with 1-minute bars
        batch_size: Number of rows per batch (default 10,000)
    """
    print(f"\nImporting to database: {DB_PATH}")
    print(f"Total rows to import: {len(df):,}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Clean symbols
    df['symbol'] = df['symbol'].apply(clean_symbol)

    # Convert datetime to string
    df['datetime'] = df['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')

    # Import in batches
    total_inserted = 0
    total_skipped = 0
    start_time = time.time()

    for i in range(0, len(df), batch_size):
        batch = df.iloc[i:i+batch_size]

        inserted = 0
        skipped = 0

        for _, row in batch.iterrows():
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO option_bars_1min
                    (symbol, datetime, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    row['symbol'],
                    row['datetime'],
                    row['open'],
                    row['high'],
                    row['low'],
                    row['close'],
                    row['volume']
                ))

                if cursor.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1

            except Exception as e:
                print(f"  Warning: Skipped row due to error: {e}")
                skipped += 1

        conn.commit()
        total_inserted += inserted
        total_skipped += skipped

        # Progress update
        elapsed = time.time() - start_time
        pct = ((i + len(batch)) / len(df)) * 100
        rows_per_sec = (i + len(batch)) / elapsed if elapsed > 0 else 0
        eta = (len(df) - (i + len(batch))) / rows_per_sec if rows_per_sec > 0 else 0

        print(f"  Progress: {i+len(batch):,}/{len(df):,} ({pct:.1f}%) | "
              f"Inserted: {total_inserted:,} | Skipped: {total_skipped:,} | "
              f"Speed: {rows_per_sec:,.0f} rows/s | ETA: {eta:.0f}s", end='\r')

    conn.close()

    print()  # New line after progress
    print(f"\n✓ Import complete!")
    print(f"  Total inserted: {total_inserted:,}")
    print(f"  Total skipped:  {total_skipped:,}")
    print(f"  Time elapsed:   {time.time() - start_time:.1f}s")

def get_database_stats():
    """Show database statistics after import."""
    conn = sqlite3.connect(DB_PATH)

    query = """
        SELECT
            COUNT(*) as total_bars,
            COUNT(DISTINCT symbol) as unique_symbols,
            MIN(datetime) as first_bar,
            MAX(datetime) as last_bar,
            ROUND((JULIANDAY(MAX(datetime)) - JULIANDAY(MIN(datetime))), 0) as days
        FROM option_bars_1min
    """

    df = pd.read_sql_query(query, conn)

    print(f"\n{'='*70}")
    print("DATABASE STATISTICS")
    print(f"{'='*70}\n")

    print(df.to_string(index=False))

    # Sample data
    print(f"\n{'='*70}")
    print("SAMPLE DATA")
    print(f"{'='*70}\n")

    sample_df = pd.read_sql_query("""
        SELECT symbol, datetime, open, high, low, close, volume
        FROM option_bars_1min
        ORDER BY datetime ASC
        LIMIT 10
    """, conn)

    print(sample_df.to_string(index=False))

    conn.close()
    print(f"\n{'='*70}\n")

def main():
    print(f"\n{'='*70}")
    print("DATABENTO NDX OPTIONS IMPORT")
    print(f"{'='*70}\n")

    # Check files exist
    if not CSV_FILE.exists():
        print(f"❌ CSV file not found: {CSV_FILE}")
        print("   Run: python3 download_databento_ndx.py --batch-id OPRA-20260110-VNGJGNEUVK")
        sys.exit(1)

    if not DB_PATH.exists():
        print(f"❌ Database not found: {DB_PATH}")
        print("   Run: python3 data_collector_enhanced.py --historical")
        sys.exit(1)

    print(f"CSV File: {CSV_FILE}")
    print(f"Database: {DB_PATH}")
    print()

    # Read CSV
    print("Reading CSV file...")
    df = pd.read_csv(CSV_FILE)
    print(f"✓ Loaded {len(df):,} rows from CSV")
    print(f"  Columns: {list(df.columns)}")
    print()

    # Show sample
    print("Sample data:")
    print(df.head(3).to_string(index=False))
    print()

    # Aggregate to 1-minute bars
    df_1min = aggregate_to_1min(df)

    # Import to database
    import_to_database(df_1min)

    # Show statistics
    get_database_stats()

    print("✅ NDX options data successfully imported!")

if __name__ == '__main__':
    main()
