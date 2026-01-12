#!/usr/bin/env python3
"""
Enhanced Market Simulator with Volatility Clustering, Momentum, and Consolidation

This version adds realistic market behaviors on top of basic Brownian motion:
1. Volatility clustering (GARCH-like)
2. Momentum/trend periods
3. Consolidation patterns
4. Intraday volatility curve (U-shaped)
5. Breakout events

Use this to generate more realistic losing trades and market confusion.
"""

import sys
sys.path.insert(0, '/root/gamma')

import numpy as np
import random
from datetime import datetime, timedelta
from collections import defaultdict

# Configuration (same as original)
STARTING_CAPITAL = 20000
MAX_CONTRACTS = 10
STOP_LOSS_PER_CONTRACT = 150

PROGRESSIVE_TP_SCHEDULE = [
    (0.0, 0.50),
    (1.0, 0.55),
    (2.0, 0.60),
    (3.0, 0.70),
    (4.0, 0.80),
]

HOLD_PROFIT_THRESHOLD = 0.80
HOLD_VIX_MAX = 17
HOLD_MIN_TIME_LEFT_HOURS = 1.0
HOLD_MIN_ENTRY_DISTANCE = 8

STOP_LOSS_PCT = 0.10
SL_GRACE_PERIOD_MIN = 3
SL_EMERGENCY_PCT = 0.40

TRAILING_TRIGGER_PCT = 0.20
TRAILING_LOCK_IN_PCT = 0.12
TRAILING_DISTANCE_MIN = 0.08
TRAILING_TIGHTEN_RATE = 0.4


class EnhancedMarketSimulator:
    """Simulates realistic SPX with volatility clustering, momentum, and consolidation."""

    def __init__(self, start_price, gex_pin, vix, trading_hours=6.5,
                 enable_vol_clustering=True,
                 enable_momentum=True,
                 enable_consolidation=True,
                 enable_intraday_pattern=True,
                 enable_breakouts=True):
        """
        Args:
            start_price: Starting SPX price
            gex_pin: GEX pin level
            vix: VIX level
            trading_hours: Hours of trading (default 6.5)
            enable_vol_clustering: Add GARCH-like volatility changes
            enable_momentum: Add trending periods
            enable_consolidation: Add choppy sideways periods
            enable_intraday_pattern: U-shaped volatility (high at open/close)
            enable_breakouts: Sudden directional moves away from pin
        """
        self.start_price = start_price
        self.gex_pin = gex_pin
        self.vix = vix
        self.trading_hours = trading_hours
        self.minutes = int(trading_hours * 60)

        # Feature flags
        self.enable_vol_clustering = enable_vol_clustering
        self.enable_momentum = enable_momentum
        self.enable_consolidation = enable_consolidation
        self.enable_intraday_pattern = enable_intraday_pattern
        self.enable_breakouts = enable_breakouts

        # Base volatility
        self.hourly_vol = vix / 100 * start_price / np.sqrt(252 * 6.5)
        self.minute_vol = self.hourly_vol / np.sqrt(60)

        # Mean reversion
        self.pin_strength = 0.05  # 5% reversion per hour

        # Volatility clustering parameters
        self.vol_regime = 1.0  # Current volatility multiplier (1.0 = normal)
        self.vol_persistence = 0.95  # How quickly vol regime reverts to 1.0

        # Momentum parameters
        self.momentum = 0.0  # Current momentum (drift)
        self.momentum_decay = 0.98  # How quickly momentum decays

        # Consolidation state
        self.in_consolidation = False
        self.consolidation_counter = 0

        # Breakout state
        self.in_breakout = False
        self.breakout_counter = 0
        self.breakout_direction = 0

    def get_intraday_vol_multiplier(self, minute):
        """U-shaped intraday volatility pattern (high at open/close, low mid-day)."""
        if not self.enable_intraday_pattern:
            return 1.0

        # Convert minute to hour (0.0 to 6.5)
        hour = minute / 60.0

        # U-shaped curve: high at open (0h) and close (6.5h), low at midday (3.25h)
        # Use quadratic: f(x) = a(x - 3.25)^2 + b
        # At x=0: multiplier = 1.5 (high)
        # At x=3.25: multiplier = 0.7 (low)
        # At x=6.5: multiplier = 1.5 (high)

        midday = 3.25
        distance_from_midday = abs(hour - midday)
        vol_multiplier = 0.7 + (distance_from_midday / midday) * 0.8

        return vol_multiplier

    def update_volatility_regime(self):
        """GARCH-like volatility clustering (high vol follows high vol)."""
        if not self.enable_vol_clustering:
            return

        # Random shock to volatility regime
        if random.random() < 0.05:  # 5% chance per minute
            shock = random.uniform(-0.3, 0.5)  # Bias toward vol increases
            self.vol_regime += shock

        # Mean revert volatility toward 1.0
        self.vol_regime = self.vol_persistence * self.vol_regime + (1 - self.vol_persistence) * 1.0

        # Keep in reasonable bounds [0.5, 2.5]
        self.vol_regime = max(0.5, min(2.5, self.vol_regime))

    def update_momentum(self, current_price):
        """Add momentum/trend component (price continues moving in same direction)."""
        if not self.enable_momentum:
            return 0.0

        # Random momentum shocks
        if random.random() < 0.02:  # 2% chance per minute
            shock = random.uniform(-0.5, 0.5)
            self.momentum += shock

        # Decay momentum toward zero
        self.momentum *= self.momentum_decay

        # Keep in bounds [-2.0, 2.0] points per minute
        self.momentum = max(-2.0, min(2.0, self.momentum))

        return self.momentum

    def check_consolidation(self, recent_prices):
        """Detect consolidation (price stuck in tight range for extended period)."""
        if not self.enable_consolidation or len(recent_prices) < 30:
            return False

        # Check if price is in tight range over last 30 minutes
        recent_30min = recent_prices[-30:]
        price_range = max(recent_30min) - min(recent_30min)
        avg_price = np.mean(recent_30min)

        # If range < 0.2% of price, enter consolidation
        if price_range / avg_price < 0.002:
            return True
        return False

    def check_breakout(self):
        """Random breakout events (price breaks away from pin with momentum)."""
        if not self.enable_breakouts:
            return

        # Random breakout trigger (1% chance per minute if not already in breakout)
        if not self.in_breakout and random.random() < 0.01:
            self.in_breakout = True
            self.breakout_direction = random.choice([-1, 1])
            self.breakout_counter = random.randint(20, 60)  # 20-60 minutes
            # Add strong momentum in breakout direction
            self.momentum = self.breakout_direction * random.uniform(1.0, 2.0)

        # Count down breakout
        if self.in_breakout:
            self.breakout_counter -= 1
            if self.breakout_counter <= 0:
                self.in_breakout = False
                self.breakout_direction = 0

    def simulate_day(self):
        """Generate minute-by-minute SPX prices with enhanced realism."""
        prices = [self.start_price]

        for minute in range(1, self.minutes):
            current = prices[-1]

            # Update market regimes
            self.update_volatility_regime()
            momentum_drift = self.update_momentum(current)
            self.check_breakout()

            # Check for consolidation
            self.in_consolidation = self.check_consolidation(prices)

            # Intraday volatility pattern
            intraday_vol_mult = self.get_intraday_vol_multiplier(minute)

            # Calculate total volatility for this minute
            total_vol = self.minute_vol * self.vol_regime * intraday_vol_mult

            # Consolidation reduces volatility further
            if self.in_consolidation:
                total_vol *= 0.3  # Very low vol in consolidation

            # Brownian motion (random walk)
            random_move = np.random.normal(0, total_vol)

            # Mean reversion toward GEX pin (disabled during breakout)
            if self.in_breakout:
                reversion = 0.0  # No mean reversion during breakout
            else:
                pin_distance = current - self.gex_pin
                reversion = -pin_distance * (self.pin_strength / 60)

            # Combine all forces
            next_price = current + random_move + momentum_drift + reversion

            prices.append(next_price)

        return np.array(prices)


class OptionPriceSimulator:
    """Estimates option spread prices (same as original, corrected units)."""

    def __init__(self, strikes, is_put, entry_credit):
        self.short_strike = strikes[0]
        self.long_strike = strikes[1]
        self.is_put = is_put
        self.entry_credit = entry_credit
        self.spread_width = abs(strikes[0] - strikes[1]) / 100.0  # Convert to dollars

    def estimate_value(self, underlying_price, minutes_to_expiry):
        """Estimate current spread value."""
        hours_to_expiry = minutes_to_expiry / 60.0

        # Calculate intrinsic value (in DOLLARS)
        if self.is_put:
            short_intrinsic = max(0, self.short_strike - underlying_price) / 100.0
            long_intrinsic = max(0, self.long_strike - underlying_price) / 100.0
        else:
            short_intrinsic = max(0, underlying_price - self.short_strike) / 100.0
            long_intrinsic = max(0, underlying_price - self.long_strike) / 100.0

        spread_intrinsic = short_intrinsic - long_intrinsic
        spread_intrinsic = min(spread_intrinsic, self.spread_width)

        # Time value
        time_value_pct = np.exp(-3 * (6.5 - hours_to_expiry) / 6.5)
        extrinsic_remaining = max(0, self.spread_width - spread_intrinsic)
        time_value = extrinsic_remaining * time_value_pct * (self.entry_credit / self.spread_width)

        spread_value = spread_intrinsic + time_value
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


def simulate_trade(entry_time_hour, spx_price, gex_pin, vix, credit, contracts, account_balance,
                   market_features=None):
    """Simulate a single 0DTE trade with enhanced market simulation."""

    if market_features is None:
        market_features = {
            'vol_clustering': True,
            'momentum': True,
            'consolidation': True,
            'intraday_pattern': True,
            'breakouts': True
        }

    entry_distance = abs(spx_price - gex_pin)
    is_put = (spx_price < gex_pin)

    if is_put:
        short_strike = spx_price - entry_distance
        long_strike = short_strike - 10
        strikes = (short_strike, long_strike)
    else:
        short_strike = spx_price + entry_distance
        long_strike = short_strike + 10
        strikes = (short_strike, long_strike)

    # Create enhanced market simulator
    hours_remaining = 6.5 - entry_time_hour
    market_sim = EnhancedMarketSimulator(
        spx_price, gex_pin, vix, hours_remaining,
        enable_vol_clustering=market_features['vol_clustering'],
        enable_momentum=market_features['momentum'],
        enable_consolidation=market_features['consolidation'],
        enable_intraday_pattern=market_features['intraday_pattern'],
        enable_breakouts=market_features['breakouts']
    )
    minute_prices = market_sim.simulate_day()

    option_sim = OptionPriceSimulator(strikes, is_put, credit)

    best_profit_pct = 0.0
    trailing_active = False
    trailing_stop_level = None
    hold_to_expiry = False

    for minute in range(len(minute_prices)):
        current_price = minute_prices[minute]
        minutes_to_expiry = len(minute_prices) - minute
        hours_elapsed = minute / 60.0

        spread_value = option_sim.estimate_value(current_price, minutes_to_expiry)
        profit_pct = (credit - spread_value) / credit

        if profit_pct > best_profit_pct:
            best_profit_pct = profit_pct

        schedule_times = [t for t, _ in PROGRESSIVE_TP_SCHEDULE]
        schedule_tps = [tp for _, tp in PROGRESSIVE_TP_SCHEDULE]
        progressive_tp_pct = np.interp(hours_elapsed, schedule_times, schedule_tps)

        if profit_pct >= HOLD_PROFIT_THRESHOLD and not hold_to_expiry:
            hours_to_expiry = minutes_to_expiry / 60.0
            if (vix < HOLD_VIX_MAX and
                hours_to_expiry >= HOLD_MIN_TIME_LEFT_HOURS and
                entry_distance >= HOLD_MIN_ENTRY_DISTANCE):
                hold_to_expiry = True

        if not trailing_active and profit_pct >= TRAILING_TRIGGER_PCT:
            trailing_active = True

        if trailing_active:
            profit_above_trigger = best_profit_pct - TRAILING_TRIGGER_PCT
            trail_distance = (TRAILING_TRIGGER_PCT - TRAILING_LOCK_IN_PCT) - (profit_above_trigger * TRAILING_TIGHTEN_RATE)
            trail_distance = max(trail_distance, TRAILING_DISTANCE_MIN)
            trailing_stop_level = best_profit_pct - trail_distance

        # Exit checks
        if minute == len(minute_prices) - 1:
            if hold_to_expiry:
                exit_reason = "Hold-to-Expiry: Worthless"
                final_value = 0.0
            else:
                exit_reason = "0DTE Expiration"
                final_value = spread_value
            break

        if hours_elapsed >= 6.0 and not hold_to_expiry:
            exit_reason = "Auto-close 3:30 PM"
            final_value = spread_value
            break

        if profit_pct >= progressive_tp_pct and not hold_to_expiry:
            exit_reason = f"Profit Target ({progressive_tp_pct*100:.0f}%)"
            final_value = spread_value
            break

        if trailing_active and trailing_stop_level and profit_pct <= trailing_stop_level:
            exit_reason = f"Trailing Stop ({trailing_stop_level*100:.0f}% from peak {best_profit_pct*100:.0f}%)"
            final_value = spread_value
            break

        if profit_pct <= -STOP_LOSS_PCT:
            if profit_pct <= -SL_EMERGENCY_PCT:
                exit_reason = f"EMERGENCY Stop Loss ({profit_pct*100:.0f}%)"
                final_value = spread_value
                break
            elif hours_elapsed >= (SL_GRACE_PERIOD_MIN / 60.0):
                exit_reason = f"Stop Loss ({profit_pct*100:.0f}%)"
                final_value = spread_value
                break

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


def run_backtest(market_features=None, seed=42):
    """Run 1-year backtest with enhanced market simulation."""

    if market_features is None:
        # Default: ALL features enabled
        market_features = {
            'vol_clustering': True,
            'momentum': True,
            'consolidation': True,
            'intraday_pattern': True,
            'breakouts': True
        }

    print("\n" + "="*80)
    print("ENHANCED INTRADAY BACKTEST - SPX 0DTE with Market Realism")
    print("="*80)
    print()
    print("Market Features:")
    print(f"  Volatility Clustering:  {'ENABLED' if market_features['vol_clustering'] else 'DISABLED'}")
    print(f"  Momentum/Trend:         {'ENABLED' if market_features['momentum'] else 'DISABLED'}")
    print(f"  Consolidation Patterns: {'ENABLED' if market_features['consolidation'] else 'DISABLED'}")
    print(f"  Intraday Vol Pattern:   {'ENABLED' if market_features['intraday_pattern'] else 'DISABLED'}")
    print(f"  Breakout Events:        {'ENABLED' if market_features['breakouts'] else 'DISABLED'}")
    print()

    random.seed(seed)
    np.random.seed(seed)

    account_balance = STARTING_CAPITAL
    all_trades = []
    recent_trades = []
    ROLLING_WINDOW = 50

    BOOTSTRAP_WIN_RATE = 0.629
    BOOTSTRAP_AVG_WIN = 30
    BOOTSTRAP_AVG_LOSS = 9

    ENTRY_TIMES = [
        ('9:36', 0.1),
        ('10:00', 0.5),
        ('10:30', 1.0),
        ('11:00', 1.5),
        ('11:30', 2.0),
        ('12:00', 2.5),
        ('12:30', 3.0),
    ]

    num_days = 252
    base_vix = 16.0
    base_price = 6000

    for day_num in range(num_days):
        vix = max(10, min(40, base_vix + random.uniform(-2, 2)))
        base_vix = vix

        spx_price = base_price + random.uniform(-50, 50)
        base_price = spx_price

        gex_pin = spx_price + random.uniform(-10, 10)

        for entry_label, entry_hour in ENTRY_TIMES:
            if random.random() > 0.70:
                continue

            if vix < 15:
                credit = random.uniform(0.20, 0.40)
            elif vix < 22:
                credit = random.uniform(0.35, 0.65)
            elif vix < 30:
                credit = random.uniform(0.55, 0.95)
            else:
                credit = random.uniform(0.80, 1.20)

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

            trade_result = simulate_trade(entry_hour, spx_price, gex_pin, vix, credit, contracts, account_balance, market_features)

            account_balance += trade_result['total_profit']

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

    profit_factor = abs(sum(t['total_profit'] for t in winners) / sum(t['total_profit'] for t in losers)) if losers and sum(t['total_profit'] for t in losers) != 0 else float('inf')

    held_trades = [t for t in all_trades if t['hold_to_expiry']]

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
    print(f"Winners:              {len(winners)}")
    print(f"Losers:               {len(losers)}")
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
    print()
    print("="*80)
    print("EXIT REASON DISTRIBUTION")
    print("="*80)
    for reason, count in sorted(exit_reasons.items(), key=lambda x: x[1], reverse=True):
        pct = count / len(all_trades) * 100
        print(f"  {reason:40s}: {count:3d} ({pct:4.1f}%)")
    print()

    if losers:
        print("="*80)
        print("TOP 10 WORST TRADES:")
        print("-"*80)
        sorted_trades = sorted(all_trades, key=lambda x: x['total_profit'])
        for i, t in enumerate(sorted_trades[:10], 1):
            print(f"{i:2d}. Day {t['day']:3d} {t['entry_time']:>5}: ${t['total_profit']:7.0f} ({t['contracts']} × ${t['credit']:.2f}, {t['exit_reason'][:40]})")
        print()

    print("="*80)
    print("BACKTEST COMPLETE")
    print("="*80)
    print()


if __name__ == "__main__":
    # Test different market feature combinations

    print("\n" + "#"*80)
    print("TEST 1: ALL FEATURES ENABLED (Most Realistic)")
    print("#"*80)
    run_backtest(market_features={
        'vol_clustering': True,
        'momentum': True,
        'consolidation': True,
        'intraday_pattern': True,
        'breakouts': True
    }, seed=42)

    print("\n" + "#"*80)
    print("TEST 2: ONLY BREAKOUTS (Sudden Moves)")
    print("#"*80)
    run_backtest(market_features={
        'vol_clustering': False,
        'momentum': False,
        'consolidation': False,
        'intraday_pattern': False,
        'breakouts': True
    }, seed=42)

    print("\n" + "#"*80)
    print("TEST 3: ONLY VOLATILITY CLUSTERING + MOMENTUM")
    print("#"*80)
    run_backtest(market_features={
        'vol_clustering': True,
        'momentum': True,
        'consolidation': False,
        'intraday_pattern': False,
        'breakouts': False
    }, seed=42)
