#!/usr/bin/env python3
"""
Debug version of realistic intraday backtest - shows why account blows up
"""

import sys
sys.path.insert(0, '/root/gamma')

import numpy as np
import random
from datetime import datetime, timedelta

# Same config as original
STARTING_CAPITAL = 20000
MAX_CONTRACTS = 10
STOP_LOSS_PER_CONTRACT = 150

STOP_LOSS_PCT = 0.10
SL_GRACE_PERIOD_MIN = 3
SL_EMERGENCY_PCT = 0.40

PROGRESSIVE_TP_SCHEDULE = [(0.0, 0.50), (1.0, 0.55), (2.0, 0.60), (3.0, 0.70), (4.0, 0.80)]

class IntraDayMarketSimulator:
    """Simulates realistic SPX price movement throughout the day."""

    def __init__(self, start_price, gex_pin, vix, trading_hours=6.5):
        self.start_price = start_price
        self.gex_pin = gex_pin
        self.vix = vix
        self.trading_hours = trading_hours
        self.minutes = int(trading_hours * 60)

        # Brownian motion parameters
        self.hourly_vol = vix / 100 * start_price / np.sqrt(252 * 6.5)
        self.minute_vol = self.hourly_vol / np.sqrt(60)
        self.pin_strength = 0.05

    def simulate_day(self):
        """Generate minute-by-minute SPX prices."""
        prices = [self.start_price]

        for minute in range(1, self.minutes):
            current = prices[-1]
            random_move = np.random.normal(0, self.minute_vol)
            pin_distance = current - self.gex_pin
            reversion = -pin_distance * (self.pin_strength / 60)
            next_price = current + random_move + reversion
            prices.append(next_price)

        return np.array(prices)


class OptionPriceSimulator:
    """Estimates option spread prices."""

    def __init__(self, strikes, is_put, entry_credit):
        self.short_strike = strikes[0]
        self.long_strike = strikes[1]
        self.is_put = is_put
        self.entry_credit = entry_credit
        self.spread_width = abs(strikes[0] - strikes[1])

    def estimate_value(self, underlying_price, minutes_to_expiry):
        """Estimate current spread value."""
        hours_to_expiry = minutes_to_expiry / 60.0

        # Intrinsic value
        if self.is_put:
            short_intrinsic = max(0, self.short_strike - underlying_price)
            long_intrinsic = max(0, self.long_strike - underlying_price)
        else:
            short_intrinsic = max(0, underlying_price - self.short_strike)
            long_intrinsic = max(0, underlying_price - self.long_strike)

        spread_intrinsic = short_intrinsic - long_intrinsic

        # Time value (exponential theta decay)
        time_value_pct = np.exp(-3 * (6.5 - hours_to_expiry) / 6.5)
        extrinsic_max = self.entry_credit - spread_intrinsic
        time_value = extrinsic_max * time_value_pct

        spread_value = spread_intrinsic + max(0, time_value)
        return spread_value


def simulate_trade_debug(entry_time_hour, spx_price, gex_pin, vix, credit, contracts, trade_num):
    """Simulate a single trade with debug output."""

    print(f"\n{'='*80}")
    print(f"TRADE #{trade_num}")
    print(f"Entry: {entry_time_hour:.1f}h, SPX=${spx_price:.2f}, Pin=${gex_pin:.2f}, VIX={vix:.1f}, Credit=${credit:.2f}, Contracts={contracts}")

    entry_distance = abs(spx_price - gex_pin)
    is_put = (spx_price < gex_pin)

    if is_put:
        short_strike = spx_price - entry_distance
        long_strike = short_strike - 10
        strikes = (short_strike, long_strike)
        print(f"PUT Spread: Sell ${short_strike:.0f}P / Buy ${long_strike:.0f}P (SPX below pin)")
    else:
        short_strike = spx_price + entry_distance
        long_strike = short_strike + 10
        strikes = (short_strike, long_strike)
        print(f"CALL Spread: Sell ${short_strike:.0f}C / Buy ${long_strike:.0f}C (SPX above pin)")

    hours_remaining = 6.5 - entry_time_hour
    market_sim = IntraDayMarketSimulator(spx_price, gex_pin, vix, hours_remaining)
    minute_prices = market_sim.simulate_day()

    option_sim = OptionPriceSimulator(strikes, is_put, credit)

    best_profit_pct = 0.0

    # Sample every 15 minutes for debug
    sample_minutes = list(range(0, len(minute_prices), 15))
    if len(minute_prices) - 1 not in sample_minutes:
        sample_minutes.append(len(minute_prices) - 1)

    print(f"\n{'Min':>4} {'SPX':>8} {'Value':>7} {'P/L%':>7} {'TP%':>6} {'Status':>20}")
    print(f"{'-'*4} {'-'*8} {'-'*7} {'-'*7} {'-'*6} {'-'*20}")

    exit_reason = None
    exit_minute = None
    final_value = None

    for minute in range(len(minute_prices)):
        current_price = minute_prices[minute]
        minutes_to_expiry = len(minute_prices) - minute
        hours_elapsed = minute / 60.0

        spread_value = option_sim.estimate_value(current_price, minutes_to_expiry)
        profit_pct = (credit - spread_value) / credit

        if profit_pct > best_profit_pct:
            best_profit_pct = profit_pct

        # Progressive TP
        schedule_times = [t for t, _ in PROGRESSIVE_TP_SCHEDULE]
        schedule_tps = [tp for _, tp in PROGRESSIVE_TP_SCHEDULE]
        progressive_tp_pct = np.interp(hours_elapsed, schedule_times, schedule_tps)

        # Debug output at sample points
        if minute in sample_minutes:
            status = ""
            if minute == 0:
                status = "ENTRY"
            elif minute == len(minute_prices) - 1:
                status = "EXPIRATION"
            print(f"{minute:>4} ${current_price:>7.2f} ${spread_value:>6.2f} {profit_pct*100:>6.1f}% {progressive_tp_pct*100:>5.0f}% {status:>20}")

        # Exit checks
        if minute == len(minute_prices) - 1:
            exit_reason = "0DTE Expiration"
            final_value = spread_value
            exit_minute = minute
            break

        if hours_elapsed >= 6.0:
            exit_reason = "Auto-close 3:30 PM"
            final_value = spread_value
            exit_minute = minute
            break

        if profit_pct >= progressive_tp_pct:
            exit_reason = f"Profit Target ({progressive_tp_pct*100:.0f}%)"
            final_value = spread_value
            exit_minute = minute
            break

        if profit_pct <= -STOP_LOSS_PCT:
            if profit_pct <= -SL_EMERGENCY_PCT:
                exit_reason = f"EMERGENCY Stop Loss ({profit_pct*100:.0f}%)"
                final_value = spread_value
                exit_minute = minute
                break
            elif hours_elapsed >= (SL_GRACE_PERIOD_MIN / 60.0):
                exit_reason = f"Stop Loss ({profit_pct*100:.0f}%)"
                final_value = spread_value
                exit_minute = minute
                break

    # Calculate final P/L
    profit_per_contract = (credit - final_value) * 100
    total_profit = profit_per_contract * contracts

    print(f"\nEXIT: {exit_reason} at minute {exit_minute} ({exit_minute/60:.1f}h)")
    print(f"Final Value: ${final_value:.2f} (entry ${credit:.2f})")
    print(f"P/L: ${profit_per_contract:+.2f} per contract × {contracts} = ${total_profit:+.2f} TOTAL")
    print(f"Best Profit: {best_profit_pct*100:+.1f}%")

    return {
        'credit': credit,
        'contracts': contracts,
        'exit_reason': exit_reason,
        'profit_per_contract': profit_per_contract,
        'total_profit': total_profit,
        'final_value': final_value,
        'exit_minute': exit_minute,
        'best_profit_pct': best_profit_pct,
        'spread_intrinsic_at_exit': spread_value,
    }


def run_debug_backtest():
    """Run first 10 trades to see what's happening."""

    print("\n" + "="*80)
    print("DEBUG INTRADAY BACKTEST - First 10 Trades Analysis")
    print("="*80)

    random.seed(42)
    np.random.seed(42)

    account_balance = STARTING_CAPITAL
    trade_count = 0
    max_trades = 10

    base_vix = 16.0
    base_price = 6000

    ENTRY_TIMES = [('9:36', 0.1), ('10:00', 0.5), ('10:30', 1.0), ('11:00', 1.5)]

    for day_num in range(20):  # Up to 20 days to get 10 trades
        vix = max(10, min(40, base_vix + random.uniform(-2, 2)))
        base_vix = vix

        spx_price = base_price + random.uniform(-50, 50)
        base_price = spx_price
        gex_pin = spx_price + random.uniform(-10, 10)

        for entry_label, entry_hour in ENTRY_TIMES:
            if random.random() > 0.70:
                continue

            # Get credit
            if vix < 15:
                credit = random.uniform(0.20, 0.40)
            elif vix < 22:
                credit = random.uniform(0.35, 0.65)
            else:
                credit = random.uniform(0.55, 0.95)

            # Fixed 1 contract for debugging
            contracts = 1

            trade_count += 1

            print(f"\n{'#'*80}")
            print(f"DAY {day_num+1} | ACCOUNT BALANCE: ${account_balance:,.2f}")
            print(f"{'#'*80}")

            result = simulate_trade_debug(entry_hour, spx_price, gex_pin, vix, credit, contracts, trade_count)

            account_balance += result['total_profit']

            print(f"\nACCOUNT AFTER TRADE: ${account_balance:,.2f} (change: ${result['total_profit']:+.2f})")

            if trade_count >= max_trades:
                break

        if trade_count >= max_trades:
            break

    print(f"\n{'='*80}")
    print(f"SUMMARY AFTER {trade_count} TRADES")
    print(f"{'='*80}")
    print(f"Starting: ${STARTING_CAPITAL:,.2f}")
    print(f"Ending:   ${account_balance:,.2f}")
    print(f"P/L:      ${account_balance - STARTING_CAPITAL:+,.2f}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    run_debug_backtest()
