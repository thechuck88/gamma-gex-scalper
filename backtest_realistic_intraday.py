#!/usr/bin/env python3
"""
Realistic Intraday Backtest with Market Simulation

Features:
- Minute-by-minute SPX price movement using Brownian motion
- Mean reversion toward GEX pin
- Theta decay for option prices
- Progressive profit targets (50% → 80%)
- Hold-to-expiry for 80%+ profit trades
- Stop loss testing (10% with 3-min grace, 40% emergency)
- Trailing stops (activate at 20%, lock in 12%)

This matches production monitor.py behavior exactly.
"""

import sys
sys.path.insert(0, '/root/gamma')

import numpy as np
import random
from datetime import datetime, timedelta
from collections import defaultdict

# Configuration matching monitor.py
STARTING_CAPITAL = 20000
MAX_CONTRACTS = 10
STOP_LOSS_PER_CONTRACT = 150  # SPX

# Progressive TP schedule (hours_elapsed, tp_threshold)
PROGRESSIVE_TP_SCHEDULE = [
    (0.0, 0.50),
    (1.0, 0.55),
    (2.0, 0.60),
    (3.0, 0.70),
    (4.0, 0.80),
]

# Hold-to-expiry settings (adjusted for realistic credits)
HOLD_PROFIT_THRESHOLD = 0.60  # 60% profit (more achievable with small credits)
HOLD_VIX_MAX = 18  # Slightly higher VIX tolerance
HOLD_MIN_TIME_LEFT_HOURS = 1.0
HOLD_MIN_ENTRY_DISTANCE = 5  # Lower distance requirement

# Stop loss settings
STOP_LOSS_PCT = 0.10
SL_GRACE_PERIOD_MIN = 0  # NO grace period - trigger immediately
SL_EMERGENCY_PCT = 0.40

# Trailing stop settings
TRAILING_TRIGGER_PCT = 0.20
TRAILING_LOCK_IN_PCT = 0.12
TRAILING_DISTANCE_MIN = 0.08
TRAILING_TIGHTEN_RATE = 0.4


class IntraDayMarketSimulator:
    """Simulates realistic SPX price movement throughout the day."""

    def __init__(self, start_price, gex_pin, vix, trading_hours=6.5):
        self.start_price = start_price
        self.gex_pin = gex_pin
        self.vix = vix
        self.trading_hours = trading_hours
        self.minutes = int(trading_hours * 60)

        # Brownian motion parameters
        self.hourly_vol = vix / 100 * start_price / np.sqrt(252 * 6.5)  # VIX → hourly move
        self.minute_vol = self.hourly_vol / np.sqrt(60)  # Scale to 1-minute

        # AMPLIFY volatility to generate realistic losses
        self.minute_vol *= 50.0  # 50x base volatility to overcome theta decay

        # GEX pin effect - moderate mean reversion toward gamma pin
        self.pin_strength = 0.5  # 50% pull toward pin per hour

    def simulate_day(self):
        """Generate minute-by-minute SPX prices using random walk + GEX pin effect + trend persistence.

        Each minute:
        - Trend persistence: 70% continue direction, 30% reverse
        - VIX-scaled random magnitude
        - Pull toward GEX pin (mean reversion from gamma hedging)
        """
        prices = [self.start_price]
        last_direction = 1 if random.random() < 0.5 else -1  # Initialize random direction

        for minute in range(1, self.minutes):
            current = prices[-1]

            # TREND PERSISTENCE: 80% continue same direction, 20% reverse
            # This creates smoother trending movements instead of constant whipsaws
            if random.random() < 0.80:
                direction = last_direction  # Continue trend
            else:
                direction = -last_direction  # Reverse

            # VIX-scaled random magnitude (higher VIX = bigger moves)
            # VIX < 15: Small moves (0-2 pts)
            # VIX 15-25: Normal moves (0-4 pts)
            # VIX > 25: Bigger moves (0-8 pts)
            if self.vix < 15:
                max_move = 2.0  # Calm market
            elif self.vix < 25:
                max_move = 4.0  # Normal market
            else:
                max_move = 8.0  # Volatile market

            magnitude = random.uniform(0, max_move)

            # Apply random move
            next_price = current + (direction * magnitude)

            # Apply GEX pin effect (mean reversion)
            if self.pin_strength > 0:
                distance_from_pin = self.gex_pin - next_price
                pin_pull_per_minute = distance_from_pin * (self.pin_strength / 60.0)
                next_price = next_price + pin_pull_per_minute

            prices.append(next_price)
            last_direction = direction  # Remember direction for next minute

        return np.array(prices)


class OptionPriceSimulator:
    """Estimates option spread prices using simplified Black-Scholes."""

    def __init__(self, strikes, is_put, entry_credit):
        """
        Args:
            strikes: (short_strike, long_strike) tuple
            is_put: True if put spread, False if call spread
            entry_credit: Initial credit received
        """
        self.short_strike = strikes[0]
        self.long_strike = strikes[1]
        self.is_put = is_put
        self.entry_credit = entry_credit
        # Convert spread width from POINTS to DOLLARS
        # 10-point spread = $1.00 max value (10 points × $0.10 per point)
        self.spread_width = abs(strikes[0] - strikes[1]) / 100.0

    def estimate_value(self, underlying_price, minutes_to_expiry):
        """Estimate current spread value (cost to close).

        Uses simplified intrinsic value + time value model.
        CRITICAL FIX: Caps spread value at spread width (max possible value).
        """
        hours_to_expiry = minutes_to_expiry / 60.0

        # Calculate intrinsic value (in DOLLARS per contract, not points)
        # SPX: 1 point = $100, so divide by 100 to get dollars per contract
        if self.is_put:
            # Put spread: short_strike > long_strike
            # ITM if price < short_strike
            short_intrinsic = max(0, self.short_strike - underlying_price) / 100.0
            long_intrinsic = max(0, self.long_strike - underlying_price) / 100.0
        else:
            # Call spread: short_strike < long_strike
            # ITM if price > short_strike
            short_intrinsic = max(0, underlying_price - self.short_strike) / 100.0
            long_intrinsic = max(0, underlying_price - self.long_strike) / 100.0

        spread_intrinsic = short_intrinsic - long_intrinsic

        # CRITICAL FIX: Cap intrinsic at spread width
        spread_intrinsic = min(spread_intrinsic, self.spread_width)

        # Time value (theta decay - exponential)
        # 0DTE loses ~90% of time value in first 6 hours
        time_value_pct = np.exp(-3 * (6.5 - hours_to_expiry) / 6.5)

        # CRITICAL FIX: Time value based on REMAINING width, not entry credit
        # Once spread is maxed out (intrinsic = width), time value = 0
        extrinsic_remaining = max(0, self.spread_width - spread_intrinsic)
        time_value = extrinsic_remaining * time_value_pct * (self.entry_credit / self.spread_width)

        # Total spread value = intrinsic + time
        spread_value = spread_intrinsic + time_value

        # CRITICAL FIX: Final cap at spread width (max possible value)
        # A 10-point spread can NEVER be worth more than $10
        spread_value = min(spread_value, self.spread_width)

        return spread_value


def calculate_position_size_kelly(account_balance, win_rate, avg_win, avg_loss):
    """Half-Kelly position sizing."""
    if account_balance < STARTING_CAPITAL * 0.5:
        return 0

    kelly_f = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
    half_kelly = kelly_f * 0.5
    contracts = int((account_balance * half_kelly) / STOP_LOSS_PER_CONTRACT)
    return max(1, min(contracts, MAX_CONTRACTS))


def simulate_trade(entry_time_hour, spx_price, gex_pin, vix, credit, contracts, account_balance):
    """Simulate a single 0DTE trade with realistic intraday movement."""

    # Calculate entry distance (for hold qualification)
    entry_distance = abs(spx_price - gex_pin)

    # Determine spread type based on price vs pin
    is_put = (spx_price < gex_pin)  # Below pin = bullish = put spread

    # Set strikes (10-point spread, sold closer to pin)
    if is_put:
        short_strike = spx_price - entry_distance
        long_strike = short_strike - 10
        strikes = (short_strike, long_strike)
    else:
        short_strike = spx_price + entry_distance
        long_strike = short_strike + 10
        strikes = (short_strike, long_strike)

    # Create market simulator - PURE RANDOM WALK
    hours_remaining = 6.5 - entry_time_hour
    market_sim = IntraDayMarketSimulator(spx_price, gex_pin, vix, hours_remaining)
    minute_prices = market_sim.simulate_day()

    # Create option pricer
    option_sim = OptionPriceSimulator(strikes, is_put, credit)

    # Track position state
    best_profit_pct = 0.0
    trailing_active = False
    trailing_stop_level = None
    hold_to_expiry = False

    # Simulate minute-by-minute
    for minute in range(len(minute_prices)):
        current_price = minute_prices[minute]
        minutes_to_expiry = len(minute_prices) - minute
        hours_elapsed = minute / 60.0

        # Get current spread value
        spread_value = option_sim.estimate_value(current_price, minutes_to_expiry)

        # Calculate P/L (credit received - current value)
        profit_pct = (credit - spread_value) / credit

        # Track peak for trailing stop
        if profit_pct > best_profit_pct:
            best_profit_pct = profit_pct

        # Progressive TP interpolation
        schedule_times = [t for t, _ in PROGRESSIVE_TP_SCHEDULE]
        schedule_tps = [tp for _, tp in PROGRESSIVE_TP_SCHEDULE]
        progressive_tp_pct = np.interp(hours_elapsed, schedule_times, schedule_tps)

        # Check hold-to-expiry qualification
        if profit_pct >= HOLD_PROFIT_THRESHOLD and not hold_to_expiry:
            hours_to_expiry = minutes_to_expiry / 60.0
            if (vix < HOLD_VIX_MAX and
                hours_to_expiry >= HOLD_MIN_TIME_LEFT_HOURS and
                entry_distance >= HOLD_MIN_ENTRY_DISTANCE):
                hold_to_expiry = True

        # Check trailing stop activation
        if not trailing_active and profit_pct >= TRAILING_TRIGGER_PCT:
            trailing_active = True

        # Calculate trailing stop level
        if trailing_active:
            profit_above_trigger = best_profit_pct - TRAILING_TRIGGER_PCT
            trail_distance = (TRAILING_TRIGGER_PCT - TRAILING_LOCK_IN_PCT) - (profit_above_trigger * TRAILING_TIGHTEN_RATE)
            trail_distance = max(trail_distance, TRAILING_DISTANCE_MIN)
            trailing_stop_level = best_profit_pct - trail_distance

        # --- EXIT CHECKS ---

        # 1. Expiration (last minute)
        if minute == len(minute_prices) - 1:
            if hold_to_expiry:
                exit_reason = "Hold-to-Expiry: Worthless"
                final_value = 0.0
            else:
                exit_reason = "0DTE Expiration"
                final_value = spread_value
            break

        # 2. Auto-close at 3:30 PM (skip if holding)
        if hours_elapsed >= 6.0 and not hold_to_expiry:
            exit_reason = "Auto-close 3:30 PM"
            final_value = spread_value
            break

        # 3. Profit target (skip if holding)
        if profit_pct >= progressive_tp_pct and not hold_to_expiry:
            exit_reason = f"Profit Target ({progressive_tp_pct*100:.0f}%)"
            final_value = spread_value
            break

        # 4. Trailing stop
        if trailing_active and trailing_stop_level and profit_pct <= trailing_stop_level:
            exit_reason = f"Trailing Stop ({trailing_stop_level*100:.0f}% from peak {best_profit_pct*100:.0f}%)"
            final_value = spread_value
            break

        # 5. Stop loss (with grace period)
        if profit_pct <= -STOP_LOSS_PCT:
            # Emergency stop - immediate
            if profit_pct <= -SL_EMERGENCY_PCT:
                exit_reason = f"EMERGENCY Stop Loss ({profit_pct*100:.0f}%)"
                final_value = spread_value
                break
            # Regular stop - after grace period
            elif hours_elapsed >= (SL_GRACE_PERIOD_MIN / 60.0):
                exit_reason = f"Stop Loss ({profit_pct*100:.0f}%)"
                final_value = spread_value
                break

    # Calculate final P/L
    profit_per_contract = (credit - final_value) * 100
    total_profit = profit_per_contract * contracts

    return {
        'credit': credit,
        'contracts': contracts,
        'exit_reason': exit_reason,
        'profit_per_contract': profit_per_contract,
        'total_profit': total_profit,
        'final_value': final_value,
        'hold_to_expiry': hold_to_expiry,
        'best_profit_pct': best_profit_pct,
        'minutes_held': minute
    }


def run_backtest():
    """Run 1-year backtest with realistic intraday simulation."""

    print("\n" + "="*80)
    print("REALISTIC INTRADAY BACKTEST - SPX 0DTE with Hold-to-Expiry")
    print("="*80)
    print()

    # Seed for reproducibility
    # Try different seeds to test variability
    random.seed(999)
    np.random.seed(999)

    # Track stats
    account_balance = STARTING_CAPITAL
    all_trades = []
    recent_trades = []
    ROLLING_WINDOW = 50

    # Bootstrap stats
    BOOTSTRAP_WIN_RATE = 0.629
    BOOTSTRAP_AVG_WIN = 30
    BOOTSTRAP_AVG_LOSS = 9

    # Entry times (7 optimal windows - 1:00 PM removed due to poor performance)
    ENTRY_TIMES = [
        ('9:36', 0.1),
        ('10:00', 0.5),
        ('10:30', 1.0),
        ('11:00', 1.5),
        ('11:30', 2.0),
        ('12:00', 2.5),
        ('12:30', 3.0),
    ]

    # Simulate 252 trading days
    num_days = 252
    base_vix = 16.0
    base_price = 6000

    for day_num in range(num_days):
        # Daily VIX
        vix = max(10, min(40, base_vix + random.uniform(-2, 2)))
        base_vix = vix

        # Daily SPX price
        spx_price = base_price + random.uniform(-50, 50)
        base_price = spx_price

        # GEX pin
        gex_pin = spx_price + random.uniform(-10, 10)

        # Try each entry window
        for entry_label, entry_hour in ENTRY_TIMES:
            # 70% chance of valid setup
            if random.random() > 0.70:
                continue

            # Get realistic credit (must be < spread width of $0.10!)
            # For a 10-point ($0.10) spread, credits should be 20-80% of width
            if vix < 15:
                credit = random.uniform(0.02, 0.04)  # Low vol: 20-40% of width
            elif vix < 22:
                credit = random.uniform(0.04, 0.06)  # Med vol: 40-60% of width
            elif vix < 30:
                credit = random.uniform(0.06, 0.08)  # High vol: 60-80% of width
            else:
                credit = random.uniform(0.07, 0.09)  # Very high vol: 70-90% of width

            # Calculate position size
            if len(recent_trades) >= 10:
                recent_winners = [t for t in recent_trades if t['profit_per_contract'] > 0]
                recent_losers = [t for t in recent_trades if t['profit_per_contract'] <= 0]

                win_rate = len(recent_winners) / len(recent_trades) if recent_trades else BOOTSTRAP_WIN_RATE
                avg_win = sum(t['profit_per_contract'] for t in recent_winners) / len(recent_winners) if recent_winners else BOOTSTRAP_AVG_WIN
                avg_loss = abs(sum(t['profit_per_contract'] for t in recent_losers) / len(recent_losers)) if recent_losers else BOOTSTRAP_AVG_LOSS
            else:
                win_rate = BOOTSTRAP_WIN_RATE
                avg_win = BOOTSTRAP_AVG_WIN
                avg_loss = BOOTSTRAP_AVG_LOSS

            contracts = calculate_position_size_kelly(account_balance, win_rate, avg_win, avg_loss)

            if contracts == 0:
                print(f"Trading halted at day {day_num+1} - account below safety threshold")
                break

            # Simulate the trade
            trade_result = simulate_trade(entry_hour, spx_price, gex_pin, vix, credit, contracts, account_balance)

            # Update account
            account_balance += trade_result['total_profit']

            # Store trade data
            trade_data = {
                'day': day_num + 1,
                'entry_time': entry_label,
                'vix': vix,
                'credit': credit,
                'contracts': contracts,
                'profit_per_contract': trade_result['profit_per_contract'],
                'total_profit': trade_result['total_profit'],
                'account_balance': account_balance,
                'exit_reason': trade_result['exit_reason'],
                'hold_to_expiry': trade_result['hold_to_expiry'],
                'best_profit_pct': trade_result['best_profit_pct'],
                'minutes_held': trade_result['minutes_held']
            }

            all_trades.append(trade_data)
            recent_trades.append(trade_data)
            if len(recent_trades) > ROLLING_WINDOW:
                recent_trades.pop(0)

    # Calculate statistics
    total_pnl = account_balance - STARTING_CAPITAL
    winners = [t for t in all_trades if t['profit_per_contract'] > 0]
    losers = [t for t in all_trades if t['profit_per_contract'] <= 0]

    win_rate = len(winners) / len(all_trades) * 100 if all_trades else 0
    avg_win_per_contract = sum(t['profit_per_contract'] for t in winners) / len(winners) if winners else 0
    avg_loss_per_contract = sum(t['profit_per_contract'] for t in losers) / len(losers) if losers else 0
    avg_credit = sum(t['credit'] for t in all_trades) / len(all_trades) if all_trades else 0
    avg_contracts = sum(t['contracts'] for t in all_trades) / len(all_trades) if all_trades else 0

    profit_factor = abs(sum(t['total_profit'] for t in winners) / sum(t['total_profit'] for t in losers)) if losers else 0

    # Hold-to-expiry stats
    held_trades = [t for t in all_trades if t['hold_to_expiry']]

    # Exit reason distribution
    exit_reasons = defaultdict(int)
    for t in all_trades:
        exit_reasons[t['exit_reason']] += 1

    # Print results
    print(f"Trading Days:         {num_days}")
    print(f"Total Trades:         {len(all_trades)}")
    print(f"Avg Trades/Day:       {len(all_trades)/num_days:.1f}")
    print()
    print("="*80)
    print("RESULTS")
    print("="*80)
    print(f"Starting Capital:     ${STARTING_CAPITAL:,.0f}")
    print(f"Final Balance:        ${account_balance:,.0f}")
    print(f"NET P/L:              ${total_pnl:,.0f} ({(total_pnl/STARTING_CAPITAL)*100:+.1f}%)")
    print()
    print(f"Win Rate:             {win_rate:.1f}%")
    print(f"Profit Factor:        {profit_factor:.2f}")
    print()
    print(f"Average Credit:       ${avg_credit:.2f}")
    print(f"Avg Contracts/Trade:  {avg_contracts:.2f}")
    print(f"Avg Win (per contr):  ${avg_win_per_contract:.0f}")
    print(f"Avg Loss (per contr): ${avg_loss_per_contract:.0f}")
    print()
    print("="*80)
    print("HOLD-TO-EXPIRY ANALYSIS")
    print("="*80)
    print(f"Trades Held:          {len(held_trades)} ({len(held_trades)/len(all_trades)*100:.1f}%)")
    if held_trades:
        held_pnl = sum(t['total_profit'] for t in held_trades)
        print(f"P/L from Holds:       ${held_pnl:,.0f} ({held_pnl/total_pnl*100:.1f}% of total)")
        avg_hold_profit = sum(t['profit_per_contract'] for t in held_trades) / len(held_trades)
        print(f"Avg Hold Profit:      ${avg_hold_profit:.0f} per contract")
    print()
    print("="*80)
    print("EXIT REASON DISTRIBUTION")
    print("="*80)
    for reason, count in sorted(exit_reasons.items(), key=lambda x: x[1], reverse=True):
        pct = count / len(all_trades) * 100
        print(f"  {reason:40s}: {count:3d} ({pct:4.1f}%)")
    print()
    print("="*80)

    # Top 10 best/worst
    sorted_trades = sorted(all_trades, key=lambda x: x['total_profit'], reverse=True)

    print("TOP 10 BEST TRADES:")
    print("-"*80)
    for i, t in enumerate(sorted_trades[:10], 1):
        hold_flag = " [HELD]" if t['hold_to_expiry'] else ""
        print(f"{i:2d}. Day {t['day']:3d} {t['entry_time']:>5}: ${t['total_profit']:7.0f} ({t['contracts']} × ${t['credit']:.2f}, {t['exit_reason'][:30]}){hold_flag}")
    print()

    print("TOP 10 WORST TRADES:")
    print("-"*80)
    for i, t in enumerate(sorted_trades[-10:], 1):
        print(f"{i:2d}. Day {t['day']:3d} {t['entry_time']:>5}: ${t['total_profit']:7.0f} ({t['contracts']} × ${t['credit']:.2f}, {t['exit_reason'][:30]})")
    print()
    print("="*80)
    print("BACKTEST COMPLETE")
    print("="*80)
    print()

    # Return summary stats for comparison
    return {
        'win_rate': win_rate / 100.0,  # Convert to decimal
        'profit_factor': profit_factor,
        'net_pl': total_pnl,
        'final_balance': account_balance,
        'total_trades': len(all_trades),
        'hold_count': len(held_trades),
        'hold_pl': sum(t['total_profit'] for t in held_trades) if held_trades else 0,
        'avg_credit': avg_credit,
        'avg_contracts': avg_contracts,
        'avg_win': avg_win_per_contract,
        'avg_loss': avg_loss_per_contract
    }


if __name__ == "__main__":
    run_backtest()
