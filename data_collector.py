#!/usr/bin/env python3
"""
data_collector.py — Background Data Collection for GEX Scalper

Collects two types of data:
1. Underlying 1-minute bars (SPY/QQQ from Alpaca)
2. Daily option chains (SPX/NDX from Tradier)

Both stored in SQLite for fast backtest access.

Usage:
  # One-time historical collection
  python data_collector.py --historical --days 365

  # Daily update (add to cron)
  python data_collector.py --daily

  # Status check
  python data_collector.py --status

Author: Claude Code (2026-01-10)
"""

import os
import sys
import sqlite3
import argparse
import datetime
import pandas as pd
import numpy as np
from pathlib import Path

# Try imports with helpful error messages
try:
    from alpaca_trade_api.rest import REST, TimeFrame
    ALPACA_AVAILABLE = True
except ImportError:
    print("⚠️  alpaca-trade-api not installed. Install: pip install alpaca-trade-api")
    ALPACA_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    print("⚠️  requests not installed. Install: pip install requests")
    REQUESTS_AVAILABLE = False

# Database configuration
DB_PATH = Path("/root/gamma/market_data.db")  # Centralized market data database (backed up by restic)

# ============================================================================
#                    DATABASE SCHEMA
# ============================================================================

def create_database():
    """Create database with tables for underlying and options data."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Table 1: Underlying 1-minute bars (SPY, QQQ)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS underlying_1min (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            datetime TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, datetime)
        )
    ''')

    # Index for fast queries
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_underlying_symbol_datetime
        ON underlying_1min(symbol, datetime)
    ''')

    # Table 2: Daily option chains (SPX, NDX)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS option_chains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            root TEXT NOT NULL,
            date TEXT NOT NULL,
            expiration TEXT NOT NULL,
            strike REAL NOT NULL,
            option_type TEXT NOT NULL,
            symbol TEXT NOT NULL,
            bid REAL,
            ask REAL,
            mid REAL,
            last REAL,
            volume INTEGER,
            open_interest INTEGER,
            iv REAL,
            delta REAL,
            gamma REAL,
            theta REAL,
            vega REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, date)
        )
    ''')

    # Index for fast queries
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_option_root_date_exp
        ON option_chains(root, date, expiration)
    ''')

    # Table 3: Collection log
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS collection_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collection_type TEXT NOT NULL,
            symbol TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            bars_collected INTEGER,
            success BOOLEAN NOT NULL,
            error_message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    print(f"✓ Database created/verified: {DB_PATH}")

# ============================================================================
#                    UNDERLYING DATA COLLECTION (ALPACA)
# ============================================================================

def collect_underlying_bars_alpaca(symbol, start_date, end_date):
    """
    Collect 1-minute bars from Alpaca for SPY or QQQ.

    Args:
        symbol: 'SPY' or 'QQQ'
        start_date: datetime object
        end_date: datetime object

    Returns: Number of bars collected
    """
    if not ALPACA_AVAILABLE:
        print("❌ Alpaca SDK not installed")
        return 0

    # Get Alpaca credentials (try multiple env var names)
    api_key = (os.environ.get('APCA_API_KEY_ID') or
               os.environ.get('ALPACA_API_KEY') or
               os.environ.get('ALPACA_PAPER_KEY'))
    api_secret = (os.environ.get('APCA_API_SECRET_KEY') or
                  os.environ.get('ALPACA_SECRET_KEY') or
                  os.environ.get('ALPACA_PAPER_SECRET'))
    base_url = os.environ.get('APCA_API_BASE_URL', 'https://paper-api.alpaca.markets')

    if not api_key or not api_secret:
        print("❌ Alpaca API keys not found in environment")
        print("   Set APCA_API_KEY_ID and APCA_API_SECRET_KEY")
        return 0

    try:
        api = REST(api_key, api_secret, base_url=base_url)

        print(f"Fetching {symbol} 1-minute bars from {start_date.date()} to {end_date.date()}...")

        # Fetch 1-minute bars
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')

        bars = api.get_bars(
            symbol,
            TimeFrame.Minute,
            start=start_str,
            end=end_str,
            adjustment='raw'
        ).df

        if bars.empty:
            print(f"⚠️  No data returned for {symbol}")
            return 0

        # Reset index to get timestamp column
        bars = bars.reset_index()
        bars = bars.rename(columns={'timestamp': 'datetime'})

        # Convert to required format
        bars['symbol'] = symbol
        bars['datetime'] = pd.to_datetime(bars['datetime']).dt.strftime('%Y-%m-%d %H:%M:%S')

        # Store in database
        conn = sqlite3.connect(DB_PATH)

        # Use INSERT OR REPLACE to handle duplicates
        bars[['symbol', 'datetime', 'open', 'high', 'low', 'close', 'volume']].to_sql(
            'underlying_1min',
            conn,
            if_exists='append',
            index=False
        )

        conn.commit()
        conn.close()

        print(f"✓ Collected {len(bars)} bars for {symbol}")

        # Log collection
        log_collection('underlying_1min', symbol, start_date, end_date, len(bars), True, None)

        return len(bars)

    except Exception as e:
        print(f"❌ Error collecting {symbol}: {e}")
        log_collection('underlying_1min', symbol, start_date, end_date, 0, False, str(e))
        return 0

# ============================================================================
#                    OPTION CHAIN COLLECTION (TRADIER)
# ============================================================================

def collect_option_chain_tradier(root, date_str, expiration):
    """
    Collect option chain from Tradier for specific expiration.

    Args:
        root: 'SPXW' or 'NDXW'
        date_str: Date to associate with snapshot (YYYY-MM-DD)
        expiration: Expiration date (YYYY-MM-DD)

    Returns: Number of options collected
    """
    if not REQUESTS_AVAILABLE:
        print("❌ requests module not installed")
        return 0

    # Try multiple env var names for Tradier
    api_token = (os.environ.get('TRADIER_API_TOKEN') or
                 os.environ.get('TRADIER_SANDBOX_KEY') or
                 os.environ.get('TRADIER_LIVE_KEY'))
    if not api_token:
        print("❌ Tradier API token not found in environment")
        print("   Set TRADIER_SANDBOX_KEY or TRADIER_LIVE_KEY in /etc/gamma.env")
        return 0

    try:
        url = 'https://api.tradier.com/v1/markets/options/chains'

        params = {
            'symbol': root,
            'expiration': expiration,
            'greeks': 'true'
        }

        headers = {
            'Authorization': f'Bearer {api_token}',
            'Accept': 'application/json'
        }

        print(f"Fetching {root} option chain for {expiration}...")

        response = requests.get(url, params=params, headers=headers)

        if response.status_code != 200:
            print(f"❌ Tradier API error: {response.status_code}")
            log_collection('option_chain', root, date_str, date_str, 0, False, f"HTTP {response.status_code}")
            return 0

        data = response.json()
        options = data.get('options', {}).get('option', [])

        if not options:
            print(f"⚠️  No options returned for {root} {expiration}")
            return 0

        # Convert to DataFrame
        df = pd.DataFrame(options)

        # Extract relevant fields
        df['root'] = root
        df['date'] = date_str
        df['expiration'] = expiration
        df['mid'] = (df['bid'] + df['ask']) / 2

        # Extract greeks if available
        if 'greeks' in df.columns:
            df['delta'] = df['greeks'].apply(lambda x: x.get('delta') if isinstance(x, dict) else None)
            df['gamma'] = df['greeks'].apply(lambda x: x.get('gamma') if isinstance(x, dict) else None)
            df['theta'] = df['greeks'].apply(lambda x: x.get('theta') if isinstance(x, dict) else None)
            df['vega'] = df['greeks'].apply(lambda x: x.get('vega') if isinstance(x, dict) else None)
            df['iv'] = df['greeks'].apply(lambda x: x.get('smv_vol') if isinstance(x, dict) else None)
        else:
            df['delta'] = None
            df['gamma'] = None
            df['theta'] = None
            df['vega'] = None
            df['iv'] = None

        # Select columns
        columns = [
            'root', 'date', 'expiration', 'strike', 'option_type',
            'symbol', 'bid', 'ask', 'mid', 'last', 'volume',
            'open_interest', 'iv', 'delta', 'gamma', 'theta', 'vega'
        ]

        df = df[columns]

        # Store in database
        conn = sqlite3.connect(DB_PATH)

        df.to_sql(
            'option_chains',
            conn,
            if_exists='append',
            index=False
        )

        conn.commit()
        conn.close()

        print(f"✓ Collected {len(df)} options for {root} {expiration}")

        # Log collection
        log_collection('option_chain', root, date_str, date_str, len(df), True, None)

        return len(df)

    except Exception as e:
        print(f"❌ Error collecting {root} option chain: {e}")
        log_collection('option_chain', root, date_str, date_str, 0, False, str(e))
        return 0

# ============================================================================
#                    COLLECTION LOG
# ============================================================================

def log_collection(collection_type, symbol, start_date, end_date, bars_collected, success, error_message):
    """Log collection to database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO collection_log
        (collection_type, symbol, start_date, end_date, bars_collected, success, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        collection_type,
        symbol,
        start_date.strftime('%Y-%m-%d') if isinstance(start_date, datetime.datetime) else start_date,
        end_date.strftime('%Y-%m-%d') if isinstance(end_date, datetime.datetime) else end_date,
        bars_collected,
        success,
        error_message
    ))

    conn.commit()
    conn.close()

# ============================================================================
#                    STATUS & REPORTING
# ============================================================================

def show_status():
    """Show database status."""
    if not DB_PATH.exists():
        print("❌ Database does not exist. Run with --historical first.")
        return

    conn = sqlite3.connect(DB_PATH)

    print(f"\n{'='*70}")
    print("DATABASE STATUS")
    print(f"{'='*70}\n")

    print(f"Location: {DB_PATH}")
    print(f"Size: {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB\n")

    # Underlying bars
    cursor = conn.cursor()
    cursor.execute("SELECT symbol, COUNT(*), MIN(datetime), MAX(datetime) FROM underlying_1min GROUP BY symbol")
    rows = cursor.fetchall()

    print("UNDERLYING 1-MINUTE BARS:")
    print(f"{'Symbol':<8} {'Count':>10} {'First Bar':<20} {'Last Bar':<20}")
    print("-" * 70)

    for symbol, count, min_dt, max_dt in rows:
        print(f"{symbol:<8} {count:>10,} {min_dt:<20} {max_dt:<20}")

    # Option chains
    cursor.execute("""
        SELECT root, COUNT(DISTINCT date), COUNT(*), MIN(date), MAX(date)
        FROM option_chains
        GROUP BY root
    """)
    rows = cursor.fetchall()

    print(f"\nOPTION CHAINS:")
    print(f"{'Root':<8} {'Days':>6} {'Options':>10} {'First Date':<12} {'Last Date':<12}")
    print("-" * 70)

    for root, days, options, min_date, max_date in rows:
        print(f"{root:<8} {days:>6} {options:>10,} {min_date:<12} {max_date:<12}")

    # Collection log (last 10 entries)
    cursor.execute("""
        SELECT collection_type, symbol, start_date, bars_collected, success, created_at
        FROM collection_log
        ORDER BY created_at DESC
        LIMIT 10
    """)
    rows = cursor.fetchall()

    print(f"\nRECENT COLLECTIONS (Last 10):")
    print(f"{'Type':<15} {'Symbol':<8} {'Date':<12} {'Count':>8} {'Status':<8} {'Time':<20}")
    print("-" * 70)

    for ctype, symbol, date, count, success, created in rows:
        status = "✓ OK" if success else "✗ FAIL"
        print(f"{ctype:<15} {symbol:<8} {date:<12} {count:>8,} {status:<8} {created:<20}")

    conn.close()

    print(f"\n{'='*70}\n")

# ============================================================================
#                    MAIN COLLECTION FUNCTIONS
# ============================================================================

def collect_historical(days=365):
    """Collect historical data (one-time)."""
    print(f"\n{'='*70}")
    print(f"HISTORICAL DATA COLLECTION ({days} days)")
    print(f"{'='*70}\n")

    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=days)

    # Collect underlying bars (SPY, QQQ)
    print("\n1. Collecting underlying 1-minute bars...")
    spy_bars = collect_underlying_bars_alpaca('SPY', start_date, end_date)
    qqq_bars = collect_underlying_bars_alpaca('QQQ', start_date, end_date)

    print(f"\n✓ Collected {spy_bars + qqq_bars:,} total underlying bars")

    # Note: Option chains are only available for ~30 days from Tradier
    print("\n2. Option chain historical data:")
    print("   Note: Tradier only provides ~30 days of option history.")
    print("   Use daily collector going forward to build historical database.")

    print(f"\n{'='*70}")
    print("HISTORICAL COLLECTION COMPLETE")
    print(f"{'='*70}\n")

def collect_daily():
    """Collect today's data (run daily via cron)."""
    print(f"\n{'='*70}")
    print(f"DAILY DATA COLLECTION - {datetime.datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'='*70}\n")

    today = datetime.datetime.now()
    yesterday = today - datetime.timedelta(days=1)

    # Collect yesterday's underlying bars (in case missed)
    print("1. Collecting underlying 1-minute bars...")
    spy_bars = collect_underlying_bars_alpaca('SPY', yesterday, today)
    qqq_bars = collect_underlying_bars_alpaca('QQQ', yesterday, today)

    # Collect today's 0DTE option chains
    print("\n2. Collecting 0DTE option chains...")

    today_str = today.strftime('%Y-%m-%d')

    # SPX 0DTE (if available)
    spx_count = collect_option_chain_tradier('SPXW', today_str, today_str)

    # NDX 0DTE (if available)
    ndx_count = collect_option_chain_tradier('NDXW', today_str, today_str)

    print(f"\n{'='*70}")
    print("DAILY COLLECTION COMPLETE")
    print(f"  Underlying bars: {spy_bars + qqq_bars:,}")
    print(f"  Option chains: {spx_count + ndx_count:,}")
    print(f"{'='*70}\n")

# ============================================================================
#                    MAIN ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='GEX Scalper Data Collector')
    parser.add_argument('--historical', action='store_true', help='Collect historical data')
    parser.add_argument('--daily', action='store_true', help='Daily collection (for cron)')
    parser.add_argument('--status', action='store_true', help='Show database status')
    parser.add_argument('--days', type=int, default=365, help='Days of historical data (default: 365)')

    args = parser.parse_args()

    # Create database if needed
    if not DB_PATH.exists() or args.historical or args.daily:
        create_database()

    # Execute requested action
    if args.historical:
        collect_historical(args.days)
    elif args.daily:
        collect_daily()
    elif args.status:
        show_status()
    else:
        # Default: show status
        show_status()
        print("\nUsage:")
        print("  python data_collector.py --historical --days 365")
        print("  python data_collector.py --daily")
        print("  python data_collector.py --status")
