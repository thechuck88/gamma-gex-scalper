#!/usr/bin/env python3
"""
replay_data_provider.py - Unified data access for live and replay modes

Provides abstract interface that switches between:
- LiveDataProvider: Real Tradier API calls (production)
- ReplayDataProvider: Database snapshots (backtesting)

Usage:
    # Production mode
    provider = LiveDataProvider(tradier_key='...', account_id='...')

    # Replay mode
    provider = ReplayDataProvider(db_path='/root/gamma/data/gex_blackbox.db')

    # Same interface either way
    price = provider.get_index_price('SPX', datetime.now())
    vix = provider.get_vix(datetime.now())
    peaks = provider.get_gex_peaks('SPX', datetime.now())
"""

import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from abc import ABC, abstractmethod


class DataProvider(ABC):
    """Abstract base class for data access."""

    @abstractmethod
    def get_gex_peak(self, index_symbol: str, timestamp: datetime, peak_rank: int = 1) -> Optional[Dict]:
        """
        Get GEX peak for index at timestamp.

        Returns:
            {
                'strike': float,
                'gex': float,
                'peak_rank': int,
                'timestamp': datetime
            }
        """
        pass

    @abstractmethod
    def get_index_price(self, index_symbol: str, timestamp: datetime) -> Optional[float]:
        """Get underlying price at timestamp."""
        pass

    @abstractmethod
    def get_vix(self, timestamp: datetime) -> Optional[float]:
        """Get VIX level at timestamp."""
        pass

    @abstractmethod
    def get_options_bid_ask(self, index_symbol: str, strike: float, option_type: str,
                           timestamp: datetime) -> Optional[Tuple[float, float]]:
        """
        Get bid/ask for specific strike at timestamp.

        Args:
            index_symbol: 'SPX' or 'NDX'
            strike: Strike price
            option_type: 'call' or 'put'
            timestamp: Query timestamp

        Returns:
            (bid, ask) tuple or None if not found
        """
        pass

    @abstractmethod
    def get_future_timestamps(self, index_symbol: str, start_timestamp: datetime,
                             max_count: int = 100) -> List[datetime]:
        """Get list of future timestamps after start_timestamp."""
        pass


class ReplayDataProvider(DataProvider):
    """
    Backtest mode: Uses historical database snapshots.

    All data comes from pre-recorded gex_blackbox.db snapshots.
    """

    def __init__(self, db_path: str):
        """
        Initialize replay data provider.

        Args:
            db_path: Path to gex_blackbox.db database
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA cache_size=-64000")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        print(f"[REPLAY] Connected to database: {db_path}")

    def _normalize_timestamp(self, timestamp: datetime) -> str:
        """Convert datetime to database format string (YYYY-MM-DD HH:MM:SS)."""
        if isinstance(timestamp, str):
            # If already a string, ensure it's in database format
            # Strip timezone info and T character if present
            ts_str = timestamp.replace('T', ' ')
            if '+' in ts_str:
                ts_str = ts_str.split('+')[0]  # Remove +HH:MM
            if 'Z' in ts_str:
                ts_str = ts_str.replace('Z', '')  # Remove Z
            return ts_str
        if isinstance(timestamp, datetime):
            # Remove timezone info and use space separator instead of T
            # Format: YYYY-MM-DD HH:MM:SS
            if timestamp.tzinfo is not None:
                # Convert to UTC if timezone-aware
                timestamp = timestamp.replace(tzinfo=None)
            return timestamp.strftime('%Y-%m-%d %H:%M:%S')
        return str(timestamp)

    def get_gex_peak(self, index_symbol: str, timestamp: datetime, peak_rank: int = 1) -> Optional[Dict]:
        """
        Get GEX peak from database.

        Returns the specified peak_rank (default: 1 = strongest).
        """
        try:
            cursor = self.conn.cursor()
            ts = self._normalize_timestamp(timestamp)

            # Try exact timestamp first
            cursor.execute("""
                SELECT strike, gex, peak_rank, timestamp
                FROM gex_peaks
                WHERE index_symbol = ? AND timestamp = ? AND peak_rank = ?
                LIMIT 1
            """, (index_symbol, ts, peak_rank))

            row = cursor.fetchone()

            if row:
                return {
                    'strike': float(row[0]),
                    'gex': float(row[1]),
                    'peak_rank': int(row[2]),
                    'timestamp': row[3]
                }

            # Try previous timestamp (forward-fill) if exact match not found
            cursor.execute("""
                SELECT strike, gex, peak_rank, timestamp
                FROM gex_peaks
                WHERE index_symbol = ? AND timestamp <= ? AND peak_rank = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (index_symbol, ts, peak_rank))

            row = cursor.fetchone()

            if row:
                print(f"[REPLAY] Forward-filled GEX peak {peak_rank}: {index_symbol}")
                return {
                    'strike': float(row[0]),
                    'gex': float(row[1]),
                    'peak_rank': int(row[2]),
                    'timestamp': row[3]
                }

            return None

        except Exception as e:
            print(f"[REPLAY] Error getting GEX peak: {e}")
            return None

    def get_index_price(self, index_symbol: str, timestamp: datetime) -> Optional[float]:
        """Get index price from options_snapshots table."""
        try:
            cursor = self.conn.cursor()
            ts = self._normalize_timestamp(timestamp)

            # Try exact timestamp
            cursor.execute("""
                SELECT DISTINCT underlying_price
                FROM options_snapshots
                WHERE index_symbol = ? AND timestamp = ?
                LIMIT 1
            """, (index_symbol, ts))

            row = cursor.fetchone()

            if row and row[0] is not None:
                return float(row[0])

            # Forward-fill if not found
            cursor.execute("""
                SELECT underlying_price
                FROM options_snapshots
                WHERE index_symbol = ? AND timestamp <= ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (index_symbol, ts))

            row = cursor.fetchone()

            if row and row[0] is not None:
                return float(row[0])

            return None

        except Exception as e:
            print(f"[REPLAY] Error getting index price: {e}")
            return None

    def get_vix(self, timestamp: datetime) -> Optional[float]:
        """Get VIX level from options_snapshots table."""
        try:
            cursor = self.conn.cursor()
            ts = self._normalize_timestamp(timestamp)

            # Try exact timestamp
            cursor.execute("""
                SELECT vix
                FROM options_snapshots
                WHERE timestamp = ?
                LIMIT 1
            """, (ts,))

            row = cursor.fetchone()

            if row and row[0] is not None:
                return float(row[0])

            # Forward-fill if not found
            cursor.execute("""
                SELECT vix
                FROM options_snapshots
                WHERE timestamp <= ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (ts,))

            row = cursor.fetchone()

            if row and row[0] is not None:
                return float(row[0])

            return None

        except Exception as e:
            print(f"[REPLAY] Error getting VIX: {e}")
            return None

    def get_options_bid_ask(self, index_symbol: str, strike: float, option_type: str,
                           timestamp: datetime) -> Optional[Tuple[float, float]]:
        """
        Get bid/ask for specific strike at timestamp.
        """
        try:
            cursor = self.conn.cursor()
            ts = self._normalize_timestamp(timestamp)

            # Try exact timestamp
            cursor.execute("""
                SELECT bid, ask
                FROM options_prices_live
                WHERE index_symbol = ? AND strike = ? AND option_type = ? AND timestamp = ?
                LIMIT 1
            """, (index_symbol, strike, option_type, ts))

            row = cursor.fetchone()

            if row and row[0] is not None and row[1] is not None:
                return (float(row[0]), float(row[1]))

            # Forward-fill if not found
            cursor.execute("""
                SELECT bid, ask
                FROM options_prices_live
                WHERE index_symbol = ? AND strike = ? AND option_type = ? AND timestamp <= ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (index_symbol, strike, option_type, ts))

            row = cursor.fetchone()

            if row and row[0] is not None and row[1] is not None:
                return (float(row[0]), float(row[1]))

            return None

        except Exception as e:
            print(f"[REPLAY] Error getting options bid/ask: {e}")
            return None

    def get_future_timestamps(self, index_symbol: str, start_timestamp: datetime,
                             max_count: int = 100) -> List[datetime]:
        """Get list of future timestamps after start_timestamp from options_prices_live."""
        try:
            cursor = self.conn.cursor()
            ts = self._normalize_timestamp(start_timestamp)

            cursor.execute("""
                SELECT DISTINCT timestamp
                FROM options_prices_live
                WHERE index_symbol = ? AND timestamp > ?
                ORDER BY timestamp ASC
                LIMIT ?
            """, (index_symbol, ts, max_count))

            rows = cursor.fetchall()

            # Convert strings to datetime objects
            timestamps = []
            for row in rows:
                ts_str = row[0]
                # Parse ISO format timestamp
                if isinstance(ts_str, str):
                    dt = datetime.fromisoformat(ts_str)
                    timestamps.append(dt)
                else:
                    timestamps.append(ts_str)

            return timestamps

        except Exception as e:
            print(f"[REPLAY] Error getting future timestamps: {e}")
            return []

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()

    def __del__(self):
        """Ensure connection is closed."""
        self.close()


class LiveDataProvider(DataProvider):
    """
    Production mode: Uses real API calls.

    NOTE: This is a placeholder. In production, this would integrate with
    actual Tradier API and live GEX computation service.
    """

    def __init__(self, tradier_key: str = None, account_id: str = None):
        """Initialize live data provider."""
        self.tradier_key = tradier_key
        self.account_id = account_id
        print("[LIVE] Live data provider initialized (placeholder)")

    def get_gex_peak(self, index_symbol: str, timestamp: datetime, peak_rank: int = 1) -> Optional[Dict]:
        """Get GEX peak from live service."""
        # TODO: Implement call to live GEX service
        raise NotImplementedError("Live GEX computation needs local service integration")

    def get_index_price(self, index_symbol: str, timestamp: datetime) -> Optional[float]:
        """Get index price from Tradier API."""
        # TODO: Implement Tradier API call
        raise NotImplementedError("Live price data needs Tradier integration")

    def get_vix(self, timestamp: datetime) -> Optional[float]:
        """Get VIX from Tradier API."""
        # TODO: Implement Tradier API call
        raise NotImplementedError("Live VIX needs Tradier integration")

    def get_options_bid_ask(self, index_symbol: str, strike: float, option_type: str,
                           timestamp: datetime) -> Optional[Tuple[float, float]]:
        """Get bid/ask from Tradier API."""
        # TODO: Implement Tradier API call
        raise NotImplementedError("Live options data needs Tradier integration")

    def get_future_timestamps(self, index_symbol: str, start_timestamp: datetime,
                             max_count: int = 100) -> List[datetime]:
        """Not applicable in live mode."""
        return []
