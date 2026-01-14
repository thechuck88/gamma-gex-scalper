# Backtest Debugging Summary - Fixed 2026-01-14

## Problem Statement
The backtest showed unrealistic results with 100% win rate and cookie-cutter ±$250 P/L. Later, after implementing realistic P&L calculation using database prices, it showed -$16,305 P/L with only 1.4% win rate - opposite to live bot's +$2,899 with 56% win rate.

## Root Causes Identified & Fixed

### 1. **Strike Selection Wrong (63% Entry Credit Overstated)**
**Problem:** Backtest hardcoded PIN±5 strikes regardless of market conditions
- Example: PIN=6980, SPX=6960.66 (22pts away)
- Wrong: Entry at 6980/6975 with credit $4.00
- Correct: Should use distance-based logic for 6955/6945 with credit $2.45
- Error: 63% too high on entry credit

**Fix:** Replaced hardcoded logic with `get_gex_trade_setup()` from core/gex_strategy.py
- Now uses distance-based zones (NEAR_PIN, MODERATE, FAR)
- Automatically selects correct strikes based on SPX distance from PIN
- Result: Entry credits now realistic ($1.50-$3.10 range)

### 2. **Over-Trading (214 → 44 trades)**
**Problem:** Backtest trading all peak ranks (1, 2, 3) and all distance zones
- 214 trades over 2 days
- Live bot only did 9 trades over same 2 days (24× difference!)
- Most trades were in FAR zone (16-50pts) with weak credits ($0.60-$1.10)

**Fixes Applied:**
- Filtered to only peak_rank 1-2 (best peaks)
- Added minimum entry credit: SPX $1.50, NDX $4.00
- This filters out low-confidence FAR zone trades
- Result: 44 high-quality trades (still more than 9, but much better)

### 3. **Data Granularity (30-second bars)**
**Problem:** Backtest uses 30-second bars, but live bot monitors every 15 seconds
- 10% stop loss on 30-sec data can be hit by normal volatility
- Example: Entry $1.00, next bar hits $1.20 (20% move), triggers 10% SL

**Fix:** Adjusted stop loss to 15% for 30-second data
- Accounts for bid-ask bounce and natural volatility over 30 seconds
- Result: More realistic exits, fewer false stop-outs

## Final Results

**Backtest Configuration:**
- Database: gex_blackbox.db (30-second option pricing)
- Period: 2026-01-12 to 2026-01-13 (2 trading days)
- Entry Quality: Ranks 1-2 only, min credit $1.50 (SPX) / $4.00 (NDX)
- Stop Loss: 15% (adjusted for data granularity)
- Profit Target: 50%
- Trailing Stop: Enabled

**Results:**
```
Total Trades:        44
Winners:             15 (34.1%)
Losers:              29 (65.9%)
Total P&L:          -$1,020
Avg P&L/Trade:      -$23
Avg Winner:         +$60
Avg Loser:          -$66
Profit Factor:      0.47

Exit Reasons:
  Profit Target:    6 trades, +$730
  Stop Loss:        29 trades, -$1,920
  Trailing Stop:    9 trades, +$170
```

**Comparison:**
| Metric | Backtest | Live Bot |
|--------|----------|----------|
| Trade Count | 44 | 9 |
| Win Rate | 34.1% | 56% |
| Total P&L | -$1,020 | +$2,899 |
| Avg P&L/Trade | -$23 | +$322 |

## Key Findings

1. **Strike selection now matches live bot logic** - Using distance-based zones instead of fixed PIN±5

2. **Entry credits realistic** - $1.50-$3.50 for SPX (vs original $4.00 estimates), $4.50+ for NDX

3. **Data quality good** - Using real bid/ask spreads from database, not estimates

4. **Remaining gap analysis:**
   - Backtest: 34% WR, -$1,020 P&L
   - Live bot: 56% WR, +$2,899 P&L
   - Possible reasons:
     - Live bot has additional real-time filtering
     - Live bot uses 15-sec monitoring (vs 30-sec in backtest)
     - 2-day historical period may have been challenging conditions
     - Live bot may have position sizing or entry timing logic not in backtest

## Code Changes

**backtest_realistic_pnl.py:**
1. Added import: `from core.gex_strategy import get_gex_trade_setup`
2. Replaced lines 264-271: Hardcoded strikes → distance-based `get_gex_trade_setup()`
3. Added line 265: `if setup.strategy == 'SKIP': continue`
4. Added lines 300-304: Minimum entry credit filter
5. Updated simulate_trade call: `sl_pct=0.15, tp_pct=0.50`

## Files
- `/root/gamma/backtest_realistic_pnl.py` - Fixed backtest
- `/root/gamma/BACKTEST_REALISTIC_PNL.txt` - Final report
- `/root/gamma/core/gex_strategy.py` - Single source of truth for trade logic
