# Observation Period - Pre-Trade Risk Filter

## Overview

The observation period is a "look before you leap" filter that monitors price action for 1-2 minutes **before** placing the actual trade. It detects dangerous market conditions that would likely cause emergency stops.

**Created**: 2026-02-10
**Status**: Available, disabled by default

## Problem It Solves

Sometimes GEX pin setups pass all filters but the market is already moving fast or volatile. By the time the order fills, we're immediately underwater and hit the emergency stop. The observation period catches these scenarios before we enter.

## How It Works

1. **GEX pin signal detected** - All normal filters pass
2. **Enter observation mode** - Record SPX price, start timer
3. **Monitor for 90 seconds** - Check SPX price every 2 seconds (45 data points)
4. **Analyze movement patterns**:
   - **Volatility**: Price range vs spread width
   - **Choppiness**: Number of direction reversals
   - **Emergency stop proximity**: Would we get stopped out?
   - **Velocity**: How fast is price moving?
5. **Make decision**:
   - ✅ **SAFE** → Place actual trade
   - 🚫 **DANGEROUS** → Skip trade, log reason

## Detection Criteria

### 1. High Volatility (Range Check)
- **Metric**: Price range during observation period
- **Threshold**: Default 15% of spread width
- **Example**: For 10-point spread, max range = 1.5 points
- **Why dangerous**: Wide swings mean entry slippage + immediate stop risk

### 2. Choppy Movement (Direction Changes)
- **Metric**: Number of price reversals (peaks/valleys)
- **Threshold**: Default 5 changes in 90 seconds
- **Example**: Price goes up-down-up-down repeatedly
- **Why dangerous**: Erratic movement breaks GEX pin assumption

### 3. Emergency Stop Territory
- **Metric**: Maximum loss % during observation
- **Threshold**: Default 40% (emergency stop level)
- **Example**: Price moves against us enough to trigger 40% stop
- **Why dangerous**: Would get stopped out immediately after entry

### 4. Fast-Moving Market (Velocity)
- **Metric**: Average price change per second
- **Threshold**: Default 0.5 points/second (30 pts/min)
- **Example**: Price moving 1+ point every 2 seconds
- **Why dangerous**: Trending market overwhelms GEX pin effect

## Configuration

### Environment Variables

Add to `/etc/gamma.env`:

```bash
# Enable observation period (default: false)
GAMMA_OBSERVATION_ENABLED=true

# Observation duration in seconds (default: 90)
GAMMA_OBSERVATION_PERIOD_SECONDS=90

# Max price range as % of spread width (default: 0.15 = 15%)
GAMMA_OBSERVATION_MAX_RANGE_PCT=0.15

# Max direction changes (default: 5)
GAMMA_OBSERVATION_MAX_DIRECTION_CHANGES=5

# Emergency stop threshold (default: 0.40 = 40%)
GAMMA_OBSERVATION_EMERGENCY_STOP_THRESHOLD=0.40

# Seconds between price checks (default: 2.0)
GAMMA_OBSERVATION_MIN_TICK_INTERVAL=2.0
```

### Testing Different Sensitivities

**Conservative (fewer trades, higher safety)**:
```bash
GAMMA_OBSERVATION_MAX_RANGE_PCT=0.10        # Tighter (10% instead of 15%)
GAMMA_OBSERVATION_MAX_DIRECTION_CHANGES=3   # Fewer reversals allowed
GAMMA_OBSERVATION_PERIOD_SECONDS=120        # Longer observation (2 min)
```

**Aggressive (more trades, less filtering)**:
```bash
GAMMA_OBSERVATION_MAX_RANGE_PCT=0.20        # Wider (20%)
GAMMA_OBSERVATION_MAX_DIRECTION_CHANGES=8   # More reversals allowed
GAMMA_OBSERVATION_PERIOD_SECONDS=60         # Shorter observation (1 min)
```

## Integration with Scalper

The observation period runs **after** all other filters pass but **before** sending the order:

```
1. GEX pin detected
2. Credit safety check ✓
3. Market momentum check ✓
4. Position limit check ✓
5. → OBSERVATION PERIOD (NEW)
6. Calculate position size
7. Send order
```

If observation fails, the trade is skipped and logged with reason.

## Logging and Analysis

### Decision Log

All observation decisions are logged to:
```
/root/gamma/data/observation_decisions.jsonl
```

Format:
```json
{
  "timestamp": "2026-02-10 14:35:00",
  "is_safe": false,
  "reason": "High volatility: 18.5% > 15.0% threshold",
  "observation_enabled": true,
  "duration_seconds": 90,
  "prices_tracked": 45,
  "price_high": 5825.75,
  "price_low": 5823.90,
  "price_range": 1.85,
  "direction_changes": 3,
  "start_time": "2026-02-10 14:33:30",
  "end_time": "2026-02-10 14:35:00"
}
```

### Analysis Queries

**Count observations by result**:
```bash
jq -s 'group_by(.is_safe) | map({result: (.[0].is_safe | if . then "SAFE" else "DANGEROUS" end), count: length})' \
  /root/gamma/data/observation_decisions.jsonl
```

**Find what causes failures**:
```bash
jq -s '[.[] | select(.is_safe == false) | .reason] | group_by(.) | map({reason: .[0], count: length}) | sort_by(.count) | reverse' \
  /root/gamma/data/observation_decisions.jsonl
```

**Average metrics**:
```bash
jq -s '[.[] | {range: .price_range, changes: .direction_changes}] |
  {avg_range: (map(.range) | add / length), avg_changes: (map(.changes) | add / length)}' \
  /root/gamma/data/observation_decisions.jsonl
```

## Testing

### Unit Test
```bash
cd /root/gamma
python3 test_observation_period.py
```

This runs two tests:
1. **Normal conditions** - Should pass observation
2. **Tight thresholds** - Should fail (simulates volatile market)

### Live Test (Disabled Entry)

To test observation without placing trades:

1. Enable observation in `/etc/gamma.env`:
   ```bash
   GAMMA_OBSERVATION_ENABLED=true
   ```

2. Run scalper in paper mode and watch logs:
   ```bash
   python3 scalper.py --paper
   ```

3. Check observation decisions:
   ```bash
   tail -f /root/gamma/data/observation_decisions.jsonl
   ```

## Performance Impact

### Backtest Analysis (Recommended)

Before enabling in production, backtest with historical data:

1. **Collect observation decisions** for 1-2 weeks (enabled, no trades blocked)
2. **Analyze what % would be blocked** and why
3. **Compare P&L impact**:
   - Trades that would've been blocked vs actual outcomes
   - Did observation prevent emergency stops?
   - False positives (safe trades blocked)?

### Expected Impact

**Best case**:
- Prevents 20-30% of trades that hit emergency stops
- Minor reduction in total trades (5-10%)
- Significant improvement in profit factor

**Worst case**:
- Blocks too many trades (>20% of valid setups)
- False positives cost winning trades
- Net negative impact on P&L

**Tuning**: Adjust thresholds based on backtest results.

## Failure Modes and Safety

### What if price fetch fails?
- Observation fails safe → Trade skipped
- Error logged to console and Discord
- Never enters trade without observation data

### What if API is slow?
- Extends observation period slightly (tolerance built in)
- Still gets required number of data points
- Decision based on actual data collected

### What if observation contradicts other filters?
- Observation is the FINAL filter before entry
- If observation fails, trade is skipped (overrides earlier approvals)
- Logged separately for analysis

## Discord Alerts

When observation blocks a trade:

```
🚫 GEX Scalper - Trade Skipped

Observation period failed: High volatility: 18.5% > 15.0% threshold

Setup: PUT spread 5820/5810 (MEDIUM confidence)
Credit: $2.45 expected
SPX: 5823.50, VIX: 14.2

Observation summary:
- Duration: 90s
- Price range: 1.85 points
- Direction changes: 3
- Max loss during observation: 12%

Reason: Market conditions too dangerous for entry
```

## Recommendations

### Phase 1: Data Collection (Week 1)
- Enable observation with default settings
- **Don't block trades yet** - just log decisions
- Analyze what would've been blocked
- Check if blocked trades would've hit stops

### Phase 2: Conservative Testing (Week 2)
- Enable blocking with **tight thresholds**:
  - MAX_RANGE_PCT = 0.10 (very conservative)
  - MAX_DIRECTION_CHANGES = 3
- Monitor P&L impact vs baseline
- Adjust thresholds based on data

### Phase 3: Production (Week 3+)
- Use recommended settings (defaults)
- Continue monitoring blocked vs completed trades
- Fine-tune thresholds quarterly based on market regime

## Related Files

- **Implementation**: `/root/gamma/observation_period.py`
- **Configuration**: `/root/gamma/config.py`
- **Integration**: `/root/gamma/scalper.py` (lines ~2160-2210)
- **Tests**: `/root/gamma/test_observation_period.py`
- **Logs**: `/root/gamma/data/observation_decisions.jsonl`

## Credits

Inspired by user request 2026-02-10:
> "can i add some code that 'simulates' a gex pin entry, and watches 1 or 2 minutes
> and tries to determine if the price movement is indicative of a dangerous trade"

**Status**: ✅ Implemented, 🔍 Testing recommended before production use
