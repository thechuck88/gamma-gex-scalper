#!/usr/bin/env python3
"""
Analyze today's (2026-02-10) actual losses with ADX + momentum filter retroactively.

Today's 3 emergency stops:
- 10:30 AM: -$195 (EMERGENCY -26%, 1 min)
- 11:00 AM: -$150 (EMERGENCY -33%, 4 min)
- 11:30 AM: -$120 (EMERGENCY -26%, 1 min)

Question: Would ADX + momentum filters have blocked these?
"""

import yfinance as yf
import talib
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

print("=" * 80)
print("RETROACTIVE FILTER ANALYSIS - 2026-02-10 Losses")
print("=" * 80)
print()

# Today's losing trades
losing_trades = [
    {'time': '10:30', 'pl': -195, 'reason': 'EMERGENCY Stop Loss (-26%)', 'duration': '1m'},
    {'time': '11:00', 'pl': -150, 'reason': 'EMERGENCY Stop Loss (-33%)', 'duration': '4m'},
    {'time': '11:30', 'pl': -120, 'reason': 'EMERGENCY Stop Loss (-26%)', 'duration': '1m'},
]

total_loss = sum(t['pl'] for t in losing_trades)

print(f"TODAY'S LOSSES: ${total_loss} (3 emergency stops)")
print()
print("Trade breakdown:")
for i, trade in enumerate(losing_trades, 1):
    print(f"  #{i} {trade['time']}: {trade['pl']:+d} ({trade['reason']}, {trade['duration']})")
print()

# Download SPY data for today
print("Downloading SPY 5-minute data for 2026-02-10...")
try:
    data = yf.download('SPY', start="2026-02-09", end="2026-02-11", interval="5m", progress=False)

    if len(data) < 20:
        print("ERROR: Insufficient data")
        exit(1)

    # Handle multi-index columns
    if isinstance(data.columns, pd.MultiIndex):
        high = data['High']['SPY'].values
        low = data['Low']['SPY'].values
        close = data['Close']['SPY'].values
        timestamps = data.index
    else:
        high = data['High'].values
        low = data['Low'].values
        close = data['Close'].values
        timestamps = data.index

    # Calculate ADX and momentum
    adx = talib.ADX(high, low, close, timeperiod=14)
    plus_di = talib.PLUS_DI(high, low, close, timeperiod=14)
    minus_di = talib.MINUS_DI(high, low, close, timeperiod=14)

    print("✅ Data loaded successfully")
    print()

    # Filter settings
    ADX_THRESHOLD = 25
    MOMENTUM_THRESHOLD = 10  # SPX points
    LOOKBACK_BARS = 6  # 30 minutes

    print("=" * 80)
    print("FILTER ANALYSIS AT EACH ENTRY TIME")
    print("=" * 80)
    print()

    blocked_count = 0
    saved_money = 0

    for trade in losing_trades:
        entry_time = trade['time']
        print(f"Trade at {entry_time} (Loss: ${trade['pl']})")
        print("-" * 80)

        # Find closest timestamp to entry time
        # Entry times are ET, need to convert to UTC (add 5 hours)
        entry_dt = datetime.strptime(f"2026-02-10 {entry_time}", "%Y-%m-%d %H:%M")
        entry_utc = entry_dt + timedelta(hours=5)

        # Find closest bar
        closest_idx = None
        min_diff = timedelta(days=999)
        for idx, ts in enumerate(timestamps):
            ts_naive = ts.replace(tzinfo=None) if ts.tzinfo else ts
            diff = abs(ts_naive - entry_utc)
            if diff < min_diff:
                min_diff = diff
                closest_idx = idx

        if closest_idx is None or closest_idx < LOOKBACK_BARS:
            print(f"  ⚠️  Cannot analyze (insufficient data)")
            print()
            continue

        # Check ADX
        current_adx = adx[closest_idx]
        current_plus_di = plus_di[closest_idx]
        current_minus_di = minus_di[closest_idx]

        if np.isnan(current_adx):
            print(f"  ⚠️  ADX data not available")
            print()
            continue

        di_spread = abs(current_plus_di - current_minus_di)
        direction = "UP" if current_plus_di > current_minus_di else "DOWN"

        print(f"  ADX: {current_adx:.1f} (threshold: {ADX_THRESHOLD})")
        print(f"  +DI: {current_plus_di:.1f}, -DI: {current_minus_di:.1f}")
        print(f"  DI Spread: {di_spread:.1f} ({direction} bias)")

        # Check momentum
        current_price = close[closest_idx]
        price_30min_ago = close[closest_idx - LOOKBACK_BARS]
        spy_move = abs(current_price - price_30min_ago)
        spx_equiv_move = spy_move * 10  # Rough SPY to SPX conversion

        print(f"  SPY price now: ${current_price:.2f}")
        print(f"  SPY price 30 min ago: ${price_30min_ago:.2f}")
        print(f"  SPY movement: ${spy_move:.2f}")
        print(f"  SPX equivalent: ~{spx_equiv_move:.0f} points")

        # Determine if would be blocked
        adx_block = current_adx > ADX_THRESHOLD
        momentum_block = spx_equiv_move > MOMENTUM_THRESHOLD

        if adx_block or momentum_block:
            print(f"  🚫 WOULD BE BLOCKED:")
            if adx_block:
                print(f"     - ADX {current_adx:.1f} > {ADX_THRESHOLD} (Strong {direction} trend)")
            if momentum_block:
                print(f"     - Momentum {spx_equiv_move:.0f} pts > {MOMENTUM_THRESHOLD} pts")
            blocked_count += 1
            saved_money += abs(trade['pl'])
        else:
            print(f"  ✅ WOULD BE ALLOWED (ADX and momentum OK)")

        print()

    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    print(f"Total trades analyzed: {len(losing_trades)}")
    print(f"Trades that would be blocked: {blocked_count}")
    print(f"Trades that would be allowed: {len(losing_trades) - blocked_count}")
    print()
    print(f"Money lost today: ${total_loss}")
    print(f"Money saved with filter: ${saved_money}")
    print(f"Remaining loss: ${total_loss - saved_money}")
    print()

    if blocked_count == len(losing_trades):
        print("✅ RESULT: ALL losing trades would have been blocked!")
        print(f"   Filter would have saved ${saved_money} today")
    elif blocked_count > 0:
        print(f"✅ RESULT: Filter would have blocked {blocked_count}/{len(losing_trades)} trades")
        print(f"   Saved ${saved_money} out of ${total_loss} loss ({saved_money/abs(total_loss)*100:.0f}%)")
    else:
        print("⚠️ RESULT: Filter would NOT have helped today")
        print("   (Market conditions were below thresholds)")

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
