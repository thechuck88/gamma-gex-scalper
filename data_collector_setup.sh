#!/bin/bash
#
# data_collector_setup.sh — Setup Background Data Collection
#
# This script:
# 1. Collects historical underlying data (365 days)
# 2. Sets up daily cron job for ongoing collection
# 3. Creates systemd service for automatic startup
#
# Usage: bash data_collector_setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================="
echo "GEX Scalper Data Collector Setup"
echo "========================================="
echo

# Check for required Python packages
echo "1. Checking dependencies..."
python3 -c "import alpaca_trade_api" 2>/dev/null || {
    echo "   Installing alpaca-trade-api..."
    pip3 install alpaca-trade-api
}

python3 -c "import requests" 2>/dev/null || {
    echo "   Installing requests..."
    pip3 install requests
}

echo "   ✓ Dependencies OK"
echo

# Source environment file if it exists
if [ -f /etc/gamma.env ]; then
    echo "2. Sourcing /etc/gamma.env..."
    set -a  # Export all variables
    source /etc/gamma.env
    set +a
    echo "   ✓ Environment loaded"
else
    echo "2. /etc/gamma.env not found, checking environment..."
fi
echo

# Check for Alpaca API keys (try multiple names)
echo "3. Checking Alpaca API keys..."
if [ -z "$APCA_API_KEY_ID" ] && [ -z "$ALPACA_PAPER_KEY" ]; then
    echo "   ❌ Alpaca API keys not found"
    echo "   Add to /etc/gamma.env:"
    echo "   ALPACA_PAPER_KEY=your_key"
    echo "   ALPACA_PAPER_SECRET=your_secret"
    exit 1
fi
echo "   ✓ Alpaca keys found"
echo

# Check for Tradier API key (optional)
echo "4. Checking Tradier API key..."
if [ -z "$TRADIER_SANDBOX_KEY" ] && [ -z "$TRADIER_LIVE_KEY" ]; then
    echo "   ⚠️  Tradier key not set (option chains will be skipped)"
    echo "   Optional: Add TRADIER_SANDBOX_KEY or TRADIER_LIVE_KEY to /etc/gamma.env"
else
    echo "   ✓ Tradier key found"
fi
echo

# Collect historical data
echo "5. Collecting historical data..."
read -p "   Collect 365 days of historical data? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "   This may take 5-10 minutes..."
    python3 data_collector.py --historical --days 365
    echo "   ✓ Historical data collected"
else
    echo "   Skipped historical collection"
fi
echo

# Setup cron job
echo "6. Setting up daily cron job..."
CRON_CMD="0 17 * * 1-5 cd $SCRIPT_DIR && source /etc/gamma.env && python3 data_collector.py --daily >> $SCRIPT_DIR/data_collector.log 2>&1"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "data_collector.py"; then
    echo "   ✓ Cron job already exists"
else
    # Add to crontab
    (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
    echo "   ✓ Cron job added (runs daily at 5 PM ET)"
fi
echo

# Show status
echo "7. Database status..."
python3 data_collector.py --status
echo

echo "========================================="
echo "Setup Complete!"
echo "========================================="
echo
echo "Data collection configured:"
echo "  • Historical: 365 days (if collected)"
echo "  • Daily: Runs at 5 PM ET (17:00) weekdays"
echo "  • Database: $SCRIPT_DIR/market_data.db"
echo
echo "Check collection log:"
echo "  tail -f $SCRIPT_DIR/data_collector.log"
echo
echo "Manual commands:"
echo "  python3 data_collector.py --status     # Check status"
echo "  python3 data_collector.py --daily      # Run daily collection"
echo "  python3 data_collector.py --historical # Re-collect historical"
echo
