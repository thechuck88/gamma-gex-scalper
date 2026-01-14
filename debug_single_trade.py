#!/usr/bin/env python3
"""
Debug a single trade to understand why backtest is showing losses
"""

import sqlite3
import pandas as pd
from datetime import datetime
import sys
sys.path.insert(0, '/root/gamma')
from core.gex_strategy import get_gex_trade_setup

DB_PATH = "/root/gamma/data/gex_blackbox.db"

def get_optimized_connection():
    """Get database connection with optimizations."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

# Get first trade from database
conn = get_optimized_connection()
cursor = conn.cursor()

# Get first GEX peak
cursor.execute("""
SELECT 
    g.timestamp,
    g.index_symbol,
    s.underlying_price,
    s.vix,
    g.strike as pin_strike,
    g.gex,
    g.peak_rank
FROM gex_peaks g
LEFT JOIN options_snapshots s ON g.timestamp = s.timestamp
    AND g.index_symbol = s.index_symbol
WHERE g.peak_rank <= 1
ORDER BY g.timestamp ASC
LIMIT 1
""")

row = cursor.fetchone()
if not row:
    print("No trades found")
    exit(1)

timestamp, index_symbol, underlying, vix, pin_strike, gex, peak_rank = row

print(f"=== TRADE DEBUG ===")
print(f"Timestamp (UTC): {timestamp}")
print(f"Index: {index_symbol}")
print(f"Underlying Price: {underlying}")
print(f"VIX: {vix}")
print(f"PIN Strike: {pin_strike}")
print(f"GEX: {gex}")
print(f"Peak Rank: {peak_rank}")

# Get trade setup
setup = get_gex_trade_setup(pin_strike, underlying, vix, vix_threshold=20.0)
print(f"\nTrade Setup from get_gex_trade_setup():")
print(f"  Strategy: {setup.strategy}")
print(f"  Strikes: {setup.strikes}")
print(f"  Direction: {setup.direction}")
print(f"  Description: {setup.description}")

if setup.strategy == 'SKIP':
    print("SKIPPED - VIX too high or too far from PIN")
    exit(0)

# Get entry credit
if setup.strategy == 'CALL':
    short_strike, long_strike = setup.strikes[0], setup.strikes[1]
    spread_type = 'call'
elif setup.strategy == 'PUT':
    short_strike, long_strike = setup.strikes[0], setup.strikes[1]
    spread_type = 'put'
elif setup.strategy == 'IC':
    short_strike, long_strike = setup.strikes[0], setup.strikes[1]
    spread_type = 'call'
else:
    print("Unknown strategy")
    exit(1)

print(f"\nEntry Setup:")
print(f"  Short Strike: {short_strike}")
print(f"  Long Strike: {long_strike}")
print(f"  Spread Type: {spread_type.upper()}")

# Get entry credit
cursor.execute("""
SELECT DISTINCT timestamp FROM options_prices_live
WHERE timestamp >= ? AND index_symbol = ?
ORDER BY timestamp ASC LIMIT 1
""", (timestamp, index_symbol))

closest_ts_row = cursor.fetchone()
if not closest_ts_row:
    print("No option prices found")
    exit(1)

closest_ts = closest_ts_row[0]
print(f"  Closest Timestamp: {closest_ts}")

# Get short leg bid
cursor.execute("""
SELECT bid FROM options_prices_live
WHERE timestamp = ? AND index_symbol = ? AND strike = ? AND option_type = ?
""", (closest_ts, index_symbol, short_strike, spread_type))

short_bid_row = cursor.fetchone()
short_bid = short_bid_row[0] if short_bid_row else None

# Get long leg ask
cursor.execute("""
SELECT ask FROM options_prices_live
WHERE timestamp = ? AND index_symbol = ? AND strike = ? AND option_type = ?
""", (closest_ts, index_symbol, long_strike, spread_type))

long_ask_row = cursor.fetchone()
long_ask = long_ask_row[0] if long_ask_row else None

print(f"\nOption Prices at Entry:")
print(f"  Short {short_strike} {spread_type.upper()} Bid: ${short_bid}")
print(f"  Long {long_strike} {spread_type.upper()} Ask: ${long_ask}")

entry_credit = short_bid - long_ask if short_bid and long_ask else None
print(f"  Entry Credit: ${entry_credit}")

if not entry_credit or entry_credit < 0.25:
    print("Entry credit too low, would skip")
    exit(0)

# Get next 10 timestamps for tracking
cursor.execute("""
SELECT DISTINCT timestamp FROM options_prices_live
WHERE timestamp > ? AND index_symbol = ?
ORDER BY timestamp ASC
LIMIT 10
""", (closest_ts, index_symbol))

future_timestamps = [row[0] for row in cursor.fetchall()]

print(f"\nTracking through {len(future_timestamps)} future bars:")
print(f"{'Bar':<4} {'Timestamp':<20} {'Short Bid':<12} {'Long Ask':<12} {'Spread Val':<12} {'vs Entry':<12} {'Status'}")
print("-" * 100)

sl_threshold = entry_credit * 1.10  # 10% stop loss
tp_threshold = entry_credit * 0.50  # 50% profit target

for i, ts in enumerate(future_timestamps, 1):
    # Get short ask (cost to buy to close)
    cursor.execute("""
    SELECT ask FROM options_prices_live
    WHERE timestamp = ? AND index_symbol = ? AND strike = ? AND option_type = ?
    """, (ts, index_symbol, short_strike, spread_type))
    
    short_ask_row = cursor.fetchone()
    short_ask = short_ask_row[0] if short_ask_row else None
    
    # Get long bid (receipt to sell to close)
    cursor.execute("""
    SELECT bid FROM options_prices_live
    WHERE timestamp = ? AND index_symbol = ? AND strike = ? AND option_type = ?
    """, (ts, index_symbol, long_strike, spread_type))
    
    long_bid_row = cursor.fetchone()
    long_bid = long_bid_row[0] if long_bid_row else None
    
    if not short_ask or not long_bid:
        print(f"{i:<4} {ts:<20} (Missing prices)")
        continue
    
    spread_value = short_ask - long_bid
    pnl = (entry_credit - spread_value) * 100
    
    status = ""
    if spread_value > sl_threshold:
        status = "❌ STOP LOSS HIT!"
    elif spread_value < tp_threshold:
        status = "✓ PROFIT TARGET HIT!"
    
    vs_entry = f"+{spread_value - entry_credit:.2f}" if spread_value > entry_credit else f"{spread_value - entry_credit:.2f}"
    
    print(f"{i:<4} {ts:<20} ${short_ask:<11.2f} ${long_bid:<11.2f} ${spread_value:<11.2f} {vs_entry:<12} {status}")
    
    if status:
        print(f"\n*** Trade would exit here with P/L: ${pnl:.0f} ***")
        break

conn.close()
