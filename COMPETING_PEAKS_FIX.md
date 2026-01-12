# Competing Peaks Detection - Fix for "Between Peaks" Scenario

## Problem

**Scenario**: Price between two significant GEX peaks
```
Peak 1: 5900 (120B GEX) - 50pts below
Peak 2: 6000 (100B GEX) - 50pts above
Current: 5950 (equidistant)
```

**Current Bot Behavior**:
1. Picks 5900 (slightly higher GEX)
2. Sells PUT spreads (expects rally UP to 5900)
3. **Ignores 6000 peak pulling UP**
4. Gets whipsawed between competing magnetic pulls → **LOSS**

**Should**: Skip trade OR use Iron Condor (profit from caged volatility)

---

## Detection Logic

### When to Skip (Competing Peaks):
```python
# After scoring peaks, check if top 2 are comparable and opposing

top_2_peaks = sorted(scored_peaks, key=lambda x: x[2], reverse=True)[:2]

if len(top_2_peaks) >= 2:
    peak1_strike, peak1_gex, peak1_score = top_2_peaks[0]
    peak2_strike, peak2_gex, peak2_score = top_2_peaks[1]

    # Check if peaks are:
    # 1. Comparable score (within 2x of each other)
    # 2. On opposite sides of current price
    score_ratio = min(peak1_score, peak2_score) / max(peak1_score, peak2_score)
    opposite_sides = (peak1_strike < index_price < peak2_strike) or \
                     (peak2_strike < index_price < peak1_strike)

    if score_ratio > 0.5 and opposite_sides:
        # Price is between two comparable peaks - competing magnetic pulls
        distance1 = abs(peak1_strike - index_price)
        distance2 = abs(peak2_strike - index_price)

        log(f"⚠️  COMPETING PEAKS DETECTED:")
        log(f"   {peak1_strike}: {peak1_gex/1e9:.1f}B GEX, {distance1}pts away")
        log(f"   {peak2_strike}: {peak2_gex/1e9:.1f}B GEX, {distance2}pts away")
        log(f"   Price between peaks → skip directional trade")

        # Option 1: Skip entirely
        return None

        # Option 2: Force Iron Condor (profit from caged volatility)
        # return peak1_strike  # Use for IC setup
```

---

## Implementation Options

### Option 1: **Skip Trade** (Conservative)
```python
if competing_peaks_detected:
    log("NO TRADE - Price between competing gamma walls")
    send_discord_skip_alert("Competing peaks - no directional edge")
    return None
```

**Pros**:
- Avoids losses from whipsaw
- Maintains high win rate (only trades with clear edge)

**Cons**:
- Reduces trade frequency
- Misses potential IC opportunities

---

### Option 2: **Force Iron Condor** (Aggressive)
```python
if competing_peaks_detected:
    log("Price between peaks → IC strategy (profit from cage)")
    # Return midpoint for IC setup
    midpoint = (peak1_strike + peak2_strike) / 2
    return round_to_5(midpoint)
```

**Pros**:
- Profits from "caged" volatility between walls
- Research-backed (dealer hedging dampens moves)

**Cons**:
- IC needs time for theta decay (bad if entered late)
- Still risky if one peak dominates later

---

### Option 3: **Hybrid** (Recommended)
```python
if competing_peaks_detected:
    # Skip if too late in day for IC (need time for theta)
    if now_et.hour >= 12:  # After noon
        log("Competing peaks + late entry → SKIP")
        return None

    # Early in day: Use IC to profit from cage
    log("Competing peaks + early entry → IC strategy")
    midpoint = (peak1_strike + peak2_strike) / 2
    return round_to_5(midpoint)
```

**Pros**:
- Skips risky late-day setups
- Captures IC edge early (time for theta decay)
- Best of both worlds

---

## Testing the Fix

```python
# Test case 1: Competing peaks (equidistant, comparable GEX)
index_price = 5950
peaks = [(5900, 120e9), (6000, 100e9)]
# Expected: Skip or IC (not directional)

# Test case 2: Clear dominant peak (not competing)
index_price = 5920
peaks = [(5950, 100e9), (6000, 120e9)]
# Expected: Pick 5950 (much closer, no competition)

# Test case 3: Dominant peak on one side only
index_price = 5950
peaks = [(5900, 50e9), (6000, 200e9)]
# Expected: Pick 6000 (4x larger, clear dominance)
```

---

## Implementation Steps

1. **Add competing peaks detection** after peak scoring
2. **Choose strategy**: Skip (Option 1) or Hybrid (Option 3)
3. **Test with unit tests** (3 scenarios above)
4. **Deploy to paper** for 30-day validation
5. **Track metrics**:
   - % of days with competing peaks
   - Win rate on skipped vs IC trades
   - P&L impact of detection

---

## Expected Impact

### Before Fix:
- ❌ Trades directionally between competing peaks
- ❌ Gets whipsawed by opposing magnetic pulls
- ❌ Lower win rate on these setups

### After Fix (Option 1 - Skip):
- ✅ Skips competing peak scenarios
- ✅ Maintains high win rate (only clear edges)
- ⚠️ Reduces trade frequency (~10-20% fewer trades)

### After Fix (Option 3 - Hybrid):
- ✅ Skips late competing peaks (risky)
- ✅ Uses IC for early competing peaks (edge)
- ✅ Similar trade frequency
- ✅ Higher win rate on these setups

---

## Open Questions

1. **What score ratio threshold?** (Currently 0.5 = 2x difference)
2. **Should we check distance ratio too?** (Equidistant = competing)
3. **What time cutoff for IC?** (Currently noon)
4. **Does this happen often?** (Track % of days)

---

**Status**: 🛠️ **NEEDS IMPLEMENTATION**
**Priority**: 🔴 **HIGH** - Critical edge case that causes losses
**Recommendation**: Start with **Option 1 (Skip)** for safety, then test **Option 3 (Hybrid)** if skipping too many trades
