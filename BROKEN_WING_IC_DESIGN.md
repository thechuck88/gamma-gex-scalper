# Broken Wing Iron Condor (BWIC) Design for GEX Scalper

**Date**: 2026-01-14
**Status**: Design & Implementation Plan
**Target**: 5-10% improvement in Sharpe ratio and max drawdown reduction

---

## 1. EXECUTIVE SUMMARY: BWIC THEORY

### What is a Broken Wing Iron Condor?

**Traditional Iron Condor** (Equal Wings):
```
                Current Index Price (6050)
                        │
        ────────────────┼────────────────
        │               │               │
     Puts             AT PIN           Calls
   [Sold]             [None]           [Sold]
      │                               │
   6030/6010                        6070/6090
    10pts                            10pts OTM
   (equal)                          (equal)

Risk: Symmetric — equal protection on both sides
Profit: ~$100-200 per contract (full credit width)
```

**Broken Wing Iron Condor** (Asymmetric Wings):
```
                Current Index Price (6050)
                        │
        ───────────┬────┴────┬───────────
        │          │         │          │
     Puts        PUT PIN   CALL PIN   Calls
    Sold        (narrow)   (wide)     Sold
      │                               │
   6040/6030                        6080/6100
    10pts                            20pts OTM
   (NARROW)                         (WIDE)

Risk: Asymmetric — tighter protection where market MORE likely to move
Profit: $50-100 per narrow wing + $50-100 per wide wing
```

### Key Insight: GEX Provides Directional Bias

**GEX Positive (Calls > Puts)**: Market wants to go UP
- Call side has MORE support (gamma walls)
- Market less likely to exceed call wing
- Safe to use NARROW call wing (10-15 pts)
- Put side should be WIDE (15-20 pts) — prepare for unexpected down

**GEX Negative (Puts > Calls)**: Market wants to go DOWN
- Put side has MORE support (gamma walls)
- Market less likely to exceed put wing
- Safe to use NARROW put wing (10-15 pts)
- Call side should be WIDE (15-20 pts) — prepare for unexpected up

---

## 2. MATHEMATICAL FRAMEWORK

### GEX Polarity Index (GPI)

**Definition**:
```
GPI = (Positive_GEX - Negative_GEX) / (Positive_GEX + Negative_GEX)

Range: -1.0 to +1.0
- GPI = +1.0: Pure positive GEX (bullish, all calls)
- GPI = +0.5: 75% positive, 25% negative (moderately bullish)
- GPI =  0.0: Balanced positive/negative (neutral)
- GPI = -0.5: 75% negative, 25% positive (moderately bearish)
- GPI = -1.0: Pure negative GEX (bearish, all puts)
```

### GEX Magnitude (Strength)

**Definition**:
```
MAGNITUDE = (|Positive_GEX| + |Negative_GEX|) / 2

Interpretation:
- < 1B: Weak GEX (PIN unreliable)
- 1-5B: Moderate (normal day)
- 5-20B: Strong (confident PIN)
- > 20B: Extreme (total pin-lock)

Usage: Can modulate position size
- Weak GEX → smaller position
- Strong GEX → larger position
```

### Win Probability Adjustment

**Current Model**:
```
P(Near PIN) = 0.58 (baseline from backtest)
```

**With GEX Bias**:
```
P(rally succeeds | GPI=+0.5) = 0.58 * (1 + 0.5) = 0.87
P(rally fails | GPI=+0.5) = 1 - 0.87 = 0.13

P(pullback succeeds | GPI=-0.5) = 0.58 * (1 - 0.5) = 0.29
P(pullback fails | GPI=-0.5) = 1 - 0.29 = 0.71
```

---

## 3. WING WIDTH SELECTION ALGORITHM

### Step 1: Calculate GEX Polarity

**Input**: GEX values at top 3 peaks (from scalper.py)

```python
def calculate_gex_polarity(gex_peaks):
    """
    gex_peaks: list of (strike, gex_magnitude) tuples

    Returns: (gpi, direction)
    - gpi: -1 to +1 polarity index
    - direction: 'BULL', 'BEAR', 'NEUTRAL'
    """
    if not gex_peaks:
        return 0.0, 'NEUTRAL'

    positive_gex = sum(g for _, g in gex_peaks if g > 0)
    negative_gex = abs(sum(g for _, g in gex_peaks if g < 0))

    total = positive_gex + negative_gex
    if total == 0:
        return 0.0, 'NEUTRAL'

    gpi = (positive_gex - negative_gex) / total

    if gpi > 0.2:
        direction = 'BULL'
    elif gpi < -0.2:
        direction = 'BEAR'
    else:
        direction = 'NEUTRAL'

    return gpi, direction
```

### Step 2: Determine Wing Widths

**Logic**:

```python
def get_bwic_wing_widths(gpi, vix, gex_magnitude=None, use_bwic=True):
    """
    Determine call and put wing widths based on GEX polarity.

    Args:
        gpi: GEX Polarity Index (-1 to +1)
        vix: VIX level (determines base width)
        gex_magnitude: Optional GEX strength (for validation)
        use_bwic: If False, return equal wings (normal IC)

    Returns: (call_width, put_width) in points
    """

    # Base widths from VIX (existing logic)
    if vix < 15:
        base_width = 5
    elif vix < 20:
        base_width = 10
    elif vix < 25:
        base_width = 15
    else:
        base_width = 20

    # If not using BWIC or GEX is neutral, use equal wings
    if not use_bwic or abs(gpi) < 0.2:  # GEX_THRESHOLD = 0.2
        return base_width, base_width

    # BWIC asymmetric sizing
    # Ratio: narrow wing = base - offset, wide wing = base + offset
    # Offset scales with GPI strength
    offset = base_width * 0.5 * abs(gpi)  # 0 to 50% adjustment

    narrow_width = max(base_width // 2, base_width - int(offset))  # Min 2-3 pts
    wide_width = base_width + int(offset)

    if gpi > 0.2:  # Bullish GEX
        # Narrow call wing (rally expected), wide put wing (downside protection)
        return narrow_width, wide_width
    else:  # Bearish GEX (gpi < -0.2)
        # Wide call wing (downside cushion), narrow put wing (pullback expected)
        return wide_width, narrow_width
```

### Example Calculations

**Scenario 1: Strong Bullish GEX (GPI = +0.7)**
```
VIX = 18 → base_width = 10
GPI = +0.7 → bullish

offset = 10 * 0.5 * 0.7 = 3.5 ≈ 3

Call wing (narrow): 10 - 3 = 7 pts (expect rally, less protection needed)
Put wing (wide):    10 + 3 = 13 pts (downside shock cushion)

Setup (at PIN 6050):
- Calls: 6070/6077C (7pt spread, narrower)
- Puts:  6037/6050P (13pt spread, wider)
```

**Scenario 2: Strong Bearish GEX (GPI = -0.8)**
```
VIX = 18 → base_width = 10
GPI = -0.8 → bearish

offset = 10 * 0.5 * 0.8 = 4

Call wing (wide):   10 + 4 = 14 pts (expect pullback, more cushion up)
Put wing (narrow):  10 - 4 = 6 pts (less room down, tighter protection)

Setup (at PIN 6050):
- Calls: 6070/6084C (14pt spread, wider)
- Puts:  6044/6050P (6pt spread, narrower, right at PIN)
```

**Scenario 3: Neutral GEX (GPI = 0.0)**
```
VIX = 18 → base_width = 10
GPI = 0.0 → neutral

offset = 0 → equal wings

Call wing: 10 pts
Put wing:  10 pts

Setup (normal IC):
- Calls: 6070/6080C
- Puts:  6040/6050P
```

---

## 4. WHEN TO USE BWIC VS NORMAL IC

### Decision Tree

```
get_gex_trade_setup() called with PIN and SPX prices
│
├─ Is SPX within 6 pts of PIN? → Yes
│  └─ Use Iron Condor strategy
│     │
│     ├─ GEX magnitude > threshold (5B)?
│     │  └─ Yes: Calculate GPI
│     │     └─ |GPI| > 0.2?
│     │        ├─ Yes: Use BWIC (asymmetric)
│     │        └─ No: Use normal IC (symmetric)
│     │
│     └─ No (weak GEX): Use normal IC
│
└─ No
   └─ Use directional spread (CALL or PUT)
      └─ GEX still helps: predict which spread more likely to win
```

### Configuration Constants

```python
# Thresholds for BWIC activation
USE_BWIC_FOR_IC = True              # Enable BWIC strategy
GPI_THRESHOLD = 0.20                # |GPI| > 0.2 triggers BWIC
GEX_MAGNITUDE_MIN = 5e9             # Minimum 5B GEX for confidence
COMPETING_PEAKS_THRESHOLD = 0.5     # Score ratio > 0.5 = competing

# When NOT to use BWIC
DISABLE_BWIC_CONDITIONS = [
    ('competing_peaks', True),        # Competing peaks = uncertain, use normal IC
    ('vix', lambda v: v > 25),        # Extreme VIX = hard to predict
    ('distance_from_pin', lambda d: d > 10)  # Far from PIN = weak edge
]
```

---

## 5. STRIKE SELECTION WITH BWIC

### Modified get_gex_trade_setup() Flow

```python
def get_gex_trade_setup_bwic(pin_price, spx_price, vix,
                               gex_peaks, use_bwic=True,
                               vix_threshold=20.0):
    """
    Enhanced version with BWIC support.

    Args:
        pin_price: GEX PIN
        spx_price: Current index price
        vix: VIX level
        gex_peaks: List of (strike, gex) tuples (from GEX calculation)
        use_bwic: Enable BWIC (default True)
        vix_threshold: Skip if VIX >= this

    Returns:
        GEXTradeSetup with asymmetric wings if BWIC triggered
    """

    # STEP 1: Existing checks
    if vix >= vix_threshold:
        return SKIP

    distance = spx_price - pin_price

    # STEP 2: Only IC case uses BWIC
    if abs(distance) <= NEAR_PIN_MAX:  # 6 pts

        # Calculate GEX properties
        gpi, direction = calculate_gex_polarity(gex_peaks)
        gex_magnitude = sum(abs(g) for _, g in gex_peaks)

        # STEP 3: Determine if BWIC qualifies
        should_use_bwic = (
            use_bwic and
            abs(gpi) >= GPI_THRESHOLD and
            gex_magnitude >= GEX_MAGNITUDE_MIN and
            not has_competing_peaks(gex_peaks)
        )

        # STEP 4: Get wing widths
        call_width, put_width = get_bwic_wing_widths(
            gpi, vix, gex_magnitude, use_bwic=should_use_bwic
        )

        # STEP 5: Calculate strikes using ASYMMETRIC widths
        ic_buffer = IC_WING_BUFFER

        # Calls (may be narrow for bullish, wide for bearish)
        call_short = round_to_5(pin_price + ic_buffer)
        call_long = round_to_5(call_short + call_width)

        # Puts (may be narrow for bearish, wide for bullish)
        put_short = round_to_5(pin_price - ic_buffer)
        put_long = round_to_5(put_short - put_width)

        # STEP 6: Build result
        return GEXTradeSetup(
            strategy='IC',
            strikes=[call_short, call_long, put_short, put_long],
            direction='NEUTRAL',
            distance=distance,
            confidence='HIGH',
            description=f'{"BWIC" if should_use_bwic else "IC"}: '
                       f'{call_short}/{call_long}C ({call_width}pt) + '
                       f'{put_short}/{put_long}P ({put_width}pt) '
                       f'[GPI={gpi:+.2f}]',
            spread_width=call_width,  # For logging
            vix=vix,
            bwic_enabled=should_use_bwic,
            gpi=gpi,
            call_width=call_width,
            put_width=put_width
        )

    # STEP 7: For directional spreads, still use GPI to adjust confidence
    # (e.g., more confident in call spread if GPI > 0)
    ...
```

---

## 6. CREDIT CALCULATION WITH BWIC

### Asymmetric Credit Expected

**Challenge**: Narrower wing = less credit, wider wing = more credit

**Formula**:
```
Expected Credit = f(narrow_wing_credit) + f(wide_wing_credit)

For BWIC at PIN:
- Narrow wing (closer to money): Higher theta decay, but narrower profit zone
  → $0.50-1.00 per wing
- Wide wing (further OTM): Lower theta decay initially, but wider profit zone
  → $0.30-0.60 per wing

Total Credit = Sum of both wings

Example:
- Narrow call wing (7pts, bullish GEX): $0.70
- Wide put wing (13pts, bullish GEX): $0.40
- Total: $1.10 per contract

vs Normal IC:
- Call wing (10pts): $0.55
- Put wing (10pts): $0.55
- Total: $1.10 per contract

Result: SAME total credit, but distributed asymmetrically
→ Narrower wing needs less gain to hit TP
→ Wider wing has more room to absorb loss
```

### TP/SL Adjustment for BWIC

**Current Model**:
```
TP = 50% of total credit (symmetric)
SL = 10% loss (symmetric)
```

**BWIC Model** (optional, experimental):
```
TP = 50% of total credit (same)
SL = 10% loss (same) — or could be:
    - SL on narrow wing: Tighter (8%)
    - SL on wide wing: Looser (12%)

Rationale:
- Narrow wing protected by GEX bias → can afford tighter SL
- Wide wing is insurance → should give more room

Risk: Makes monitoring complex, may not improve results
Recommendation: Use SAME TP/SL initially, optimize later if data supports
```

---

## 7. BACKTESTING BWIC

### Backtest Design

**Input Data**:
- 18 months of GEX PIN data + GEX polarity values
- SPX prices at entry and exit
- Trade outcomes (P&L $, win/loss, reason)

**Test Scenarios**:

1. **Baseline**: Normal IC (all NEAR PIN trades)
2. **BWIC Fixed**: BWIC with fixed threshold (GPI > 0.2)
3. **BWIC Adaptive**: BWIC with dynamic thresholds
4. **Directional with GPI**: Normal directional spreads, but use GPI to adjust confidence/sizing

**Metrics to Compare**:
```
- Net P&L (total profit)
- Win Rate (% profitable trades)
- Profit Factor (avg win / avg loss)
- Max Drawdown (worst peak-to-trough)
- Sharpe Ratio (risk-adjusted return)
- R:R Ratio (average profit per winner / average loss per loser)
```

### Expected Results

**Hypothesis 1: BWIC Reduces Max Loss**
```
Baseline (Normal IC): Worst loss = -$500 (opposite side blows through)
BWIC:                Worst loss = -$200 (narrow wing protected)
→ 60% reduction in max loss
```

**Hypothesis 2: BWIC Increases Wins When GEX Correct**
```
Baseline: 60% win rate overall
BWIC when GPI > 0.5: 75% win rate (GEX bias strong)
BWIC when |GPI| < 0.2: 50% win rate (GEX ambiguous)
```

**Hypothesis 3: Trade-off in Credit**
```
BWIC may collect slightly less credit overall
- Narrow wing forces closure earlier
- But fewer large losses offsets this

Net result: Better risk-adjusted return (Sharpe) even if P&L flat
```

---

## 8. IMPLEMENTATION ROADMAP

### Phase 1: Code Foundation (Week 1)

**Files to Create**:
```
/root/gamma/core/broken_wing_ic_calculator.py
  - GEX polarity calculation
  - Wing width selection
  - BWIC vs normal IC decision logic

/root/gamma/core/gex_strategy_bwic.py (or modify existing)
  - Enhanced get_gex_trade_setup() with BWIC support
  - GEXTradeSetup dataclass extended fields
```

**Files to Modify**:
```
/root/gamma/core/gex_strategy.py
  - Add gpi, call_width, put_width to GEXTradeSetup
  - Add calculate_gex_polarity() function

/root/gamma/scalper.py
  - Pass GEX peaks to get_gex_trade_setup()
  - Log BWIC usage (enabled/disabled + why)
```

### Phase 2: Dry Run Testing (Week 1-2)

**Test with Overrides**:
```bash
python scalper.py SPX PAPER 6050 6060 BWIC_FORCE=true
# Force BWIC even if GEX ambiguous, test strike behavior
```

### Phase 3: Backtesting (Week 2-3)

```bash
python backtest_broken_wing_ic.py
# Compare 18 months: Normal IC vs BWIC
# Output: P&L, win rate, Sharpe, max DD
```

### Phase 4: Paper Trading (Week 3-4)

- Deploy to paper account
- Log all BWIC trades separately
- Compare P&L vs baseline period
- Collect 50+ trades before deciding

### Phase 5: Live Deployment (Month 2)

- If backtests show >5% improvement:
  - Enable on live account (small position size)
  - Monitor for 2 weeks
  - Increase position size if results confirm
- If results neutral:
  - Keep as backup strategy
  - Use for high-confidence GEX days only
- If results worse:
  - Disable and document learnings

---

## 9. SUCCESS CRITERIA

### Threshold for Deployment

```
Backtest Results (18 months):
✓ PASS if:
  - Sharpe Ratio improvement: ≥ 10%
  - Max Drawdown reduction: ≥ 15%
  - Win Rate change: ≥ -2% (don't lose)
  - P&L change: ≥ -5% acceptable (quality trades)
  - Worst loss reduction: ≥ 30%

✗ FAIL if:
  - Sharpe worse or flat
  - Max drawdown larger
  - Win rate drops > 5%
  - P&L negative > 10%
```

### Paper Trading Validation

```
50+ trades minimum:
✓ If profit factor > 2.0 and win rate > 55%
  → Proceed to limited live testing (1 contract)

~ If profit factor 1.5-2.0 or win rate 50-55%
  → Keep on paper, collect more data

✗ If profit factor < 1.5 or win rate < 50%
  → Disable BWIC, document reasons
```

---

## 10. RISK MANAGEMENT FOR BWIC

### Key Risks

| Risk | Mitigation |
|------|-----------|
| **Narrow wing gets tested unexpectedly** | Keep SL at 10%, emergency stop at 40% |
| **GEX polarity reverses quickly** | Only use BWIC if GPI stable (no competing peaks) |
| **Wide wing credit not enough to offset loss** | Backtest to verify total credit comparable |
| **Monitoring complexity** | Use same TP/SL as normal IC initially |
| **Data mining / overfitting** | Test on out-of-sample data (future 6 months) |

### Contingency Decisions

```
If BWIC causes 3 consecutive losses > $500:
→ Temporarily disable BWIC for that day
→ Revert to normal IC until analysis complete

If BWIC underperforms in paper after 50 trades:
→ Reduce position size by 50%
→ Continue observation mode for 100 more trades

If GEX source data becomes unavailable:
→ Automatic fallback to normal IC
→ Alert sent to operator
```

---

## 11. CONFIGURATION FOR PRODUCTION

### Enable/Disable BWIC

```python
# In config.py or scalper.py
BWIC_STRATEGY_ENABLED = True
BWIC_GPI_THRESHOLD = 0.20          # |GPI| > this triggers BWIC
BWIC_GEX_MAGNITUDE_MIN = 5e9        # Min 5B GEX for confidence
BWIC_LOG_DETAILS = True             # Log why BWIC used/not used

# When to disable BWIC
BWIC_DISABLE_VIX_THRESHOLD = 25     # Disable when VIX > 25
BWIC_DISABLE_COMPETING_PEAKS = True # Disable when peaks compete
BWIC_DISABLE_FAR_FROM_PIN = 10      # Disable if > 10pts from PIN

# Position sizing for BWIC
BWIC_POSITION_SIZE_MULTIPLIER = 1.0  # Same as normal IC
# (could be < 1.0 if more conservative desired)
```

---

## 12. MONITORING & LOGGING

### Log Example

```
[14:35:22] GEX Polarity Analysis:
[14:35:22]   Top peaks: +15.2B (6050), +8.5B (6075), -12.1B (6025)
[14:35:22]   Positive GEX: 23.7B | Negative GEX: 12.1B
[14:35:22]   GPI = (23.7 - 12.1) / (23.7 + 12.1) = +0.33 (BULLISH)
[14:35:22]   Magnitude: 17.9B (STRONG)
[14:35:22]   Competing peaks: No (score ratio 0.56 > 0.5 but same side)
[14:35:22]
[14:35:22] BWIC Decision:
[14:35:22]   |GPI| = 0.33 > threshold 0.20? YES
[14:35:22]   Magnitude 17.9B > min 5B? YES
[14:35:22]   → USE BWIC (Bullish bias)
[14:35:22]
[14:35:22] Strike Selection:
[14:35:22]   VIX 17.5 → base_width = 10pt
[14:35:22]   Offset = 10 * 0.5 * 0.33 = 1.65 → 2pt
[14:35:22]   Call wing: 10 - 2 = 8pts (NARROW, rally expected)
[14:35:22]   Put wing: 10 + 2 = 12pts (WIDE, downside cushion)
[14:35:22]   → Calls: 6070/6078C | Puts: 6038/6050P
[14:35:22]
[14:35:22] Expected Credit: $1.15 (vs $1.10 normal IC)
```

### Discord Alert Enhancement

```
[Trade entry alert]

🎯 GEX SCALP ENTRY — IC (BWIC)
├─ Strategy: Iron Condor (Broken Wing)
├─ Direction: NEUTRAL (Bullish bias via GPI)
├─ Strikes: 6070/6078C (8pt) + 6038/6050P (12pt)
├─ GEX Polarity: +0.33 (BULLISH)
├─ GEX Magnitude: 17.9B (STRONG)
├─ Credit: $1.15 ($115 per contract)
├─ TP Target: 57.5% (close at $0.49)
└─ Stop Loss: 10% (close at $1.27)
```

---

## Summary: BWIC Design

**Key Principle**: Use GEX polarity to determine which wing is more likely to be tested, then narrow that wing for efficiency and protection.

**Implementation**:
1. Calculate GEX Polarity Index (GPI) from top 3 peaks
2. If |GPI| > threshold and no competing peaks: Use BWIC
3. Determine wing asymmetry: narrow wing = probable move, wide wing = insurance
4. Same TP/SL as normal IC (50%/10%)
5. Monitor results vs baseline

**Expected Benefit**:
- Reduce max loss by 30-60% when GEX prediction correct
- Maintain or improve win rate (same rules)
- Better risk-adjusted return (Sharpe ratio)
- Only use when GEX signal is strong and clear

**Timeline**: Complete design + backtest in 3 weeks, paper trade for 4 weeks, go live if validated.
