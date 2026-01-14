#!/usr/bin/env python3
"""
extract_0dte_from_existing_db.py - Extract 0DTE Options from Existing Database

Filters the existing option_bars_1min table to find options where:
  trade_date = expiration_date (embedded in symbol)

This identifies any 0DTE (same-day expiration) data we already have.

Usage:
  python3 extract_0dte_from_existing_db.py --analyze
  python3 extract_0dte_from_existing_db.py --extract

Author: Claude Code (2026-01-10)
"""

import sqlite3
import pandas as pd
from pathlib import Path
import argparse

DB_PATH = Path("/root/gamma/market_data.db")  # Centralized market data database (backed up by restic)

# ============================================================================
#                    ANALYSIS FUNCTIONS
# ============================================================================

def analyze_0dte_availability():
    """
    Check if database contains any 0DTE options.

    0DTE = options where trade date equals expiration date.
    Symbol format: NDX250117C10200000
      - Positions 3-9: YYMMDD (expiration date)
    """
    print(f"\n{'='*70}")
    print("ANALYZING 0DTE AVAILABILITY IN EXISTING DATABASE")
    print(f"{'='*70}\n")

    conn = sqlite3.connect(DB_PATH)

    # Query to find 0DTE options
    # Extract expiration from symbol and compare to trade date
    query = """
    SELECT
        COUNT(*) as total_0dte_bars,
        COUNT(DISTINCT symbol) as unique_0dte_contracts,
        COUNT(DISTINCT date(datetime)) as unique_0dte_days
    FROM option_bars_1min
    WHERE
        -- Extract YYMMDD from symbol (positions 4-9 in cleaned symbol)
        -- Symbol format: NDX250117C10200000 (after removing spaces)
        date(datetime) = date('20' || substr(replace(symbol, ' ', ''), 4, 6),
                               'unixepoch' IS NULL,
                               substr(replace(symbol, ' ', ''), 4, 2) || '-' ||
                               substr(replace(symbol, ' ', ''), 6, 2) || '-' ||
                               substr(replace(symbol, ' ', ''), 8, 2))
    """

    # Simpler approach - build the date string manually
    query = """
    WITH cleaned AS (
        SELECT
            symbol,
            replace(symbol, ' ', '') as symbol_clean,
            datetime,
            date(datetime) as trade_date
        FROM option_bars_1min
    ),
    with_expiration AS (
        SELECT
            symbol,
            symbol_clean,
            datetime,
            trade_date,
            -- Build expiration date from symbol: 20 + YY + - + MM + - + DD
            '20' || substr(symbol_clean, 4, 2) || '-' ||
            substr(symbol_clean, 6, 2) || '-' ||
            substr(symbol_clean, 8, 2) as expiration_date
        FROM cleaned
    )
    SELECT
        COUNT(*) as total_0dte_bars,
        COUNT(DISTINCT symbol) as unique_0dte_contracts,
        COUNT(DISTINCT trade_date) as unique_0dte_days
    FROM with_expiration
    WHERE trade_date = expiration_date
    """

    print("Querying database for 0DTE options...")
    print("(Options where trade_date = expiration_date)\n")

    df_stats = pd.read_sql_query(query, conn)

    total_bars = df_stats.iloc[0]['total_0dte_bars']
    unique_contracts = df_stats.iloc[0]['unique_0dte_contracts']
    unique_days = df_stats.iloc[0]['unique_0dte_days']

    print(f"Results:")
    print(f"  Total 0DTE Bars:        {total_bars:,}")
    print(f"  Unique 0DTE Contracts:  {unique_contracts:,}")
    print(f"  Unique 0DTE Days:       {unique_days:,}")

    if total_bars == 0:
        print(f"\n❌ NO 0DTE DATA FOUND")
        print(f"\nDatabase contains only weekly/monthly options.")
        print(f"All options expire 7+ days after trade date.")
    else:
        print(f"\n✅ 0DTE DATA FOUND!")
        print(f"\nWe can extract {total_bars:,} bars of 0DTE data from existing database!")

        # Get sample 0DTE dates
        query_samples = """
        WITH cleaned AS (
            SELECT
                symbol,
                replace(symbol, ' ', '') as symbol_clean,
                datetime,
                date(datetime) as trade_date
            FROM option_bars_1min
        ),
        with_expiration AS (
            SELECT
                symbol_clean as symbol,
                trade_date,
                '20' || substr(symbol_clean, 4, 2) || '-' ||
                substr(symbol_clean, 6, 2) || '-' ||
                substr(symbol_clean, 8, 2) as expiration_date
            FROM cleaned
        )
        SELECT DISTINCT trade_date, COUNT(*) as bars_count
        FROM with_expiration
        WHERE trade_date = expiration_date
        GROUP BY trade_date
        ORDER BY trade_date
        LIMIT 10
        """

        df_samples = pd.read_sql_query(query_samples, conn)

        print(f"\nSample 0DTE Trading Days:")
        for _, row in df_samples.iterrows():
            print(f"  {row['trade_date']}: {row['bars_count']} bars")

    conn.close()
    return total_bars > 0

# ============================================================================
#                    EXTRACTION FUNCTIONS
# ============================================================================

def extract_0dte_to_table():
    """
    Extract all 0DTE options to a separate table for easy querying.
    """
    print(f"\n{'='*70}")
    print("EXTRACTING 0DTE OPTIONS TO SEPARATE TABLE")
    print(f"{'='*70}\n")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create 0DTE table if it doesn't exist
    print("Creating option_bars_0dte table...")
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

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_0dte_symbol_datetime
        ON option_bars_0dte(symbol, datetime)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_0dte_trade_date
        ON option_bars_0dte(trade_date)
    """)

    print("✓ Table created\n")

    # Extract 0DTE data
    print("Extracting 0DTE options from option_bars_1min...")

    extract_query = """
    INSERT OR REPLACE INTO option_bars_0dte
    (symbol, datetime, open, high, low, close, volume, expiration_date, trade_date)
    WITH cleaned AS (
        SELECT
            replace(symbol, ' ', '') as symbol,
            datetime,
            open,
            high,
            low,
            close,
            volume,
            date(datetime) as trade_date
        FROM option_bars_1min
    ),
    with_expiration AS (
        SELECT
            symbol,
            datetime,
            open,
            high,
            low,
            close,
            volume,
            trade_date,
            '20' || substr(symbol, 4, 2) || '-' ||
            substr(symbol, 6, 2) || '-' ||
            substr(symbol, 8, 2) as expiration_date
        FROM cleaned
    )
    SELECT
        symbol,
        datetime,
        open,
        high,
        low,
        close,
        volume,
        expiration_date,
        trade_date
    FROM with_expiration
    WHERE trade_date = expiration_date
    """

    cursor.execute(extract_query)
    inserted = cursor.rowcount
    conn.commit()

    print(f"✓ Extracted {inserted:,} 0DTE bars\n")

    # Verify extraction
    cursor.execute("SELECT COUNT(*) FROM option_bars_0dte")
    total_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT symbol) FROM option_bars_0dte")
    unique_symbols = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT trade_date) FROM option_bars_0dte")
    unique_dates = cursor.fetchone()[0]

    print(f"{'='*70}")
    print("EXTRACTION COMPLETE")
    print(f"{'='*70}\n")

    print(f"Table: option_bars_0dte")
    print(f"  Total Bars:       {total_count:,}")
    print(f"  Unique Contracts: {unique_symbols:,}")
    print(f"  Trading Days:     {unique_dates}")

    # Show sample data
    print(f"\nSample 0DTE Data:")
    query_sample = """
    SELECT symbol, datetime, close, volume, trade_date
    FROM option_bars_0dte
    ORDER BY datetime
    LIMIT 5
    """
    df_sample = pd.read_sql_query(query_sample, conn)
    print(df_sample.to_string(index=False))

    conn.close()

    print(f"\n✅ 0DTE data extracted successfully!")
    print(f"   Use table: option_bars_0dte")
    print()

# ============================================================================
#                    COMPARISON WITH WEEKLY
# ============================================================================

def compare_0dte_vs_weekly():
    """
    Compare 0DTE vs weekly option premiums to validate pricing difference.
    """
    print(f"\n{'='*70}")
    print("COMPARING 0DTE vs WEEKLY OPTION PREMIUMS")
    print(f"{'='*70}\n")

    conn = sqlite3.connect(DB_PATH)

    # First check if we have any 0DTE data
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM option_bars_0dte")
    count_0dte = cursor.fetchone()[0]

    if count_0dte == 0:
        print("❌ No 0DTE data in database")
        print("   Run with --extract first to populate option_bars_0dte table")
        conn.close()
        return

    # Get sample 0DTE prices
    print("Sample 0DTE Premiums (same-day expiration):\n")
    query_0dte = """
    SELECT
        symbol,
        datetime,
        close as premium,
        volume,
        trade_date
    FROM option_bars_0dte
    WHERE time(datetime) = '10:00:00'  -- 10 AM entry time
    ORDER BY datetime
    LIMIT 10
    """

    df_0dte = pd.read_sql_query(query_0dte, conn)
    print(df_0dte.to_string(index=False))

    if not df_0dte.empty:
        avg_0dte = df_0dte['premium'].mean()
        print(f"\nAverage 0DTE Premium: ${avg_0dte:.2f}")

    # Compare with weekly options (7 DTE)
    print(f"\n{'-'*70}\n")
    print("Sample Weekly Premiums (7 days to expiration):\n")

    query_weekly = """
    WITH cleaned AS (
        SELECT
            replace(symbol, ' ', '') as symbol,
            datetime,
            close,
            volume,
            date(datetime) as trade_date
        FROM option_bars_1min
    ),
    with_expiration AS (
        SELECT
            symbol,
            datetime,
            close as premium,
            volume,
            trade_date,
            '20' || substr(symbol, 4, 2) || '-' ||
            substr(symbol, 6, 2) || '-' ||
            substr(symbol, 8, 2) as expiration_date,
            julianday('20' || substr(symbol, 4, 2) || '-' ||
                     substr(symbol, 6, 2) || '-' ||
                     substr(symbol, 8, 2)) - julianday(trade_date) as dte
        FROM cleaned
    )
    SELECT
        symbol,
        datetime,
        premium,
        volume,
        trade_date,
        CAST(dte AS INTEGER) as days_to_expiration
    FROM with_expiration
    WHERE time(datetime) = '10:00:00'
      AND dte >= 6 AND dte <= 8  -- 7 DTE (±1 day)
    ORDER BY datetime
    LIMIT 10
    """

    df_weekly = pd.read_sql_query(query_weekly, conn)
    print(df_weekly.to_string(index=False))

    if not df_weekly.empty:
        avg_weekly = df_weekly['premium'].mean()
        print(f"\nAverage Weekly Premium: ${avg_weekly:.2f}")

        if not df_0dte.empty:
            ratio = avg_weekly / avg_0dte if avg_0dte > 0 else 0
            print(f"\nWeekly / 0DTE Ratio: {ratio:.1f}x")
            print(f"Weekly premiums are {ratio:.1f}× higher than 0DTE")

    conn.close()
    print()

# ============================================================================
#                    MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Extract 0DTE options from existing database'
    )
    parser.add_argument(
        '--analyze',
        action='store_true',
        help='Analyze if database contains 0DTE data'
    )
    parser.add_argument(
        '--extract',
        action='store_true',
        help='Extract 0DTE data to separate table'
    )
    parser.add_argument(
        '--compare',
        action='store_true',
        help='Compare 0DTE vs weekly premiums'
    )

    args = parser.parse_args()

    if not any([args.analyze, args.extract, args.compare]):
        print("Usage:")
        print("  --analyze   Check if database has 0DTE data")
        print("  --extract   Extract 0DTE to separate table")
        print("  --compare   Compare 0DTE vs weekly premiums")
        print()
        print("Example:")
        print("  python3 extract_0dte_from_existing_db.py --analyze")
        return

    if args.analyze:
        has_0dte = analyze_0dte_availability()

    if args.extract:
        extract_0dte_to_table()

    if args.compare:
        compare_0dte_vs_weekly()

if __name__ == '__main__':
    main()
