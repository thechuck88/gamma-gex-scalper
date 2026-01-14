#!/bin/bash
#
# setup_0dte_collection.sh - Setup Daily 0DTE Data Collection
#
# This script sets up automated 0DTE options data collection via Tradier API.
#
# Usage:
#   bash setup_0dte_collection.sh
#
# Author: Claude Code (2026-01-10)
#

set -e

echo "======================================================================="
echo "SETTING UP 0DTE DATA COLLECTION"
echo "======================================================================="
echo ""

# Check for Tradier API key
if ! grep -q "TRADIER_SANDBOX_KEY" /etc/gamma.env 2>/dev/null; then
    echo "❌ Error: TRADIER_SANDBOX_KEY not found in /etc/gamma.env"
    echo ""
    echo "Please add to /etc/gamma.env:"
    echo "  TRADIER_SANDBOX_KEY=\"your_key_here\""
    exit 1
fi

echo "✓ Tradier API key found"
echo ""

# Create log directory
echo "Creating log directory..."
sudo mkdir -p /var/log
sudo touch /var/log/0dte_collector.log
sudo chmod 666 /var/log/0dte_collector.log
echo "✓ Log file: /var/log/0dte_collector.log"
echo ""

# Make collector script executable
echo "Making collector script executable..."
chmod +x /root/gamma/collect_0dte_tradier.py
echo "✓ Script is executable"
echo ""

# Setup cron job
echo "Setting up cron job..."

CRON_ENTRY="# 0DTE Data Collection (Mon/Wed/Fri at 10:00 AM ET = 15:00 UTC)
0 15 * * 1,3,5 cd /root/gamma && source /etc/gamma.env && /usr/bin/python3 collect_0dte_tradier.py --symbol SPX >> /var/log/0dte_collector.log 2>&1
30 15 * * 1,3,5 cd /root/gamma && source /etc/gamma.env && /usr/bin/python3 collect_0dte_tradier.py --symbol SPX >> /var/log/0dte_collector.log 2>&1
0 16 * * 1,3,5 cd /root/gamma && source /etc/gamma.env && /usr/bin/python3 collect_0dte_tradier.py --symbol SPX >> /var/log/0dte_collector.log 2>&1
30 16 * * 1,3,5 cd /root/gamma && source /etc/gamma.env && /usr/bin/python3 collect_0dte_tradier.py --symbol SPX >> /var/log/0dte_collector.log 2>&1
0 17 * * 1,3,5 cd /root/gamma && source /etc/gamma.env && /usr/bin/python3 collect_0dte_tradier.py --symbol SPX >> /var/log/0dte_collector.log 2>&1
30 17 * * 1,3,5 cd /root/gamma && source /etc/gamma.env && /usr/bin/python3 collect_0dte_tradier.py --symbol SPX >> /var/log/0dte_collector.log 2>&1
0 18 * * 1,3,5 cd /root/gamma && source /etc/gamma.env && /usr/bin/python3 collect_0dte_tradier.py --symbol SPX >> /var/log/0dte_collector.log 2>&1
30 18 * * 1,3,5 cd /root/gamma && source /etc/gamma.env && /usr/bin/python3 collect_0dte_tradier.py --symbol SPX >> /var/log/0dte_collector.log 2>&1
0 19 * * 1,3,5 cd /root/gamma && source /etc/gamma.env && /usr/bin/python3 collect_0dte_tradier.py --symbol SPX >> /var/log/0dte_collector.log 2>&1
30 19 * * 1,3,5 cd /root/gamma && source /etc/gamma.env && /usr/bin/python3 collect_0dte_tradier.py --symbol SPX >> /var/log/0dte_collector.log 2>&1
0 20 * * 1,3,5 cd /root/gamma && source /etc/gamma.env && /usr/bin/python3 collect_0dte_tradier.py --symbol SPX >> /var/log/0dte_collector.log 2>&1
30 20 * * 1,3,5 cd /root/gamma && source /etc/gamma.env && /usr/bin/python3 collect_0dte_tradier.py --symbol SPX >> /var/log/0dte_collector.log 2>&1
0 21 * * 1,3,5 cd /root/gamma && source /etc/gamma.env && /usr/bin/python3 collect_0dte_tradier.py --symbol SPX >> /var/log/0dte_collector.log 2>&1"

# Remove old 0DTE cron entries if they exist
crontab -l 2>/dev/null | grep -v "0DTE Data Collection" | grep -v "collect_0dte_tradier" > /tmp/crontab_new || true

# Add new entries
echo "$CRON_ENTRY" >> /tmp/crontab_new

# Install new crontab
crontab /tmp/crontab_new
rm /tmp/crontab_new

echo "✓ Cron jobs installed"
echo ""

# Show schedule
echo "Collection Schedule (ET):"
echo "  Mon/Wed/Fri:"
echo "    10:00 AM - Market open"
echo "    10:30 AM"
echo "    11:00 AM"
echo "    11:30 AM"
echo "    12:00 PM"
echo "    12:30 PM"
echo "    1:00 PM"
echo "    1:30 PM"
echo "    2:00 PM"
echo "    2:30 PM"
echo "    3:00 PM"
echo "    3:30 PM"
echo "    4:00 PM - Market close"
echo ""
echo "  Total: 13 snapshots per day"
echo "  Days: Mon/Wed/Fri (0DTE expiration days for SPX)"
echo ""

echo "======================================================================="
echo "SETUP COMPLETE"
echo "======================================================================="
echo ""
echo "Data will be collected starting next Mon/Wed/Fri."
echo ""
echo "Manual Commands:"
echo "  # Collect now (single snapshot)"
echo "  source /etc/gamma.env && python3 /root/gamma/collect_0dte_tradier.py --symbol SPX"
echo ""
echo "  # View status"
echo "  python3 /root/gamma/collect_0dte_tradier.py --status"
echo ""
echo "  # View logs"
echo "  tail -f /var/log/0dte_collector.log"
echo ""
echo "  # Check cron schedule"
echo "  crontab -l | grep 0DTE"
echo ""
echo "Database: /root/gamma/market_data.db"
echo "Table: option_bars_0dte"
echo ""
