#!/usr/bin/env python3
"""
Observation Period - Pre-Trade Risk Filter

Simulates a GEX pin entry and monitors price action for 1-2 minutes before
placing the actual trade. Detects dangerous movement patterns that would
cause emergency stops.

Strategy:
1. Detect valid GEX pin setup
2. Enter "observation mode" - track entry price
3. Monitor SPX price for configured period (default 90s)
4. Analyze movement patterns:
   - Volatility (price range vs spread width)
   - Direction changes (choppy vs trending)
   - Emergency stop proximity (would trade get stopped out?)
   - Momentum (speed of price changes)
5. Decision:
   - SAFE → Proceed with actual trade
   - DANGEROUS → Skip trade, log reason

Created: 2026-02-10
"""

import time
import logging
import datetime
import pytz
from typing import Dict, List, Tuple, Optional
import yfinance as yf

# Timezone
ET = pytz.timezone('America/New_York')

logger = logging.getLogger(__name__)


class ObservationPeriod:
    """Pre-trade observation to detect dangerous market conditions"""

    def __init__(self, config: Dict):
        """
        Initialize observation period with configuration

        Args:
            config: Dict with keys:
                - enabled: bool (default False)
                - period_seconds: int (default 90)
                - max_range_pct: float (default 0.15, max 15% of spread width)
                - max_direction_changes: int (default 5)
                - emergency_stop_threshold: float (default 0.40, 40% loss)
                - min_tick_interval: float (default 2.0, seconds between price checks)
        """
        self.enabled = config.get('enabled', False)
        self.period_seconds = config.get('period_seconds', 90)
        self.max_range_pct = config.get('max_range_pct', 0.15)
        self.max_direction_changes = config.get('max_direction_changes', 5)
        self.emergency_stop_threshold = config.get('emergency_stop_threshold', 0.40)
        self.min_tick_interval = config.get('min_tick_interval', 2.0)

        # State tracking
        self.prices: List[float] = []
        self.timestamps: List[datetime.datetime] = []
        self.start_time: Optional[datetime.datetime] = None
        self.entry_price: Optional[float] = None

    def observe(self, index_symbol: str, entry_credit: float,
                spread_width: float, direction: str) -> Tuple[bool, str]:
        """
        Monitor price action during observation period

        Args:
            index_symbol: Symbol to monitor (e.g., 'SPX')
            entry_credit: Expected credit received (e.g., 2.50)
            spread_width: Width of spread in points (e.g., 10)
            direction: 'PUT' or 'CALL' (determines risk direction)

        Returns:
            (is_safe, reason) tuple:
                - is_safe: True if safe to trade, False if dangerous
                - reason: Description of decision
        """
        if not self.enabled:
            return True, "Observation period disabled"

        logger.info("=" * 70)
        logger.info("🔍 OBSERVATION PERIOD STARTED")
        logger.info(f"   Duration: {self.period_seconds}s")
        logger.info(f"   Entry credit: ${entry_credit:.2f}")
        logger.info(f"   Spread width: {spread_width} points")
        logger.info(f"   Direction: {direction}")
        logger.info("=" * 70)

        # Get initial price
        try:
            initial_price = self._get_current_price(index_symbol)
            if initial_price is None:
                return False, "Failed to fetch initial price - aborting observation"
        except Exception as e:
            logger.error(f"Error fetching initial price: {e}")
            return False, f"Price fetch error: {e}"

        self.entry_price = initial_price
        self.start_time = datetime.datetime.now(ET)
        self.prices = [initial_price]
        self.timestamps = [self.start_time]

        logger.info(f"⏱️  Observation start: {self.start_time.strftime('%H:%M:%S')}")
        logger.info(f"💵 Initial SPX price: {initial_price:.2f}")

        # Monitor for configured period
        checks = 0
        max_checks = int(self.period_seconds / self.min_tick_interval)

        while len(self.prices) < max_checks:
            time.sleep(self.min_tick_interval)
            checks += 1
            elapsed = checks * self.min_tick_interval

            try:
                current_price = self._get_current_price(index_symbol)
                if current_price is None:
                    logger.warning(f"[{elapsed:.0f}s] Failed to fetch price, skipping tick")
                    continue

                now = datetime.datetime.now(ET)
                self.prices.append(current_price)
                self.timestamps.append(now)

                # Calculate metrics so far
                price_range = max(self.prices) - min(self.prices)
                range_pct = price_range / spread_width if spread_width > 0 else 0
                direction_changes = self._count_direction_changes()

                # Check if would hit emergency stop
                max_loss_pct = self._calculate_max_loss_pct(
                    entry_credit, spread_width, direction
                )

                logger.info(f"[{elapsed:.0f}s] SPX: {current_price:.2f} | "
                          f"Range: {price_range:.2f} ({range_pct:.1%}) | "
                          f"Changes: {direction_changes} | "
                          f"Max loss: {max_loss_pct:.1%}")

            except Exception as e:
                logger.error(f"[{elapsed:.0f}s] Error during observation: {e}")
                continue

        # Analysis complete - make decision
        return self._analyze_safety(entry_credit, spread_width, direction)

    def _get_current_price(self, symbol: str) -> Optional[float]:
        """Fetch current market price from Yahoo Finance"""
        try:
            ticker = yf.Ticker(f"^{symbol}")
            data = ticker.history(period='1d', interval='1m')
            if data.empty:
                return None
            return float(data['Close'].iloc[-1])
        except Exception as e:
            logger.error(f"Price fetch error: {e}")
            return None

    def _count_direction_changes(self) -> int:
        """Count number of direction reversals in price series"""
        if len(self.prices) < 3:
            return 0

        changes = 0
        for i in range(1, len(self.prices) - 1):
            # Check if this is a peak (higher than neighbors)
            is_peak = self.prices[i] > self.prices[i-1] and self.prices[i] > self.prices[i+1]
            # Check if this is a valley (lower than neighbors)
            is_valley = self.prices[i] < self.prices[i-1] and self.prices[i] < self.prices[i+1]

            if is_peak or is_valley:
                changes += 1

        return changes

    def _calculate_max_loss_pct(self, entry_credit: float,
                                 spread_width: float, direction: str) -> float:
        """
        Calculate maximum loss percentage based on price movement

        For PUT spread: Lose if price drops below short strike
        For CALL spread: Lose if price rises above short strike
        """
        if not self.prices or self.entry_price is None:
            return 0.0

        current_price = self.prices[-1]
        price_move = current_price - self.entry_price

        # Simplified loss calculation:
        # Assume worst case is price moves against us by full spread width
        # Max loss = spread_width - entry_credit (what we keep)
        max_loss = spread_width - entry_credit

        # Estimate current loss based on price movement
        # If price moves against us by X% of spread width, we lose proportionally
        if direction == 'PUT':
            # PUT spread loses when price drops
            if price_move < 0:
                loss_factor = abs(price_move) / spread_width
                current_loss = loss_factor * max_loss
                return current_loss / (entry_credit * 100) if entry_credit > 0 else 0
        elif direction == 'CALL':
            # CALL spread loses when price rises
            if price_move > 0:
                loss_factor = price_move / spread_width
                current_loss = loss_factor * max_loss
                return current_loss / (entry_credit * 100) if entry_credit > 0 else 0

        return 0.0

    def _analyze_safety(self, entry_credit: float,
                       spread_width: float, direction: str) -> Tuple[bool, str]:
        """
        Analyze collected data and determine if trade is safe

        Returns:
            (is_safe, reason) tuple
        """
        if len(self.prices) < 2:
            return False, "Insufficient price data collected"

        # Calculate metrics
        price_high = max(self.prices)
        price_low = min(self.prices)
        price_range = price_high - price_low
        range_pct = price_range / spread_width if spread_width > 0 else 0
        direction_changes = self._count_direction_changes()
        max_loss_pct = max(
            self._calculate_max_loss_pct(entry_credit, spread_width, direction)
            for _ in [None]  # Just use final value
        )

        # Calculate velocity (avg change per second)
        if len(self.prices) > 1:
            total_time = (self.timestamps[-1] - self.timestamps[0]).total_seconds()
            avg_velocity = price_range / total_time if total_time > 0 else 0
        else:
            avg_velocity = 0

        logger.info("=" * 70)
        logger.info("📊 OBSERVATION ANALYSIS")
        logger.info(f"   Prices tracked: {len(self.prices)}")
        logger.info(f"   Price range: {price_range:.2f} points ({range_pct:.1%} of spread)")
        logger.info(f"   High: {price_high:.2f}, Low: {price_low:.2f}")
        logger.info(f"   Direction changes: {direction_changes}")
        logger.info(f"   Max loss reached: {max_loss_pct:.1%}")
        logger.info(f"   Avg velocity: {avg_velocity:.2f} pts/sec")
        logger.info("=" * 70)

        # Decision logic
        failures = []

        # Check 1: Excessive range (high volatility)
        if range_pct > self.max_range_pct:
            failures.append(
                f"High volatility: {range_pct:.1%} > {self.max_range_pct:.1%} threshold"
            )

        # Check 2: Too many direction changes (choppy)
        if direction_changes > self.max_direction_changes:
            failures.append(
                f"Choppy movement: {direction_changes} changes > {self.max_direction_changes} threshold"
            )

        # Check 3: Would have hit emergency stop
        if max_loss_pct >= self.emergency_stop_threshold:
            failures.append(
                f"Emergency stop territory: {max_loss_pct:.1%} >= {self.emergency_stop_threshold:.1%}"
            )

        # Check 4: High velocity (fast-moving market)
        max_velocity = 0.5  # 0.5 points per second = 30 points per minute
        if avg_velocity > max_velocity:
            failures.append(
                f"Fast-moving market: {avg_velocity:.2f} pts/s > {max_velocity:.2f} threshold"
            )

        if failures:
            reason = " | ".join(failures)
            logger.warning(f"🚫 OBSERVATION FAILED: {reason}")
            return False, reason
        else:
            logger.info("✅ OBSERVATION PASSED: Market conditions safe for entry")
            return True, (
                f"Safe conditions: {range_pct:.1%} range, "
                f"{direction_changes} changes, {max_loss_pct:.1%} max loss"
            )

    def get_summary(self) -> Dict:
        """Return summary of observation period for logging"""
        if not self.prices or not self.timestamps:
            return {}

        return {
            'observation_enabled': self.enabled,
            'duration_seconds': self.period_seconds,
            'prices_tracked': len(self.prices),
            'price_high': max(self.prices),
            'price_low': min(self.prices),
            'price_range': max(self.prices) - min(self.prices),
            'direction_changes': self._count_direction_changes(),
            'start_time': self.start_time.strftime('%Y-%m-%d %H:%M:%S') if self.start_time else None,
            'end_time': self.timestamps[-1].strftime('%Y-%m-%d %H:%M:%S') if self.timestamps else None,
        }


def log_observation_decision(is_safe: bool, reason: str, summary: Dict):
    """Log observation decision to dedicated file for analysis"""
    import os
    import json

    GAMMA_HOME = os.environ.get('GAMMA_HOME', '/root/gamma')
    LOG_FILE = f"{GAMMA_HOME}/data/observation_decisions.jsonl"

    entry = {
        'timestamp': datetime.datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S'),
        'is_safe': is_safe,
        'reason': reason,
        **summary
    }

    try:
        with open(LOG_FILE, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception as e:
        logger.error(f"Failed to log observation decision: {e}")
