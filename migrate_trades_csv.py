#!/usr/bin/env python3
"""
Migrate trades.csv to include Account_ID column.
Adds Account_ID as 3rd column (after Trade_ID).
Defaults old trades to PAPER account.
"""

import csv
import shutil
from datetime import datetime

# Backup original file
TRADE_LOG = "/root/gamma/data/trades.csv"
BACKUP_FILE = f"/root/gamma/data/trades_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# Account IDs
PAPER_ACCOUNT_ID = "VA45627947"
LIVE_ACCOUNT_ID = "6YA47852"

# Create backup
shutil.copy(TRADE_LOG, BACKUP_FILE)
print(f"Backup created: {BACKUP_FILE}")

# Read existing data
rows = []
with open(TRADE_LOG, 'r') as f:
    reader = csv.reader(f)
    for row in reader:
        rows.append(row)

# Check if Account_ID already exists
header = rows[0]
if 'Account_ID' in header:
    print("Account_ID column already exists! No migration needed.")
    exit(0)

# Update header: insert Account_ID after Trade_ID (position 2)
# OLD: Timestamp_ET, Trade_ID, Strategy, Strikes, ...
# NEW: Timestamp_ET, Trade_ID, Account_ID, Strategy, Strikes, ...
new_header = header[:2] + ['Account_ID'] + header[2:]

# Update data rows: insert PAPER account ID for all old trades
new_rows = [new_header]
for row in rows[1:]:
    if len(row) >= 2:
        # Insert PAPER_ACCOUNT_ID at position 2
        new_row = row[:2] + [PAPER_ACCOUNT_ID] + row[2:]
        new_rows.append(new_row)
    else:
        # Skip malformed rows
        print(f"Skipping malformed row: {row}")

# Write updated CSV
with open(TRADE_LOG, 'w', newline='') as f:
    csv.writer(f).writerows(new_rows)

print(f"Migration complete!")
print(f"Updated {len(new_rows)-1} trade records")
print(f"All old trades assigned to PAPER account: {PAPER_ACCOUNT_ID}")
