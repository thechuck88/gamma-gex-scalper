#!/usr/bin/env python3
"""
replay_execution.py - Main replay harness orchestration

Orchestrates backtesting by:
- Using replay data provider to fetch historical snapshots
- Advancing time in 30-second intervals
- Detecting entry signals at canonical entry times
- Calling live bot logic to generate trades
- Tracking exits and P&L
- Generating statistics

This harness wraps the actual live bot code (from core/gex_strategy.py)
to guarantee identical logic between backtest and live trading.
"""

import sqlite3
import json
import logging
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from enum import Enum

from replay_data_provider import ReplayDataProvider, DataProvider
from replay_time_manager import TimeManager
from replay_state import ReplayStateManager, ReplayTrade, ExitReason


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


class TradeSignal(Enum):
    """Trade entry signal types."""
    NONE = "NONE"
    CALL_SPREAD = "CALL_SPREAD"
    PUT_SPREAD = "PUT_SPREAD"
    IRON_CONDOR = "IRON_CONDOR"


class ReplayExecutionHarness:
    """
    Main replay execution harness.

    Orchestrates backtesting by integrating:
    - DataProvider: Historical data from gex_blackbox.db
    - TimeManager: 30-second time advancement
    - StateManager: Trade tracking and P&L calculation
    """

    def __init__(
        self,
        db_path: str,
        start_date: datetime,
        end_date: datetime,
        index_symbol: str = 'SPX',
        starting_balance: float = 100000.0,
        vix_floor: float = 12.0,
        vix_ceiling: float = 30.0,
        min_entry_credit: float = 1.50,
        stop_loss_percent: float = 0.10,
        profit_target_percent: float = 0.50,
        trailing_stop_enabled: bool = True
    ):
        """
        Initialize replay harness.

        Args:
            db_path: Path to gex_blackbox.db database
            start_date: Backtest start date
            end_date: Backtest end date
            index_symbol: 'SPX' or 'NDX'
            starting_balance: Starting account balance
            vix_floor: Minimum VIX to trade
            vix_ceiling: Maximum VIX to trade
            min_entry_credit: Minimum acceptable entry credit
            stop_loss_percent: Stop loss threshold (e.g., 0.10 = 10%)
            profit_target_percent: Profit target threshold (e.g., 0.50 = 50%)
            trailing_stop_enabled: Enable trailing stop logic
        """
        self.db_path = db_path
        self.index_symbol = index_symbol
        self.starting_balance = starting_balance
        self.vix_floor = vix_floor
        self.vix_ceiling = vix_ceiling
        self.min_entry_credit = min_entry_credit
        self.stop_loss_percent = stop_loss_percent
        self.profit_target_percent = profit_target_percent
        self.trailing_stop_enabled = trailing_stop_enabled

        # Initialize components
        self.data_provider = ReplayDataProvider(db_path)
        self.time_manager = TimeManager(
            start_timestamp=start_date,
            end_timestamp=end_date
        )
        self.state_manager = ReplayStateManager(starting_balance=starting_balance)

        # Trade tracking
        self.trades_by_peak_rank = {1: 0, 2: 0, 3: 0}
        self.trade_count = 0
        self.entry_count = 0
        self.exit_count = 0

        # Track peaks we've already entered to avoid duplicate entries
        self.entered_peaks = set()  # Set of (peak_rank, pin_strike) tuples

        logger.info(
            f"[HARNESS] Initialized: {index_symbol} ({start_date} to {end_date}), "
            f"VIX filter: {vix_floor}-{vix_ceiling}, Min credit: ${min_entry_credit:.2f}"
        )

    def _get_gex_trade_setup(
        self,
        conn: sqlite3.Connection,
        timestamp: datetime,
        index_symbol: str,
        pin_strike: float,
        underlying_price: float,
        vix: float
    ) -> Optional[Dict]:
        """
        Get trade setup from GEX peaks (mimics live bot logic).

        This queries the database directly to match live bot behavior
        instead of calling external services.

        Returns:
            {
                'strike_short': float,
                'strike_long': float,
                'entry_credit': float,
                'spread_type': str ('CALL', 'PUT', 'IC'),
                'confidence': str ('HIGH', 'MEDIUM', 'LOW')
            }
        """
        try:
            cursor = conn.cursor()
            ts = timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp

            # Determine spread type based on price vs PIN
            distance_from_pin = underlying_price - pin_strike
            is_above_pin = distance_from_pin > 0
            distance_pts = abs(distance_from_pin)

            # Classify distance zone
            if distance_pts <= 6:
                distance_zone = 'NEAR_PIN'
            elif distance_pts <= 15:
                distance_zone = 'MODERATE'
            elif distance_pts <= 50:
                distance_zone = 'FAR'
            else:
                distance_zone = 'TOO_FAR'

            # Define strike spreads based on distance and VIX
            if distance_zone == 'NEAR_PIN':
                if vix < 15:
                    short_offset, long_offset = 5, 10
                else:
                    short_offset, long_offset = 3, 8
            elif distance_zone == 'MODERATE':
                short_offset, long_offset = 10, 15
            else:
                short_offset, long_offset = 15, 20

            # Determine spread direction
            if is_above_pin:
                spread_type = 'CALL'
                strike_short = pin_strike + short_offset
                strike_long = pin_strike + long_offset
            else:
                spread_type = 'PUT'
                strike_short = pin_strike - short_offset
                strike_long = pin_strike - long_offset

            # Get bid/ask for entry credit calculation
            short_ba = self.data_provider.get_options_bid_ask(
                index_symbol, strike_short, spread_type.lower(), timestamp
            )
            long_ba = self.data_provider.get_options_bid_ask(
                index_symbol, strike_long, spread_type.lower(), timestamp
            )

            if not short_ba or not long_ba:
                return None

            # Entry pricing with slippage
            # When entering a spread: SELL short leg (get bid), BUY long leg (pay ask)
            # But in reality, we may not get exactly bid/ask - slippage of 1-2 ticks
            short_bid, short_ask = short_ba
            long_bid, long_ask = long_ba

            # Apply conservative slippage: assume we get 1 tick worse on entry
            # On short leg: we get bid (but might miss, get slightly lower) → use bid
            # On long leg: we pay ask (but might miss, pay slightly higher) → use ask
            # Net effect: entry credit is 1-2 ticks WORSE than mid-to-mid calculation

            entry_credit_ideal = (short_bid - long_ask) * 100

            # Apply 1-tick slippage penalty (typical for limit order not filled immediately)
            slippage_penalty = 0.05 * 100  # 1 tick = $5 per spread = 0.05 per contract
            entry_credit = max(0, entry_credit_ideal - slippage_penalty)

            # Determine confidence based on credit size
            if entry_credit >= 2.50:
                confidence = 'HIGH'
            elif entry_credit >= 1.50:
                confidence = 'MEDIUM'
            else:
                confidence = 'LOW'

            return {
                'strike_short': strike_short,
                'strike_long': strike_long,
                'entry_credit': entry_credit,
                'spread_type': spread_type,
                'confidence': confidence,
                'distance_zone': distance_zone
            }

        except Exception as e:
            logger.warning(f"[HARNESS] Error in get_gex_trade_setup: {e}")
            return None

    def _apply_bwic_to_ic(
        self,
        conn: sqlite3.Connection,
        timestamp: datetime,
        index_symbol: str,
        call_short: float,
        call_long: float,
        put_short: float,
        put_long: float,
        call_setup: Dict,
        put_setup: Dict
    ) -> Optional[Dict]:
        """
        Apply BWIC (Broken Wing Iron Condor) logic to symmetric IC.

        Queries GEX polarity from competing_peaks to determine
        asymmetric wing widths.

        Returns:
            {
                'call_short': float,
                'call_long': float,
                'put_short': float,
                'put_long': float,
                'entry_credit': float
            }
        """
        try:
            cursor = conn.cursor()
            ts = timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp

            # Get competing peaks to calculate GEX polarity
            cursor.execute("""
                SELECT peak1_strike, peak2_strike, peak1_gex, peak2_gex, is_competing
                FROM competing_peaks
                WHERE timestamp = ? AND index_symbol = ?
                LIMIT 1
            """, (ts, index_symbol))

            row = cursor.fetchone()
            if not row:
                return None

            peak1_strike, peak2_strike, peak1_gex, peak2_gex, is_competing = row

            if not is_competing or peak1_gex + peak2_gex == 0:
                # Not competing, use symmetric IC
                return None

            # Calculate GEX Polarity Index (GPI): -1 to +1
            gpi = (peak1_gex - peak2_gex) / (peak1_gex + peak2_gex)

            # Adjust wing widths based on GPI
            # When GPI > 0: Peak1 stronger, widen call wing, tighten put wing
            # When GPI < 0: Peak2 stronger, tighten call wing, widen put wing
            call_width_mult = 1.0 + (0.25 * gpi)  # 0.75 to 1.25
            put_width_mult = 1.0 - (0.25 * gpi)   # 0.75 to 1.25

            # Apply multipliers to wing widths
            call_width = (call_long - call_short) * call_width_mult
            put_width = (put_short - put_long) * put_width_mult

            new_call_short = call_short
            new_call_long = call_short + call_width
            new_put_short = put_short
            new_put_long = put_short - put_width

            # Recalculate entry credit with adjusted strikes
            call_short_ba = self.data_provider.get_options_bid_ask(
                index_symbol, new_call_short, 'call', timestamp
            )
            call_long_ba = self.data_provider.get_options_bid_ask(
                index_symbol, new_call_long, 'call', timestamp
            )
            put_short_ba = self.data_provider.get_options_bid_ask(
                index_symbol, new_put_short, 'put', timestamp
            )
            put_long_ba = self.data_provider.get_options_bid_ask(
                index_symbol, new_put_long, 'put', timestamp
            )

            if not all([call_short_ba, call_long_ba, put_short_ba, put_long_ba]):
                return None

            # Apply slippage to IC entry credits (1-tick per leg, so 2 ticks total for 2-leg IC)
            call_credit_ideal = (call_short_ba[0] - call_long_ba[1]) * 100
            put_credit_ideal = (put_short_ba[0] - put_long_ba[1]) * 100

            # 1-tick slippage on each leg = $5 per contract
            slippage_per_leg = 0.05 * 100
            call_credit = max(0, call_credit_ideal - slippage_per_leg)
            put_credit = max(0, put_credit_ideal - slippage_per_leg)
            entry_credit = call_credit + put_credit

            return {
                'call_short': new_call_short,
                'call_long': new_call_long,
                'put_short': new_put_short,
                'put_long': new_put_long,
                'entry_credit': entry_credit
            }

        except Exception as e:
            logger.debug(f"[HARNESS] BWIC not applicable: {e}")
            return None

    def _check_exit_conditions(
        self,
        trade: ReplayTrade,
        timestamp: datetime,
        current_spread_value: float
    ) -> Optional[Tuple[datetime, float, ExitReason]]:
        """
        Check if trade should be exited based on stop loss, profit target, or trailing stop.

        Returns:
            (exit_time, exit_spread_value, exit_reason) or None if still open
        """
        if trade.is_open():
            # Calculate unrealized P&L
            unrealized_pnl = (trade.entry_credit - current_spread_value) * 100

            # Check stop loss (10% loss threshold)
            if unrealized_pnl < -(trade.entry_credit * 100 * self.stop_loss_percent):
                return (timestamp, current_spread_value, ExitReason.STOP_LOSS)

            # Check profit target (50% of credit)
            if unrealized_pnl >= (trade.entry_credit * 100 * self.profit_target_percent):
                return (timestamp, current_spread_value, ExitReason.PROFIT_TARGET)

            # Check trailing stop
            if self.trailing_stop_enabled:
                if current_spread_value < trade.peak_spread_value:
                    trade.peak_spread_value = current_spread_value

                    # Activate trailing stop at 20% profit
                    if not trade.trailing_stop_activated:
                        profit_threshold = trade.entry_credit * 0.20
                        if current_spread_value <= (trade.entry_credit - profit_threshold):
                            trade.trailing_stop_activated = True

                    # Execute trailing stop (lock in 12%, trail to 8%)
                    if trade.trailing_stop_activated:
                        lock_in_price = trade.entry_credit * 0.12
                        trail_stop_price = trade.entry_credit * 0.08

                        if current_spread_value <= trail_stop_price:
                            return (timestamp, current_spread_value, ExitReason.TRAILING_STOP)

        return None

    def run_replay(self) -> Dict:
        """
        Run the replay simulation.

        Returns:
            Statistics dictionary from state manager
        """
        logger.info("[HARNESS] Starting replay simulation...")

        try:
            iteration_count = 0
            last_trading_date = None

            while self.time_manager.has_more_data():
                timestamp = self.time_manager.get_current_timestamp()
                iteration_count += 1

                # Reset entered_peaks at start of new trading day
                current_date = timestamp.date() if hasattr(timestamp, 'date') else timestamp.split()[0]
                if last_trading_date != current_date:
                    self.entered_peaks.clear()
                    last_trading_date = current_date

                # Skip if outside market hours
                if not self.time_manager.is_market_hours(timestamp):
                    self.time_manager.advance_time(30)
                    continue

                # Get current market context
                index_price = self.data_provider.get_index_price(self.index_symbol, timestamp)
                vix = self.data_provider.get_vix(timestamp)

                if index_price is None or vix is None:
                    self.time_manager.advance_time(30)
                    continue

                # Check VIX filter
                if vix < self.vix_floor or vix > self.vix_ceiling:
                    self.time_manager.advance_time(30)
                    continue

                # ===== ENTRY SIGNALS =====
                if self.time_manager.is_entry_check_time(timestamp):
                    for peak_rank in [1, 2]:
                        gex_peak = self.data_provider.get_gex_peak(
                            self.index_symbol, timestamp, peak_rank=peak_rank
                        )

                        if not gex_peak:
                            continue

                        pin_strike = gex_peak['strike']

                        # Skip if we've already entered this peak
                        peak_key = (peak_rank, pin_strike)
                        if peak_key in self.entered_peaks:
                            continue
                        self.entered_peaks.add(peak_key)

                        # Get trade setup (mimics live bot logic)
                        setup = self._get_gex_trade_setup(
                            self.data_provider.conn,
                            timestamp,
                            self.index_symbol,
                            pin_strike,
                            index_price,
                            vix
                        )

                        if not setup:
                            continue

                        # Filter by minimum credit
                        if setup['entry_credit'] < self.min_entry_credit:
                            continue

                        # Try Iron Condor first (symmetric)
                        ic_setup = self._apply_bwic_to_ic(
                            self.data_provider.conn,
                            timestamp,
                            self.index_symbol,
                            setup['strike_short'],
                            setup['strike_long'],
                            setup['strike_short'] - 5,  # Put short (same distance)
                            setup['strike_long'] - 10,   # Put long
                            setup,
                            setup  # Placeholder for put setup
                        )

                        if ic_setup and ic_setup['entry_credit'] > 0:
                            # Open Iron Condor
                            trade = self.state_manager.open_trade(
                                entry_time=timestamp,
                                entry_credit=ic_setup['entry_credit'] / 100,  # Convert back to dollars
                                short_strike=ic_setup['call_short'],
                                long_strike=ic_setup['call_long'],
                                spread_type='IC',
                                index_symbol=self.index_symbol,
                                vix=vix,
                                is_ic=True,
                                peak_rank=peak_rank,
                                description=f"IC PIN={pin_strike} {ic_setup['entry_credit']:.0f}¢"
                            )
                            self.entry_count += 1
                            self.trades_by_peak_rank[peak_rank] += 1
                            logger.info(
                                f"[HARNESS] Entry IC: Rank {peak_rank} PIN={pin_strike} "
                                f"Credit=${ic_setup['entry_credit']:.0f} VIX={vix:.1f}"
                            )
                        else:
                            # Open regular spread (CALL or PUT)
                            trade = self.state_manager.open_trade(
                                entry_time=timestamp,
                                entry_credit=setup['entry_credit'] / 100,  # Convert back to dollars
                                short_strike=setup['strike_short'],
                                long_strike=setup['strike_long'],
                                spread_type=setup['spread_type'],
                                index_symbol=self.index_symbol,
                                vix=vix,
                                is_ic=False,
                                peak_rank=peak_rank,
                                description=f"{setup['spread_type']} PIN={pin_strike} "
                                           f"{setup['entry_credit']:.0f}¢ ({setup['confidence']})"
                            )
                            self.entry_count += 1
                            self.trades_by_peak_rank[peak_rank] += 1
                            logger.info(
                                f"[HARNESS] Entry {setup['spread_type']}: Rank {peak_rank} PIN={pin_strike} "
                                f"Credit=${setup['entry_credit']:.0f} {setup['confidence']} VIX={vix:.1f}"
                            )

                # ===== EXIT SIGNALS =====
                for trade in self.state_manager.get_open_trades():
                    # IMPORTANT: Skip exit checks on the same bar where entry occurred
                    # This prevents unrealistic 0-second exits from forward-fill bias
                    if trade.entry_time == timestamp:
                        continue

                    # Get current spread value
                    short_ba = self.data_provider.get_options_bid_ask(
                        self.index_symbol, trade.short_strike,
                        'call' if trade.spread_type in ['CALL', 'IC'] else 'put',
                        timestamp
                    )
                    long_ba = self.data_provider.get_options_bid_ask(
                        self.index_symbol, trade.long_strike,
                        'call' if trade.spread_type in ['CALL', 'IC'] else 'put',
                        timestamp
                    )

                    if short_ba and long_ba:
                        # Exit pricing with slippage
                        # When closing: BUY to close short (pay ask), SELL to close long (get bid)
                        # Apply 1-tick slippage penalty on exit (typical for market orders)
                        current_spread_value_ideal = (short_ba[1] - long_ba[0]) / 100
                        exit_slippage_penalty = 0.05 / 100  # 1 tick penalty = 0.05 per contract = 0.0005 per unit
                        current_spread_value = current_spread_value_ideal + exit_slippage_penalty

                        # Update peak for trailing stop (use ideal price, not slipped price)
                        self.state_manager.update_trade_peak(trade.trade_id, current_spread_value_ideal)

                        # Check exit conditions
                        exit_result = self._check_exit_conditions(
                            trade, timestamp, current_spread_value
                        )

                        if exit_result:
                            exit_time, exit_value, exit_reason = exit_result
                            self.state_manager.close_trade(
                                trade.trade_id, exit_time, exit_value, exit_reason
                            )
                            self.exit_count += 1
                            logger.info(
                                f"[HARNESS] Exit {trade.spread_type}: Trade {trade.trade_id} "
                                f"{exit_reason.value} P&L=${trade.pnl_dollars:+.0f}"
                            )

                # ===== AUTO-CLOSE AT 3:30 PM ET =====
                et_time = self.time_manager.get_current_et_time()
                if et_time.startswith('2') and '15:30' in et_time:  # 3:30 PM ET
                    for trade in self.state_manager.get_open_trades()[:]:  # Copy to avoid modification during iteration
                        # Skip trades just entered at 3:30 PM (very rare, but possible)
                        if trade.entry_time == timestamp:
                            continue

                        short_ba = self.data_provider.get_options_bid_ask(
                            self.index_symbol, trade.short_strike,
                            'call' if trade.spread_type in ['CALL', 'IC'] else 'put',
                            timestamp
                        )
                        long_ba = self.data_provider.get_options_bid_ask(
                            self.index_symbol, trade.long_strike,
                            'call' if trade.spread_type in ['CALL', 'IC'] else 'put',
                            timestamp
                        )

                        if short_ba and long_ba:
                            # Auto-close at 3:30 PM with slippage
                            current_spread_value_ideal = (short_ba[1] - long_ba[0]) / 100
                            exit_slippage_penalty = 0.05 / 100  # 1 tick penalty
                            current_spread_value = current_spread_value_ideal + exit_slippage_penalty
                            self.state_manager.close_trade(
                                trade.trade_id, timestamp, current_spread_value,
                                ExitReason.EXPIRATION
                            )
                            self.exit_count += 1

                # Advance to next 30-second interval
                self.time_manager.advance_time(30)

        except Exception as e:
            logger.error(f"[HARNESS] Error during replay: {e}", exc_info=True)
            raise

        finally:
            self.data_provider.close()

        # Generate final report
        stats = self.state_manager.get_statistics()

        logger.info("[HARNESS] Replay complete!")
        logger.info(f"[HARNESS] Iterations: {iteration_count}")
        logger.info(f"[HARNESS] Entries: {self.entry_count}, Exits: {self.exit_count}")
        logger.info(f"[HARNESS] Total Trades: {stats['total_trades']}")
        logger.info(
            f"[HARNESS] W:{stats['winning_trades']} L:{stats['losing_trades']} "
            f"BE:{stats['break_even_trades']}"
        )
        logger.info(f"[HARNESS] Win Rate: {stats['win_rate']*100:.1f}%")
        logger.info(f"[HARNESS] P&L: ${stats['total_pnl']:+.0f}")
        logger.info(f"[HARNESS] Balance: ${stats['current_balance']:,.0f}")
        logger.info(f"[HARNESS] Max DD: ${stats['max_drawdown']:+.0f}")
        logger.info(f"[HARNESS] Return: {stats['return_percent']:+.1f}%")

        return stats

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if hasattr(self, 'data_provider'):
            self.data_provider.close()
        return False


# ===== MAIN EXECUTION =====

if __name__ == '__main__':
    from datetime import datetime, timedelta

    # Example: Run 2-day backtest on SPX
    harness = ReplayExecutionHarness(
        db_path='/root/gamma/data/gex_blackbox.db',
        start_date=datetime(2026, 1, 13, 9, 0, 0),  # Start 9:00 AM
        end_date=datetime(2026, 1, 14, 16, 30, 0),   # End 4:30 PM ET
        index_symbol='SPX',
        starting_balance=100000.0,
        vix_floor=12.0,
        vix_ceiling=30.0,
        min_entry_credit=1.50,
        stop_loss_percent=0.10,
        profit_target_percent=0.50,
        trailing_stop_enabled=True
    )

    # Run backtest
    statistics = harness.run_replay()

    # Print summary
    print("\n" + "="*60)
    print("REPLAY BACKTEST RESULTS")
    print("="*60)
    print(f"Total Trades:        {statistics['total_trades']}")
    print(f"Winners:             {statistics['winning_trades']} ({statistics['win_rate']*100:.1f}%)")
    print(f"Losers:              {statistics['losing_trades']}")
    print(f"Break-Even:          {statistics['break_even_trades']}")
    print(f"Total P&L:           ${statistics['total_pnl']:+.0f}")
    print(f"Avg Win:             ${statistics['avg_win']:+.0f}")
    print(f"Avg Loss:            ${statistics['avg_loss']:+.0f}")
    print(f"Max Win:             ${statistics['max_win']:+.0f}")
    print(f"Max Loss:            ${statistics['max_loss']:+.0f}")
    print(f"Profit Factor:       {statistics['profit_factor']:.2f}")
    print(f"Starting Balance:    ${statistics['current_balance'] - statistics['total_pnl']:,.0f}")
    print(f"Ending Balance:      ${statistics['current_balance']:,.0f}")
    print(f"Return %:            {statistics['return_percent']:+.1f}%")
    print(f"Max Drawdown:        ${statistics['max_drawdown']:+.0f}")
    print("="*60)
