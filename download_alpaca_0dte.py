#!/usr/bin/env python3
"""
download_alpaca_0dte.py - Download Historical 0DTE Options Data from Alpaca

Downloads SPX and NDX 0DTE options data (Mon/Wed/Fri expirations) from Alpaca Markets.
Uses free paper trading account - no cost.

Features:
- Downloads 1-minute OHLCV bars for 0DTE options
- Covers 1-2 years of historical data
- Checkpointing (resume if interrupted)
- Progress tracking
- Rate limiting (200 req/min free tier)
- Stores in market_data.db

Usage:
  source /etc/gamma.env
  python3 download_alpaca_0dte.py --start 2024-01-01 --end 2025-12-31

  # Test with single date
  python3 download_alpaca_0dte.py --start 2025-01-17 --end 2025-01-17 --test

  # Resume from checkpoint
  python3 download_alpaca_0dte.py --resume

Author: Claude Code (2026-01-10)
"""

import os
import sys
import sqlite3
import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from alpaca.data.historical import OptionHistoricalDataClient
from alpaca.data.requests import OptionBarsRequest
from alpaca.data.timeframe import TimeFrame

# Configuration
DB_PATH = '/root/gamma/market_data.db'  # Centralized market data database (backed up by restic)
CHECKPOINT_FILE = '/root/gamma/alpaca_0dte_checkpoint.json'

# Alpaca credentials
ALPACA_PAPER_KEY = os.environ.get('ALPACA_PAPER_KEY')
ALPACA_PAPER_SECRET = os.environ.get('ALPACA_PAPER_SECRET')

# Strike selection
ATM_RANGE = 10  # Download ATM ± 10 strikes
STRIKE_INTERVAL_SPX = 5  # SPX strikes every $5
STRIKE_INTERVAL_NDX = 50  # NDX strikes every $50

# Rate limiting
REQUESTS_PER_MINUTE = 180  # Conservative (API limit is 200)
SLEEP_BETWEEN_REQUESTS = 60.0 / REQUESTS_PER_MINUTE  # ~0.33 seconds

class AlpacaDownloader:
    """Download 0DTE options data from Alpaca."""

    def __init__(self, api_key, api_secret):
        """Initialize Alpaca client."""
        self.client = OptionHistoricalDataClient(api_key, api_secret)
        self.checkpoint = self.load_checkpoint()
        # BUGFIX (2026-01-16): Use UTC-aware datetime for performance tracking
        # Ensures ETA calculations are timezone-consistent
        self.stats = {
            'dates_processed': 0,
            'symbols_downloaded': 0,
            'bars_stored': 0,
            'errors': 0,
            'start_time': datetime.now(timezone.utc)
        }

    def load_checkpoint(self):
        """Load checkpoint from file."""
        if os.path.exists(CHECKPOINT_FILE):
            with open(CHECKPOINT_FILE, 'r') as f:
                return json.load(f)
        return {'completed_dates': [], 'last_date': None}

    def save_checkpoint(self, date_str):
        """Save checkpoint after completing a date."""
        if date_str not in self.checkpoint['completed_dates']:
            self.checkpoint['completed_dates'].append(date_str)
        self.checkpoint['last_date'] = date_str

        with open(CHECKPOINT_FILE, 'w') as f:
            json.dump(self.checkpoint, f, indent=2)

    def get_0dte_dates(self, start_date, end_date):
        """Get list of Mon/Wed/Fri dates (0DTE expirations)."""
        dates = []
        current = start_date

        while current <= end_date:
            # Mon=0, Wed=2, Fri=4
            if current.weekday() in [0, 2, 4]:
                dates.append(current)
            current += timedelta(days=1)

        return dates

    def get_strike_range(self, underlying, atm_price):
        """Generate strike prices around ATM."""
        if underlying == 'SPX':
            interval = STRIKE_INTERVAL_SPX
        elif underlying == 'NDX':
            interval = STRIKE_INTERVAL_NDX
        else:
            interval = 1

        # Round ATM to nearest interval
        atm_strike = round(atm_price / interval) * interval

        # Generate ATM ± range
        strikes = []
        for i in range(-ATM_RANGE, ATM_RANGE + 1):
            strike = atm_strike + (i * interval)
            if strike > 0:
                strikes.append(strike)

        return strikes

    def get_atm_price(self, underlying, date):
        """Estimate ATM price for underlying on given date.

        Uses historical averages. In production, would query actual prices.
        """
        # These are rough estimates - actual ATM will vary
        # Script will still work even if not perfectly ATM
        estimates = {
            'SPX': 4500 + ((date - datetime(2024, 1, 1)).days * 2),  # Trending up ~$2/day
            'NDX': 16000 + ((date - datetime(2024, 1, 1)).days * 7)  # Trending up ~$7/day
        }

        # Clamp to reasonable ranges
        if underlying == 'SPX':
            return max(4000, min(6500, estimates['SPX']))
        elif underlying == 'NDX':
            return max(14000, min(22000, estimates['NDX']))

        return estimates.get(underlying, 5000)

    def generate_option_symbols(self, underlying, expiration_date, strikes):
        """Generate OCC option symbols."""
        symbols = []

        # Format: SPX250117C05900000
        year = expiration_date.strftime('%y')
        month = expiration_date.strftime('%m')
        day = expiration_date.strftime('%d')

        for strike in strikes:
            # Format strike with 8 digits (5 digits + 3 decimal places)
            if underlying in ['SPX', 'NDX']:
                strike_str = f"{int(strike * 1000):08d}"
            else:
                strike_str = f"{int(strike * 1000):08d}"

            # Calls
            call_symbol = f"{underlying}{year}{month}{day}C{strike_str}"
            symbols.append(call_symbol)

            # Puts
            put_symbol = f"{underlying}{year}{month}{day}P{strike_str}"
            symbols.append(put_symbol)

        return symbols

    def download_option_bars(self, symbol, date):
        """Download 1-minute bars for a specific option on specific date."""
        try:
            # Query for expiration day only (0DTE)
            start_time = datetime.combine(date, datetime.min.time()).replace(hour=9, minute=30)
            end_time = datetime.combine(date, datetime.min.time()).replace(hour=16, minute=0)

            request = OptionBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Minute,
                start=start_time,
                end=end_time
            )

            bars = self.client.get_option_bars(request)

            if bars and hasattr(bars, 'df') and len(bars.df) > 0:
                return bars.df
            else:
                return None

        except Exception as e:
            if "rate limit" in str(e).lower():
                print(f"  ⚠️  Rate limit hit, sleeping 60 seconds...")
                time.sleep(60)
                return self.download_option_bars(symbol, date)  # Retry
            else:
                # Silent error for missing options (many won't have data)
                return None

    def store_bars_in_db(self, df, symbol, expiration_date):
        """Store option bars in database."""
        if df is None or len(df) == 0:
            return 0

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Parse symbol for metadata
        underlying = symbol[:3]
        option_type = 'call' if 'C' in symbol[9:] else 'put'
        strike = int(symbol[-8:]) / 1000.0

        inserted = 0

        for idx, row in df.iterrows():
            # idx is (symbol, timestamp)
            if isinstance(idx, tuple):
                timestamp = idx[1]
            else:
                timestamp = idx

            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO option_bars_0dte
                    (symbol, datetime, open, high, low, close, volume,
                     underlying, strike, option_type, expiration)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    symbol,
                    timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    float(row['open']),
                    float(row['high']),
                    float(row['low']),
                    float(row['close']),
                    int(row['volume']) if 'volume' in row else 0,
                    underlying,
                    strike,
                    option_type,
                    expiration_date.strftime('%Y-%m-%d')
                ))
                inserted += 1
            except Exception as e:
                print(f"    Error inserting row: {e}")
                continue

        conn.commit()
        conn.close()

        return inserted

    def download_date(self, date, underlyings=['SPX', 'NDX'], test_mode=False):
        """Download all 0DTE options for a specific date."""
        date_str = date.strftime('%Y-%m-%d')

        # Check if already completed
        if date_str in self.checkpoint['completed_dates']:
            print(f"⏭️  Skipping {date_str} (already completed)")
            return

        print(f"\n{'='*70}")
        print(f"📅 {date_str} ({date.strftime('%A')})")
        print(f"{'='*70}")

        date_bars = 0
        date_symbols = 0

        for underlying in underlyings:
            print(f"\n{underlying}:")

            # Estimate ATM price
            atm_price = self.get_atm_price(underlying, date)
            print(f"  ATM estimate: ${atm_price:,.0f}")

            # Generate strikes
            strikes = self.get_strike_range(underlying, atm_price)
            print(f"  Strikes: {strikes[0]} to {strikes[-1]} ({len(strikes)} strikes)")

            # Generate option symbols
            symbols = self.generate_option_symbols(underlying, date, strikes)

            if test_mode:
                symbols = symbols[:10]  # Test with first 10 options only

            print(f"  Options: {len(symbols)} symbols")
            print(f"  Downloading...")

            # Download each option
            success_count = 0
            for i, symbol in enumerate(symbols):
                # Progress indicator every 20 symbols
                if (i + 1) % 20 == 0:
                    print(f"    Progress: {i+1}/{len(symbols)} ({success_count} with data)")

                # Download bars
                df = self.download_option_bars(symbol, date)

                if df is not None and len(df) > 0:
                    # Store in database
                    bars_inserted = self.store_bars_in_db(df, symbol, date)
                    date_bars += bars_inserted
                    success_count += 1
                    date_symbols += 1

                # Rate limiting
                time.sleep(SLEEP_BETWEEN_REQUESTS)

            print(f"  ✓ {underlying}: {success_count}/{len(symbols)} options had data")

        # Update stats
        self.stats['dates_processed'] += 1
        self.stats['symbols_downloaded'] += date_symbols
        self.stats['bars_stored'] += date_bars

        print(f"\n✓ {date_str} complete: {date_symbols} options, {date_bars} bars")

        # Save checkpoint
        self.save_checkpoint(date_str)

    def download_range(self, start_date, end_date, test_mode=False):
        """Download 0DTE data for a date range."""
        dates = self.get_0dte_dates(start_date, end_date)

        print(f"\n{'='*70}")
        print(f"ALPACA 0DTE HISTORICAL DOWNLOAD")
        print(f"{'='*70}")
        print(f"Date Range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        print(f"0DTE Dates: {len(dates)} (Mon/Wed/Fri)")
        print(f"Underlyings: SPX, NDX")
        print(f"Strikes: ATM ± {ATM_RANGE} ({ATM_RANGE * 2 + 1} strikes per underlying)")
        print(f"Options per date: ~{(ATM_RANGE * 2 + 1) * 2 * 2} (calls + puts, 2 underlyings)")
        print(f"Estimated bars: {len(dates) * 400 * 150:,} (rough estimate)")

        if test_mode:
            print(f"\n⚠️  TEST MODE: First 10 options per underlying only")

        print(f"\nCheckpoint: {len(self.checkpoint['completed_dates'])} dates already completed")

        # Filter out completed dates
        remaining_dates = [d for d in dates if d.strftime('%Y-%m-%d') not in self.checkpoint['completed_dates']]
        print(f"Remaining: {len(remaining_dates)} dates to download")

        if not remaining_dates:
            print("\n✓ All dates already completed!")
            return

        # Estimate time
        options_per_date = (ATM_RANGE * 2 + 1) * 2 * 2  # strikes × sides × underlyings
        if test_mode:
            options_per_date = 20  # 10 per underlying × 2
        seconds_per_date = options_per_date * SLEEP_BETWEEN_REQUESTS
        estimated_hours = (len(remaining_dates) * seconds_per_date) / 3600

        print(f"\nEstimated time: {estimated_hours:.1f} hours ({seconds_per_date/60:.1f} min per date)")
        print(f"\nPress Ctrl+C to stop (progress will be saved)")

        input("\nPress Enter to start download...")

        # Download each date
        try:
            for i, date in enumerate(remaining_dates):
                print(f"\n[{i+1}/{len(remaining_dates)}]")
                self.download_date(date, test_mode=test_mode)

                # Show progress
                # BUGFIX (2026-01-16): Use UTC-aware datetime for ETA calculation
                elapsed = (datetime.now(timezone.utc) - self.stats['start_time']).total_seconds()
                if i > 0:
                    avg_seconds_per_date = elapsed / (i + 1)
                    remaining_seconds = avg_seconds_per_date * (len(remaining_dates) - i - 1)
                    eta = datetime.now(timezone.utc) + timedelta(seconds=remaining_seconds)
                    print(f"\n⏱️  ETA: {eta.strftime('%Y-%m-%d %H:%M')} ({remaining_seconds/3600:.1f} hours)")

        except KeyboardInterrupt:
            print(f"\n\n⚠️  Download interrupted by user")
            self.print_stats()
            print(f"\nCheckpoint saved. Run with --resume to continue.")
            sys.exit(0)

        # Final stats
        print(f"\n\n{'='*70}")
        print(f"DOWNLOAD COMPLETE")
        print(f"{'='*70}")
        self.print_stats()

    def print_stats(self):
        """Print download statistics."""
        elapsed = (datetime.now() - self.stats['start_time']).total_seconds()

        print(f"\nStatistics:")
        print(f"  Dates processed: {self.stats['dates_processed']}")
        print(f"  Options downloaded: {self.stats['symbols_downloaded']}")
        print(f"  Bars stored: {self.stats['bars_stored']:,}")
        print(f"  Errors: {self.stats['errors']}")
        print(f"  Elapsed time: {elapsed/3600:.1f} hours")

        if self.stats['bars_stored'] > 0:
            bars_per_hour = (self.stats['bars_stored'] / elapsed) * 3600
            print(f"  Rate: {bars_per_hour:,.0f} bars/hour")

        print(f"\nDatabase: {DB_PATH}")
        print(f"Checkpoint: {CHECKPOINT_FILE}")

def main():
    parser = argparse.ArgumentParser(description='Download 0DTE options data from Alpaca')
    parser.add_argument('--start', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--resume', action='store_true', help='Resume from checkpoint')
    parser.add_argument('--test', action='store_true', help='Test mode (first 10 options only)')
    parser.add_argument('--status', action='store_true', help='Show database status')

    args = parser.parse_args()

    # Check credentials
    if not ALPACA_PAPER_KEY or not ALPACA_PAPER_SECRET:
        print("ERROR: Alpaca credentials not found")
        print("Set environment variables: ALPACA_PAPER_KEY, ALPACA_PAPER_SECRET")
        print("Or source /etc/gamma.env")
        sys.exit(1)

    # Show status
    if args.status:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM option_bars_0dte")
        total_bars = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT symbol) FROM option_bars_0dte")
        unique_symbols = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT DATE(datetime)) FROM option_bars_0dte")
        unique_dates = cursor.fetchone()[0]

        cursor.execute("SELECT MIN(datetime), MAX(datetime) FROM option_bars_0dte")
        date_range = cursor.fetchone()

        conn.close()

        print(f"\nDatabase Status: {DB_PATH}")
        print(f"  Total bars: {total_bars:,}")
        print(f"  Unique options: {unique_symbols:,}")
        print(f"  Trading days: {unique_dates}")
        print(f"  Date range: {date_range[0]} to {date_range[1]}")

        return

    # Initialize downloader
    downloader = AlpacaDownloader(ALPACA_PAPER_KEY, ALPACA_PAPER_SECRET)

    # Determine date range
    if args.resume:
        # Resume from checkpoint
        if downloader.checkpoint['last_date']:
            start_date = datetime.strptime(downloader.checkpoint['last_date'], '%Y-%m-%d')
            print(f"Resuming from {start_date.strftime('%Y-%m-%d')}")
        else:
            print("No checkpoint found, specify --start and --end")
            sys.exit(1)

        # Default end to today
        end_date = datetime.now()

    elif args.start and args.end:
        start_date = datetime.strptime(args.start, '%Y-%m-%d')
        end_date = datetime.strptime(args.end, '%Y-%m-%d')

    else:
        print("Specify --start and --end, or use --resume")
        print("\nExamples:")
        print("  python3 download_alpaca_0dte.py --start 2024-01-01 --end 2025-12-31")
        print("  python3 download_alpaca_0dte.py --start 2025-01-17 --end 2025-01-17 --test")
        print("  python3 download_alpaca_0dte.py --resume")
        print("  python3 download_alpaca_0dte.py --status")
        sys.exit(1)

    # Download
    downloader.download_range(start_date, end_date, test_mode=args.test)

if __name__ == '__main__':
    main()
