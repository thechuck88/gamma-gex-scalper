#!/usr/bin/env python3
"""
data_collector_enhanced.py — Enhanced Data Collection with 1-Minute Option Bars

Collects three types of data:
1. Underlying 1-minute bars (SPY/QQQ from Alpaca)
2. Daily option chains (SPX/NDX from Tradier)
3. **NEW**: 1-minute option bars for individual contracts (Tradier/Polygon)

The critical enhancement: Collects intraday 1-minute bars for each option contract
in today's 0DTE chain, enabling realistic backtesting with actual option prices.

Usage:
  # One-time historical collection (underlying + chains)
  python data_collector_enhanced.py --historical --days 365

  # Daily update (underlying + chains + 1min option bars)
  python data_collector_enhanced.py --daily

  # Status check
  python data_collector_enhanced.py --status

  # Collect 1-min option bars for specific date
  python data_collector_enhanced.py --collect-option-bars --date 2026-01-10

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
import time

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
#                    DATABASE SCHEMA (ENHANCED)
# ============================================================================

def create_database():
    """Create database with tables for underlying, chains, and 1-min option bars."""
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

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_option_root_date_exp
        ON option_chains(root, date, expiration)
    ''')

    # Table 3: **NEW** - 1-minute option bars for individual contracts
    cursor.execute('''
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
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_option_bars_symbol_datetime
        ON option_bars_1min(symbol, datetime)
    ''')

    # Table 4: Collection log
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
#                    **NEW**: 1-MINUTE OPTION BARS (TRADIER)
# ============================================================================

def collect_option_bars_1min_tradier(option_symbol, date_str, start_time='09:30', end_time='16:00'):
    """
    Collect 1-minute bars for a specific option contract using Tradier timesales API.

    Args:
        option_symbol: OCC option symbol (e.g., 'SPXW260110C06900000')
        date_str: Trading date (YYYY-MM-DD)
        start_time: Start time (HH:MM)
        end_time: End time (HH:MM)

    Returns: Number of bars collected
    """
    if not REQUESTS_AVAILABLE:
        print("❌ requests module not installed")
        return 0

    # Get Tradier credentials
    api_token = (os.environ.get('TRADIER_API_TOKEN') or
                 os.environ.get('TRADIER_LIVE_KEY'))  # Note: Sandbox may not have timesales

    if not api_token:
        print("❌ Tradier API token not found (need LIVE key for timesales)")
        return 0

    try:
        url = 'https://api.tradier.com/v1/markets/timesales'

        # Build start/end timestamps
        start_dt = datetime.datetime.strptime(f"{date_str} {start_time}", '%Y-%m-%d %H:%M')
        end_dt = datetime.datetime.strptime(f"{date_str} {end_time}", '%Y-%m-%d %H:%M')

        params = {
            'symbol': option_symbol,
            'interval': '1min',  # 1-minute bars
            'start': start_dt.strftime('%Y-%m-%d %H:%M'),
            'end': end_dt.strftime('%Y-%m-%d %H:%M')
        }

        headers = {
            'Authorization': f'Bearer {api_token}',
            'Accept': 'application/json'
        }

        response = requests.get(url, params=params, headers=headers)

        if response.status_code != 200:
            # Don't log error for every option (too noisy), just skip
            return 0

        data = response.json()
        series = data.get('series', {}).get('data', [])

        if not series:
            return 0

        # Convert to DataFrame
        df = pd.DataFrame(series)

        if df.empty:
            return 0

        # Rename columns and add metadata
        df = df.rename(columns={'time': 'datetime', 'price': 'close'})
        df['symbol'] = option_symbol

        # Calculate OHLC from price (if not provided)
        if 'open' not in df.columns:
            df['open'] = df['close']
        if 'high' not in df.columns:
            df['high'] = df['close']
        if 'low' not in df.columns:
            df['low'] = df['close']

        # Calculate mid from bid/ask if available
        if 'bid' in df.columns and 'ask' in df.columns:
            df['mid'] = (df['bid'] + df['ask']) / 2
        else:
            df['bid'] = None
            df['ask'] = None
            df['mid'] = df['close']

        # Greeks (if available)
        df['iv'] = df.get('iv', None)
        df['delta'] = df.get('delta', None)
        df['gamma'] = df.get('gamma', None)

        # Select columns for database
        columns = ['symbol', 'datetime', 'open', 'high', 'low', 'close', 'volume',
                   'bid', 'ask', 'mid', 'iv', 'delta', 'gamma']

        df = df[columns]

        # Store in database
        conn = sqlite3.connect(DB_PATH)

        df.to_sql(
            'option_bars_1min',
            conn,
            if_exists='append',
            index=False
        )

        conn.commit()
        conn.close()

        return len(df)

    except Exception as e:
        # Silent failure for individual options (too many to log)
        return 0

# ============================================================================
#                    **NEW**: 1-MINUTE OPTION BARS (POLYGON.IO)
# ============================================================================

def collect_option_bars_1min_polygon(option_symbol, date_str):
    """
    Collect 1-minute bars for a specific option contract using Polygon.io API.

    Args:
        option_symbol: OCC option symbol (e.g., 'SPXW260110C06900000')
        date_str: Trading date (YYYY-MM-DD)

    Returns: Number of bars collected
    """
    if not REQUESTS_AVAILABLE:
        return 0

    # Get Polygon API key
    api_key = os.environ.get('POLYGON_API_KEY')

    if not api_key:
        # Polygon not configured, skip silently
        return 0

    try:
        # Convert OCC symbol to Polygon format
        # Example: SPXW260110C06900000 → O:SPXW260110C06900000
        polygon_ticker = f"O:{option_symbol}"

        url = f"https://api.polygon.io/v2/aggs/ticker/{polygon_ticker}/range/1/minute/{date_str}/{date_str}"

        params = {
            'apiKey': api_key,
            'adjusted': 'false',
            'sort': 'asc'
        }

        response = requests.get(url, params=params)

        if response.status_code != 200:
            return 0

        data = response.json()
        results = data.get('results', [])

        if not results:
            return 0

        # Convert to DataFrame
        df = pd.DataFrame(results)

        # Rename columns (Polygon format)
        df = df.rename(columns={
            'o': 'open',
            'h': 'high',
            'l': 'low',
            'c': 'close',
            'v': 'volume',
            't': 'timestamp'
        })

        # Convert timestamp to datetime
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms').dt.strftime('%Y-%m-%d %H:%M:%S')
        df['symbol'] = option_symbol

        # Polygon doesn't provide bid/ask in aggregates
        df['bid'] = None
        df['ask'] = None
        df['mid'] = df['close']
        df['iv'] = None
        df['delta'] = None
        df['gamma'] = None

        # Select columns
        columns = ['symbol', 'datetime', 'open', 'high', 'low', 'close', 'volume',
                   'bid', 'ask', 'mid', 'iv', 'delta', 'gamma']

        df = df[columns]

        # Store in database
        conn = sqlite3.connect(DB_PATH)

        df.to_sql(
            'option_bars_1min',
            conn,
            if_exists='append',
            index=False
        )

        conn.commit()
        conn.close()

        return len(df)

    except Exception as e:
        return 0

# ============================================================================
#                    **NEW**: COLLECT ALL OPTIONS FOR A DATE
# ============================================================================

def collect_all_option_bars_for_date(date_str, root='SPXW'):
    """
    Collect 1-minute bars for all options in today's 0DTE chain.

    This is the CRITICAL function that builds the historical database of
    1-minute option pricing data.

    Args:
        date_str: Date to collect (YYYY-MM-DD)
        root: 'SPXW' or 'NDXW'

    Returns: Total number of bars collected
    """
    print(f"\n{'='*70}")
    print(f"COLLECTING 1-MIN OPTION BARS FOR {root} ON {date_str}")
    print(f"{'='*70}\n")

    # First, get the option chain to know which options exist
    print("Step 1: Fetching option chain to identify contracts...")
    option_count = collect_option_chain_tradier(root, date_str, date_str)

    if option_count == 0:
        print("❌ No option chain available, cannot collect 1-min bars")
        return 0

    # Query database for options collected
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(f"""
        SELECT symbol, strike, option_type
        FROM option_chains
        WHERE root = '{root}' AND date = '{date_str}'
        ORDER BY strike
    """, conn)
    conn.close()

    if df.empty:
        print("❌ No options found in database")
        return 0

    print(f"✓ Found {len(df)} option contracts in chain")
    print(f"\nStep 2: Collecting 1-minute bars for each contract...")
    print(f"  This may take several minutes (rate limits apply)...\n")

    total_bars = 0
    success_count = 0
    failed_count = 0

    # Try Tradier first, fall back to Polygon if available
    for idx, row in df.iterrows():
        symbol = row['symbol']
        strike = row['strike']
        opt_type = row['option_type']

        # Progress indicator
        if (idx + 1) % 10 == 0:
            print(f"  Progress: {idx + 1}/{len(df)} options ({success_count} success, {failed_count} failed)")

        # Try Tradier first
        bars = collect_option_bars_1min_tradier(symbol, date_str)

        # Fall back to Polygon if Tradier failed
        if bars == 0:
            bars = collect_option_bars_1min_polygon(symbol, date_str)

        if bars > 0:
            total_bars += bars
            success_count += 1
        else:
            failed_count += 1

        # Rate limiting (Tradier: 120 req/min, Polygon: 5 req/min free tier)
        time.sleep(0.5)  # 2 requests per second

    print(f"\n{'='*70}")
    print(f"COLLECTION COMPLETE")
    print(f"  Contracts processed: {len(df)}")
    print(f"  Successful: {success_count}")
    print(f"  Failed: {failed_count}")
    print(f"  Total 1-min bars: {total_bars:,}")
    print(f"{'='*70}\n")

    # Log collection
    log_collection('option_bars_1min', root, date_str, date_str, total_bars, True, None)

    return total_bars

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
    """Show database status including new 1-min option bars table."""
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

    # **NEW**: 1-minute option bars
    cursor.execute("""
        SELECT
            SUBSTR(symbol, 1, 4) as root,
            COUNT(DISTINCT SUBSTR(datetime, 1, 10)) as days,
            COUNT(DISTINCT symbol) as contracts,
            COUNT(*) as bars,
            MIN(datetime) as first_bar,
            MAX(datetime) as last_bar
        FROM option_bars_1min
        GROUP BY SUBSTR(symbol, 1, 4)
    """)
    rows = cursor.fetchall()

    print(f"\n⭐ 1-MINUTE OPTION BARS (NEW):")
    print(f"{'Root':<8} {'Days':>6} {'Contracts':>10} {'Total Bars':>12} {'First Bar':<20} {'Last Bar':<20}")
    print("-" * 100)

    for root, days, contracts, bars, first_bar, last_bar in rows:
        print(f"{root:<8} {days:>6} {contracts:>10,} {bars:>12,} {first_bar:<20} {last_bar:<20}")

    # Collection log (last 10 entries)
    cursor.execute("""
        SELECT collection_type, symbol, start_date, bars_collected, success, created_at
        FROM collection_log
        ORDER BY created_at DESC
        LIMIT 10
    """)
    rows = cursor.fetchall()

    print(f"\nRECENT COLLECTIONS (Last 10):")
    print(f"{'Type':<20} {'Symbol':<8} {'Date':<12} {'Count':>10} {'Status':<8} {'Time':<20}")
    print("-" * 90)

    for ctype, symbol, date, count, success, created in rows:
        status = "✓ OK" if success else "✗ FAIL"
        print(f"{ctype:<20} {symbol:<8} {date:<12} {count:>10,} {status:<8} {created:<20}")

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

    # Note: Option chains and 1-min bars are only available for ~30 days from Tradier
    print("\n2. Option chain & 1-min bar historical data:")
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

    # **NEW**: Collect 1-minute option bars for today's 0DTE
    print("\n3. Collecting 1-minute option bars for 0DTE contracts...")

    spx_bars = 0
    ndx_bars = 0

    if spx_count > 0:
        spx_bars = collect_all_option_bars_for_date(today_str, 'SPXW')

    if ndx_count > 0:
        ndx_bars = collect_all_option_bars_for_date(today_str, 'NDXW')

    print(f"\n{'='*70}")
    print("DAILY COLLECTION COMPLETE")
    print(f"  Underlying bars: {spy_bars + qqq_bars:,}")
    print(f"  Option chains: {spx_count + ndx_count:,}")
    print(f"  ⭐ 1-min option bars: {spx_bars + ndx_bars:,}")
    print(f"{'='*70}\n")

# ============================================================================
#                    MAIN ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='GEX Scalper Enhanced Data Collector')
    parser.add_argument('--historical', action='store_true', help='Collect historical data')
    parser.add_argument('--daily', action='store_true', help='Daily collection (for cron)')
    parser.add_argument('--status', action='store_true', help='Show database status')
    parser.add_argument('--collect-option-bars', action='store_true', help='Collect 1-min option bars for specific date')
    parser.add_argument('--date', type=str, help='Date for option bar collection (YYYY-MM-DD)')
    parser.add_argument('--root', type=str, default='SPXW', help='Option root (SPXW or NDXW)')
    parser.add_argument('--days', type=int, default=365, help='Days of historical data (default: 365)')

    args = parser.parse_args()

    # Create database if needed
    if not DB_PATH.exists() or args.historical or args.daily or args.collect_option_bars:
        create_database()

    # Execute requested action
    if args.historical:
        collect_historical(args.days)
    elif args.daily:
        collect_daily()
    elif args.collect_option_bars:
        if not args.date:
            print("❌ --date required for option bar collection")
            sys.exit(1)
        collect_all_option_bars_for_date(args.date, args.root)
    elif args.status:
        show_status()
    else:
        # Default: show status
        show_status()
        print("\nUsage:")
        print("  python data_collector_enhanced.py --historical --days 365")
        print("  python data_collector_enhanced.py --daily")
        print("  python data_collector_enhanced.py --collect-option-bars --date 2026-01-10 --root SPXW")
        print("  python data_collector_enhanced.py --status")
