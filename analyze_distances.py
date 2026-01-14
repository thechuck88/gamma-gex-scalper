#!/usr/bin/env python3
import sqlite3
import sys
sys.path.insert(0, '/root/gamma')
from core.gex_strategy import get_gex_trade_setup

DB_PATH = "/root/gamma/data/gex_blackbox.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Get first 20 GEX peaks with ranks 1-2
cursor.execute("""
SELECT 
    g.timestamp,
    s.underlying_price,
    s.vix,
    g.strike as pin_strike,
    g.peak_rank
FROM gex_peaks g
LEFT JOIN options_snapshots s ON g.timestamp = s.timestamp
    AND g.index_symbol = s.index_symbol
WHERE g.peak_rank <= 2
ORDER BY g.timestamp ASC
LIMIT 20
""")

rows = cursor.fetchall()

print(f"{'Time':<20} {'SPX':<8} {'PIN':<8} {'Distance':<10} {'VIX':<6} {'Rank':<5} {'Zone':<20} {'Strategy'}")
print("-" * 130)

zone_stats = {}

for row in rows:
    timestamp, underlying, vix, pin_strike, peak_rank = row
    
    if vix is None or vix < 12.0 or vix >= 20.0:
        continue
    
    setup = get_gex_trade_setup(pin_strike, underlying, vix, vix_threshold=20.0)
    
    distance = underlying - pin_strike
    abs_distance = abs(distance)
    
    if abs_distance <= 6:
        zone = "NEAR_PIN (0-6)"
    elif abs_distance <= 15:
        zone = "MODERATE (7-15)"
    elif abs_distance <= 50:
        zone = "FAR (16-50)"
    else:
        zone = "TOO_FAR (>50)"
    
    if zone not in zone_stats:
        zone_stats[zone] = 0
    zone_stats[zone] += 1
    
    print(f"{timestamp:<20} {underlying:<8.0f} {pin_strike:<8.0f} {distance:+8.0f}pts  {vix:<6.1f} {peak_rank:<5} {zone:<20} {setup.strategy}")

print("\nZone Distribution:")
for zone, count in sorted(zone_stats.items()):
    print(f"  {zone}: {count}")

conn.close()
