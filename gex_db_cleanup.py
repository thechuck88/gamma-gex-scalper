#!/usr/bin/env python3
"""GEX Blackbox DB retention cleanup — deletes rows older than 60 days and vacuums."""

import os
import sqlite3
from datetime import datetime, timedelta, timezone

DB_PATH = "/root/gamma/data/gex_blackbox.db"
RETENTION_DAYS = 60

TABLES = [
    "options_prices_live",
    "options_snapshots",
    "gex_peaks",
    "market_context",
    "competing_peaks",
]


def get_db_size_mb():
    """Return DB file size in MB (includes WAL if present)."""
    total = 0
    for suffix in ("", "-wal", "-shm"):
        path = DB_PATH + suffix
        if os.path.exists(path):
            total += os.path.getsize(path)
    return total / (1024 * 1024)


def main():
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    size_before = get_db_size_mb()

    print(f"[{now:%Y-%m-%d %H:%M:%S}] GEX DB cleanup — retention {RETENTION_DAYS}d, cutoff {cutoff}")
    print(f"  DB size before: {size_before:,.1f} MB")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    total_deleted = 0
    for table in TABLES:
        cursor = conn.execute(f"DELETE FROM {table} WHERE timestamp < ?", (cutoff,))
        deleted = cursor.rowcount
        total_deleted += deleted
        print(f"  {table}: {deleted:,} rows deleted")

    conn.commit()

    print(f"  Total: {total_deleted:,} rows deleted")

    if total_deleted > 0:
        print("  Running VACUUM (this may take a minute)...")
        conn.execute("VACUUM")
        print("  VACUUM complete")

    conn.close()

    size_after = get_db_size_mb()
    saved = size_before - size_after
    print(f"  DB size after: {size_after:,.1f} MB (saved {saved:,.1f} MB)")
    print(f"  Done.")


if __name__ == "__main__":
    main()
