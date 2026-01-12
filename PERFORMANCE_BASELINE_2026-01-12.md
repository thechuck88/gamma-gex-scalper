# Gamma GEX Strategy - Performance Baseline (Jan 12, 2026)

## Starting Point - Clean Slate

**Date Started**: January 12, 2026
**Reason**: Prior bot issues resolved, backtest found to be unreliable (fake GEX, inflated trade count)
**Goal**: Measure REAL performance with REAL GEX calculations going forward

---

## Starting Capital
- **Paper Account**: $20,000 (reset Jan 10, 2026)
- **Live Account**: TBD (when deployed)

---

## Backtest Claims vs Reality Check

### Backtest Results (UNRELIABLE)
- **Method**: Fake GEX pins (`gex_pin = spx_price + random.uniform(-10, 10)`)
- **Trade Frequency**: 2,834 trades over 723 days = **3.9 trades/day**
- **Win Rate**: 58.2%
- **Total Return**: +12,408% over 3 years
- **Final Balance**: $3.1M from $25k

### Why Backtest is Unreliable
1. ❌ **No real GEX calculation** - just random pins ±10pts from SPX
2. ❌ **Assumes 70% setup rate** - massively inflates trade count
3. ❌ **Ignores selectivity** - live bot only trades when dominant GEX peak exists
4. ❌ **No historical options OI data** - cannot reconstruct true gamma landscape

### What We Expect from Live Trading
- **Trade Frequency**: 0-2 trades/day (depends on clear GEX pin)
- **Many zero-trade days**: No trade if no dominant gamma peak
- **Win Rate**: Unknown (backtest unreliable)
- **Profit Factor**: Unknown (backtest unreliable)

---

## Real Strategy Edge (If It Exists)

The strategy depends on:
1. **GEX Pin Effect**: Market makers hedge gamma by buying/selling deltas, creating magnetic pull toward high OI strikes
2. **0DTE Theta Decay**: Options lose value rapidly in final hours
3. **Directional Bias**: Price gravitates toward the pin → fade moves away from pin

**Critical Question**: Does this edge exist in live markets?

**Answer Method**: Forward testing only - no backtests can validate without historical OI data

---

## Performance Tracking

### Key Metrics to Track
1. **Trade Frequency**: Trades/day (expect 0-2, not 3.9)
2. **Win Rate**: % of profitable trades
3. **Profit Factor**: Gross wins / gross losses
4. **Average Win vs Avg Loss**: R:R ratio
5. **Max Drawdown**: Largest equity peak-to-trough
6. **Days with valid GEX setup**: % of days bot finds tradeable pin

### Red Flags to Watch For
- **No trades for weeks**: Strategy may be too selective (or GEX pin not reliable)
- **Win rate < 40%**: Strategy edge doesn't exist
- **Profit factor < 1.5**: Risk/reward not favorable
- **Frequent stop losses**: Entry timing or strike selection flawed

### Success Criteria (30 days minimum)
- ✅ **Positive P&L** after 30+ days
- ✅ **Win rate > 50%** (need edge over coin flip)
- ✅ **Profit factor > 2.0** (wins 2x larger than losses)
- ✅ **Consistent trade flow** (1-2 trades/day on average)

---

## Current Status

**Last Trade**: Dec 18, 2025 (paper account)
**Days Since Last Trade**: 25 days
**Current Balance**: $20,000 (paper)
**Total Trades (2026)**: 0

**Bot Status**:
- Live monitor: Running
- Paper monitor: Running
- Scalper cron: Scheduled (9:36 AM - 2 PM ET, every 30 min)

**Next Steps**:
1. Monitor logs for trade entries (check for GEX pin calculations)
2. Track win/loss pattern over 30+ days
3. Compare actual trade frequency to backtest assumptions
4. Decide on live deployment only after consistent paper profitability

---

## Log Analysis Commands

```bash
# Check if scalper is running (finding valid GEX pins)
tail -f /root/gamma/data/monitor_paper.log

# Check recent trade results
tail -20 /root/gamma/data/trades.csv

# Check account balance
cat /root/gamma/data/account_balance.json

# Check for GEX calculation logs
grep "GEX PIN calculated" /root/gamma/data/monitor_paper.log | tail -10

# Count trades per day
awk -F, 'NR>1 {print $1}' /root/gamma/data/trades.csv | cut -d' ' -f1 | uniq -c
```

---

## Decision Tree (After 30 Days)

```
IF trades_per_day < 0.5:
    → Strategy too selective, GEX pin not reliable enough

ELIF win_rate < 40%:
    → No edge exists, abandon strategy

ELIF profit_factor < 1.5:
    → Risk/reward unfavorable, adjust parameters or abandon

ELIF positive_pnl AND win_rate > 50% AND profit_factor > 2.0:
    → Strategy validated, consider live deployment

ELSE:
    → Continue monitoring for another 30 days
```

---

**Status**: 🟡 **VALIDATION PHASE** - Monitoring live performance with real GEX
**Last Updated**: January 12, 2026
