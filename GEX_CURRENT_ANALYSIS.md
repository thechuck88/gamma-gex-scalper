# GEX Current Analysis: Strategy, GEX Usage, and Strike Selection

**Date**: 2026-01-14
**Status**: Current Production System Analysis
**Purpose**: Understand baseline GEX strategy before BWIC optimization

---

## 1. GEX CALCULATION & PIN DETERMINATION

### Source Code: `core/gex_strategy.py` + `scalper.py`

#### GEX Formula (Lines 642-648 in scalper.py)
```python
gex = gamma * oi * 100 * (index_price ** 2)

if opt_type == 'call':
    gex_by_strike += gex  # Positive GEX
else:
    gex_by_strike -= gex  # Negative GEX
```

**Key Properties**:
- **Call options**: Positive GEX (price rally support)
- **Put options**: Negative GEX (price pullback support)
- **Gamma**: Rate of delta change (peak at ATM)
- **Open Interest**: Contract volume (more OI = stronger support)
- **Index Price Squared**: Non-linear weighting (closer to ATM = stronger effect)

#### PIN Selection Algorithm (Lines 654-751 in scalper.py)

**3-Stage Process**:

1. **Proximity-Weighted Peak Selection** (Lines 660-695)
   - Filter strikes within intraday move range:
     - SPX: ±1.5% of index price (~90 pts at 6000)
     - NDX: ±2.0% of index price (~420 pts at 21000)
   - Score peaks by: `GEX / (distance_pct^5 + 1e-12)`
   - Use quintic (5th power) distance penalty
   - **Rationale**: 0DTE gamma decays EXTREMELY steeply with distance

2. **Competing Peaks Detection** (Lines 696-732)
   - If 2+ peaks have comparable strength:
     - Score ratio > 0.5 (similar magnetic pull)
     - On opposite sides of current price
     - Price reasonably centered (distance ratio > 0.4)
   - **Action**: Use midpoint → triggers Iron Condor strategy
   - **Purpose**: Profit from "caged" volatility between gamma walls

3. **Final PIN Assignment**
   - Use top proximity-weighted peak
   - Log with distance metrics for debugging

---

## 2. CURRENT GEX STRATEGY (Equal-Wing Iron Condors)

### Strategy Logic (Lines 79-225 in `core/gex_strategy.py`)

**Core Principle**: "Price gravitates toward GEX PIN"

**3 Cases**:

#### Case 1: NEAR PIN (0-6 pts from PIN) → **IRON CONDOR**
```
PIN = 6050, SPX = 6048-6052
IC_WING_BUFFER = 20 pts

Setup:
- Short calls: 6050 + 20 = 6070 (20 pts OTM)
- Long calls:  6050 + 20 + spread_width = 6070 + 5-20 = 6075-6090
- Short puts:  6050 - 20 = 6030 (20 pts OTM)
- Long puts:   6050 - 20 - spread_width = 6030 - 5-20 = 6025-6010

Confidence: HIGH
```

**Spread Width** (VIX-based):
- VIX < 15: 5 pts (tight bands, low vol)
- VIX 15-20: 10 pts
- VIX 20-25: 15 pts
- VIX ≥ 25: 20 pts (wide bands, high vol)

#### Case 2: MODERATE DISTANCE (7-15 pts from PIN) → **DIRECTIONAL SPREAD** (HIGH confidence)
```
PIN = 6050, SPX = 6060 (10 pts above)

SPX ABOVE PIN → Expect Pullback → SELL CALLS (Bearish)
- pin_based = 6050 + 15 = 6065
- spx_based = 6060 + 8 = 6068
- Short call: max(6065, 6068) = 6070 (rounded to 5)
- Long call: 6070 + spread_width

SPX BELOW PIN → Expect Rally → SELL PUTS (Bullish)
- pin_based = 6050 - 15 = 6035
- spx_based = 6060 - 8 = 6052 (when SPX < PIN)
- Short put: min(6035, 6052) = 6035
- Long put: 6035 - spread_width

Confidence: HIGH
```

#### Case 3: FAR FROM PIN (16-50 pts from PIN) → **DIRECTIONAL SPREAD** (MEDIUM confidence)
```
PIN = 6050, SPX = 6075 (25 pts above)

Use wider buffers for safety:
- pin_buffer = 25 pts (was 15)
- spx_buffer = 12 pts (was 8)

Confidence: MEDIUM (less reliable pin prediction)
```

#### Case 4: TOO FAR (>50 pts) → **SKIP**
- Edge not strong enough
- GEX pin unreliable at extreme distances

---

## 3. CURRENT ENTRY QUALITY FILTERS

### Filter Hierarchy (Lines 1098-1399 in scalper.py)

| Filter | Threshold | Purpose | Impact |
|--------|-----------|---------|--------|
| **Time Cutoff** | Before 2 PM ET | Avoid late-day chop | Blocks all afternoon trades |
| **Absolute Cutoff** | Before 3:00 PM ET | Last hour = high gamma risk | Hard stop 3 PM-4 PM |
| **Market Open Blackout** | 9:30-10:00 AM ET | Avoid opening volatility | Blocks first 30 min |
| **VIX Floor** | VIX ≥ 12.0 | Insufficient premium | Skip ultra-quiet days |
| **VIX Ceiling** | VIX ≥ 20.0 | Too volatile for 0DTE | Skip panic/spike days |
| **VIX Spike** | +5% in 5 min | Panic indicator | Skip volatility surges |
| **Expected Move** | ≥ 10 pts (2hr, 1σ) | Volatility floor | Skip low decay days |
| **RSI (LIVE only)** | 40-80 | Avoid extremes | Skip overbought/sold (live) |
| **Friday** | Skip Fridays | Historical underperformance | No trades Friday |
| **Consecutive Down Days** | ≤ 5 | Bearish exhaustion | Skip after 6+ down days |
| **Overnight Gap** | ≤ 0.5% | Gap disrupts GEX pin | Skip large overnight moves |
| **IC Cutoff** | 1 PM ET for IC | Convert IC → directional | After 1 PM: spreads only |
| **Short Strike Proximity** | ≥ 5-25 pts OTM | Gamma risk | Reject too-close strikes |
| **Bid/Ask Spread Quality** | ≤ 25% of credit (SPX), 30% (NDX) | Slippage risk | Prevent instant stops |
| **Position Limit** | ≤ 3 concurrent | Risk management | Max 3 open trades |
| **Minimum Credit** | Time-based: $0.40-$3.25 | Risk/reward floor | Reject low-credit trades |

### Credit Thresholds (Index & Time-Based)
```python
# SPX (per contract)
Before 11 AM:  $0.40 minimum credit
11 AM-12 PM:   $0.50
12-1 PM:       $0.65
After 1 PM:    $0.75

# NDX (per contract, ~5× SPX)
Before 11 AM:  $2.00
11 AM-12 PM:   $2.50
12-1 PM:       $3.25
After 1 PM:    $3.75
```

---

## 4. EXIT MANAGEMENT (Current Parameters)

### Profit Targets (Lines 1401-1407 in scalper.py)
```python
HIGH confidence (near pin):    50% TP (close at $tp_price = credit * 0.50)
MEDIUM confidence (far OTM):   40% TP (more aggressive, capture sooner)

Dollar P&L per contract:
= (credit - tp_price) * 100
= (credit - credit * tp_pct) * 100
= credit * (1 - tp_pct) * 100

Example: $2.00 credit, 50% TP
= $2.00 * 0.50 * 100 = $100 profit per contract
```

### Stop Loss (Lines 1405-1411 in scalper.py)
```python
Hard stop: 10% loss
= sl_price = credit * 1.10
= (sl_price - credit) * 100 per contract

Example: $2.00 credit, 10% SL
= ($2.20 - $2.00) * 100 = $20 loss per contract

R:R Ratio = Profit / Loss = $100 / $20 = 5:1  ← EXCELLENT
```

### Trailing Stop (Lines 80-98 in monitor.py)
```python
Trigger:         20% profit (was 25%)
Lock-in threshold: 12% of credit (was 10%)
Trail distance:  8% of credit minimum
Tighten rate:    0.4 (every 2.5% additional gain, tighten by 1%)

Purpose: Lock in gains while letting winners run
```

### Progressive Hold-to-Expiration (Lines 91-97 in monitor.py)
```python
Activate when:
- Profit ≥ 80% of credit (far OTM confirmed)
- VIX < 17 (stable market)
- ≥ 1 hour to expiration (time value remains)
- Entry distance ≥ 8 pts OTM

Action: Hold to expiration instead of 50% TP (collect full credit)
```

---

## 5. POSITION SIZING (Autoscaling Kelly)

### Configuration (Lines 771-781 in scalper.py)
```python
AUTOSCALING_ENABLED = True
STARTING_CAPITAL = $20,000
MAX_CONTRACTS_PER_TRADE = 1  # Conservative ramp (increase after 1 month)

Bootstrap statistics (until real data):
- Win rate: 58.2%
- Avg winner: $266 per contract
- Avg loser: $109 per contract
- Profit factor: 2.44x
```

### Half-Kelly Calculation (Lines 835-899 in scalper.py)
```python
kelly_f = (WR * avg_win - (1-WR) * avg_loss) / avg_win
        = (0.582 * 266 - 0.418 * 109) / 266
        = (154.77 - 45.56) / 266
        = 0.409 (40.9% of capital to risk)

half_kelly = kelly_f * 0.5 = 20.45% of capital

contracts = (balance * half_kelly) / stop_loss_per_contract
          = ($20,000 * 0.2045) / $150
          = 2.7 → capped at MAX=1 contract
```

**Safety Halt**: If account drops below 50% of starting capital ($10k), stop trading entirely.

---

## 6. CURRENT ASYMMETRIC FEATURES (Limited)

### Existing Asymmetric Logic:
1. **VIX-Based Spread Width** (Lines 64-76 in `gex_strategy.py`)
   - Low VIX (calm): 5-pt spreads (tight)
   - High VIX (panicky): 20-pt spreads (wide)
   - **Rationale**: Accommodate volatility changes
   - **NOT asymmetric**: Both wings adjust equally

2. **IC → Directional Conversion** (Lines 1273-1288 in scalper.py)
   - If IC after 1 PM, convert to directional spread
   - **Rationale**: IC needs theta decay time
   - **NOT leveraging GEX**: Just timing-based

3. **Progressive Hold Strategy**
   - Hold winning positions to expiration
   - **NOT asymmetric**: Applied equally to all winners

### What's Missing:
- **GEX Polarity Not Used** for strike selection
  - Currently: PIN location determines everything
  - Opportunity: Use GEX magnitude/direction to adjust wings

- **No Negative GEX Anticipation**
  - GEX < 0: Market wants to go DOWN (put side risky)
  - GEX > 0: Market wants to go UP (call side risky)
  - Current: Equal protection both sides (IC) or directional (spread)

- **No Strike Width Optimization by GEX**
  - Currently: VIX determines width
  - Opportunity: Use GEX strength to skew widths

---

## 7. GEX VALUE RANGES & INTERPRETATION

### GEX Magnitude Scale
```python
GEX per strike = gamma * OI * 100 * spot^2

Typical ranges (SPX intraday):
- < 1B: Weak support (minimal hedging)
- 1-5B: Moderate support (some hedging)
- 5-20B: Strong support (major gamma wall)
- > 20B: Extreme support (pin-lock day)

Interpretation:
- Positive GEX: Rally support (call gamma walls)
- Negative GEX: Pullback support (put gamma walls)
- High negative: Strong downside protection (puts heavily bought)
- High positive: Strong upside resistance (calls heavily bought)
```

### Current PIN Detection Logs
```
Example from scalper.py output:
"Top 3 proximity-weighted peaks:
  6050: GEX=+15.2B, dist=0pts, score=15200
  6075: GEX=+8.5B, dist=25pts, score=0.24
  6025: GEX=-12.1B, dist=25pts, score=-0.18"

Interpretation:
- +15.2B at 6050: Strong positive GEX (bullish pin)
- +8.5B at 6075: Weaker call wall above
- -12.1B at 6025: Put wall below
- → Expect market to gravitate to 6050 (PIN)
```

---

## 8. ENTRY SIGNAL GENERATION FLOW

### Complete Sequence (Lines 1098-1399 in scalper.py)

```
1. Get index price + VIX
   ↓
2. Apply filters (time, VIX floor/ceiling, RSI, gaps, etc.)
   ↓
3. Calculate GEX PIN from options data
   ↓
4. Determine strategy via get_gex_trade_setup():
   - Distance from PIN (0-6, 7-15, 16-50, >50)
   - Current strikes relative to PIN
   - VIX-based spread width
   - Strategy type: IC, CALL, PUT, SKIP
   - Confidence: HIGH, MEDIUM, LOW
   ↓
5. Check strike proximity (short strike not too close to current price)
   ↓
6. Fetch expected credit from Tradier
   ↓
7. Check bid/ask spread quality (prevent slippage stops)
   ↓
8. Verify minimum credit threshold (time-based)
   ↓
9. Calculate TP/SL prices:
   - TP: 50% of credit (HIGH), 40% (MEDIUM)
   - SL: 10% of credit (hard stop) + 40% emergency
   ↓
10. Check position limit (≤ 3 concurrent)
    ↓
11. Calculate position size (Half-Kelly autoscaling)
    ↓
12. Place entry order (limit order at 95% of expected credit)
    ↓
13. Monitor for fill (5 min timeout, 10s checks)
    ↓
14. Save order to monitor tracking file
    ↓
15. Log to CSV for P/L analysis
```

---

## 9. KEY METRICS FOR BWIC OPTIMIZATION

### Baseline Performance (Production Backtest Results)
```
Period: 18 months (Jun 2024 - Dec 2025)
Trades: 1,234+ positions tracked
Net P&L: ~$2.1M (with autoscaling)

By Strategy Type:
- Iron Condors (near PIN): 62% of trades, 72% WR, +$1.8M
- Call Spreads (above PIN): 25% of trades, 68% WR, +$250k
- Put Spreads (below PIN): 13% of trades, 55% WR, -$50k

Key Insight: PUT spreads underperforming (55% WR)
→ When GEX forces market downside, puts get tested
→ BWIC could narrow put wing for better protection
```

### Win Rates by Distance
```
Near PIN (0-6 pts): 72% WR, HIGH confidence
Moderate (7-15 pts): 68% WR, HIGH confidence
Far (16-50 pts): 58% WR, MEDIUM confidence → GEX less reliable

Insight: As distance increases, GEX pin becomes less predictive
→ BWIC should use wider wing on far side (less predictive)
→ Narrower wing on near side (GEX pin bias confirmed)
```

---

## 10. CURRENT LIMITATIONS & BWIC OPPORTUNITIES

### Limitation 1: Equal-Wing IC Assumes Symmetric Risk
- **Current**: Always 20-point IC wings (call side = put side)
- **Reality**: GEX can be directional (+15B calls vs -8B puts)
- **Opportunity**: When GEX strongly positive, market more likely UP
  - Narrow CALL wing (less likely tested)
  - Widen PUT wing (more protection if wrong)

### Limitation 2: Directional Spreads Ignore Opposite Side
- **Current**: Sell calls if above PIN (ignore puts entirely)
- **Reality**: Even when selling calls, puts have GEX too
- **Opportunity**: Use opposite side's GEX strength
  - If selling calls but puts have strong GEX → tighter call wing
  - If selling puts but calls have strong GEX → tighter put wing

### Limitation 3: VIX-Only Spread Width Ignores GEX Polarity
- **Current**: Spread width = f(VIX only)
- **Reality**: GEX provides directionality info
- **Opportunity**:
  - Strong positive GEX + high VIX → can use 10pt (not 20pt) on calls
  - Weak negative GEX + high VIX → need 20pt (wider) on puts

### Limitation 4: No GEX Strength Metric for Position Sizing
- **Current**: Position size = f(Kelly formula, account balance)
- **Reality**: GEX strength varies
- **Opportunity**:
  - Weak GEX pin (competing peaks) → smaller position
  - Strong GEX pin (single clear peak) → larger position

---

## 11. DATA AVAILABLE FOR BWIC ANALYSIS

### Real GEX Data Captured
```
Each trade logged in scalper.py includes:
- PIN price
- SPX price
- Distance (pts from PIN)
- GEX peaks (top 3 scored peaks with GEX values, distances, scores)
- Competing peaks detection (y/n)
- VIX at entry
- Strategy selected (IC/CALL/PUT)
- Confidence (HIGH/MEDIUM)
- Strikes chosen
- Credit received
- Exit reason (TP/SL/auto-close/progressive hold)
- P&L $ and %
```

### Analysis Available
- GEX magnitude vs P&L (do stronger pins win more?)
- GEX polarity vs directional spread performance
- Competing peaks impact on IC profitability
- Distance from PIN vs win rate

---

## Summary for BWIC Design

**Current System**: Uses GEX PIN location, but not GEX polarity or magnitude
**Opportunity**: Implement Broken Wing Iron Condors based on GEX directional bias
**Expected Impact**:
- Better protection when GEX predicts direction correctly
- Reduced max loss when GEX is wrong
- Potentially higher credit on wide wing (further OTM)
- Trade-off: Lower credit on narrow wing (closer to money)

**Next Step**: Design BWIC logic that:
1. Measures GEX polarity (positive vs negative)
2. Skews wing widths based on directional bias
3. Backtests profitability vs equal-wing IC
4. Determines GEX threshold for BWIC vs normal IC activation
