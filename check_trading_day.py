#!/usr/bin/env python3
"""
check_trading_day.py — Creates /etc/trading-day if today is a valid trading day.

Run at 8:00 AM ET via cron. Creates the flag file if:
1. Market is NOT closed (regular trading day)
2. NOT an FOMC announcement day
3. NOT a short/early-close day

Usage: python check_trading_day.py
"""

import os
import sys
import re
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path
import pytz

# Load from environment (set in /etc/gamma.env or ~/.bashrc)
TRADIER_KEY = os.environ.get('TRADIER_LIVE_KEY')
if not TRADIER_KEY:
    print("ERROR: TRADIER_LIVE_KEY not set in environment")
    sys.exit(1)

ET = pytz.timezone('US/Eastern')
FLAG_FILE = '/etc/trading-day'
FOMC_CACHE_FILE = '/root/gamma/data/fomc_dates_cache.json'

# Tradier API
BASE_URL = "https://api.tradier.com/v1"
HEADERS = {"Accept": "application/json", "Authorization": f"Bearer {TRADIER_KEY}"}

# Fallback FOMC dates (used if Fed website is unavailable)
# Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
FOMC_DATES_FALLBACK = [
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    # 2026
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]


def log(msg):
    now = datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")


def fetch_fomc_dates_from_fed():
    """Fetch FOMC meeting dates from the Federal Reserve website."""
    try:
        url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
        r = requests.get(url, timeout=15)
        r.raise_for_status()

        # The Fed website embeds dates in URLs like:
        # fomcpresconf20250129.htm - Press conferences (only at actual FOMC meetings)
        # This filters out Jackson Hole and other non-FOMC announcements
        # Format: YYYYMMDD
        date_pattern = re.compile(r'fomcpresconf(\d{8})')

        dates = set()
        for match in date_pattern.finditer(r.text):
            date_str = match.group(1)
            year = int(date_str[:4])
            month = int(date_str[4:6])
            day = int(date_str[6:8])

            # Only include current and future years
            current_year = datetime.now(ET).year
            if current_year <= year <= current_year + 2:
                formatted = f"{year}-{month:02d}-{day:02d}"
                dates.add(formatted)

        return sorted(dates) if dates else None

    except Exception as e:
        log(f"Error fetching FOMC dates from Fed: {e}")
        return None


def get_fomc_dates():
    """Get FOMC dates with caching (refreshes daily)."""
    cache_file = Path(FOMC_CACHE_FILE)

    # Check cache
    if cache_file.exists():
        try:
            with open(cache_file, 'r') as f:
                cache = json.load(f)
            cache_date = cache.get('date')
            today = datetime.now(ET).strftime('%Y-%m-%d')

            # Use cache if it's from today
            if cache_date == today and cache.get('dates'):
                log(f"Using cached FOMC dates (from {cache_date})")
                return cache['dates']
        except Exception as e:
            log(f"Error reading FOMC cache: {e}")

    # Fetch fresh data
    log("Fetching FOMC dates from Federal Reserve website...")
    dates = fetch_fomc_dates_from_fed()

    if dates:
        log(f"Fetched {len(dates)} FOMC dates from Fed website")
        # Save to cache
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, 'w') as f:
                json.dump({
                    'date': datetime.now(ET).strftime('%Y-%m-%d'),
                    'dates': dates,
                    'source': 'federalreserve.gov'
                }, f, indent=2)
        except Exception as e:
            log(f"Error saving FOMC cache: {e}")
        return dates
    else:
        log("Failed to fetch FOMC dates, using fallback list")
        return FOMC_DATES_FALLBACK


def get_early_close_dates(year):
    """Calculate early close dates for a given year (1 PM close days)."""
    early_close = []

    # Day before July 4th (July 3rd, unless it's a weekend)
    july_3 = datetime(year, 7, 3)
    if july_3.weekday() < 5:  # Mon-Fri
        early_close.append(july_3.strftime('%Y-%m-%d'))

    # Black Friday (day after Thanksgiving = 4th Thursday of November + 1)
    # Find 4th Thursday of November
    nov_1 = datetime(year, 11, 1)
    # Days until first Thursday
    days_to_thu = (3 - nov_1.weekday()) % 7
    first_thu = nov_1 + timedelta(days=days_to_thu)
    fourth_thu = first_thu + timedelta(weeks=3)
    black_friday = fourth_thu + timedelta(days=1)
    early_close.append(black_friday.strftime('%Y-%m-%d'))

    # Christmas Eve (Dec 24, unless it's a weekend)
    dec_24 = datetime(year, 12, 24)
    if dec_24.weekday() < 5:  # Mon-Fri
        early_close.append(dec_24.strftime('%Y-%m-%d'))

    return early_close


def check_market_open():
    """Check if today is a regular trading day (not weekend/holiday)."""
    try:
        r = requests.get(f"{BASE_URL}/markets/clock", headers=HEADERS, timeout=10)
        data = r.json()
        clock = data.get("clock", {})
        state = clock.get("state", "")
        description = clock.get("description", "")

        log(f"Market state: {state} — {description}")

        # If state is "closed", it's a holiday/weekend
        if state == "closed":
            log("Market is CLOSED today (holiday/weekend)")
            return False

        # Valid states: premarket, open, postmarket
        return True

    except Exception as e:
        log(f"Error checking market clock: {e}")
        return False


def check_fomc():
    """Check if today is an FOMC announcement day."""
    today = datetime.now(ET).strftime('%Y-%m-%d')
    fomc_dates = get_fomc_dates()

    if today in fomc_dates:
        log(f"TODAY IS FOMC DAY ({today}) — skipping trading")
        return True

    # Also log the next upcoming FOMC date for reference
    future_dates = [d for d in fomc_dates if d > today]
    if future_dates:
        log(f"Next FOMC date: {future_dates[0]}")

    return False


def check_early_close():
    """Check if today is an early close day."""
    today = datetime.now(ET).strftime('%Y-%m-%d')
    year = datetime.now(ET).year
    early_close_dates = get_early_close_dates(year)

    if today in early_close_dates:
        log(f"TODAY IS EARLY CLOSE DAY ({today}) — skipping trading")
        return True

    return False


def main():
    log("=" * 50)
    log("Checking if today is a valid trading day...")

    # Check conditions
    is_market_day = check_market_open()
    is_fomc = check_fomc()
    is_early_close = check_early_close()

    # Determine if we should trade
    should_trade = is_market_day and not is_fomc and not is_early_close

    if should_trade:
        log(f"VALID TRADING DAY — creating {FLAG_FILE}")
        try:
            with open(FLAG_FILE, 'w') as f:
                f.write(datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S'))
            log("Flag file created successfully")
        except Exception as e:
            log(f"Error creating flag file: {e}")
            sys.exit(1)
    else:
        log(f"NOT A TRADING DAY — removing {FLAG_FILE} if exists")
        try:
            if os.path.exists(FLAG_FILE):
                os.remove(FLAG_FILE)
                log("Flag file removed")
            else:
                log("Flag file didn't exist")
        except Exception as e:
            log(f"Error removing flag file: {e}")

    log("=" * 50)


if __name__ == "__main__":
    main()
