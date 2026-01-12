#!/usr/bin/env python3
"""
AGGRESSIVE Market Simulator - Generates realistic losses

This version has aggressively tuned parameters to create losing trades:
- Weak mean reversion (0.02 instead of 0.05)
- Strong persistent breakouts (2-3% drift for 1-2 hours)
- High volatility clustering (up to 5x spikes)
- Entry gap risk (15% of trades)
- Persistent momentum (0.995 decay)

Expected: 55-65% win rate with realistic losses
"""

import sys
sys.path.insert(0, '/root/gamma')

import numpy as np
import random
from datetime import datetime, timedelta
from collections import defaultdict

# Import from original (option pricing, position sizing, etc.)
from backtest_realistic_intraday_enhanced import (
    STARTING_CAPITAL, MAX_CONTRACTS, STOP_LOSS_PER_CONTRACT,
    PROGRESSIVE_TP_SCHEDULE, HOLD_PROFIT_THRESHOLD, HOLD_VIX_MAX,
    HOLD_MIN_TIME_LEFT_HOURS, HOLD_MIN_ENTRY_DISTANCE,
    STOP_LOSS_PCT, SL_GRACE_PERIOD_MIN, SL_EMERGENCY_PCT,
    TRAILING_TRIGGER_PCT, TRAILING_LOCK_IN_PCT, TRAILING_DISTANCE_MIN,
    TRAILING_TIGHTEN_RATE, OptionPriceSimulator, calculate_position_size_kelly
)


class AggressiveMarketSimulator:
    """Ultra-realistic market with frequent adverse conditions."""

    def __init__(self, start_price, gex_pin, vix, trading_hours=6.5):
        self.start_price = start_price
        self.gex_pin = gex_pin
        self.vix = vix
        self.trading_hours = trading_hours
        self.minutes = int(trading_hours * 60)

        # Base volatility
        self.hourly_vol = vix / 100 * start_price / np.sqrt(252 * 6.5)
        self.minute_vol = self.hourly_vol / np.sqrt(60)

        # AGGRESSIVE: Weak mean reversion (price can drift far from pin)
        self.pin_strength = 0.02  # 2% reversion per hour (was 0.05)

        # AGGRESSIVE: High persistence volatility clustering
        self.vol_regime = 1.0
        self.vol_persistence = 0.90  # Slower reversion to normal (was 0.95)

        # AGGRESSIVE: Persistent momentum
        self.momentum = 0.0
        self.momentum_decay = 0.995  # Very slow decay (was 0.98)

        # Breakout state
        self.in_breakout = False
        self.breakout_counter = 0
        self.breakout_direction = 0

    def update_volatility_regime(self):
        """AGGRESSIVE: Bigger vol shocks, higher maximum."""
        # 10% chance of shock (was 5%)
        if random.random() < 0.10:
            # Bigger shocks: -0.5 to +1.5 (was -0.3 to +0.5)
            shock = random.uniform(-0.5, 1.5)
            self.vol_regime += shock

        # Mean revert toward 1.0
        self.vol_regime = (self.vol_persistence * self.vol_regime +
                          (1 - self.vol_persistence) * 1.0)

        # Allow up to 5x volatility spikes (was 2.5x)
        self.vol_regime = max(0.3, min(5.0, self.vol_regime))

    def update_momentum(self):
        """AGGRESSIVE: Persistent momentum with slow decay."""
        # 3% chance of momentum shock (was 2%)
        if random.random() < 0.03:
            shock = random.uniform(-1.0, 1.0)
            self.momentum += shock

        # Very slow decay (0.995 vs 0.98)
        self.momentum *= self.momentum_decay

        # Larger bounds (±3 pts/min instead of ±2)
        self.momentum = max(-3.0, min(3.0, self.momentum))

        return self.momentum

    def check_breakout(self):
        """AGGRESSIVE: More frequent, longer, stronger breakouts."""
        # 2% chance per minute (was 1%)
        if not self.in_breakout and random.random() < 0.02:
            self.in_breakout = True
            self.breakout_direction = random.choice([-1, 1])
            # 1-2 HOURS (was 20-60 minutes)
            self.breakout_counter = random.randint(60, 120)
            # 2-4 points per minute drift (was 1-2)
            self.momentum = self.breakout_direction * random.uniform(2.0, 4.0)

        if self.in_breakout:
            self.breakout_counter -= 1
            if self.breakout_counter <= 0:
                self.in_breakout = False
                self.breakout_direction = 0

    def simulate_day(self):
        """Generate minute-by-minute prices with AGGRESSIVE adverse conditions."""
        prices = [self.start_price]

        for minute in range(1, self.minutes):
            current = prices[-1]

            # Update regimes
            self.update_volatility_regime()
            momentum_drift = self.update_momentum()
            self.check_breakout()

            # Total volatility
            total_vol = self.minute_vol * self.vol_regime

            # Brownian motion
            random_move = np.random.normal(0, total_vol)

            # Mean reversion (disabled during breakout)
            if self.in_breakout:
                reversion = 0.0
            else:
                pin_distance = current - self.gex_pin
                reversion = -pin_distance * (self.pin_strength / 60)

            # Combine forces
            next_price = current + random_move + momentum_drift + reversion

            prices.append(next_price)

        return np.array(prices)


def simulate_trade(entry_time_hour, spx_price, gex_pin, vix, credit, contracts, account_balance):
    """Simulate trade with AGGRESSIVE market and entry gap risk."""

    # AGGRESSIVE: 15% of trades have entry gap (immediate adverse move)
    entry_gap = 0.0
    if random.random() < 0.15:
        entry_gap = random.uniform(-20, 20)  # ±20 SPX points
        spx_price += entry_gap

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

    # AGGRESSIVE market simulator
    hours_remaining = 6.5 - entry_time_hour
    market_sim = AggressiveMarketSimulator(spx_price, gex_pin, vix, hours_remaining)
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
        'minutes_held': minute,
        'entry_gap': entry_gap
    }


def run_backtest(seed=42):
    """Run 1-year backtest with AGGRESSIVE market conditions."""

    print("\n" + "="*80)
    print("AGGRESSIVE BACKTEST - Realistic Losses Expected")
    print("="*80)
    print()
    print("Aggressive Settings:")
    print("  Pin Strength:        0.02 (weak reversion)")
    print("  Breakouts:           2% chance, 60-120 min, 2-4 pts/min")
    print("  Momentum Decay:      0.995 (very persistent)")
    print("  Vol Clustering:      10% chance, 1.5x shocks, 5x max")
    print("  Entry Gap Risk:      15% of trades")
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

            trade_result = simulate_trade(entry_hour, spx_price, gex_pin, vix, credit, contracts, account_balance)

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
                'minutes_held': trade_result['minutes_held'],
                'entry_gap': trade_result['entry_gap']
            }

            all_trades.append(trade_data)
            recent_trades.append(trade_data)
            if len(recent_trades) > ROLLING_WINDOW:
                recent_trades.pop(0)

    # Statistics
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
    gapped_trades = [t for t in all_trades if abs(t['entry_gap']) > 0]

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
    print(f"Win Rate:             {win_rate:.1f}% ✅" if win_rate >= 55 else f"Win Rate:             {win_rate:.1f}% ❌")
    print(f"Profit Factor:        {profit_factor:.2f}")
    print()
    print(f"Winners:              {len(winners)} ({len(winners)/len(all_trades)*100:.1f}%)")
    print(f"Losers:               {len(losers)} ({len(losers)/len(all_trades)*100:.1f}%)")
    print(f"Average Credit:       ${avg_credit:.2f}")
    print(f"Avg Contracts/Trade:  {avg_contracts:.2f}")
    print(f"Avg Win (per contr):  ${avg_win_per_contract:.0f}")
    print(f"Avg Loss (per contr): ${avg_loss_per_contract:.0f}")
    print()
    print(f"Entry Gaps:           {len(gapped_trades)} ({len(gapped_trades)/len(all_trades)*100:.1f}%)")
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
        print("TOP 10 WORST TRADES (LOSSES):")
        print("-"*80)
        sorted_trades = sorted(all_trades, key=lambda x: x['total_profit'])
        for i, t in enumerate(sorted_trades[:min(10, len(losers))], 1):
            gap_str = f" [GAP {t['entry_gap']:+.1f}]" if abs(t['entry_gap']) > 0.1 else ""
            print(f"{i:2d}. Day {t['day']:3d} {t['entry_time']:>5}: ${t['total_profit']:7.0f} ({t['contracts']} × ${t['credit']:.2f}, {t['exit_reason'][:30]}){gap_str}")
        print()

    print("="*80)
    print("BACKTEST COMPLETE")
    print("="*80)
    print()


if __name__ == "__main__":
    run_backtest(seed=42)
