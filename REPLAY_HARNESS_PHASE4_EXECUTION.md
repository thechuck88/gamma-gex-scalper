# Replay Harness - Phase 4: Execution Harness Implementation

**Purpose**: Core orchestration logic that ties everything together
**File**: `/root/gamma/replay_execution.py`
**Size**: ~800 lines
**Status**: Ready for implementation (copy-paste template provided)

---

## Overview

The execution harness is the glue that:
1. Instantiates all components (DataProvider, TimeManager, StateManager)
2. Loops through time iterations
3. Invokes entry/exit logic at each step
4. Generates final reports

---

## Complete Source Code Template

```python
#!/usr/bin/env python3
"""
replay_execution.py - Main execution harness for replay backtest

This module orchestrates the entire replay simulation:
- Initializes data providers and state managers
- Advances time through 30-second intervals
- Invokes entry/exit decision logic
- Collects results and statistics

Usage:
    with ReplayExecutionHarness(
        db_path='/gamma-scalper/data/gex_blackbox.db',
        start_date=datetime(2026, 1, 10),
        end_date=datetime(2026, 1, 13),
        index_symbol='SPX'
    ) as harness:
        state = harness.run_replay()
        print(state.get_statistics())
"""

import os
import sys
import uuid
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import pytz

# Import our modules
from replay_data_provider import ReplayDataProvider, LiveDataProvider
from replay_time_manager import ReplayTimeManager
from replay_state import ReplayStateManager, ReplayTrade

# Import live bot strategy logic (single source of truth)
from core.gex_strategy import get_gex_trade_setup


class ReplayExecutionHarness:
    """
    Main harness for replay backtest execution.

    Combines data provider, time manager, and state manager
    into a cohesive replay loop.

    Context manager ensures proper cleanup of resources.
    """

    def __init__(self,
                 db_path: str,
                 start_date: datetime,
                 end_date: datetime,
                 index_symbol: str = 'SPX',
                 dry_run: bool = True,
                 verbose: bool = True):
        """
        Initialize replay harness.

        Args:
            db_path: Path to gex_blackbox.db
            start_date: Start replay from this date (inclusive)
            end_date: End replay at this date (inclusive)
            index_symbol: 'SPX' or 'NDX'
            dry_run: If True, no Tradier API calls are made
            verbose: If True, print detailed logs
        """
        self.db_path = db_path
        self.start_date = start_date
        self.end_date = end_date
        self.index_symbol = index_symbol
        self.dry_run = dry_run
        self.verbose = verbose

        # Initialize components
        self.data_provider = ReplayDataProvider(db_path)
        self.time_manager = ReplayTimeManager(start_date, end_date)
        self.state_manager = ReplayStateManager()

        # Configuration
        self.profit_target_high = 0.50  # 50% for HIGH confidence
        self.profit_target_medium = 0.60  # 60% for MEDIUM confidence
        self.stop_loss_pct = 0.10  # 10% max loss
        self.emergency_stop_pct = 0.40  # 40% emergency stop
        self.vix_threshold = 20.0  # Skip if VIX >= 20

        # Statistics
        self.entries_attempted = 0
        self.entries_successful = 0
        self.entries_skipped = 0
        self.skip_reasons = {}

        print(f"\n{'='*70}")
        print(f"REPLAY HARNESS INITIALIZATION")
        print(f"{'='*70}")
        print(f"Index:               {index_symbol}")
        print(f"Period:              {start_date.date()} to {end_date.date()}")
        print(f"Database:            {db_path}")
        print(f"Mode:                {'DRY RUN (no API calls)' if dry_run else 'NORMAL'}")
        print(f"{'='*70}\n")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, *args):
        """Context manager exit - clean up resources."""
        self.cleanup()

    def cleanup(self):
        """Close database connections."""
        if self.data_provider:
            self.data_provider.close()
        print("\n[HARNESS] Cleanup complete")

    def log(self, msg: str, level: str = 'INFO') -> None:
        """Print timestamped log message."""
        if not self.verbose:
            return

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        prefix = f"[{timestamp}] [{level}]" if level else f"[{timestamp}]"
        print(f"{prefix} {msg}")

    def run_replay(self) -> ReplayStateManager:
        """
        Execute complete replay through all historical snapshots.

        Returns:
            ReplayStateManager with all trade records and statistics
        """
        self.log(f"Starting replay: {self.index_symbol} {self.start_date} to {self.end_date}")

        iteration = 0
        max_iterations = 100000  # Safety limit (about 10 years of data)

        try:
            while self.time_manager.advance() and iteration < max_iterations:
                iteration += 1
                current_time = self.time_manager.get_current_time()

                # Execute main replay logic
                self._execute_iteration(current_time)

                # Periodic progress update
                if iteration % 1000 == 0:
                    self.log(self.time_manager.get_progress())

                # Daily summary at end of day
                if self.time_manager.is_session_change():
                    self._print_daily_summary()

        except KeyboardInterrupt:
            self.log("Replay interrupted by user", 'WARN')
        except Exception as e:
            self.log(f"Error during replay: {e}", 'ERROR')
            import traceback
            traceback.print_exc()

        # Final report
        self._print_final_report(iteration)

        return self.state_manager

    def _execute_iteration(self, current_time: datetime) -> None:
        """
        Execute bot logic for one time snapshot.

        This is where entry and exit logic is invoked.
        """
        # Skip if outside market hours
        if not self.time_manager.is_market_hours():
            return

        # Get current market context
        spx_price = self.data_provider.get_index_price(self.index_symbol, current_time)
        vix = self.data_provider.get_vix(current_time)

        if spx_price is None or vix is None:
            return  # Incomplete data, skip this snapshot

        # === ENTRY LOGIC ===
        # Only check for entries at specific times (bot entry check times)
        if self.time_manager.is_market_open_time():
            self._check_entries(current_time, spx_price, vix)

        # === EXIT LOGIC ===
        # Check exits every iteration (monitor runs every 15 sec live, we check every 30 sec)
        self._check_exits(current_time, spx_price, vix)

    def _check_entries(self, current_time: datetime, spx_price: float, vix: float) -> None:
        """
        Check for entry opportunities at current time.

        Uses live bot's strategy logic to determine trade setup.
        """
        self.entries_attempted += 1

        # Get GEX peak at this time
        gex_peak = self.data_provider.get_gex_peak(self.index_symbol, current_time)

        if not gex_peak:
            skip_reason = "No GEX peak data"
            self._record_skip(skip_reason)
            return

        # Use live bot's strategy logic (single source of truth)
        setup = get_gex_trade_setup(
            pin_price=gex_peak['strike'],
            spx_price=spx_price,
            vix=vix,
            vix_threshold=self.vix_threshold
        )

        # Skip if strategy says no
        if setup.strategy == 'SKIP':
            self._record_skip(setup.description)
            return

        # Calculate entry credit (amount received for selling spread)
        credit = self._calculate_entry_credit(setup, current_time)

        if credit is None or credit <= 0:
            skip_reason = f"Credit calculation failed: {credit}"
            self._record_skip(skip_reason)
            return

        # Record new trade
        trade = ReplayTrade(
            order_id=f"{current_time.timestamp()}_{uuid.uuid4().hex[:8]}",
            timestamp_entry=current_time,
            strategy=setup.strategy,
            direction=setup.direction,
            confidence=setup.confidence,
            strikes=setup.strikes,
            entry_credit=credit,
            entry_value=credit,  # At entry, spread value = credit received
            quantity=1,  # Conservative: 1 spread per trade
            index_symbol=self.index_symbol,
            expiration=self._get_0dte_expiration(current_time)
        )

        self.state_manager.add_trade(trade)
        self.entries_successful += 1

        self.log(
            f"ENTRY: {setup.strategy} @ {current_time} | Pin: {gex_peak['strike']:.0f} | "
            f"SPX: {spx_price:.0f} | Credit: ${credit:.2f} | "
            f"Confidence: {setup.confidence}"
        )

    def _check_exits(self, current_time: datetime, spx_price: float, vix: float) -> None:
        """
        Check exit conditions for all active trades.

        Checks profit target, stop loss, emergency stop, and end-of-day close.
        """
        if not self.state_manager.active_trades:
            return

        # Iterate through copy of active trades dict (we'll modify it during iteration)
        for order_id, trade in list(self.state_manager.active_trades.items()):

            if not trade.position_active:
                continue

            # Get current spread value (mid-price)
            current_value = self._get_current_spread_value(trade, current_time)

            if current_value is None:
                continue

            # Update unrealized P&L
            self.state_manager.update_trade_price(order_id, current_value, current_time)

            # Determine exit reason (first match wins)
            exit_reason = None
            exit_value = current_value

            # 1. Check profit target (primary exit)
            tp_threshold = (self.profit_target_high
                           if trade.confidence == 'HIGH'
                           else self.profit_target_medium)
            pnl_pct = (trade.entry_credit - current_value) / trade.entry_credit

            if pnl_pct >= tp_threshold:
                exit_reason = 'Profit Target'

            # 2. Check emergency stop (highest loss allowed)
            elif current_value >= trade.entry_credit * (1 + self.emergency_stop_pct):
                exit_reason = 'Emergency Stop'

            # 3. Check regular stop loss
            elif current_value >= trade.entry_credit * (1 + self.stop_loss_pct):
                exit_reason = 'Stop Loss'

            # 4. Check end-of-day auto-close (3:30 PM ET for 0DTE)
            elif self.time_manager.is_end_of_day():
                # Only close if < 1 hour to expiration
                et = pytz.timezone('America/New_York')
                et_time = current_time.astimezone(et)
                if et_time.hour >= 15 and et_time.minute >= 30:
                    exit_reason = 'End of Day Auto-Close'

            # Execute exit if reason found
            if exit_reason:
                self.state_manager.close_trade(order_id, exit_value, exit_reason, current_time)
                self.log(
                    f"EXIT: {trade.strategy} {trade.strikes} | {exit_reason} | "
                    f"Entry: ${trade.entry_credit:.2f} | Exit: ${exit_value:.2f} | "
                    f"P&L: ${trade.pnl_dollars:+.2f}"
                )

    def _calculate_entry_credit(self, setup: Dict, timestamp: datetime) -> Optional[float]:
        """
        Calculate credit received for this trade setup at entry time.

        For credit spreads:
        - CALL spread: Sell call spread, collect credit = sell_bid - buy_ask
        - PUT spread: Sell put spread, collect credit = sell_bid - buy_ask
        - Iron Condor: Sell both sides, collect credit = call_credit + put_credit

        Args:
            setup: Trade setup from get_gex_trade_setup()
            timestamp: Entry time

        Returns:
            Credit per contract (use worst prices to be conservative)
        """
        strikes = setup.strikes
        option_type = 'CALL' if setup.strategy == 'CALL' else 'PUT'
        expiration = self._get_0dte_expiration(timestamp)

        # Get bid/ask for all strikes
        prices = self.data_provider.get_strike_prices(
            index_symbol=self.index_symbol,
            strikes=strikes,
            option_type=option_type,
            expiration=expiration,
            timestamp=timestamp
        )

        if not prices:
            return None

        try:
            if setup.strategy == 'IC':
                # Iron Condor: 4 legs
                # Short call spread + short put spread
                call_short = prices[setup.strikes[0]]  # Short call
                call_long = prices[setup.strikes[1]]   # Long call
                put_short = prices[setup.strikes[2]]   # Short put
                put_long = prices[setup.strikes[3]]    # Long put

                # Use worst prices (conservative)
                call_credit = (call_short.get('bid') or 0) - (call_long.get('ask') or 0)
                put_credit = (put_short.get('bid') or 0) - (put_long.get('ask') or 0)

                total_credit = call_credit + put_credit

                if total_credit <= 0:
                    return None

                return total_credit

            else:
                # Directional spread (CALL or PUT): 2 legs
                # Sell short, buy long for protection
                short = prices[setup.strikes[0]]
                long = prices[setup.strikes[1]]

                short_bid = short.get('bid') or 0
                long_ask = long.get('ask') or 0

                credit = short_bid - long_ask

                if credit <= 0:
                    return None

                return credit

        except Exception as e:
            self.log(f"Error calculating entry credit: {e}", 'ERROR')
            return None

    def _get_current_spread_value(self, trade: ReplayTrade,
                                 timestamp: datetime) -> Optional[float]:
        """
        Get current spread value (mark/mid-price) at timestamp.

        For credit spreads, the value is the debit needed to buy back the spread.
        Lower value = more profit (gap between short and long narrows).

        Args:
            trade: The trade to value
            timestamp: Current time

        Returns:
            Spread value (debit to buy back), or None if data unavailable
        """
        prices = self.data_provider.get_strike_prices(
            index_symbol=trade.index_symbol,
            strikes=trade.strikes,
            option_type='CALL' if trade.strategy == 'CALL' else 'PUT',
            expiration=trade.expiration,
            timestamp=timestamp
        )

        if not prices:
            return None

        try:
            if trade.strategy == 'IC':
                # Iron Condor: 4 legs
                call_short_mid = self._get_mid_price(prices.get(trade.strikes[0]))
                call_long_mid = self._get_mid_price(prices.get(trade.strikes[1]))
                put_short_mid = self._get_mid_price(prices.get(trade.strikes[2]))
                put_long_mid = self._get_mid_price(prices.get(trade.strikes[3]))

                if not all([call_short_mid, call_long_mid, put_short_mid, put_long_mid]):
                    return None

                call_spread_value = call_short_mid - call_long_mid
                put_spread_value = put_short_mid - put_long_mid

                total_value = call_spread_value + put_spread_value

                return total_value

            else:
                # Directional spread: 2 legs
                short_mid = self._get_mid_price(prices.get(trade.strikes[0]))
                long_mid = self._get_mid_price(prices.get(trade.strikes[1]))

                if not short_mid or not long_mid:
                    return None

                spread_value = short_mid - long_mid

                return spread_value

        except Exception as e:
            self.log(f"Error valuing spread: {e}", 'ERROR')
            return None

    def _get_mid_price(self, price_data: Optional[Dict]) -> Optional[float]:
        """
        Get mid-price from bid/ask.

        Handles missing data gracefully.
        """
        if not price_data:
            return None

        bid = price_data.get('bid')
        ask = price_data.get('ask')

        if bid is None or ask is None:
            return None

        return (bid + ask) / 2

    def _get_0dte_expiration(self, timestamp: datetime) -> str:
        """Get 0DTE expiration date for timestamp."""
        # Always trade 0DTE (expires same day)
        return timestamp.strftime('%Y-%m-%d')

    def _record_skip(self, reason: str) -> None:
        """Record skip reason for statistics."""
        self.entries_skipped += 1
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1

    def _print_daily_summary(self) -> None:
        """Print daily performance summary."""
        trades_today = [t for t in self.state_manager.closed_trades
                       if t.timestamp_exit and
                       t.timestamp_exit.date() == self.time_manager.get_current_time().date()]

        if not trades_today:
            return

        winners = len([t for t in trades_today if t.pnl_dollars > 0])
        losers = len([t for t in trades_today if t.pnl_dollars < 0])
        pnl = sum(t.pnl_dollars for t in trades_today)

        self.log(
            f"DAILY: {trades_today[0].timestamp_exit.date()} | "
            f"Trades: {len(trades_today)} ({winners}W/{losers}L) | "
            f"P&L: ${pnl:+.2f} | Balance: ${self.state_manager.current_balance:,.2f}",
            'INFO'
        )

    def _print_final_report(self, iterations: int) -> None:
        """Print final backtest report."""
        stats = self.state_manager.get_statistics()

        print(f"\n{'='*70}")
        print(f"REPLAY BACKTEST COMPLETE")
        print(f"{'='*70}")
        print(f"Total Iterations:    {iterations:,}")
        print(f"Total Trades:        {stats['total_trades']}")
        print(f"  Winners:           {stats['winners']} ({stats['win_rate']*100:.1f}%)")
        print(f"  Losers:            {stats['losers']}")
        print(f"  Breakeven:         {stats['breakeven']}")
        print(f"Total P&L:           ${stats['total_pnl']:+,.2f}")
        print(f"Avg Win:             ${stats['avg_win']:,.2f}")
        print(f"Avg Loss:            ${stats['avg_loss']:,.2f}")
        print(f"Max Win:             ${stats['max_win']:,.2f}")
        print(f"Max Loss:            ${stats['max_loss']:,.2f}")
        print(f"Profit Factor:       {stats['profit_factor']:.2f}")
        print(f"Max Drawdown:        ${stats['max_drawdown']:,.2f}")
        print(f"Final Balance:       ${stats['final_balance']:,.2f}")
        print(f"Return on Capital:   {stats['return_pct']:+.1f}%")
        print(f"\nEntry Attempts:      {self.entries_attempted}")
        print(f"Successful Entries:  {self.entries_successful}")
        print(f"Skipped Entries:     {self.entries_skipped}")
        print(f"Entry Success Rate:  {self.entries_successful/self.entries_attempted*100 if self.entries_attempted > 0 else 0:.1f}%")
        print(f"\nTop Skip Reasons:")
        for reason, count in sorted(self.skip_reasons.items(), key=lambda x: x[1], reverse=True)[:5]:
            pct = count / (self.entries_skipped) * 100 if self.entries_skipped > 0 else 0
            print(f"  {reason:40s} {count:5d} ({pct:5.1f}%)")
        print(f"{'='*70}\n")
```

---

## Usage Example

```python
#!/usr/bin/env python3
"""
Main entry point for replay backtest.

Example: python run_replay_backtest.py --index SPX --start 2026-01-10 --end 2026-01-13
"""

import argparse
from datetime import datetime
from replay_execution import ReplayExecutionHarness

def main():
    parser = argparse.ArgumentParser(description='Run replay backtest')
    parser.add_argument('--index', default='SPX', choices=['SPX', 'NDX'],
                       help='Index to trade')
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--db', default='/gamma-scalper/data/gex_blackbox.db',
                       help='Database path')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')

    args = parser.parse_args()

    start_date = datetime.strptime(args.start, '%Y-%m-%d')
    end_date = datetime.strptime(args.end, '%Y-%m-%d')

    with ReplayExecutionHarness(
        db_path=args.db,
        start_date=start_date,
        end_date=end_date,
        index_symbol=args.index,
        verbose=args.verbose
    ) as harness:

        state = harness.run_replay()

        # Export results
        output_file = f"/root/gamma/replay_results_{args.index}_{args.start}_to_{args.end}.json"
        state.export_trades_json(output_file)
        state.print_summary()

        print(f"\nResults exported to: {output_file}")

if __name__ == '__main__':
    main()
```

---

## Testing Strategy

### Step 1: Single Day Test
```bash
python run_replay_backtest.py --index SPX --start 2026-01-10 --end 2026-01-10 --verbose
```

**Expected**:
- 0-5 trades
- Completes in < 10 seconds
- No errors
- P&L reasonable (±$500)

### Step 2: One Week Test
```bash
python run_replay_backtest.py --index SPX --start 2026-01-10 --end 2026-01-17
```

**Expected**:
- 20-50 trades
- Completes in < 30 seconds
- Win rate 55-65%
- P&L $500-$5000

### Step 3: Full Month Test
```bash
python run_replay_backtest.py --index SPX --start 2026-01-01 --end 2026-01-31
```

**Expected**:
- 100-200 trades
- Completes in < 60 seconds
- Win rate 55-65%
- P&L $5000-$50000

### Step 4: Dual Index Test
```bash
python run_replay_backtest.py --index SPX --start 2026-01-10 --end 2026-01-13
python run_replay_backtest.py --index NDX --start 2026-01-10 --end 2026-01-13
```

**Expected**:
- Both should complete independently
- Slightly different P&L (different pin levels)
- Stats similar structure

---

## Validation Checklist

- [ ] Results file contains all trades as JSON
- [ ] Trade count matches expected
- [ ] P&L calculation verified manually on 5 sample trades
- [ ] Win rate in reasonable range (50-70%)
- [ ] No missing prices (check for None values)
- [ ] Timestamps are chronological
- [ ] Database queries complete without errors
- [ ] Memory usage stays < 500MB
- [ ] No floating point precision issues (round to 2 decimals)

---

**This completes Phase 4: Execution Harness**

Next: Phase 5 involves integration testing and validation against manual backtests.

