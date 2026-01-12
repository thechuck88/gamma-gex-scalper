# Tradier API - Black Box Data Availability

## What Black Box Needs

### 1. GEX Peak Calculation (12 times per day)
- ✅ Full options chain (all strikes)
- ✅ Open Interest (OI)
- ✅ Gamma values
- ✅ Bid/Ask prices
- ✅ Underlying price

### 2. Live Pricing (Every 30 seconds)
- ✅ Bid/Ask/Last for specific strikes
- ✅ Volume
- ✅ Open Interest

---

## Tradier API Endpoint Used

### `/markets/options/chains`

**URL**: `https://api.tradier.com/v1/markets/options/chains`

**Parameters**:
```python
{
    "symbol": "SPX",           # or "NDX"
    "expiration": "2026-01-13", # 0DTE date
    "greeks": "true"            # CRITICAL - includes gamma!
}
```

**Returns** (per option):
```json
{
  "strike": 6000,
  "option_type": "call",
  "bid": 12.50,
  "ask": 13.00,
  "last": 12.75,
  "open_interest": 5432,
  "volume": 1234,
  "greeks": {
    "delta": 0.45,
    "gamma": 0.0012,    // ← Used for GEX calculation
    "theta": -0.15,
    "vega": 0.08
  }
}
```

---

## Data Quality

### Real-Time vs Delayed

**LIVE Account (TRADIER_LIVE_KEY):**
- ✅ **Real-time data** (not delayed)
- ✅ Greeks calculated in real-time
- ✅ Bid/Ask updated every quote
- ✅ OI updated throughout day

**Sandbox Account (TRADIER_SANDBOX_KEY):**
- ❌ **15-minute delayed** data
- ❌ Not suitable for black box recording
- ❌ **Do NOT use for black box!**

**Black box recorder uses**: `TRADIER_LIVE_KEY` ✅

---

## Rate Limits

### Tradier LIVE Account Limits

**Market Data API:**
- **120 requests per minute** (averaged)
- **28,800 requests per day**

### Black Box Usage

**GEX Recording (12 times per day):**
- 2 full chain requests per check (SPX + NDX)
- 12 checks × 2 requests = **24 requests per day**
- Well under limit ✅

**Price Monitoring (every 30 seconds):**
- During market hours: 6.5 hours × 120 per hour = 780 snapshots
- 2 requests per snapshot (SPX + NDX)
- 780 × 2 = **1,560 requests per day**
- Well under 28,800 limit ✅

**Total daily requests**: ~1,584 (5.5% of daily limit)

---

## Greeks Availability for 0DTE

### Question: Does Tradier provide greeks for 0DTE options?

**Answer**: ✅ **YES**

Tradier calculates greeks for all options, including:
- 0DTE (same-day expiration)
- Weekly options
- Monthly options
- LEAPS

**How it works**:
- Tradier uses Black-Scholes model
- Updated in real-time as underlying moves
- Gamma is highest for ATM 0DTE options (exactly what we need!)

---

## Data Accuracy

### Gamma Values

**Tradier gamma** = Per-share gamma from Black-Scholes

**GEX calculation**: `gamma × OI × 100 × spot²`
- We multiply by 100 (options control 100 shares)
- We multiply by spot² (notional exposure)
- Result is in dollars of gamma exposure

**Example**:
```python
strike = 6000
gamma = 0.0012        # From Tradier
OI = 5000            # From Tradier
spot = 5950          # SPX price

GEX = 0.0012 × 5000 × 100 × (5950²)
    = 0.0012 × 5000 × 100 × 35,402,500
    = 21,241,500,000  # $21.2 billion
```

---

## What's NOT Available

### Limitations

❌ **Historical greeks** - Tradier doesn't store historical gamma values
  - This is WHY we need the black box!
  - We record gamma NOW for backtest LATER

❌ **Tick-by-tick data** - Greeks update on quotes, not every tick
  - 30-second sampling is optimal
  - Faster would hit rate limits

❌ **After-hours options data** - Limited after 4:00 PM ET
  - Not needed (0DTE expires at 4:00 PM)
  - Black box only records during market hours

---

## API Response Size

### Full Chain Request

**Typical SPX 0DTE chain**:
- ~300 strikes (calls + puts)
- ~150 KB per response (with greeks)

**Per day**:
- GEX checks: 12 × 150 KB = 1.8 MB
- Price checks: 780 × 150 KB = 117 MB ← **Too much!**

### Optimization: Price Monitoring

Instead of fetching FULL chain every 30s, we:
1. Get latest pin from database
2. Fetch only strikes within ±60 points
3. ~20 strikes instead of 300
4. ~10 KB per response instead of 150 KB

**Optimized per day**:
- Price checks: 780 × 10 KB = 7.8 MB ✅

---

## Backup: What if Tradier API Goes Down?

### Failure Handling

The black box service has built-in retry logic:

```python
try:
    success = record_snapshot(index_symbol)
    if success:
        print("✓ Recorded")
    else:
        print("✗ Failed (will retry next interval)")
except Exception as e:
    print(f"ERROR: {e}")
    # Service continues, tries again in 30s
```

**Worst case**: Miss a few snapshots
- GEX checks: Can interpolate missing data
- Price checks: 30-second gaps are acceptable

**Service auto-restarts** if it crashes completely

---

## Summary

✅ **Tradier LIVE API provides everything needed**
✅ **Real-time data** (not delayed)
✅ **Greeks included** (gamma for GEX calculation)
✅ **Rate limits are safe** (1,584 requests vs 28,800 limit)
✅ **0DTE options supported** (includes gamma)
✅ **Already implemented** in gex_blackbox_recorder.py

**The black box is ready to record when market opens Monday!**

🚀 **All data comes from Tradier LIVE account with real-time pricing and greeks.**
