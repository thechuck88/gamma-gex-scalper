#!/usr/bin/env python3
import sqlite3
from datetime import datetime

DB_PATH = "/root/gamma/data/gex_blackbox.db"
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Get a few timestamps
cursor.execute("SELECT DISTINCT timestamp FROM options_snapshots LIMIT 5")
rows = cursor.fetchall()

print("Database timestamps (raw):")
for row in rows:
    print(f"  {row[0]}")

print("\nInterpretation:")
print("If 2026-01-12 14:35:10 UTC → converts to ET with -5 hours → 2026-01-12 09:35:10")
print("If 2026-01-12 14:35:10 ET → already in ET, no conversion needed")

# Check trading activity pattern
print("\nHourly trade count by UTC hour:")
cursor.execute("""
SELECT 
    CAST(strftime('%H', timestamp) AS INTEGER) as hour_utc,
    COUNT(*) as count
FROM gex_peaks
GROUP BY hour_utc
ORDER BY hour_utc
""")

for row in cursor.fetchall():
    hour_utc = row[0]
    hour_et = (hour_utc - 5) % 24
    count = row[1]
    print(f"  {hour_utc:02d}:00 UTC = {hour_et:02d}:00 ET: {count:3d} peaks")

conn.close()
