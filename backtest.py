#!/usr/bin/env python3
"""
gex_backtest.py — 6-Month GEX Scalper Backtest (Dec 2025)

Simulates the GEX scalper strategy over historical data.

Uses shared module: core.gex_strategy (single source of truth)
This ensures backtest and live scalper use IDENTICAL trade setup logic.

Assumptions/Approximations:
  - GEX Pin: Uses previous close rounded to nearest 25 (simplified proxy)
  - Entry Credit: Estimated from VIX using empirical formula
  - Entry Time: Assumes entry at 10:00 AM ET (SPX open + 30 min)
  - Exit: TP/SL or market close at 3:50 PM
  - SPX Close: Used to determine if spread expired ITM/OTM

Usage:
  python gex_backtest.py              # Run backtest
  python gex_backtest.py --days 180   # Custom lookback period

Author: Claude + Human collaboration
"""

import datetime
import argparse
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm

# Import shared GEX strategy logic (single source of truth)
from core.gex_strategy import get_gex_trade_setup as core_get_gex_trade_setup
from core.gex_strategy import round_to_5, get_spread_width

# ============================================================================
#                           STRATEGY PARAMETERS
# ============================================================================

# From gex_scalper.py settings
PROFIT_TARGET_HIGH = 0.50      # 50% profit for HIGH confidence
PROFIT_TARGET_MEDIUM = 0.70    # 70% profit for MEDIUM confidence
STOP_LOSS_PCT = 0.10           # 10% stop loss (spread increases 10%)
VIX_MAX_THRESHOLD = 20         # Skip trading if VIX >= 20

# Trailing stop settings (from gex_monitor.py)
TRAILING_STOP_ENABLED = True
TRAILING_TRIGGER_PCT = 0.25     # Activate at 25% profit
TRAILING_LOCK_IN_PCT = 0.10     # Lock in 10% profit when triggered
TRAILING_DISTANCE_MIN = 0.08    # Minimum trail distance (8%)
TRAILING_TIGHTEN_RATE = 0.4     # Tighten rate

# Entry times (hours after market open: 9:36, 10:00, 11:00, 12:00, 13:00)
ENTRY_TIMES = [0.1, 0.5, 1.5, 2.5, 3.5]  # Hours after 9:30 open

# 2025 FOMC meeting dates (announcement days)
FOMC_DATES_2025 = [
    '2025-01-29', '2025-03-19', '2025-05-07', '2025-06-18',
    '2025-07-30', '2025-09-17', '2025-11-05', '2025-12-17'
]

# 2024 FOMC dates (for 6-month lookback)
FOMC_DATES_2024 = [
    '2024-01-31', '2024-03-20', '2024-05-01', '2024-06-12',
    '2024-07-31', '2024-09-18', '2024-11-07', '2024-12-18'
]

FOMC_DATES = set(FOMC_DATES_2024 + FOMC_DATES_2025)

# Short trading days (1pm close) - 2024 and 2025
SHORT_DAYS = [
    # 2024
    '2024-07-03', '2024-11-29', '2024-12-24',
    # 2025
    '2025-07-03', '2025-11-28', '2025-12-24'
]

SHORT_DAYS_SET = set(SHORT_DAYS)

# get_spread_width is imported from core.gex_strategy

def is_excluded_day(date_str):
    """Check if date should be excluded (FOMC or short day)."""
    return date_str in FOMC_DATES or date_str in SHORT_DAYS_SET

# ============================================================================
#                           HELPER FUNCTIONS
# ============================================================================

# round_to_5 is imported from core.gex_strategy

def round_to_25(price):
    """Round to nearest 25 for GEX pin approximation."""
    return round(price / 25) * 25

def black_scholes_put(S, K, T, r, sigma):
    """Black-Scholes put price."""
    if T <= 0:
        return max(K - S, 0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

def black_scholes_call(S, K, T, r, sigma):
    """Black-Scholes call price."""
    if T <= 0:
        return max(S - K, 0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)

def estimate_spread_credit(spx, short_strike, long_strike, vix, is_call=True, hours_to_expiry=6):
    """
    Estimate credit for a vertical spread using Black-Scholes.

    Args:
        spx: Current SPX price
        short_strike: Strike we're selling
        long_strike: Strike we're buying (protection)
        vix: Current VIX level
        is_call: True for call spread, False for put spread
        hours_to_expiry: Hours until expiration (0DTE)

    Returns:
        Estimated credit received per contract (in dollars, not multiplied by 100)
    """
    T = hours_to_expiry / (252 * 6.5)  # Trading hours per year
    sigma = vix / 100  # VIX is annualized vol in %
    r = 0.05  # Risk-free rate assumption

    if is_call:
        short_price = black_scholes_call(spx, short_strike, T, r, sigma)
        long_price = black_scholes_call(spx, long_strike, T, r, sigma)
    else:
        short_price = black_scholes_put(spx, short_strike, T, r, sigma)
        long_price = black_scholes_put(spx, long_strike, T, r, sigma)

    credit = short_price - long_price
    return max(credit, 0.05)  # Minimum credit floor

def get_gex_trade_setup(pin_price, spx_price, vix):
    """
    Wrapper for core.gex_strategy.get_gex_trade_setup

    Uses shared module: core.gex_strategy (single source of truth)
    This ensures backtest and live scalper use IDENTICAL trade setup logic.
    """
    # Use core module (GEXTradeSetup dataclass)
    setup = core_get_gex_trade_setup(pin_price, spx_price, vix, vix_threshold=VIX_MAX_THRESHOLD)

    # Convert dataclass to dict for backwards compatibility
    result = {
        'strategy': setup.strategy,
        'strikes': setup.strikes,
        'direction': setup.direction,
        'distance': setup.distance,
        'confidence': setup.confidence,
        'description': setup.description
    }

    # Add skip_reason for VIX skips (backwards compatibility)
    if setup.strategy == 'SKIP' and 'VIX' in setup.description:
        result['skip_reason'] = setup.description

    return result

def estimate_spread_value_at_price(setup, spx_price, entry_credit):
    """Estimate spread value when SPX is at a given price."""
    strategy = setup['strategy']
    strikes = setup['strikes']

    if strategy == 'IC':
        call_short, call_long, put_short, put_long = strikes
        spread_width = call_long - call_short

        if spx_price >= call_long:
            return spread_width  # Max loss call side
        elif spx_price >= call_short:
            return (spx_price - call_short) * 0.7 + 0.3  # ITM call side
        elif spx_price <= put_long:
            return spread_width  # Max loss put side
        elif spx_price <= put_short:
            return (put_short - spx_price) * 0.7 + 0.3  # ITM put side
        else:
            # OTM both sides - estimate based on distance from nearest strike
            dist_to_call = call_short - spx_price
            dist_to_put = spx_price - put_short
            min_dist = min(dist_to_call, dist_to_put)
            # Further OTM = lower value (more profit)
            return max(0, entry_credit * (1 - min_dist / 20))

    elif strategy == 'CALL':
        short_strike, long_strike = strikes
        spread_width = long_strike - short_strike

        if spx_price >= long_strike:
            return spread_width  # Max loss
        elif spx_price >= short_strike:
            return (spx_price - short_strike) * 0.7 + 0.3  # ITM
        else:
            # OTM - estimate based on distance
            dist_otm = short_strike - spx_price
            return max(0, entry_credit * (1 - dist_otm / 15))

    elif strategy == 'PUT':
        short_strike, long_strike = strikes
        spread_width = short_strike - long_strike

        if spx_price <= long_strike:
            return spread_width  # Max loss
        elif spx_price <= short_strike:
            return (short_strike - spx_price) * 0.7 + 0.3  # ITM
        else:
            # OTM - estimate based on distance
            dist_otm = spx_price - short_strike
            return max(0, entry_credit * (1 - dist_otm / 15))

    return entry_credit

def simulate_trade_outcome(setup, entry_credit, spx_open, spx_high, spx_low, spx_close, vix):
    """
    Simulate trade outcome with trailing stop support.

    Uses intraday high/low to simulate price path and trailing stop behavior.

    Returns:
        dict with exit_reason, exit_value, pnl_dollars, pnl_pct
    """
    strategy = setup['strategy']
    strikes = setup['strikes']
    confidence = setup['confidence']

    if strategy == 'SKIP':
        return None

    # Determine profit target based on confidence
    tp_pct = PROFIT_TARGET_MEDIUM if confidence == 'MEDIUM' else PROFIT_TARGET_HIGH

    # Get spread width for max loss calculation
    if strategy == 'IC':
        spread_width = strikes[1] - strikes[0]  # call_long - call_short
    else:
        spread_width = abs(strikes[1] - strikes[0])

    # Calculate spread values at different price points
    value_at_open = estimate_spread_value_at_price(setup, spx_open, entry_credit)
    value_at_close = estimate_spread_value_at_price(setup, spx_close, entry_credit)

    # Determine best/worst case based on strategy direction
    if strategy == 'CALL':
        # CALL spread profits when SPX goes down (away from strikes)
        best_price = spx_low   # Best case: price went to daily low
        worst_price = spx_high  # Worst case: price went to daily high
    elif strategy == 'PUT':
        # PUT spread profits when SPX goes up (away from strikes)
        best_price = spx_high  # Best case: price went to daily high
        worst_price = spx_low   # Worst case: price went to daily low
    else:  # IC
        # IC profits when SPX stays near center
        center = (strikes[0] + strikes[2]) / 2  # Midpoint between call_short and put_short
        if abs(spx_high - center) > abs(spx_low - center):
            worst_price = spx_high
            best_price = spx_low if abs(spx_low - center) < abs(spx_open - center) else spx_open
        else:
            worst_price = spx_low
            best_price = spx_high if abs(spx_high - center) < abs(spx_open - center) else spx_open

    value_at_best = estimate_spread_value_at_price(setup, best_price, entry_credit)
    value_at_worst = estimate_spread_value_at_price(setup, worst_price, entry_credit)

    # Calculate profit percentages
    best_profit_pct = (entry_credit - value_at_best) / entry_credit if entry_credit > 0 else 0
    worst_profit_pct = (entry_credit - value_at_worst) / entry_credit if entry_credit > 0 else 0
    close_profit_pct = (entry_credit - value_at_close) / entry_credit if entry_credit > 0 else 0

    # Simulation logic with trailing stop
    exit_reason = None
    final_profit_pct = None

    # Check if TP was hit (best profit reached TP level)
    if best_profit_pct >= tp_pct:
        exit_reason = f"TP ({int(tp_pct*100)}%)"
        final_profit_pct = tp_pct

    # Check trailing stop logic
    elif TRAILING_STOP_ENABLED and best_profit_pct >= TRAILING_TRIGGER_PCT:
        # Trailing stop was activated at some point
        # Calculate trailing stop level based on best profit reached
        initial_trail_distance = TRAILING_TRIGGER_PCT - TRAILING_LOCK_IN_PCT
        profit_above_trigger = best_profit_pct - TRAILING_TRIGGER_PCT
        trail_distance = initial_trail_distance - (profit_above_trigger * TRAILING_TIGHTEN_RATE)
        trail_distance = max(trail_distance, TRAILING_DISTANCE_MIN)
        trailing_stop_level = best_profit_pct - trail_distance

        # Did we drop below trailing stop?
        # Assume price path: open -> best -> worst -> close (simplified)
        # If worst profit is below trailing stop level, we got stopped out
        if worst_profit_pct <= trailing_stop_level:
            exit_reason = f"Trail ({int(trailing_stop_level*100)}%)"
            final_profit_pct = trailing_stop_level
        elif close_profit_pct <= trailing_stop_level:
            exit_reason = f"Trail ({int(trailing_stop_level*100)}%)"
            final_profit_pct = trailing_stop_level
        else:
            # Held to close with trailing active
            exit_reason = "Close (trail)"
            final_profit_pct = close_profit_pct

    # Check regular stop loss (only if trailing not active)
    elif worst_profit_pct <= -STOP_LOSS_PCT:
        exit_reason = "SL (10%)"
        final_profit_pct = -STOP_LOSS_PCT

    # Otherwise, held to close
    else:
        exit_reason = "Close"
        final_profit_pct = close_profit_pct

    # Calculate final values
    final_value = entry_credit * (1 - final_profit_pct)
    final_value = max(0, min(final_value, spread_width))  # Clamp to valid range

    pnl_dollars = final_profit_pct * entry_credit * 100  # Per contract
    pnl_pct = final_profit_pct * 100

    return {
        'exit_reason': exit_reason,
        'exit_value': round(final_value, 2),
        'pnl_dollars': round(pnl_dollars, 2),
        'pnl_pct': round(pnl_pct, 1),
        'best_profit_pct': round(best_profit_pct * 100, 1),
        'trailing_activated': best_profit_pct >= TRAILING_TRIGGER_PCT if TRAILING_STOP_ENABLED else False
    }

# ============================================================================
#                           MAIN BACKTEST
# ============================================================================

def run_backtest(days=180, realistic=False):
    """Run the GEX scalper backtest."""

    print("=" * 70)
    print("GEX SCALPER BACKTEST")
    print(f"Period: Last {days} trading days")
    if realistic:
        print("MODE: REALISTIC (slippage, 10% SL hits, 2% gap risk)")
    print("=" * 70)

    # Fetch historical data
    print("\nFetching historical data...")
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=int(days * 1.5))  # Extra buffer for weekends

    spy = yf.download("SPY", start=start_date, end=end_date, progress=False)
    vix = yf.download("^VIX", start=start_date, end=end_date, progress=False)

    if spy.empty or vix.empty:
        print("ERROR: Could not fetch historical data")
        return

    # Handle multi-level columns from yfinance
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    # Convert SPY to SPX (multiply by 10)
    spy['SPX_Open'] = spy['Open'] * 10
    spy['SPX_High'] = spy['High'] * 10
    spy['SPX_Low'] = spy['Low'] * 10
    spy['SPX_Close'] = spy['Close'] * 10

    # Merge VIX
    spy['VIX'] = vix['Close']

    # Calculate IVR (52-week rank)
    spy['VIX_52w_high'] = spy['VIX'].rolling(window=252, min_periods=50).max()
    spy['VIX_52w_low'] = spy['VIX'].rolling(window=252, min_periods=50).min()
    spy['IVR'] = ((spy['VIX'] - spy['VIX_52w_low']) / (spy['VIX_52w_high'] - spy['VIX_52w_low'])) * 100
    spy['IVR'] = spy['IVR'].fillna(50)  # Default to 50 if not enough history

    # Day of week (0=Mon, 4=Fri)
    spy['day_of_week'] = spy.index.dayofweek
    spy['day_name'] = spy.index.day_name()

    # Gap size (open vs previous close)
    spy['prev_close'] = spy['SPX_Close'].shift(1)
    spy['gap_pct'] = ((spy['SPX_Open'] - spy['prev_close']) / spy['prev_close'] * 100).abs()

    # 20-day SMA trend
    spy['sma20'] = spy['SPX_Close'].rolling(window=20).mean()
    spy['above_sma20'] = spy['SPX_Open'] > spy['sma20']

    # Previous day range (ATR proxy)
    spy['prev_range'] = (spy['SPX_High'].shift(1) - spy['SPX_Low'].shift(1))
    spy['avg_range'] = spy['prev_range'].rolling(window=10).mean()
    spy['range_ratio'] = spy['prev_range'] / spy['avg_range']  # >1 = high range day

    # Consecutive up/down days
    spy['daily_return'] = spy['SPX_Close'].pct_change()
    spy['up_day'] = spy['daily_return'] > 0

    # Calculate consecutive days
    def count_consecutive(series):
        result = []
        count = 0
        prev_val = None
        for val in series:
            if prev_val is None:
                count = 1
            elif val == prev_val:
                count += 1
            else:
                count = 1
            result.append(count if val else -count)
            prev_val = val
        return result

    spy['consec_days'] = count_consecutive(spy['up_day'].tolist())
    spy['consec_days'] = spy['consec_days'].shift(1)  # Use previous day's streak

    # OPEX week (3rd Friday of month)
    def is_opex_week(date):
        # Find 3rd Friday of the month
        first_day = date.replace(day=1)
        first_friday = first_day + pd.Timedelta(days=(4 - first_day.dayofweek + 7) % 7)
        third_friday = first_friday + pd.Timedelta(days=14)
        # OPEX week is Mon-Fri of that week
        opex_monday = third_friday - pd.Timedelta(days=4)
        return opex_monday <= date <= third_friday

    spy['opex_week'] = [is_opex_week(d) for d in spy.index]

    # RSI (14-period)
    def calculate_rsi(prices, period=14):
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    spy['RSI'] = calculate_rsi(spy['SPX_Close'], 14)
    spy['RSI'] = spy['RSI'].fillna(50)

    spy = spy.dropna()

    # Limit to requested days
    spy = spy.tail(days)

    print(f"Loaded {len(spy)} trading days")
    print(f"Date range: {spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}")
    print(f"SPX range: {spy['SPX_Low'].min():.0f} - {spy['SPX_High'].max():.0f}")
    print(f"VIX range: {spy['VIX'].min():.1f} - {spy['VIX'].max():.1f}")
    print(f"IVR range: {spy['IVR'].min():.0f} - {spy['IVR'].max():.0f}")

    # Run simulation
    print("\nRunning simulation...")
    print(f"Entry times: 9:36 AM, 10:00 AM, 11:00 AM, 12:00 PM, 1:00 PM")
    print(f"VIX filter: < {VIX_MAX_THRESHOLD}")
    print(f"Excluding: FOMC days, short trading days")

    trades = []
    skipped_days = {'fomc': 0, 'short': 0, 'vix': 0}
    prev_close = None

    for date, row in spy.iterrows():
        date_str = date.strftime('%Y-%m-%d')

        # Check for excluded days
        if date_str in FOMC_DATES:
            skipped_days['fomc'] += 1
            prev_close = row['SPX_Close']
            continue
        if date_str in SHORT_DAYS_SET:
            skipped_days['short'] += 1
            prev_close = row['SPX_Close']
            continue

        spx_open = row['SPX_Open']
        spx_high = row['SPX_High']
        spx_low = row['SPX_Low']
        spx_close = row['SPX_Close']
        vix_val = row['VIX']
        ivr_val = row['IVR']
        day_name = row['day_name']
        gap_pct = row['gap_pct']
        above_sma = row['above_sma20']
        range_ratio = row['range_ratio']
        consec = row['consec_days']
        opex = row['opex_week']
        rsi = row['RSI']

        # Approximate GEX pin using previous close rounded to 25
        if prev_close is None:
            pin_price = round_to_25(spx_open)
        else:
            pin_price = round_to_25(prev_close)

        prev_close = spx_close

        # Try each entry time
        for entry_idx, hours_after_open in enumerate(ENTRY_TIMES):
            entry_time_label = ['9:36', '10:00', '11:00', '12:00', '13:00'][entry_idx]
            hours_to_expiry = 6.5 - hours_after_open  # Market closes 4pm, 6.5hrs after 9:30

            # Estimate SPX price at entry time (interpolate between open and close)
            # Simple model: price moves linearly from open toward close
            progress = hours_after_open / 6.5
            spx_at_entry = spx_open + (spx_close - spx_open) * progress * 0.5  # Dampened

            # Get trade setup
            setup = get_gex_trade_setup(pin_price, spx_at_entry, vix_val)

            if setup['strategy'] == 'SKIP':
                if 'VIX' in setup.get('skip_reason', ''):
                    skipped_days['vix'] += 1
                continue  # Try next entry time

            # Estimate entry credit with time to expiry
            strikes = setup['strikes']
            if setup['strategy'] == 'IC':
                call_credit = estimate_spread_credit(spx_at_entry, strikes[0], strikes[1], vix_val,
                                                     is_call=True, hours_to_expiry=hours_to_expiry)
                put_credit = estimate_spread_credit(spx_at_entry, strikes[2], strikes[3], vix_val,
                                                    is_call=False, hours_to_expiry=hours_to_expiry)
                entry_credit = call_credit + put_credit
            else:
                is_call = setup['strategy'] == 'CALL'
                entry_credit = estimate_spread_credit(spx_at_entry, strikes[0], strikes[1], vix_val,
                                                      is_call=is_call, hours_to_expiry=hours_to_expiry)

            # Simulate outcome
            outcome = simulate_trade_outcome(setup, entry_credit, spx_at_entry, spx_high, spx_low, spx_close, vix_val)

            if outcome:
                trades.append({
                    'date': date_str,
                    'entry_time': entry_time_label,
                    'day': day_name,
                    'spx_entry': round(spx_at_entry, 0),
                    'spx_close': round(spx_close, 0),
                    'vix': round(vix_val, 1),
                    'ivr': round(ivr_val, 0),
                    'gap_pct': round(gap_pct, 2),
                    'above_sma20': above_sma,
                    'range_ratio': round(range_ratio, 2) if not pd.isna(range_ratio) else 1.0,
                    'consec_days': int(consec) if not pd.isna(consec) else 0,
                    'opex_week': opex,
                    'rsi': round(rsi, 1),
                    'pin': pin_price,
                    'distance': setup['distance'],
                    'strategy': setup['strategy'],
                    'confidence': setup['confidence'],
                    'strikes': '/'.join(map(str, strikes)),
                    'entry_credit': round(entry_credit, 2),
                    **outcome
                })
                # Allow multiple trades per day at different entry times

    # Create results DataFrame
    df = pd.DataFrame(trades)

    print(f"\nDays skipped: FOMC={skipped_days['fomc']}, Short={skipped_days['short']}, VIX>={VIX_MAX_THRESHOLD}: {skipped_days['vix']} entry attempts")

    if df.empty:
        print("No trades generated!")
        return

    # ============================================================================
    #                     REALISTIC ADJUSTMENTS
    # ============================================================================
    if realistic:
        print("\n" + "-" * 40)
        print("APPLYING REALISTIC ADJUSTMENTS:")
        print("-" * 40)

        np.random.seed(42)  # Reproducible results

        # 1. Slippage & commissions
        SLIPPAGE_PER_LEG = 0.02  # $0.02 slippage per leg
        COMMISSION_PER_CONTRACT = 0.50  # $0.50 per contract
        legs = df['strategy'].apply(lambda x: 4 if x == 'IC' else 2)
        slippage_cost = legs * SLIPPAGE_PER_LEG * 100 + legs * COMMISSION_PER_CONTRACT
        df['pnl_dollars'] = df['pnl_dollars'] - slippage_cost
        print(f"  1) Slippage & commissions: -${slippage_cost.sum():,.0f} total")

        # 2. Random stop loss hits (10% of trades)
        STOP_LOSS_RATE = 0.10
        STOP_LOSS_AVG = -150  # Average loss when SL hits
        hit_sl = np.random.random(len(df)) < STOP_LOSS_RATE
        sl_count = hit_sl.sum()
        sl_impact = df.loc[hit_sl, 'pnl_dollars'].sum() - (sl_count * STOP_LOSS_AVG)
        df.loc[hit_sl, 'pnl_dollars'] = STOP_LOSS_AVG
        df.loc[hit_sl, 'exit_reason'] = 'SL (realistic)'
        print(f"  2) Stop loss hits: {sl_count} trades ({STOP_LOSS_RATE*100:.0f}%) → -${sl_impact:,.0f}")

        # 3. Gap/assignment risk (2% catastrophic)
        GAP_RISK_RATE = 0.02
        GAP_LOSS = -500
        # Only apply to trades not already hit by SL
        remaining = ~hit_sl
        hit_gap = np.random.random(len(df)) < GAP_RISK_RATE
        hit_gap = hit_gap & remaining  # Don't double-count
        gap_count = hit_gap.sum()
        gap_impact = df.loc[hit_gap, 'pnl_dollars'].sum() - (gap_count * GAP_LOSS)
        df.loc[hit_gap, 'pnl_dollars'] = GAP_LOSS
        df.loc[hit_gap, 'exit_reason'] = 'Gap (realistic)'
        print(f"  3) Gap/assignment risk: {gap_count} trades ({GAP_RISK_RATE*100:.0f}%) → -${gap_impact:,.0f}")

        print("-" * 40)

    # ============================================================================
    #                           RESULTS SUMMARY
    # ============================================================================

    print("\n" + "=" * 70)
    print("BACKTEST RESULTS")
    print("=" * 70)

    total_trades = len(df)
    winners = df[df['pnl_dollars'] > 0]
    losers = df[df['pnl_dollars'] <= 0]

    win_rate = len(winners) / total_trades * 100
    total_pnl = df['pnl_dollars'].sum()
    avg_win = winners['pnl_dollars'].mean() if len(winners) > 0 else 0
    avg_loss = losers['pnl_dollars'].mean() if len(losers) > 0 else 0

    print(f"\nTotal Trades:     {total_trades}")
    print(f"Winners:          {len(winners)} ({win_rate:.1f}%)")
    print(f"Losers:           {len(losers)} ({100-win_rate:.1f}%)")
    print(f"\nTotal P/L:        ${total_pnl:+,.2f}")
    print(f"Avg Winner:       ${avg_win:+,.2f}")
    print(f"Avg Loser:        ${avg_loss:+,.2f}")

    if avg_loss != 0:
        profit_factor = abs(winners['pnl_dollars'].sum() / losers['pnl_dollars'].sum()) if losers['pnl_dollars'].sum() != 0 else float('inf')
        print(f"Profit Factor:    {profit_factor:.2f}")

    # Trailing stop statistics
    if TRAILING_STOP_ENABLED and 'trailing_activated' in df.columns:
        print("\n" + "-" * 40)
        print("TRAILING STOP ANALYSIS:")
        print("-" * 40)

        # Count by exit reason
        exit_reasons = df['exit_reason'].value_counts()
        for reason, count in exit_reasons.items():
            reason_df = df[df['exit_reason'] == reason]
            reason_pnl = reason_df['pnl_dollars'].sum()
            print(f"{reason:20s}  Count: {count:3d}  P/L: ${reason_pnl:+8,.2f}")

        # Trailing activation stats
        trail_activated = df[df['trailing_activated'] == True]
        trail_not_activated = df[df['trailing_activated'] == False]

        if len(trail_activated) > 0:
            print(f"\nTrailing Activated: {len(trail_activated)} trades ({len(trail_activated)/total_trades*100:.1f}%)")
            trail_pnl = trail_activated['pnl_dollars'].sum()
            trail_avg = trail_activated['pnl_dollars'].mean()
            print(f"  Total P/L: ${trail_pnl:+,.2f}  Avg: ${trail_avg:+,.2f}")

        if len(trail_not_activated) > 0:
            no_trail_pnl = trail_not_activated['pnl_dollars'].sum()
            no_trail_avg = trail_not_activated['pnl_dollars'].mean()
            print(f"No Trailing:        {len(trail_not_activated)} trades")
            print(f"  Total P/L: ${no_trail_pnl:+,.2f}  Avg: ${no_trail_avg:+,.2f}")

        # Best profit reached analysis
        if 'best_profit_pct' in df.columns:
            reached_25 = df[df['best_profit_pct'] >= 25]
            reached_35 = df[df['best_profit_pct'] >= 35]
            reached_45 = df[df['best_profit_pct'] >= 45]
            print(f"\nPeak profit reached:")
            print(f"  >= 25%: {len(reached_25)} trades ({len(reached_25)/total_trades*100:.1f}%)")
            print(f"  >= 35%: {len(reached_35)} trades ({len(reached_35)/total_trades*100:.1f}%)")
            print(f"  >= 45%: {len(reached_45)} trades ({len(reached_45)/total_trades*100:.1f}%)")

    # By strategy type
    print("\n" + "-" * 40)
    print("BY STRATEGY TYPE:")
    print("-" * 40)
    for strat in df['strategy'].unique():
        strat_df = df[df['strategy'] == strat]
        strat_wins = len(strat_df[strat_df['pnl_dollars'] > 0])
        strat_wr = strat_wins / len(strat_df) * 100
        strat_pnl = strat_df['pnl_dollars'].sum()
        print(f"{strat:8s}  Trades: {len(strat_df):3d}  WR: {strat_wr:5.1f}%  P/L: ${strat_pnl:+8,.2f}")

    # By confidence level
    print("\n" + "-" * 40)
    print("BY CONFIDENCE LEVEL:")
    print("-" * 40)
    for conf in df['confidence'].unique():
        conf_df = df[df['confidence'] == conf]
        conf_wins = len(conf_df[conf_df['pnl_dollars'] > 0])
        conf_wr = conf_wins / len(conf_df) * 100
        conf_pnl = conf_df['pnl_dollars'].sum()
        print(f"{conf:8s}  Trades: {len(conf_df):3d}  WR: {conf_wr:5.1f}%  P/L: ${conf_pnl:+8,.2f}")

    # By entry time
    print("\n" + "-" * 40)
    print("BY ENTRY TIME:")
    print("-" * 40)
    for etime in ['9:36', '10:00', '11:00', '12:00', '13:00']:
        time_df = df[df['entry_time'] == etime]
        if len(time_df) == 0:
            continue
        time_wins = len(time_df[time_df['pnl_dollars'] > 0])
        time_wr = time_wins / len(time_df) * 100
        time_pnl = time_df['pnl_dollars'].sum()
        print(f"{etime:8s}  Trades: {len(time_df):3d}  WR: {time_wr:5.1f}%  P/L: ${time_pnl:+8,.2f}")

    # By IVR buckets
    print("\n" + "-" * 40)
    print("BY IVR (Implied Volatility Rank):")
    print("-" * 40)
    ivr_buckets = [
        ('0-20 (Low)', 0, 20),
        ('20-40', 20, 40),
        ('40-60 (Mid)', 40, 60),
        ('60-80', 60, 80),
        ('80-100 (High)', 80, 101)
    ]
    for label, low, high in ivr_buckets:
        ivr_df = df[(df['ivr'] >= low) & (df['ivr'] < high)]
        if len(ivr_df) == 0:
            print(f"{label:15s}  Trades:   0")
            continue
        ivr_wins = len(ivr_df[ivr_df['pnl_dollars'] > 0])
        ivr_wr = ivr_wins / len(ivr_df) * 100
        ivr_pnl = ivr_df['pnl_dollars'].sum()
        avg_credit = ivr_df['entry_credit'].mean()
        print(f"{label:15s}  Trades: {len(ivr_df):3d}  WR: {ivr_wr:5.1f}%  P/L: ${ivr_pnl:+8,.2f}  Avg Credit: ${avg_credit:.2f}")

    # By day of week
    print("\n" + "-" * 40)
    print("BY DAY OF WEEK:")
    print("-" * 40)
    for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
        day_df = df[df['day'] == day]
        if len(day_df) == 0:
            continue
        day_wins = len(day_df[day_df['pnl_dollars'] > 0])
        day_wr = day_wins / len(day_df) * 100
        day_pnl = day_df['pnl_dollars'].sum()
        print(f"{day:12s}  Trades: {len(day_df):3d}  WR: {day_wr:5.1f}%  P/L: ${day_pnl:+8,.2f}")

    # By gap size
    print("\n" + "-" * 40)
    print("BY GAP SIZE (open vs prev close):")
    print("-" * 40)
    gap_buckets = [
        ('< 0.25%', 0, 0.25),
        ('0.25-0.5%', 0.25, 0.5),
        ('0.5-1.0%', 0.5, 1.0),
        ('> 1.0%', 1.0, 100)
    ]
    for label, low, high in gap_buckets:
        gap_df = df[(df['gap_pct'] >= low) & (df['gap_pct'] < high)]
        if len(gap_df) == 0:
            print(f"{label:12s}  Trades:   0")
            continue
        gap_wins = len(gap_df[gap_df['pnl_dollars'] > 0])
        gap_wr = gap_wins / len(gap_df) * 100
        gap_pnl = gap_df['pnl_dollars'].sum()
        print(f"{label:12s}  Trades: {len(gap_df):3d}  WR: {gap_wr:5.1f}%  P/L: ${gap_pnl:+8,.2f}")

    # By trend (above/below SMA20)
    print("\n" + "-" * 40)
    print("BY TREND (SPX vs 20-day SMA):")
    print("-" * 40)
    for trend_label, trend_val in [('Above SMA20', True), ('Below SMA20', False)]:
        trend_df = df[df['above_sma20'] == trend_val]
        if len(trend_df) == 0:
            continue
        trend_wins = len(trend_df[trend_df['pnl_dollars'] > 0])
        trend_wr = trend_wins / len(trend_df) * 100
        trend_pnl = trend_df['pnl_dollars'].sum()
        print(f"{trend_label:12s}  Trades: {len(trend_df):3d}  WR: {trend_wr:5.1f}%  P/L: ${trend_pnl:+8,.2f}")

    # By previous day range
    print("\n" + "-" * 40)
    print("BY PREV DAY RANGE (vs 10-day avg):")
    print("-" * 40)
    range_buckets = [
        ('Low (<0.8x)', 0, 0.8),
        ('Normal', 0.8, 1.2),
        ('High (>1.2x)', 1.2, 100)
    ]
    for label, low, high in range_buckets:
        rng_df = df[(df['range_ratio'] >= low) & (df['range_ratio'] < high)]
        if len(rng_df) == 0:
            print(f"{label:15s}  Trades:   0")
            continue
        rng_wins = len(rng_df[rng_df['pnl_dollars'] > 0])
        rng_wr = rng_wins / len(rng_df) * 100
        rng_pnl = rng_df['pnl_dollars'].sum()
        print(f"{label:15s}  Trades: {len(rng_df):3d}  WR: {rng_wr:5.1f}%  P/L: ${rng_pnl:+8,.2f}")

    # By consecutive days
    print("\n" + "-" * 40)
    print("BY CONSECUTIVE UP/DOWN DAYS (prev):")
    print("-" * 40)
    consec_buckets = [
        ('3+ down', -10, -2),
        ('1-2 down', -2, 0),
        ('1-2 up', 1, 3),
        ('3+ up', 3, 10)
    ]
    for label, low, high in consec_buckets:
        con_df = df[(df['consec_days'] >= low) & (df['consec_days'] < high)]
        if len(con_df) == 0:
            print(f"{label:12s}  Trades:   0")
            continue
        con_wins = len(con_df[con_df['pnl_dollars'] > 0])
        con_wr = con_wins / len(con_df) * 100
        con_pnl = con_df['pnl_dollars'].sum()
        print(f"{label:12s}  Trades: {len(con_df):3d}  WR: {con_wr:5.1f}%  P/L: ${con_pnl:+8,.2f}")

    # By OPEX week
    print("\n" + "-" * 40)
    print("BY OPEX WEEK (monthly options exp):")
    print("-" * 40)
    for opex_label, opex_val in [('OPEX week', True), ('Non-OPEX', False)]:
        opex_df = df[df['opex_week'] == opex_val]
        if len(opex_df) == 0:
            continue
        opex_wins = len(opex_df[opex_df['pnl_dollars'] > 0])
        opex_wr = opex_wins / len(opex_df) * 100
        opex_pnl = opex_df['pnl_dollars'].sum()
        print(f"{opex_label:12s}  Trades: {len(opex_df):3d}  WR: {opex_wr:5.1f}%  P/L: ${opex_pnl:+8,.2f}")

    # By RSI
    print("\n" + "-" * 40)
    print("BY RSI (14-period):")
    print("-" * 40)
    rsi_buckets = [
        ('< 30 (Oversold)', 0, 30),
        ('30-40', 30, 40),
        ('40-50', 40, 50),
        ('50-60', 50, 60),
        ('60-70', 60, 70),
        ('> 70 (Overbought)', 70, 101)
    ]
    for label, low, high in rsi_buckets:
        rsi_df = df[(df['rsi'] >= low) & (df['rsi'] < high)]
        if len(rsi_df) == 0:
            print(f"{label:18s}  Trades:   0")
            continue
        rsi_wins = len(rsi_df[rsi_df['pnl_dollars'] > 0])
        rsi_wr = rsi_wins / len(rsi_df) * 100
        rsi_pnl = rsi_df['pnl_dollars'].sum()
        print(f"{label:18s}  Trades: {len(rsi_df):3d}  WR: {rsi_wr:5.1f}%  P/L: ${rsi_pnl:+8,.2f}")

    # Monthly breakdown
    print("\n" + "-" * 40)
    print("MONTHLY BREAKDOWN:")
    print("-" * 40)
    df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
    monthly = df.groupby('month').agg({
        'pnl_dollars': ['count', 'sum', lambda x: (x > 0).sum()]
    })
    monthly.columns = ['trades', 'pnl', 'wins']
    monthly['wr'] = monthly['wins'] / monthly['trades'] * 100

    for month, row in monthly.iterrows():
        print(f"{month}  Trades: {int(row['trades']):3d}  WR: {row['wr']:5.1f}%  P/L: ${row['pnl']:+8,.2f}")

    # Drawdown analysis
    df['cumulative_pnl'] = df['pnl_dollars'].cumsum()
    df['peak'] = df['cumulative_pnl'].cummax()
    df['drawdown'] = df['cumulative_pnl'] - df['peak']
    max_drawdown = df['drawdown'].min()

    # Sortino ratio (daily)
    daily_pnl = df.groupby('date')['pnl_dollars'].sum()
    mean_daily = daily_pnl.mean()
    negative_days = daily_pnl[daily_pnl < 0]
    if len(negative_days) > 1:
        downside_dev = negative_days.std()
    elif len(negative_days) == 1:
        downside_dev = abs(negative_days.iloc[0])
    else:
        downside_dev = 0.01  # Avoid div by zero
    sortino = mean_daily / downside_dev if downside_dev > 0 else float('inf')

    # Profit factor
    gross_profit = df[df['pnl_dollars'] > 0]['pnl_dollars'].sum()
    gross_loss = abs(df[df['pnl_dollars'] <= 0]['pnl_dollars'].sum()) or 1
    pf = gross_profit / gross_loss

    print("\n" + "-" * 40)
    print("RISK METRICS:")
    print("-" * 40)
    print(f"Profit Factor:    {pf:.2f}")
    print(f"Sortino Ratio:    {sortino:.2f}" if sortino < 1000 else "Sortino Ratio:    ∞ (no losing days)")
    print(f"Max Drawdown:     ${max_drawdown:,.2f}")
    print(f"Peak Equity:      ${df['peak'].max():,.2f}")
    print(f"Final Equity:     ${df['cumulative_pnl'].iloc[-1]:,.2f}")
    print(f"Avg Daily P/L:    ${mean_daily:,.2f}")
    print(f"Losing Days:      {len(negative_days)}")

    # Save detailed results
    output_file = "/root/gamma/data/backtest_results.csv"
    df.to_csv(output_file, index=False)
    print(f"\nDetailed results saved to: {output_file}")

    # Show last 10 trades
    print("\n" + "-" * 40)
    print("LAST 10 TRADES:")
    print("-" * 40)
    print(df[['date', 'entry_time', 'vix', 'strategy', 'strikes', 'entry_credit', 'exit_reason', 'pnl_dollars']].tail(10).to_string(index=False))

    print("\n" + "=" * 70)
    print("BACKTEST COMPLETE")
    print("=" * 70)

    return df

# ============================================================================
#                              MAIN
# ============================================================================

def run_monte_carlo(df, simulations=1000, periods=252):
    """
    Run Monte Carlo simulation on trade results.

    Randomly samples from actual trade P/L to project future outcomes.
    Shows range of possible results with confidence intervals.
    """
    print("\n" + "=" * 70)
    print(f"MONTE CARLO SIMULATION ({simulations:,} runs, {periods} trading days)")
    print("=" * 70)

    # Get trade P/L distribution
    trade_pnls = df['pnl_dollars'].values
    trades_per_day = len(df) / df['date'].nunique()

    print(f"\nInput: {len(trade_pnls)} historical trades")
    print(f"Avg trades/day: {trades_per_day:.1f}")
    print(f"Trade P/L range: ${trade_pnls.min():.0f} to ${trade_pnls.max():.0f}")
    print(f"Trade P/L mean: ${trade_pnls.mean():.2f}, std: ${trade_pnls.std():.2f}")

    # Run simulations
    final_pnls = []
    max_drawdowns = []
    win_rates = []

    for _ in range(simulations):
        # Sample trades for N trading days
        n_trades = int(trades_per_day * periods)
        sampled = np.random.choice(trade_pnls, size=n_trades, replace=True)

        # Calculate equity curve
        equity = np.cumsum(sampled)
        peak = np.maximum.accumulate(equity)
        drawdown = equity - peak

        final_pnls.append(equity[-1])
        max_drawdowns.append(drawdown.min())
        win_rates.append((sampled > 0).mean() * 100)

    final_pnls = np.array(final_pnls)
    max_drawdowns = np.array(max_drawdowns)
    win_rates = np.array(win_rates)

    # Calculate percentiles
    percentiles = [5, 10, 25, 50, 75, 90, 95]

    print("\n" + "-" * 50)
    print(f"PROJECTED {periods}-DAY P/L DISTRIBUTION:")
    print("-" * 50)
    for p in percentiles:
        val = np.percentile(final_pnls, p)
        print(f"  {p:3d}th percentile: ${val:>10,.0f}")

    print(f"\n  Mean:             ${final_pnls.mean():>10,.0f}")
    print(f"  Std Dev:          ${final_pnls.std():>10,.0f}")

    print("\n" + "-" * 50)
    print("MAX DRAWDOWN DISTRIBUTION:")
    print("-" * 50)
    for p in [5, 10, 25, 50]:
        val = np.percentile(max_drawdowns, p)
        print(f"  {p:3d}th percentile: ${val:>10,.0f}")
    print(f"  Worst case (5%):  ${np.percentile(max_drawdowns, 5):>10,.0f}")

    print("\n" + "-" * 50)
    print("WIN RATE DISTRIBUTION:")
    print("-" * 50)
    print(f"  5th percentile:   {np.percentile(win_rates, 5):>6.1f}%")
    print(f"  Median:           {np.percentile(win_rates, 50):>6.1f}%")
    print(f"  95th percentile:  {np.percentile(win_rates, 95):>6.1f}%")

    # Risk of ruin (ending negative)
    ruin_pct = (final_pnls < 0).mean() * 100

    # Probability of various outcomes
    print("\n" + "-" * 50)
    print("PROBABILITY OF OUTCOMES:")
    print("-" * 50)
    print(f"  P(Loss):          {ruin_pct:>6.1f}%")
    print(f"  P(> $25K):        {(final_pnls > 25000).mean()*100:>6.1f}%")
    print(f"  P(> $50K):        {(final_pnls > 50000).mean()*100:>6.1f}%")
    print(f"  P(> $75K):        {(final_pnls > 75000).mean()*100:>6.1f}%")
    print(f"  P(> $100K):       {(final_pnls > 100000).mean()*100:>6.1f}%")

    # Sortino distribution
    print("\n" + "-" * 50)
    print("RISK-ADJUSTED METRICS (from simulations):")
    print("-" * 50)

    # Calculate Sortino for each simulation
    sortinos = []
    for _ in range(min(500, simulations)):
        n_trades = int(trades_per_day * periods)
        sampled = np.random.choice(trade_pnls, size=n_trades, replace=True)

        # Group into ~daily chunks
        chunk_size = max(1, int(trades_per_day))
        daily_pnls = [sampled[i:i+chunk_size].sum() for i in range(0, len(sampled), chunk_size)]
        daily_pnls = np.array(daily_pnls)

        mean_daily = daily_pnls.mean()
        neg_days = daily_pnls[daily_pnls < 0]
        if len(neg_days) > 1:
            downside = neg_days.std()
        elif len(neg_days) == 1:
            downside = abs(neg_days[0])
        else:
            downside = 0.01

        sortino = mean_daily / downside if downside > 0.01 else 99
        sortinos.append(min(sortino, 99))

    sortinos = np.array(sortinos)
    print(f"  Sortino 10th pct: {np.percentile(sortinos, 10):>6.2f}")
    print(f"  Sortino median:   {np.percentile(sortinos, 50):>6.2f}")
    print(f"  Sortino 90th pct: {np.percentile(sortinos, 90):>6.2f}")

    print("\n" + "=" * 70)
    print("MONTE CARLO COMPLETE")
    print("=" * 70)

    return {
        'final_pnls': final_pnls,
        'max_drawdowns': max_drawdowns,
        'win_rates': win_rates
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='GEX Scalper Backtest')
    parser.add_argument('--days', type=int, default=180, help='Number of trading days to backtest')
    parser.add_argument('--realistic', action='store_true', help='Apply realistic adjustments (slippage, 10%% SL hits, 2%% gap risk)')
    parser.add_argument('--monte-carlo', type=int, metavar='N', help='Run N Monte Carlo simulations')
    args = parser.parse_args()

    df = run_backtest(days=args.days, realistic=args.realistic)

    if args.monte_carlo and df is not None:
        run_monte_carlo(df, simulations=args.monte_carlo)
