# Replay Harness - Implementation Guide

**Purpose**: Step-by-step instructions for implementing the replay harness architecture
**Target**: Developers implementing `/root/gamma/replay_*.py` modules
**Companion Document**: `REPLAY_HARNESS_ARCHITECTURE.md`

---

## Module 1: replay_data_provider.py

**Purpose**: Unified interface for data access that switches between live and replay modes
**File Size**: ~600 lines
**Dependencies**: sqlite3, requests, json, datetime

### 1.1 Abstract Base Class

```python
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
    provider = ReplayDataProvider(db_path='/gamma-scalper/data/gex_blackbox.db')

    # Same interface either way
    price = provider.get_index_price('SPX', datetime.now())
    vix = provider.get_vix(datetime.now())
    peak = provider.get_gex_peak('SPX', datetime.now())
"""

import sqlite3
import requests
import json
from datetime import datetime
from typing import Optional, Dict, List
from abc import ABC, abstractmethod
import pytz


class DataProvider(ABC):
    """Abstract base class for data access."""

    @abstractmethod
    def get_gex_peak(self, index_symbol: str, timestamp: datetime) -> Optional[Dict]:
        """
        Get GEX peak for index at timestamp.

        Returns:
            {
                'strike': float,
                'gex': float,
                'distance_from_price': float,
                'proximity_score': float
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
    def get_options_chain(self, index_symbol: str, expiration: str,
                         timestamp: datetime) -> Optional[List[Dict]]:
        """
        Get options chain snapshot at timestamp.

        Returns list of option contracts:
            [
                {
                    'strike': float,
                    'bid': float,
                    'ask': float,
                    'volume': int,
                    'open_interest': int
                },
                ...
            ]
        """
        pass

    @abstractmethod
    def get_strike_prices(self, index_symbol: str, strikes: List[float],
                         option_type: str, expiration: str,
                         timestamp: datetime) -> Dict[float, Dict]:
        """
        Get bid/ask for specific strikes at timestamp.

        Args:
            strikes: List of strike prices

        Returns:
            {
                6950.0: {'bid': 0.45, 'ask': 0.55},
                6960.0: {'bid': 0.35, 'ask': 0.45},
                ...
            }
        """
        pass


class LiveDataProvider(DataProvider):
    """
    Production mode: Uses real Tradier API calls.

    This is essentially a pass-through to existing code.
    """

    def __init__(self, tradier_key: str, account_id: str, base_url: str = 'https://api.tradier.com/v1'):
        """
        Initialize live data provider.

        Args:
            tradier_key: API key for Tradier
            account_id: Account ID for Tradier
            base_url: Base URL for Tradier API (sandbox or live)
        """
        self.tradier_key = tradier_key
        self.account_id = account_id
        self.base_url = base_url
        self.headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {tradier_key}'
        }

    def get_gex_peak(self, index_symbol: str, timestamp: datetime) -> Optional[Dict]:
        """
        Get GEX peak from live GEX service.

        Note: This would typically call the GEX computation service
        running on the system, not Tradier API.
        """
        # TODO: Implement call to live GEX service
        # This is typically computed locally, not from API
        raise NotImplementedError("Live GEX computation needs local service integration")

    def get_index_price(self, index_symbol: str, timestamp: datetime) -> Optional[float]:
        """Get index price from Tradier quote API."""
        try:
            url = f"{self.base_url}/markets/quotes"
            params = {'symbols': index_symbol}

            response = requests.get(url, headers=self.headers, params=params, timeout=10)

            if response.status_code != 200:
                print(f"[LIVE] Failed to get {index_symbol} price: {response.status_code}")
                return None

            data = response.json()
            quote = data.get('quotes', {}).get('quote')

            if not quote:
                return None

            if isinstance(quote, list):
                quote = quote[0]

            # Get price (last > bid > ask)
            price = quote.get('last') or quote.get('bid') or quote.get('ask')
            return price

        except Exception as e:
            print(f"[LIVE] Error getting {index_symbol} price: {e}")
            return None

    def get_vix(self, timestamp: datetime) -> Optional[float]:
        """Get VIX from Tradier quote API."""
        try:
            url = f"{self.base_url}/markets/quotes"
            params = {'symbols': '$VIX.X'}

            response = requests.get(url, headers=self.headers, params=params, timeout=10)

            if response.status_code != 200:
                return None

            data = response.json()
            quote = data.get('quotes', {}).get('quote')

            if not quote:
                return None

            if isinstance(quote, list):
                quote = quote[0]

            price = quote.get('last') or quote.get('bid') or quote.get('ask')
            return price

        except Exception as e:
            print(f"[LIVE] Error getting VIX: {e}")
            return None

    def get_options_chain(self, index_symbol: str, expiration: str,
                         timestamp: datetime) -> Optional[List[Dict]]:
        """Get options chain from Tradier API."""
        try:
            # Map index symbol to option root
            symbol_map = {'SPX': '.SPX', 'NDX': '.NDX'}
            symbol = symbol_map.get(index_symbol, index_symbol)

            url = f"{self.base_url}/markets/options/chains"
            params = {
                'symbol': symbol,
                'expiration': expiration,
                'includeAll': 'true'
            }

            response = requests.get(url, headers=self.headers, params=params, timeout=20)

            if response.status_code != 200:
                return None

            data = response.json()
            options = data.get('options', {}).get('option', [])

            if not options:
                return None

            if not isinstance(options, list):
                options = [options]

            return options

        except Exception as e:
            print(f"[LIVE] Error getting options chain: {e}")
            return None

    def get_strike_prices(self, index_symbol: str, strikes: List[float],
                         option_type: str, expiration: str,
                         timestamp: datetime) -> Dict[float, Dict]:
        """Get bid/ask for specific strikes."""
        chain = self.get_options_chain(index_symbol, expiration, timestamp)

        if not chain:
            return {}

        prices = {}
        for strike in strikes:
            # Find matching option in chain
            for option in chain:
                if (abs(option.get('strike') - strike) < 0.01 and
                    option.get('option_type') == option_type):
                    prices[strike] = {
                        'bid': option.get('bid'),
                        'ask': option.get('ask')
                    }
                    break

        return prices
```

### 1.2 Replay Data Provider

```python
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
        self.conn.row_factory = sqlite3.Row  # Enable column access by name
        print(f"[REPLAY] Connected to database: {db_path}")

    def _normalize_timestamp(self, timestamp: datetime) -> str:
        """Convert datetime to ISO format string for database queries."""
        if isinstance(timestamp, str):
            return timestamp
        return timestamp.isoformat()

    def get_gex_peak(self, index_symbol: str, timestamp: datetime) -> Optional[Dict]:
        """
        Get GEX peak from database.

        Returns the rank=1 peak (strongest GEX concentration).
        """
        try:
            cursor = self.conn.cursor()
            ts = self._normalize_timestamp(timestamp)

            # Try exact timestamp first
            cursor.execute("""
                SELECT strike, gex, distance_from_price, proximity_score
                FROM gex_peaks
                WHERE index_symbol = ? AND timestamp = ? AND peak_rank = 1
                LIMIT 1
            """, (index_symbol, ts))

            row = cursor.fetchone()

            if row:
                return {
                    'strike': float(row[0]),
                    'gex': float(row[1]),
                    'distance_from_price': float(row[2]),
                    'proximity_score': float(row[3])
                }

            # Try previous timestamp (forward-fill) if exact match not found
            cursor.execute("""
                SELECT strike, gex, distance_from_price, proximity_score
                FROM gex_peaks
                WHERE index_symbol = ? AND timestamp <= ? AND peak_rank = 1
                ORDER BY timestamp DESC
                LIMIT 1
            """, (index_symbol, ts))

            row = cursor.fetchone()

            if row:
                print(f"[REPLAY] Forward-filled GEX peak: {index_symbol} @ {ts}")
                return {
                    'strike': float(row[0]),
                    'gex': float(row[1]),
                    'distance_from_price': float(row[2]),
                    'proximity_score': float(row[3])
                }

            return None

        except Exception as e:
            print(f"[REPLAY] Error getting GEX peak: {e}")
            return None

    def get_index_price(self, index_symbol: str, timestamp: datetime) -> Optional[float]:
        """Get index price from market context snapshot."""
        try:
            cursor = self.conn.cursor()
            ts = self._normalize_timestamp(timestamp)

            # Try exact timestamp
            cursor.execute("""
                SELECT underlying_price
                FROM market_context
                WHERE index_symbol = ? AND timestamp = ?
                LIMIT 1
            """, (index_symbol, ts))

            row = cursor.fetchone()

            if row:
                return float(row[0])

            # Forward-fill if not found
            cursor.execute("""
                SELECT underlying_price
                FROM market_context
                WHERE index_symbol = ? AND timestamp <= ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (index_symbol, ts))

            row = cursor.fetchone()

            if row:
                return float(row[0])

            return None

        except Exception as e:
            print(f"[REPLAY] Error getting index price: {e}")
            return None

    def get_vix(self, timestamp: datetime) -> Optional[float]:
        """Get VIX level from market context snapshot."""
        try:
            cursor = self.conn.cursor()
            ts = self._normalize_timestamp(timestamp)

            # Try exact timestamp
            cursor.execute("""
                SELECT vix
                FROM market_context
                WHERE timestamp = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (ts,))

            row = cursor.fetchone()

            if row and row[0] is not None:
                return float(row[0])

            # Forward-fill if not found
            cursor.execute("""
                SELECT vix
                FROM market_context
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

    def get_options_chain(self, index_symbol: str, expiration: str,
                         timestamp: datetime) -> Optional[List[Dict]]:
        """Get options chain snapshot from database."""
        try:
            cursor = self.conn.cursor()
            ts = self._normalize_timestamp(timestamp)

            # Try exact timestamp
            cursor.execute("""
                SELECT chain_data
                FROM options_snapshots
                WHERE index_symbol = ? AND expiration = ? AND timestamp = ?
                LIMIT 1
            """, (index_symbol, expiration, ts))

            row = cursor.fetchone()

            if row and row[0]:
                chain = json.loads(row[0])
                return chain if isinstance(chain, list) else [chain]

            # Forward-fill: get most recent snapshot before this timestamp
            cursor.execute("""
                SELECT chain_data
                FROM options_snapshots
                WHERE index_symbol = ? AND expiration = ? AND timestamp <= ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (index_symbol, expiration, ts))

            row = cursor.fetchone()

            if row and row[0]:
                chain = json.loads(row[0])
                return chain if isinstance(chain, list) else [chain]

            return None

        except Exception as e:
            print(f"[REPLAY] Error getting options chain: {e}")
            return None

    def get_strike_prices(self, index_symbol: str, strikes: List[float],
                         option_type: str, expiration: str,
                         timestamp: datetime) -> Dict[float, Dict]:
        """Get bid/ask for specific strikes from pricing snapshots."""
        try:
            cursor = self.conn.cursor()
            ts = self._normalize_timestamp(timestamp)

            prices = {}

            for strike in strikes:
                # Try exact timestamp
                cursor.execute("""
                    SELECT bid, ask
                    FROM options_prices_live
                    WHERE index_symbol = ? AND strike = ? AND option_type = ?
                          AND timestamp = ?
                    LIMIT 1
                """, (index_symbol, strike, option_type, ts))

                row = cursor.fetchone()

                if row:
                    prices[strike] = {
                        'bid': float(row[0]) if row[0] else None,
                        'ask': float(row[1]) if row[1] else None
                    }
                    continue

                # Forward-fill: get most recent price before timestamp
                cursor.execute("""
                    SELECT bid, ask
                    FROM options_prices_live
                    WHERE index_symbol = ? AND strike = ? AND option_type = ?
                          AND timestamp <= ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (index_symbol, strike, option_type, ts))

                row = cursor.fetchone()

                if row:
                    prices[strike] = {
                        'bid': float(row[0]) if row[0] else None,
                        'ask': float(row[1]) if row[1] else None
                    }
                else:
                    # No data for this strike
                    prices[strike] = {'bid': None, 'ask': None}

            return prices

        except Exception as e:
            print(f"[REPLAY] Error getting strike prices: {e}")
            return {}

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            print("[REPLAY] Database connection closed")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
```

---

## Module 2: replay_time_manager.py

**Purpose**: Manage time advancement during replay
**File Size**: ~200 lines

```python
#!/usr/bin/env python3
"""
replay_time_manager.py - Time management for replay execution

Controls time progression through 30-second intervals matching
historical database snapshots. Handles market hours and entry
check time detection.
"""

from datetime import datetime, timedelta
import pytz


class ReplayTimeManager:
    """
    Manages time progression during replay.

    Time advances in discrete 30-second intervals matching
    gex_blackbox.db snapshot resolution.

    Usage:
        manager = ReplayTimeManager(
            start_date=datetime(2026, 1, 10),
            end_date=datetime(2026, 1, 13)
        )

        while manager.advance():
            current = manager.get_current_time()
            if manager.is_market_open_time():
                # Execute entry logic
                pass

            if manager.is_market_hours():
                # Execute monitoring logic
                pass
    """

    def __init__(self, start_date: datetime, end_date: datetime, step_seconds: int = 30):
        """
        Initialize time manager.

        Args:
            start_date: Begin replay from this date (inclusive)
            end_date: End replay at this date (inclusive)
            step_seconds: Time increment per iteration (default 30s)
        """
        self.start_time = start_date
        self.end_time = end_date
        self.current_time = start_date
        self.step_seconds = step_seconds
        self.iteration_count = 0
        self.et = pytz.timezone('America/New_York')

    def advance(self) -> bool:
        """
        Advance to next replay timestamp.

        Returns:
            True if within replay range, False if reached end
        """
        self.current_time += timedelta(seconds=self.step_seconds)
        self.iteration_count += 1

        if self.iteration_count % 100 == 0:
            print(f"[TIME] Iteration {self.iteration_count}: {self.current_time}")

        return self.current_time <= self.end_time

    def get_current_time(self) -> datetime:
        """Get current replay time."""
        return self.current_time

    def get_iteration_count(self) -> int:
        """Get number of iterations completed."""
        return self.iteration_count

    def get_elapsed_days(self) -> float:
        """Get elapsed trading days since start."""
        return (self.current_time - self.start_time).total_seconds() / (24 * 3600)

    def is_market_hours(self) -> bool:
        """
        Check if current time is during market hours.

        Market hours: 9:30 AM - 4:00 PM ET

        Returns:
            True if within market hours, False otherwise
        """
        et_time = self._to_et(self.current_time)

        market_open = et_time.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = et_time.replace(hour=16, minute=0, second=0, microsecond=0)

        return market_open <= et_time < market_close

    def is_market_open_time(self) -> bool:
        """
        Check if current time matches bot's entry check times.

        Bot checks at: 9:36, 10:00, 10:30, 11:00, 11:30, 12:00, 12:30,
                       13:00, 13:30, 14:00, 14:30, 15:00 ET

        Returns:
            True if at exact check time, False otherwise
        """
        et_time = self._to_et(self.current_time)

        # Entry check times: HH:00, HH:30, 09:36
        valid_seconds = {0}  # Must be at :00 seconds
        valid_hours = {9, 10, 11, 12, 13, 14, 15}  # 9 AM - 3 PM ET
        valid_minutes = {36, 0, 30}  # :36 (9 AM), :00, :30

        is_valid_time = (
            et_time.hour in valid_hours and
            et_time.minute in valid_minutes and
            et_time.second in valid_seconds
        )

        return is_valid_time

    def is_end_of_day(self) -> bool:
        """Check if current time is after 3:30 PM ET (auto-close time)."""
        et_time = self._to_et(self.current_time)
        return et_time.hour >= 15 and et_time.minute >= 30

    def is_session_change(self) -> bool:
        """
        Check if we've crossed into a new trading day.

        This is useful for daily reporting and resetting per-day counters.
        """
        # Check if previous time was yesterday and current is today
        prev_time = self.current_time - timedelta(seconds=self.step_seconds)

        et_prev = self._to_et(prev_time)
        et_curr = self._to_et(self.current_time)

        return et_prev.date() != et_curr.date()

    def skip_to_time(self, target_time: datetime) -> bool:
        """
        Fast-forward to specific time.

        Args:
            target_time: Target datetime to skip to

        Returns:
            True if successfully skipped, False if target is in past
        """
        if target_time <= self.current_time:
            return False

        self.current_time = target_time

        # Snap to next 30-second boundary
        remainder = self.current_time.second % 30
        if remainder != 0:
            self.current_time += timedelta(seconds=30 - remainder)

        return True

    def skip_to_market_open(self) -> None:
        """Fast-forward to next market open (9:30 AM ET)."""
        et_time = self._to_et(self.current_time)

        # If already past market open today, skip to tomorrow
        market_open = et_time.replace(hour=9, minute=30, second=0, microsecond=0)

        if et_time >= market_open:
            # Skip to tomorrow's market open
            self.current_time += timedelta(days=1)
            et_time = self._to_et(self.current_time)
            market_open = et_time.replace(hour=9, minute=30, second=0, microsecond=0)

        # Convert market_open back to current timezone and set
        self.current_time = market_open.astimezone(self.current_time.tzinfo or pytz.UTC)

    def skip_to_next_day(self) -> None:
        """Fast-forward to next day's market open."""
        et_time = self._to_et(self.current_time)
        tomorrow_open = (et_time + timedelta(days=1)).replace(
            hour=9, minute=30, second=0, microsecond=0
        )
        self.current_time = tomorrow_open.astimezone(self.current_time.tzinfo or pytz.UTC)

    def _to_et(self, dt: datetime) -> datetime:
        """Convert datetime to ET timezone."""
        if dt.tzinfo is None:
            # Assume UTC if no timezone
            dt = pytz.UTC.localize(dt)

        return dt.astimezone(self.et)

    def get_progress(self) -> str:
        """Get human-readable progress string."""
        total_time = (self.end_time - self.start_time).total_seconds()
        elapsed_time = (self.current_time - self.start_time).total_seconds()
        progress_pct = (elapsed_time / total_time * 100) if total_time > 0 else 0

        return (
            f"Progress: {progress_pct:.1f}% "
            f"({self.current_time.date()}) "
            f"[{self.iteration_count} iterations]"
        )
```

---

## Module 3: replay_state.py

**Purpose**: Maintain position state during replay
**File Size**: ~400 lines

```python
#!/usr/bin/env python3
"""
replay_state.py - State management for replay execution

Maintains all active and closed trades, calculates P&L,
and generates performance statistics.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import json


@dataclass
class ReplayTrade:
    """Represents a single trade during replay."""

    # Entry information
    order_id: str
    timestamp_entry: datetime
    strategy: str  # 'CALL', 'PUT', 'IC'
    direction: str  # 'BULLISH', 'BEARISH', 'NEUTRAL'
    confidence: str  # 'HIGH', 'MEDIUM', 'LOW'
    strikes: List[float]
    entry_credit: float  # Price per contract received
    entry_value: float  # Initial position value
    quantity: int  # Number of contracts/spreads
    index_symbol: str  # 'SPX' or 'NDX'
    expiration: str  # '2026-01-14'

    # Dynamic state during trade
    position_active: bool = True
    peak_value: float = field(default_factory=lambda: float('inf'))  # Best price (lowest)
    valley_value: float = field(default_factory=lambda: float('-inf'))  # Worst price (highest)
    last_check_time: Optional[datetime] = None
    trailing_stop_activated: bool = False
    trailing_stop_peak: float = 0.0  # Peak value since trailing activated
    max_loss_seen: float = 0.0  # Worst unrealized loss

    # Exit information
    timestamp_exit: Optional[datetime] = None
    exit_value: float = 0.0
    exit_reason: str = ""
    pnl_dollars: float = 0.0
    pnl_percent: float = 0.0

    def get_time_alive_seconds(self) -> float:
        """Get seconds the trade was open."""
        exit_time = self.timestamp_exit or datetime.now()
        return (exit_time - self.timestamp_entry).total_seconds()

    def get_time_alive_minutes(self) -> float:
        """Get minutes the trade was open."""
        return self.get_time_alive_seconds() / 60

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return {
            'order_id': self.order_id,
            'timestamp_entry': self.timestamp_entry.isoformat(),
            'timestamp_exit': self.timestamp_exit.isoformat() if self.timestamp_exit else None,
            'strategy': self.strategy,
            'direction': self.direction,
            'confidence': self.confidence,
            'strikes': self.strikes,
            'entry_credit': self.entry_credit,
            'entry_value': self.entry_value,
            'exit_value': self.exit_value,
            'quantity': self.quantity,
            'index_symbol': self.index_symbol,
            'expiration': self.expiration,
            'pnl_dollars': round(self.pnl_dollars, 2),
            'pnl_percent': round(self.pnl_percent * 100, 2),
            'exit_reason': self.exit_reason,
            'time_alive_minutes': round(self.get_time_alive_minutes(), 1)
        }


class ReplayStateManager:
    """
    Maintains all state during replay execution.

    Tracks:
    - Active trades (positions still open)
    - Closed trades (positions exited)
    - Daily P&L
    - Account balance
    """

    def __init__(self, starting_balance: float = 25000.0):
        """
        Initialize state manager.

        Args:
            starting_balance: Starting account balance (default $25,000)
        """
        self.active_trades: Dict[str, ReplayTrade] = {}
        self.closed_trades: List[ReplayTrade] = []
        self.starting_balance = starting_balance
        self.current_balance = starting_balance
        self.daily_pnl = 0.0
        self.max_drawdown = 0.0
        self.peak_balance = starting_balance
        self.trade_counter = 0

    def add_trade(self, trade: ReplayTrade) -> None:
        """Record new trade entry."""
        self.active_trades[trade.order_id] = trade
        self.trade_counter += 1

    def update_trade_price(self, order_id: str, current_value: float,
                          timestamp: datetime) -> None:
        """Update position's unrealized P&L with current options price."""
        if order_id not in self.active_trades:
            return

        trade = self.active_trades[order_id]
        trade.last_check_time = timestamp

        # Track peak value (best price for credit spread = lowest value)
        if current_value < trade.peak_value:
            trade.peak_value = current_value

        # Track valley value (worst price = highest value)
        if current_value > trade.valley_value:
            trade.valley_value = current_value

        # Track max loss seen
        loss_pct = (current_value - trade.entry_credit) / trade.entry_credit
        if loss_pct > trade.max_loss_seen:
            trade.max_loss_seen = loss_pct

    def close_trade(self, order_id: str, exit_value: float, exit_reason: str,
                   timestamp: datetime) -> None:
        """Close a trade and calculate final P&L."""
        if order_id not in self.active_trades:
            print(f"[STATE] Warning: Attempt to close unknown trade {order_id}")
            return

        trade = self.active_trades.pop(order_id)
        trade.exit_value = exit_value
        trade.exit_reason = exit_reason
        trade.timestamp_exit = timestamp
        trade.position_active = False

        # P&L calculation for credit spread
        # Profit when exit_value < entry_credit (bought back cheaper)
        trade.pnl_dollars = (trade.entry_credit - exit_value) * 100 * trade.quantity
        trade.pnl_percent = (trade.entry_credit - exit_value) / trade.entry_credit

        self.closed_trades.append(trade)
        self.daily_pnl += trade.pnl_dollars
        self.current_balance += trade.pnl_dollars

        # Update drawdown
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
        else:
            drawdown = self.peak_balance - self.current_balance
            if drawdown > self.max_drawdown:
                self.max_drawdown = drawdown

    def get_unrealized_pnl(self) -> float:
        """Calculate total unrealized P&L of all active trades."""
        total = 0.0

        for trade in self.active_trades.values():
            if trade.valley_value > 0:
                # Use worst price seen since entry
                unrealized = (trade.entry_credit - trade.valley_value) * 100 * trade.quantity
            else:
                # No price data yet
                unrealized = 0.0

            total += unrealized

        return total

    def get_statistics(self) -> Dict:
        """Calculate comprehensive performance statistics."""
        if not self.closed_trades:
            return {
                'total_trades': 0,
                'winners': 0,
                'losers': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'max_win': 0.0,
                'max_loss': 0.0,
                'profit_factor': 0.0,
                'final_balance': self.current_balance,
                'return_pct': 0.0,
                'max_drawdown': 0.0,
                'trades_by_confidence': {},
                'trades_by_strategy': {}
            }

        winners = [t for t in self.closed_trades if t.pnl_dollars > 0]
        losers = [t for t in self.closed_trades if t.pnl_dollars < 0]
        breakeven = [t for t in self.closed_trades if t.pnl_dollars == 0]

        total_wins = sum(t.pnl_dollars for t in winners)
        total_losses = abs(sum(t.pnl_dollars for t in losers))

        avg_win = total_wins / len(winners) if winners else 0.0
        avg_loss = total_losses / len(losers) if losers else 0.0

        # Profit factor: gross profit / gross loss
        profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')

        # Return on capital
        return_pct = (self.current_balance - self.starting_balance) / self.starting_balance

        # Trades by confidence
        trades_by_confidence = {}
        for confidence in ['HIGH', 'MEDIUM', 'LOW']:
            trades = [t for t in self.closed_trades if t.confidence == confidence]
            if trades:
                wins = len([t for t in trades if t.pnl_dollars > 0])
                trades_by_confidence[confidence] = {
                    'count': len(trades),
                    'winners': wins,
                    'win_rate': wins / len(trades),
                    'pnl': sum(t.pnl_dollars for t in trades)
                }

        # Trades by strategy
        trades_by_strategy = {}
        for strategy in ['CALL', 'PUT', 'IC']:
            trades = [t for t in self.closed_trades if t.strategy == strategy]
            if trades:
                wins = len([t for t in trades if t.pnl_dollars > 0])
                trades_by_strategy[strategy] = {
                    'count': len(trades),
                    'winners': wins,
                    'win_rate': wins / len(trades),
                    'pnl': sum(t.pnl_dollars for t in trades)
                }

        return {
            'total_trades': len(self.closed_trades),
            'winners': len(winners),
            'losers': len(losers),
            'breakeven': len(breakeven),
            'win_rate': len(winners) / len(self.closed_trades),
            'total_pnl': round(self.daily_pnl, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'max_win': round(max([t.pnl_dollars for t in winners], default=0), 2),
            'max_loss': round(min([t.pnl_dollars for t in losers], default=0), 2),
            'profit_factor': round(profit_factor, 2),
            'final_balance': round(self.current_balance, 2),
            'return_pct': round(return_pct * 100, 2),
            'max_drawdown': round(self.max_drawdown, 2),
            'trades_by_confidence': trades_by_confidence,
            'trades_by_strategy': trades_by_strategy
        }

    def export_trades_json(self, filepath: str) -> None:
        """Export all trades to JSON file."""
        trades_data = {
            'summary': self.get_statistics(),
            'trades': [t.to_dict() for t in self.closed_trades]
        }

        with open(filepath, 'w') as f:
            json.dump(trades_data, f, indent=2, default=str)

        print(f"[STATE] Exported {len(self.closed_trades)} trades to {filepath}")

    def print_summary(self) -> None:
        """Print statistics to stdout."""
        stats = self.get_statistics()

        print("\n" + "="*70)
        print("BACKTEST STATISTICS")
        print("="*70)
        print(f"Total Trades:        {stats['total_trades']}")
        print(f"  Winners:           {stats['winners']}")
        print(f"  Losers:            {stats['losers']}")
        print(f"  Breakeven:         {stats['breakeven']}")
        print(f"Win Rate:            {stats['win_rate']*100:.1f}%")
        print(f"Total P&L:           ${stats['total_pnl']:+,.2f}")
        print(f"Avg Win:             ${stats['avg_win']:,.2f}")
        print(f"Avg Loss:            ${stats['avg_loss']:,.2f}")
        print(f"Max Win:             ${stats['max_win']:,.2f}")
        print(f"Max Loss:            ${stats['max_loss']:,.2f}")
        print(f"Profit Factor:       {stats['profit_factor']:.2f}")
        print(f"Max Drawdown:        ${stats['max_drawdown']:,.2f}")
        print(f"Final Balance:       ${stats['final_balance']:,.2f}")
        print(f"Return on Capital:   {stats['return_pct']:+.1f}%")
        print("="*70 + "\n")
```

---

## Implementation Checklist

**Phase 1: Data Provider**
- [ ] Create abstract `DataProvider` class
- [ ] Implement `LiveDataProvider` (pass-through)
- [ ] Implement `ReplayDataProvider` with database queries
- [ ] Test with sample timestamp

**Phase 2: Time Manager**
- [ ] Implement time advancement logic
- [ ] Test market hours detection
- [ ] Test entry check time detection
- [ ] Test skip functions

**Phase 3: State Manager**
- [ ] Implement trade tracking
- [ ] Implement P&L calculation
- [ ] Implement statistics generation
- [ ] Test JSON export

**Phase 4: Integration**
- [ ] Create execution harness (Module 4)
- [ ] Integrate all three components
- [ ] Test on 1-day sample
- [ ] Validate against manual backtest

---

**Code Style Guide**:
- Type hints on all functions
- Docstrings for all classes/methods
- Error handling with try/except
- Logging at key decision points
- No hardcoded paths (use config)
- UTC timestamps throughout

**Testing Strategy**:
1. Unit test each module independently
2. Integration test all together on 1 day
3. Regression test on full month
4. Compare vs. manual backtest results

