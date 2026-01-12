# Market Confusion Tuning Guide

How to add realistic volatility, consolidation, and losses to the backtest.

---

## Quick Reference: What Each Feature Does

| Feature | Purpose | Effect on Win Rate |
|---------|---------|-------------------|
| **Volatility Clustering** | High vol follows high vol (GARCH) | Increases price swings, more losses |
| **Momentum/Trend** | Price continues moving in same direction | Creates sustained adverse moves |
| **Consolidation** | Tight range choppy movement | Reduces vol, may cause time decay issues |
| **Intraday Pattern** | U-shaped vol (high at open/close) | Realistic but minimal impact |
| **Breakouts** | Sudden directional moves away from pin | Most effective for generating losses |

---

## Current Results (Too Perfect)

Even with ALL features enabled: **100% win rate**

**Why?**
1. Breakouts revert back to pin too quickly
2. Momentum decays too fast (0.98 per minute)
3. Volatility clustering not aggressive enough
4. Mean reversion (0.05) still too strong
5. No entry gap risk

---

## Parameter Tuning for Realistic Losses

### 1. Weaken Mean Reversion (Most Important!)

**Current:**
```python
self.pin_strength = 0.05  # 5% reversion per hour
```

**Aggressive (will generate losses):**
```python
self.pin_strength = 0.02  # 2% reversion per hour - weaker pin effect
```

**Effect:** Price can drift away from pin for extended periods.

---

### 2. Stronger Breakouts

**Current:**
```python
# In check_breakout()
if random.random() < 0.01:  # 1% chance per minute
    self.breakout_counter = random.randint(20, 60)  # 20-60 minutes
    self.momentum = direction * random.uniform(1.0, 2.0)  # Points per minute
```

**Aggressive:**
```python
if random.random() < 0.02:  # 2% chance (more frequent)
    self.breakout_counter = random.randint(60, 120)  # 1-2 HOURS (much longer)
    self.momentum = direction * random.uniform(2.0, 4.0)  # STRONGER drift
```

**Effect:** Creates sustained 1-2 hour moves that can blow through stop losses.

---

### 3. Persistent Momentum (Don't Let It Decay)

**Current:**
```python
self.momentum_decay = 0.98  # Decays 2% per minute
```

**Aggressive:**
```python
self.momentum_decay = 0.995  # Decays only 0.5% per minute - stays longer
```

**Effect:** Once momentum starts, it persists for 30-60 minutes instead of 5-10.

---

### 4. More Volatile Volatility Clustering

**Current:**
```python
if random.random() < 0.05:  # 5% chance
    shock = random.uniform(-0.3, 0.5)  # Small shocks

self.vol_regime = max(0.5, min(2.5, self.vol_regime))  # Capped at 2.5x
```

**Aggressive:**
```python
if random.random() < 0.10:  # 10% chance (more frequent)
    shock = random.uniform(-0.5, 1.5)  # MUCH bigger shocks

self.vol_regime = max(0.3, min(5.0, self.vol_regime))  # Allow 5x volatility!
```

**Effect:** Occasional "mini flash crashes" with 3-5x normal volatility.

---

### 5. Add Entry Gap Risk (NEW)

**Add this to simulate_trade() function:**

```python
# BEFORE creating market simulator
# Add gap risk - immediate adverse move at entry
if random.random() < 0.10:  # 10% of trades have gap
    gap_size = random.uniform(-15, 15)  # SPX points
    spx_price += gap_size
    print(f"  [GAP] Entry gapped {gap_size:+.1f} points")
```

**Effect:** 10% of trades start underwater immediately, testing stop losses.

---

### 6. Reduce Stop Loss Grace Period

**Current:**
```python
SL_GRACE_PERIOD_MIN = 3  # 3 minutes
```

**Aggressive (more realistic):**
```python
SL_GRACE_PERIOD_MIN = 0.5  # 30 seconds - hit stop immediately if underwater
```

**Effect:** Stop losses trigger faster, preventing small losses from becoming large.

---

## Realistic Configuration (Expected 55-65% WR)

Replace the `__init__` parameters in `EnhancedMarketSimulator`:

```python
class EnhancedMarketSimulator:
    def __init__(self, start_price, gex_pin, vix, trading_hours=6.5,
                 enable_vol_clustering=True,
                 enable_momentum=True,
                 enable_consolidation=True,
                 enable_intraday_pattern=True,
                 enable_breakouts=True):

        # ... existing code ...

        # AGGRESSIVE TUNING FOR REALISTIC LOSSES
        self.minute_vol = self.hourly_vol / np.sqrt(60)
        self.pin_strength = 0.02  # Weak reversion (was 0.05)

        # Volatility clustering - allow bigger spikes
        self.vol_regime = 1.0
        self.vol_persistence = 0.90  # Slower reversion (was 0.95)

        # Momentum - persist longer
        self.momentum = 0.0
        self.momentum_decay = 0.995  # Decay slower (was 0.98)

        # ... rest of code ...

    def check_breakout(self):
        if not self.enable_breakouts:
            return

        # AGGRESSIVE: More frequent, longer, stronger breakouts
        if not self.in_breakout and random.random() < 0.02:  # 2% chance (was 1%)
            self.in_breakout = True
            self.breakout_direction = random.choice([-1, 1])
            self.breakout_counter = random.randint(60, 120)  # 1-2 hours (was 20-60 min)
            self.momentum = self.breakout_direction * random.uniform(2.0, 4.0)  # Stronger (was 1-2)

        # ... rest of code ...

    def update_volatility_regime(self):
        if not self.enable_vol_clustering:
            return

        # AGGRESSIVE: Bigger vol shocks, allow 5x spikes
        if random.random() < 0.10:  # 10% chance (was 5%)
            shock = random.uniform(-0.5, 1.5)  # Bigger (was -0.3 to 0.5)
            self.vol_regime += shock

        self.vol_regime = self.vol_persistence * self.vol_regime + (1 - self.vol_persistence) * 1.0
        self.vol_regime = max(0.3, min(5.0, self.vol_regime))  # 5x max (was 2.5x)
```

---

## Alternative: Direct Stop Loss Triggering

If you want to force specific loss scenarios, add "bad trade" injection:

```python
def simulate_trade(...):
    # ... existing entry code ...

    # Inject 30% "bad luck" trades that will hit stop loss
    force_stop_loss = (random.random() < 0.30)

    if force_stop_loss:
        # Simulate adverse move that hits stop
        # Multiply initial volatility by 3x for this trade
        market_sim.minute_vol *= 3.0
        # Disable mean reversion for first hour
        market_sim.pin_strength = 0.0
        # Add strong adverse momentum
        market_sim.momentum = -2.0 if is_put else 2.0  # Against us
```

---

## Expected Results by Configuration

### Original (No Enhancements)
```
Pin Strength: 0.05
Win Rate: 100%
Losses: 0
```

### Moderate (Slight Improvements)
```
Pin Strength: 0.03
Breakouts: 1% chance, 30-60 min
Win Rate: 80-90%
Losses: 10-20%
```

### Aggressive (Realistic)
```
Pin Strength: 0.02
Breakouts: 2% chance, 60-120 min, 2-4 pts/min drift
Momentum Decay: 0.995
Vol Clustering: 10% chance, 1.5x shocks, 5x max
Win Rate: 55-65%
Losses: 35-45%
Avg Loss: -$15 to -$30 per contract
```

### Nuclear (Stress Test)
```
Pin Strength: 0.00 (no reversion!)
Breakouts: 5% chance, 2-3 hours
Momentum: No decay (persists forever)
Vol Clustering: Constant 3x
Entry Gaps: 30% of trades
Win Rate: 30-40%
Losses: 60-70%
```

---

## Testing Your Changes

Run with different seeds to validate:

```python
for seed in [42, 123, 456, 789, 999]:
    run_backtest(market_features={...}, seed=seed)
```

**Expected across 5 seeds:**
- Win rate: 55-70% (should vary!)
- Some seeds will have losing periods
- Occasional large losses from breakouts
- Profit factor: 2-4x (realistic)

---

## Real Production Data Targets

From `/root/gamma/data/trades.csv` (39 real trades):

```
Win Rate: 23% (testing) → 60% (production target)
Avg Winner: $62.89
Avg Loser: -$35.30
Profit Factor: 0.91 → 4.0+ (target)

Exit Reasons:
  Stop Loss: 44% (many before grace period - now fixed)
  Profit Target: 23%
  Other: 33%
```

**To match production behavior:**
1. Win rate: 60-65% (not 100%!)
2. Average loss: -$25 to -$40 per contract
3. Some trades hit stop loss (30-40%)
4. Occasional large loss from gap/breakout (-$50+)

---

## Quick Start

**Option 1: Edit existing enhanced backtest**

Edit `/root/gamma/backtest_realistic_intraday_enhanced.py`:

```python
# Line 76: Weaken mean reversion
self.pin_strength = 0.02  # Was 0.05

# Line 83: Slower momentum decay
self.momentum_decay = 0.995  # Was 0.98

# Line 162-167: Stronger breakouts
if not self.in_breakout and random.random() < 0.02:  # Was 0.01
    self.breakout_counter = random.randint(60, 120)  # Was 20-60
    self.momentum = self.breakout_direction * random.uniform(2.0, 4.0)  # Was 1.0-2.0
```

**Option 2: Add gap risk to original backtest**

Edit `/root/gamma/backtest_realistic_intraday.py` in `simulate_trade()`:

```python
# After line 168 (before creating market simulator)
# Add entry gap risk
if random.random() < 0.15:  # 15% of trades
    gap_size = random.uniform(-20, 20)
    spx_price += gap_size
```

---

## Summary

To generate **realistic losing trades**, you need:

✅ **Weaker mean reversion** (0.02 instead of 0.05)
✅ **Stronger, longer breakouts** (60-120 min instead of 20-60)
✅ **Persistent momentum** (0.995 decay instead of 0.98)
✅ **Bigger vol spikes** (1.5x shocks, 5x max instead of 0.5x, 2.5x)
✅ **Entry gap risk** (15% of trades gap against us)

**Target outcome:** 55-65% win rate, -$25 to -$40 avg loss, profit factor 2-4x.

The current simulation is "too perfect" because:
- Mean reversion always brings price back
- Theta decay always helps (0DTE advantage)
- No sudden adverse events (gaps, flash crashes)
- Momentum dies too quickly

Tune the parameters above to match your desired level of realism!
