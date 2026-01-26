#!/usr/bin/env python3
"""
Unified Market Veto Cache System

Works for BOTH backtesting and live trading:
- Historical timestamps: Cache forever (one-time API cost)
- Live timestamps: Cache 5 minutes (refresh every 5 min)

Usage:
    # In backtest
    cache = MarketVetoCache()
    if cache.should_block_trading(bar_timestamp, market="stocks"):
        skip_this_trade()

    # In live bot (same interface)
    if cache.should_block_trading(datetime.now(), market="stocks"):
        skip_trading()
"""

import json
import os
import fcntl
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional
import anthropic

# Set up logging
logger = logging.getLogger(__name__)

# Cache size limit to prevent unbounded growth
MAX_CACHE_ENTRIES = 10000

class MarketVetoCache:
    """Timestamp-based market-wide veto cache (not per-trade)"""

    def __init__(self, cache_dir="/root/gamma/data"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

        self.cache_file = self.cache_dir / "market_veto_cache.json"
        self.cache = self._load_cache()

        # Load API key
        self.api_key = self._load_api_key()

        # Stats
        self.stats = {
            'hits': 0,
            'misses': 0,
            'cost_spent': 0.0,
            'cost_saved': 0.0
        }

    def _load_api_key(self) -> str:
        """Load Anthropic API key from environment files"""
        for env_file in ['/etc/gamma.env', '/etc/trader.env']:
            if Path(env_file).exists():
                with open(env_file) as f:
                    for line in f:
                        if line.startswith('ANTHROPIC_API_KEY='):
                            key = line.split('=', 1)[1].strip().strip('"').strip("'")
                            if key:
                                return key

        raise ValueError("ANTHROPIC_API_KEY not found in /etc/gamma.env or /etc/trader.env")

    def _load_cache(self) -> Dict:
        """Load cache from disk"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load cache from {self.cache_file}: {e}")
                return {}
        return {}

    def _save_cache(self):
        """Save cache to disk atomically with file locking and size limit"""
        import tempfile

        # ISSUE #5: Evict oldest entries if cache too large
        if len(self.cache) > MAX_CACHE_ENTRIES:
            logger.warning(f"Cache size {len(self.cache)} exceeds limit {MAX_CACHE_ENTRIES}, evicting old entries")
            # Keep only most recent entries by cached_at timestamp
            sorted_keys = sorted(
                self.cache.keys(),
                key=lambda k: self.cache[k].get('cached_at', '1970-01-01'),
                reverse=True
            )
            self.cache = {k: self.cache[k] for k in sorted_keys[:MAX_CACHE_ENTRIES]}

        # Use tempfile in same directory for atomic rename
        fd, temp_path = tempfile.mkstemp(dir=self.cache_dir, suffix='.json')
        try:
            with os.fdopen(fd, 'w') as f:
                # ISSUE #2: Add file locking for concurrent access
                fcntl.flock(f, fcntl.LOCK_EX)
                json.dump(self.cache, f, indent=2)
                fcntl.flock(f, fcntl.LOCK_UN)
            os.replace(temp_path, self.cache_file)
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    def _make_cache_key(self, timestamp, market: str) -> str:
        """Create cache key from timestamp and market"""
        # Handle both datetime and pandas Timestamp
        if hasattr(timestamp, 'to_pydatetime'):
            timestamp = timestamp.to_pydatetime()
        return f"{timestamp.strftime('%Y-%m-%d_%H:%M')}_{market}"

    def _is_expired(self, timestamp: datetime, cached_at: str) -> bool:
        """Check if cache entry is expired"""
        # ISSUE #1: Make both timestamps timezone-naive for comparison
        now_naive = datetime.now()

        # Convert timestamp to naive if it has timezone info
        if hasattr(timestamp, 'tzinfo') and timestamp.tzinfo is not None:
            timestamp_naive = timestamp.replace(tzinfo=None)
        else:
            timestamp_naive = timestamp

        # Historical data (>1 hour old) never expires
        if timestamp_naive < now_naive - timedelta(hours=1):
            return False

        # Live data expires after 5 minutes
        cached_time = datetime.fromisoformat(cached_at)
        # Remove timezone from cached_time if present
        if hasattr(cached_time, 'tzinfo') and cached_time.tzinfo is not None:
            cached_time = cached_time.replace(tzinfo=None)

        return now_naive - cached_time > timedelta(minutes=5)

    def _get_market_data(self, timestamp, market: str) -> Dict:
        """Fetch market data for timestamp (from SQLite or live API)"""
        import sqlite3
        import pandas as pd

        # Handle pandas Timestamp
        if hasattr(timestamp, 'to_pydatetime'):
            timestamp = timestamp.to_pydatetime()

        # Make timestamp timezone-naive for comparison (if it has timezone info, remove it)
        if hasattr(timestamp, 'tzinfo') and timestamp.tzinfo is not None:
            timestamp_naive = timestamp.replace(tzinfo=None)
        else:
            timestamp_naive = timestamp

        # For backtest: Get data from SQLite
        if timestamp_naive < datetime.now() - timedelta(minutes=10):
            # ISSUE #3: Use try/finally to ensure connection is always closed
            conn = None
            try:
                # Gamma bot: Use GEX database with market_context table
                conn = sqlite3.connect('/root/gamma/data/gex_blackbox.db')

                # Get SPY data around this timestamp
                query = """
                SELECT timestamp, spy_price, vix
                FROM market_context
                WHERE timestamp >= ?
                  AND timestamp <= ?
                ORDER BY timestamp
                LIMIT 10
                """

                start = (timestamp - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
                end = (timestamp + timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')

                df = pd.read_sql_query(query, conn, params=(start, end))

                if len(df) > 0:
                    bar = df[df['timestamp'] == timestamp.strftime('%Y-%m-%d %H:%M:%S')]
                    if len(bar) == 0:
                        bar = df.iloc[[0]]  # Closest bar as DataFrame

                    # Always get first row as Series for consistent access
                    row = bar.iloc[0] if len(bar) > 0 else None

                    if row is not None and pd.notna(row['spy_price']):
                        result = {
                            'price': float(row['spy_price']),
                        }
                        # Add VIX if available
                        if pd.notna(row['vix']):
                            result['vix'] = float(row['vix'])
                        return result
            except Exception as e:
                logger.warning(f"Failed to fetch market data from database: {e}")
            finally:
                if conn:
                    conn.close()

        # For live: Would call Tradier API here
        # For now, return None and let Claude decide without data
        return {}

    def _get_economic_events(self, timestamp) -> str:
        """Check if this date has economic events (FOMC, CPI, PPI, NFP)"""
        try:
            # Import here to avoid circular dependency
            import sys
            import os
            sys.path.insert(0, '/root/TRADER')
            from stock_anomaly_detector import EconomicCalendar

            month_day = (timestamp.month, timestamp.day)
            events = []

            if month_day in EconomicCalendar.FOMC_DATES_2026:
                events.append("FOMC meeting (typically 2:00 PM ET announcement)")
            if month_day in EconomicCalendar.CPI_DATES_2026:
                events.append("CPI release (8:30 AM ET)")
            if month_day in EconomicCalendar.PPI_DATES_2026:
                events.append("PPI release (8:30 AM ET)")

            if events:
                return "⚠️  ECONOMIC EVENTS TODAY: " + ", ".join(events)
            return None
        except Exception as e:
            logger.warning(f"Failed to check economic calendar: {e}")
            return None

    def _call_claude_veto(self, timestamp, market: str, market_data: Dict) -> Dict:
        """Call Claude API for market-wide veto decision"""
        # Handle pandas Timestamp
        if hasattr(timestamp, 'to_pydatetime'):
            timestamp = timestamp.to_pydatetime()

        client = anthropic.Anthropic(api_key=self.api_key)

        # Build context based on market type
        time_str = timestamp.strftime('%A, %B %d, %Y at %I:%M %p ET')

        # Check for economic events
        economic_events = self._get_economic_events(timestamp)

        if market_data:
            context = f"""Market: {market.upper()}
Time: {time_str}
SPY Price: ${market_data.get('price', 0):.2f}"""

            # Add VIX if available
            if 'vix' in market_data and market_data['vix'] is not None:
                context += f"\nVIX: {market_data['vix']:.2f}"

            # Add volume/range only if available (not available for Gamma options data)
            if 'volume' in market_data:
                context += f"\nVolume: {market_data.get('volume', 0):,}"
            if 'high' in market_data and 'low' in market_data:
                context += f"\nHigh-Low Range: ${market_data.get('high', 0):.2f} - ${market_data.get('low', 0):.2f}"

            if economic_events:
                context += f"\n{economic_events}"
        else:
            context = f"""Market: {market.upper()}
Time: {time_str}
(Market data unavailable - use your knowledge of typical market conditions)"""
            if economic_events:
                context += f"\n{economic_events}"

        # Market-specific prompts
        if market == "mnq":
            # MNQ: Focus on market anomalies, not time (trades 23 hours)
            prompt = f"""You are a market-wide risk management system for MNQ FUTURES trading. Analyze current market conditions and decide if ALL MNQ trading should be blocked right now.

{context}

IMPORTANT: MNQ trades 23 hours/day (Sun 6 PM - Fri 5 PM ET with 1-hour break). DO NOT block based on time of day.

Block trading ONLY if:
- Flash crash or extreme price movement (>3% in 5 minutes)
- Extreme volatility spike (VIX > 50 or massive price swings)
- Major breaking news causing market panic (Fed emergency, geopolitical crisis)
- Technical/data issues (volume = 0, missing data, price = 0)
- Market circuit breaker triggered

DO NOT block for:
- Normal overnight/weekend trading (MNQ trades 23 hours)
- Lower volume during off-hours (normal for futures)
- Typical market volatility (MNQ is volatile by nature)
- Time of day or day of week

Allow trading if:
- Normal MNQ market conditions (even if volatile)
- Data is valid and available
- No extreme market-wide disruptions

Respond in this EXACT format:
DECISION: [BLOCK or ALLOW]
REASON: [One clear sentence explaining why]
CONFIDENCE: [0-100]"""

        else:
            # Stocks/Options: Extended hours allowed, focus on economic events
            prompt = f"""You are a market-wide risk management system. Analyze current market conditions and decide if ALL trading should be blocked right now.

{context}

IMPORTANT: Extended hours trading is ALLOWED and normal (4:00 AM - 8:00 PM ET for stocks, 9:30 AM - 4:00 PM ET for options).

Block trading if:
- **ECONOMIC EVENTS:** FOMC, CPI, PPI releases (block 30 min before and 90 min after release time)
  - FOMC: 2:00 PM ET (block 1:30 PM - 3:30 PM)
  - CPI/PPI: 8:30 AM ET (block 8:00 AM - 10:00 AM)
  - These events cause extreme volatility and unpredictable price action
- Extreme volatility or unusual conditions (major market disruption)
- Breaking news events that create severe uncertainty
- VIX spike above 40 (panic conditions)
- Flash crash or circuit breaker event

DO NOT block for:
- After-hours or pre-market trading (4:00 AM - 8:00 PM ET is valid for stocks)
- Normal market hours (9:30 AM - 4:00 PM ET for options)
- Weekend or holiday closures (if data exists, allow it)
- Normal market volatility
- Economic event days OUTSIDE the risk window (e.g., CPI day at 2 PM = safe)
- Missing volume data (volume not tracked for all instruments)

Allow trading if:
- Market price data is available
- No extreme market disruptions or economic events in risk window
- Normal volatility conditions (VIX < 40)

Respond in this EXACT format:
DECISION: [BLOCK or ALLOW]
REASON: [One clear sentence explaining why]
CONFIDENCE: [0-100]"""

        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=150,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}]
        )

        # Parse response
        text = response.content[0].text

        decision = "block"  # Default to safe
        reason = "Unknown"
        confidence = 50
        parsed_decision = False
        parsed_reason = False

        for line in text.split('\n'):
            if line.startswith('DECISION:'):
                decision = 'block' if 'BLOCK' in line.upper() else 'allow'
                parsed_decision = True
            elif line.startswith('REASON:'):
                reason = line.split(':', 1)[1].strip()
                parsed_reason = True
            elif line.startswith('CONFIDENCE:'):
                try:
                    confidence = int(line.split(':', 1)[1].strip())
                except Exception as e:
                    logger.warning(f"Failed to parse confidence: {e}")
                    confidence = 50

        # ISSUE #6: Validate Claude response and log if malformed
        if not parsed_decision or not parsed_reason:
            logger.warning(f"Failed to parse Claude response. Decision={parsed_decision}, Reason={parsed_reason}")
            logger.warning(f"Raw response: {text[:200]}")  # Log first 200 chars
            # Still use default values (decision='block', reason='Unknown')

        # Calculate cost
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        input_cost = input_tokens * 0.003 / 1000
        output_cost = output_tokens * 0.015 / 1000
        total_cost = input_cost + output_cost

        return {
            'veto': (decision == 'block'),
            'reason': reason,
            'confidence': confidence,
            'timestamp': timestamp.isoformat(),
            'cached_at': datetime.now().isoformat(),
            'cost': total_cost,
            'tokens_in': input_tokens,
            'tokens_out': output_tokens
        }

    def should_block_trading(self, timestamp, market: str = "stocks") -> tuple:
        """
        Main interface: Should trading be blocked at this timestamp?

        Args:
            timestamp: datetime or pandas Timestamp
            market: "stocks", "options", or "mnq"

        Returns:
            (should_block: bool, reason: str)
        """
        # Handle pandas Timestamp
        if hasattr(timestamp, 'to_pydatetime'):
            ts_for_check = timestamp.to_pydatetime()
        else:
            ts_for_check = timestamp

        cache_key = self._make_cache_key(timestamp, market)

        # Check cache
        if cache_key in self.cache:
            entry = self.cache[cache_key]

            # Check if expired
            if not self._is_expired(ts_for_check, entry['cached_at']):
                self.stats['hits'] += 1
                self.stats['cost_saved'] += entry.get('cost', 0.0018)
                return entry['veto'], entry['reason']

        # Cache miss - call Claude
        self.stats['misses'] += 1

        market_data = self._get_market_data(timestamp, market)
        decision = self._call_claude_veto(timestamp, market, market_data)

        self.stats['cost_spent'] += decision['cost']

        # Cache it
        self.cache[cache_key] = decision
        self._save_cache()

        return decision['veto'], decision['reason']

    def get_stats(self) -> Dict:
        """Get cache statistics"""
        total = self.stats['hits'] + self.stats['misses']
        hit_rate = (self.stats['hits'] / total * 100) if total > 0 else 0

        return {
            'cache_hits': self.stats['hits'],
            'cache_misses': self.stats['misses'],
            'hit_rate_pct': hit_rate,
            'cost_spent': self.stats['cost_spent'],
            'cost_saved': self.stats['cost_saved'],
            'cache_entries': len(self.cache)
        }
