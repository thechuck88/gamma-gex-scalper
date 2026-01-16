#!/usr/bin/env python3
"""
GEX Black Box Recorder - Capture real-time options market data for backtesting

Records:
- Options chains (strikes, OI, gamma, bid/ask)
- GEX calculations by strike
- Top 3 proximity-weighted peaks
- Competing peaks detection
- Underlying price, VIX

Purpose: Build historical dataset for accurate GEX backtesting

Usage:
    # Run manually (single snapshot)
    python3 gex_blackbox_recorder.py SPX
    python3 gex_blackbox_recorder.py NDX

    # Cron (every 5 min during market hours)
    */5 9-16 * * 1-5 python3 /root/gamma/gex_blackbox_recorder.py SPX >> /var/log/gex_recorder.log 2>&1
    */5 9-16 * * 1-5 python3 /root/gamma/gex_blackbox_recorder.py NDX >> /var/log/gex_recorder.log 2>&1
"""

import sys
import json
import sqlite3
import requests
from datetime import datetime, date
from collections import defaultdict
import os

# Add gamma path for imports
sys.path.insert(0, '/root/gamma')

from index_config import get_index_config

# Database location
DB_PATH = "/root/gamma/data/gex_blackbox.db"


def get_optimized_connection():
    """
    Get database connection with performance optimizations.

    Call this instead of sqlite3.connect(DB_PATH) to ensure
    all connections use optimal settings.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Apply performance optimizations (must be set per connection)
    cursor.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging
    cursor.execute("PRAGMA synchronous=NORMAL")  # Faster commits
    cursor.execute("PRAGMA cache_size=-64000")  # 64 MB cache
    cursor.execute("PRAGMA temp_store=MEMORY")  # Temp in RAM
    cursor.execute("PRAGMA mmap_size=268435456")  # 256 MB mmap

    return conn

# Tradier API (use LIVE for options data)
try:
    from config import TRADIER_LIVE_KEY
except ImportError:
    print("ERROR: Cannot import TRADIER_LIVE_KEY from config.py")
    print("Make sure /root/gamma/config.py exists with TRADIER_LIVE_KEY defined")
    sys.exit(1)

TRADIER_URL = "https://api.tradier.com/v1/"
TRADIER_HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {TRADIER_LIVE_KEY}"
}


def init_database():
    """Initialize SQLite database with schema and performance optimizations."""
    conn = get_optimized_connection()
    cursor = conn.cursor()

    # Performance optimizations for write-heavy time-series workload
    cursor.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging (faster writes)
    cursor.execute("PRAGMA synchronous=NORMAL")  # Balance safety/speed
    cursor.execute("PRAGMA cache_size=-64000")  # 64 MB cache
    cursor.execute("PRAGMA temp_store=MEMORY")  # Temp tables in RAM
    cursor.execute("PRAGMA mmap_size=268435456")  # 256 MB memory-mapped I/O

    # Table 1: Raw options snapshots (full chain data)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS options_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL,
            index_symbol TEXT NOT NULL,
            underlying_price REAL NOT NULL,
            vix REAL,
            expiration TEXT NOT NULL,
            chain_data TEXT NOT NULL,
            UNIQUE(timestamp, index_symbol, expiration)
        )
    """)

    # Table 2: Calculated GEX peaks (top 3 for quick lookup)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gex_peaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL,
            index_symbol TEXT NOT NULL,
            peak_rank INTEGER NOT NULL,
            strike REAL NOT NULL,
            gex REAL NOT NULL,
            distance_from_price REAL NOT NULL,
            distance_pct REAL NOT NULL,
            proximity_score REAL NOT NULL,
            UNIQUE(timestamp, index_symbol, peak_rank)
        )
    """)

    # Table 3: Competing peaks detection results
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS competing_peaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL,
            index_symbol TEXT NOT NULL,
            is_competing BOOLEAN NOT NULL,
            peak1_strike REAL,
            peak1_gex REAL,
            peak2_strike REAL,
            peak2_gex REAL,
            score_ratio REAL,
            adjusted_pin REAL,
            UNIQUE(timestamp, index_symbol)
        )
    """)

    # Table 4: Market context (underlying, VIX, etc.)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL,
            index_symbol TEXT NOT NULL,
            underlying_price REAL NOT NULL,
            vix REAL,
            spy_price REAL,
            qqq_price REAL,
            UNIQUE(timestamp, index_symbol)
        )
    """)

    # Indexes for fast querying
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_time ON options_snapshots(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_peaks_time ON gex_peaks(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_competing_time ON competing_peaks(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_context_time ON market_context(timestamp)")

    conn.commit()
    conn.close()
    print(f"✅ Database initialized: {DB_PATH}")


def cleanup_old_data(retention_days=365):
    """
    Remove data older than retention_days to keep database size manageable.

    Default: 365 days (1 year)

    Called daily by the service to maintain rolling 1-year window.
    """
    try:
        conn = get_optimized_connection()
        cursor = conn.cursor()

        # Calculate cutoff date
        # BUGFIX (2026-01-16): Use UTC-aware datetime for database retention
        # Database stores timestamps as UTC from Tradier API - naive datetime would use local time
        # causing wrong records to be deleted (off by EDT/EST offset)
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')

        # Count records before cleanup
        cursor.execute("SELECT COUNT(*) FROM options_snapshots WHERE timestamp < ?", (cutoff_str,))
        old_snapshots = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM gex_peaks WHERE timestamp < ?", (cutoff_str,))
        old_peaks = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM options_prices_live WHERE timestamp < ?", (cutoff_str,))
        old_prices = cursor.fetchone()[0]

        if old_snapshots == 0 and old_peaks == 0 and old_prices == 0:
            print(f"✅ No data older than {retention_days} days - cleanup skipped")
            conn.close()
            return True

        # Delete old data from all tables
        cursor.execute("DELETE FROM options_snapshots WHERE timestamp < ?", (cutoff_str,))
        cursor.execute("DELETE FROM gex_peaks WHERE timestamp < ?", (cutoff_str,))
        cursor.execute("DELETE FROM competing_peaks WHERE timestamp < ?", (cutoff_str,))
        cursor.execute("DELETE FROM market_context WHERE timestamp < ?", (cutoff_str,))
        cursor.execute("DELETE FROM options_prices_live WHERE timestamp < ?", (cutoff_str,))

        conn.commit()

        print(f"🗑️  Cleaned up data older than {retention_days} days:")
        print(f"   - {old_snapshots} option snapshots")
        print(f"   - {old_peaks} GEX peaks")
        print(f"   - {old_prices} live prices")

        # Vacuum to reclaim space
        print("   Vacuuming database...")
        cursor.execute("VACUUM")

        conn.close()
        return True

    except Exception as e:
        print(f"❌ Cleanup error: {e}")
        return False


def get_price(symbol):
    """Fetch current price from Tradier."""
    try:
        r = requests.get(
            f"{TRADIER_URL}markets/quotes",
            headers=TRADIER_HEADERS,
            params={"symbols": symbol},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            q = data.get("quotes", {}).get("quote")
            if q:
                if isinstance(q, list):
                    q = q[0]
                price = q.get("last") or q.get("bid") or q.get("ask")
                if price:
                    return float(price)
    except Exception as e:
        print(f"Error fetching {symbol} price: {e}")
    return None


def get_options_chain(index_symbol, expiration):
    """Fetch full options chain with greeks and OI."""
    try:
        r = requests.get(
            f"{TRADIER_URL}markets/options/chains",
            headers=TRADIER_HEADERS,
            params={
                "symbol": index_symbol,
                "expiration": expiration,
                "greeks": "true"
            },
            timeout=30
        )

        if r.status_code != 200:
            print(f"Options chain API failed: {r.status_code}")
            return None

        data = r.json()
        options = data.get("options", {})
        if not options:
            print("No options data returned")
            return None

        option_list = options.get("option", [])
        if not option_list:
            print("Empty options list")
            return None

        # Convert to list of dicts with relevant fields
        chain = []
        for opt in option_list:
            chain.append({
                'strike': opt.get('strike'),
                'option_type': opt.get('option_type'),
                'bid': opt.get('bid'),
                'ask': opt.get('ask'),
                'last': opt.get('last'),
                'open_interest': opt.get('open_interest', 0),
                'volume': opt.get('volume', 0),
                'greeks': {
                    'delta': opt.get('greeks', {}).get('delta', 0) if opt.get('greeks') else 0,
                    'gamma': opt.get('greeks', {}).get('gamma', 0) if opt.get('greeks') else 0,
                    'theta': opt.get('greeks', {}).get('theta', 0) if opt.get('greeks') else 0,
                    'vega': opt.get('greeks', {}).get('vega', 0) if opt.get('greeks') else 0,
                }
            })

        return chain

    except Exception as e:
        print(f"Error fetching options chain: {e}")
        return None


def calculate_gex_and_peaks(chain, underlying_price, index_config):
    """Calculate GEX by strike and identify top 3 proximity-weighted peaks."""
    gex_by_strike = defaultdict(float)

    # Calculate GEX for each strike
    for opt in chain:
        strike = opt['strike']
        oi = opt['open_interest']
        gamma = opt['greeks']['gamma']
        opt_type = opt['option_type']

        if oi == 0 or gamma == 0:
            continue

        # GEX formula: gamma × OI × 100 × spot²
        gex = gamma * oi * 100 * (underlying_price ** 2)

        if opt_type == 'call':
            gex_by_strike[strike] += gex
        else:
            gex_by_strike[strike] -= gex

    if not gex_by_strike:
        return None, None

    # Filter to positive GEX within reasonable distance
    max_distance_pct = 0.015 if index_config.code == 'SPX' else 0.020
    max_distance = underlying_price * max_distance_pct

    nearby_peaks = [(s, g) for s, g in gex_by_strike.items()
                    if abs(s - underlying_price) < max_distance and g > 0]

    if not nearby_peaks:
        # Fallback to wider range
        nearby_peaks = [(s, g) for s, g in gex_by_strike.items()
                       if abs(s - underlying_price) < index_config.far_max and g > 0]

    if not nearby_peaks:
        return None, None

    # Score peaks by proximity (same as bot logic)
    def score_peak(strike, gex):
        distance_pct = abs(strike - underlying_price) / underlying_price
        return gex / (distance_pct ** 5 + 1e-12)

    scored_peaks = [(s, g, score_peak(s, g)) for s, g in nearby_peaks]
    sorted_scored = sorted(scored_peaks, key=lambda x: x[2], reverse=True)[:3]

    return gex_by_strike, sorted_scored


def detect_competing_peaks(sorted_scored, underlying_price):
    """Detect if price is between two competing peaks (same logic as bot)."""
    if len(sorted_scored) < 2:
        return False, None, None, None, None, None

    peak1_strike, peak1_gex, peak1_score = sorted_scored[0]
    peak2_strike, peak2_gex, peak2_score = sorted_scored[1]

    score_ratio = min(peak1_score, peak2_score) / max(peak1_score, peak2_score)
    opposite_sides = (peak1_strike < underlying_price < peak2_strike) or \
                     (peak2_strike < underlying_price < peak1_strike)

    distance1 = abs(peak1_strike - underlying_price)
    distance2 = abs(peak2_strike - underlying_price)
    distance_ratio = min(distance1, distance2) / max(distance1, distance2)
    reasonably_centered = distance_ratio > 0.4

    is_competing = score_ratio > 0.5 and opposite_sides and reasonably_centered

    if is_competing:
        midpoint = (peak1_strike + peak2_strike) / 2
        # Would use INDEX_CONFIG.round_strike(midpoint) in bot
        return True, peak1_strike, peak1_gex, peak2_strike, peak2_gex, score_ratio
    else:
        return False, None, None, None, None, None


def record_snapshot(index_symbol):
    """Record a single snapshot of options market data."""
    print(f"\n{'='*60}")
    print(f"Recording snapshot: {index_symbol} at {datetime.now()}")
    print(f"{'='*60}")

    # Get index config
    try:
        index_config = get_index_config(index_symbol.upper())
    except ValueError as e:
        print(f"ERROR: {e}")
        return False

    # Get current prices
    underlying_price = get_price(index_config.index_symbol)
    if not underlying_price:
        print(f"Failed to fetch {index_config.index_symbol} price")
        return False

    vix = get_price("VIX")
    spy_price = get_price("SPY") if index_symbol.upper() == 'SPX' else None
    qqq_price = get_price("QQQ") if index_symbol.upper() == 'NDX' else None

    # Get 0DTE expiration
    today = date.today().strftime("%Y-%m-%d")

    # Fetch options chain
    print(f"Fetching options chain for {index_config.index_symbol} expiring {today}...")
    chain = get_options_chain(index_config.index_symbol, today)

    if not chain:
        print("Failed to fetch options chain")
        return False

    print(f"✓ Fetched {len(chain)} options")

    # Calculate GEX and peaks
    print("Calculating GEX and proximity-weighted peaks...")
    gex_by_strike, top_peaks = calculate_gex_and_peaks(chain, underlying_price, index_config)

    if not top_peaks:
        print("No valid GEX peaks found")
        return False

    print(f"✓ Found {len(top_peaks)} peaks")
    for rank, (strike, gex, score) in enumerate(top_peaks, 1):
        dist = abs(strike - underlying_price)
        dist_pct = dist / underlying_price * 100
        print(f"  Peak {rank}: {strike} (GEX={gex/1e9:.1f}B, {dist:.0f}pts, score={score/1e9:.1f})")

    # Detect competing peaks
    is_competing, p1_strike, p1_gex, p2_strike, p2_gex, score_ratio = \
        detect_competing_peaks(top_peaks, underlying_price)

    if is_competing:
        print(f"⚠️  COMPETING PEAKS: {p1_strike} vs {p2_strike} (ratio={score_ratio:.2f})")

    # Store to database
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_optimized_connection()
    cursor = conn.cursor()

    try:
        # Store raw chain snapshot
        chain_json = json.dumps(chain)
        cursor.execute("""
            INSERT OR REPLACE INTO options_snapshots
            (timestamp, index_symbol, underlying_price, vix, expiration, chain_data)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (timestamp, index_symbol.upper(), underlying_price, vix, today, chain_json))

        # Store top 3 peaks
        for rank, (strike, gex, score) in enumerate(top_peaks, 1):
            distance = abs(strike - underlying_price)
            distance_pct = distance / underlying_price * 100

            cursor.execute("""
                INSERT OR REPLACE INTO gex_peaks
                (timestamp, index_symbol, peak_rank, strike, gex,
                 distance_from_price, distance_pct, proximity_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (timestamp, index_symbol.upper(), rank, strike, gex,
                  distance, distance_pct, score))

        # Store competing peaks detection
        adjusted_pin = (p1_strike + p2_strike) / 2 if is_competing else None
        cursor.execute("""
            INSERT OR REPLACE INTO competing_peaks
            (timestamp, index_symbol, is_competing, peak1_strike, peak1_gex,
             peak2_strike, peak2_gex, score_ratio, adjusted_pin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (timestamp, index_symbol.upper(), is_competing,
              p1_strike, p1_gex, p2_strike, p2_gex, score_ratio, adjusted_pin))

        # Store market context
        cursor.execute("""
            INSERT OR REPLACE INTO market_context
            (timestamp, index_symbol, underlying_price, vix, spy_price, qqq_price)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (timestamp, index_symbol.upper(), underlying_price, vix, spy_price, qqq_price))

        conn.commit()
        print(f"✅ Snapshot saved to database")

        # Print storage stats
        cursor.execute("SELECT COUNT(*) FROM options_snapshots WHERE index_symbol = ?",
                      (index_symbol.upper(),))
        snapshot_count = cursor.fetchone()[0]

        cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM options_snapshots WHERE index_symbol = ?",
                      (index_symbol.upper(),))
        min_ts, max_ts = cursor.fetchone()

        print(f"📊 Total snapshots for {index_symbol}: {snapshot_count}")
        if min_ts and max_ts:
            print(f"   Date range: {min_ts} to {max_ts}")

        return True

    except Exception as e:
        print(f"Database error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 gex_blackbox_recorder.py <SPX|NDX>")
        sys.exit(1)

    index_symbol = sys.argv[1].upper()

    if index_symbol not in ['SPX', 'NDX']:
        print(f"ERROR: Invalid index '{index_symbol}'. Use SPX or NDX.")
        sys.exit(1)

    # Initialize database
    if not os.path.exists(DB_PATH):
        init_database()

    # Record snapshot
    success = record_snapshot(index_symbol)

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
