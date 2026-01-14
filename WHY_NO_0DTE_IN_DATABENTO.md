# Why Databento Doesn't Have 0DTE Data - Investigation

## The Question

Databento is a professional options data provider charging $25/month. Why don't they have 0DTE data? This seems like a critical gap.

**Date**: 2026-01-10
**Status**: INVESTIGATING

---

## What We Know

### Confirmed: Batch Downloads Have NO 0DTE

**Tested**:
1. ✓ SPX batch file: Options stop trading day before expiration
2. ✓ NDX batch file: Same pattern - no expiration day data
3. ✓ Database query: 0 rows where trade_date = expiration_date
4. ✓ API day-by-day queries: "No data found" for expiration day

**Pattern**: Every option expiration has data up to 1 day before, then nothing on expiration day.

### Possible Explanations

#### Explanation 1: Different Dataset Required

**OPRA.PILLAR Dataset** (what we used):
- May not include expiration-day data
- Could be a limitation of this specific dataset

**Other Databento Datasets**:
- OPRA.BASIC - Basic options feed
- OPRA.COMPLEX - Complex orders
- OPRA.SPREAD - Spread orders

**Possibility**: 0DTE might be in a different dataset

#### Explanation 2: Need to Specify "Include Expiration Day"

**API Parameter Missing**:
- Maybe there's a parameter like `include_expiration_day=true`
- Batch downloads might exclude it by default
- Could be opt-in for data quality reasons

#### Explanation 3: Symbol Format Different for 0DTE

**Different Root Symbol**:
- Weekly options: SPX
- 0DTE options: SPXW or SPX0DTE (different ticker)
- We might have been querying wrong symbols

**Example**:
- Regular: `SPX250117C05900000`
- 0DTE: `SPXW250117C05900000` (note the W)

#### Explanation 4: Data Quality Issues

**Why Providers Exclude Expiration Day**:
1. **Settlement Activity**: Options undergoing settlement, not normal trading
2. **Exercise/Assignment**: Automatic exercise distorts market data
3. **Sparse Liquidity**: Most options go to zero, minimal trading
4. **Data Integrity**: Closing prices may not reflect true market

**Industry Practice**: Some providers intentionally exclude expiration day

#### Explanation 5: Licensing/Exchange Restrictions

**OPRA Restrictions**:
- OPRA (Options Price Reporting Authority) may restrict expiration-day data
- Exchange policies might limit dissemination
- Special licensing needed for settlement data

#### Explanation 6: It's There But We're Querying Wrong

**Batch vs Streaming**:
- Batch downloads: Historical snapshots (no 0DTE)
- Streaming API: Real-time feeds (has 0DTE)
- Need to use different endpoint

---

## How to Find Out

### Step 1: Check Databento Documentation

**Search For**:
- "expiration day"
- "0DTE"
- "same-day expiration"
- Dataset comparisons

**Documentation**: https://databento.com/docs/

### Step 2: Check Schema Definitions

**OPRA Schemas**:
```
- ohlcv-1s: 1-second bars
- ohlcv-1m: 1-minute bars  (what we used)
- ohlcv-1h: 1-hour bars
- trades: Tick-by-tick trades
- mbp-1: Market by price
- tbbo: Top of book
```

**Question**: Does `trades` schema include expiration day?

### Step 3: Contact Databento Support

**Email**: support@databento.com

**Questions to Ask**:
1. "Does your OPRA data include options trading on their expiration day (0DTE)?"
2. "If not, why not?"
3. "Is there a different dataset or parameter to get 0DTE data?"
4. "Do you have SPXW (weekly SPX) symbols vs SPX?"

### Step 4: Check for SPXW Symbols

**Test Query**:
```python
client.timeseries.get_range(
    dataset='OPRA.PILLAR',
    symbols=['SPXW.OPT'],  # Note: SPXW not SPX
    schema='ohlcv-1m',
    start='2025-01-17T09:30',
    end='2025-01-17T16:00'
)
```

**Hypothesis**: Maybe SPXW is for weekly/0DTE options

### Step 5: Try Different Schema

**Test with Trades Schema**:
```python
client.timeseries.get_range(
    dataset='OPRA.PILLAR',
    symbols=['SPX.OPT'],
    schema='trades',  # Not ohlcv-1m
    start='2025-01-17T09:30',
    end='2025-01-17T16:00'
)
```

**Hypothesis**: Trades might include expiration day even if bars don't

---

## Alternative Low-Cost Data Sources

### Option 1: Interactive Brokers (IBKR)

**Historical Data API**:
- Available to IBKR account holders
- $10/month market data subscription
- Historical bars available via API
- TWS (Trader Workstation) or IB Gateway

**Limitations**:
- Need funded account ($0 minimum, but need to qualify)
- Complex API (need to write wrapper)
- Rate limits on historical data requests
- May not have deep history (1-2 years typical)

**Cost**: $10/month + account requirement

**0DTE Availability**: Unknown - need to test

### Option 2: Alpaca Markets

**Options Data**:
- Recently added options support
- Historical data available
- Free tier available (delayed data)
- Unlimited plan: $99/month

**Limitations**:
- Relatively new options offering
- May not have deep history
- Need to verify 0DTE availability

**Cost**:
- Free: Delayed data (15-min)
- Unlimited: $99/month (real-time)

**0DTE Availability**: Unknown - need to test

### Option 3: Tradier (Historical Bars)

**Wait - We Haven't Fully Tested This**:
- We tested snapshots (quotes)
- Did we test historical bars for OPTIONS?
- Tradier might have historical option bars we missed

**Need to Test**:
```bash
GET /v1/markets/history?symbol=SPY260117C00590000&interval=1min&start=2026-01-17&end=2026-01-17
```

**Cost**: Free (sandbox) or live account

### Option 4: FirstRate Data

**Specialty Options Data Provider**:
- Historical options data
- One-time purchases (not subscription)
- $200-500 per symbol per year
- Good for specific backtests

**Pricing Example**:
- SPX 1 year: $300 one-time
- SPX 5 years: $1,000 one-time

**0DTE**: Likely included (need to confirm)

**Cost**: $1,000-2,000 one-time for 5 years

### Option 5: QuantConnect

**Algorithmic Trading Platform**:
- Has options data
- Free tier available
- Cloud backtesting
- Can download data locally

**Limitations**:
- Must use their platform
- Backtest in cloud (not local)
- Limited local data export

**Cost**:
- Free: Limited compute
- Quant Researcher: $8/month

**0DTE Availability**: Unknown

### Option 6: CBOE Free Data

**CBOE DataShop Free Tier**:
- Limited free historical data
- End-of-day data (not intraday)
- SPX options included
- Download CSV files

**Limitations**:
- EOD only (no intraday bars)
- Limited history (1 year free)
- Manual downloads (no API)

**Cost**: Free for EOD

**0DTE**: EOD only - not useful for intraday validation

### Option 7: Academic/Research Access

**WRDS (Wharton Research Data Services)**:
- Via university affiliation
- OptionMetrics database
- Deep historical options data
- Used by researchers

**Requirements**:
- University affiliation OR
- Independent subscription: $1,000+/year

**0DTE**: Full historical data (best quality)

**Cost**: Free (if student/faculty) or $1,000+/year

---

## Cost Comparison

| Source | Cost | 0DTE? | History | Notes |
|--------|------|-------|---------|-------|
| **Databento** | $25/mo | ❓ Unknown | 5+ years | Need to verify |
| **ThetaData** | $150/mo | ✅ Yes | 5+ years | Download & cancel |
| **IBKR** | $10/mo | ❓ Unknown | 1-2 years | Need account |
| **Alpaca** | $99/mo | ❓ Unknown | Unknown | New offering |
| **Tradier** | Free | ❓ Unknown | 35 days | Need to test |
| **FirstRate** | $1,000 | Likely | 5 years | One-time |
| **QuantConnect** | $8/mo | ❓ Unknown | Varies | Platform only |
| **CBOE Free** | Free | No | 1 year | EOD only |

---

## Recommended Next Steps

### Immediate: Contact Databento

**Email Template**:
```
Subject: 0DTE Options Data Availability

Hi Databento Support,

I'm using your OPRA.PILLAR dataset to backtest 0DTE options strategies.

I've noticed that options data stops the day before expiration. For example:
- SPX options expiring Jan 17, 2025: Last trade date is Jan 16
- No data available on Jan 17 itself (expiration day)

Questions:
1. Does OPRA.PILLAR include 0DTE (same-day expiration) data?
2. If not, is there a different dataset or parameter to access it?
3. Is SPXW (weekly SPX) available separately from SPX?
4. Does the 'trades' schema include expiration day data?

I'm specifically looking for SPX/NDX options that trade on their expiration day (Mon/Wed/Fri 0DTE).

Thanks,
[Your name]
```

**Expected Response Time**: 1-2 business days

### Test SPXW Symbols

**Hypothesis**: SPXW might be separate from SPX

**Test**:
```python
# Try SPXW instead of SPX
expirations = client.metadata.get_fields(
    symbols=['SPXW.OPT'],
    dataset='OPRA.PILLAR'
)
```

### Test Trades Schema

**Hypothesis**: Tick data might include expiration day

**Test**:
```python
data = client.timesales.get_range(
    dataset='OPRA.PILLAR',
    symbols=['SPX.OPT'],
    schema='trades',  # Not ohlcv-1m
    start='2025-01-17T09:30',
    end='2025-01-17T16:00'
)
```

### Test IBKR Historical Data

**If you have IBKR account**:
1. Enable market data ($10/mo)
2. Request historical bars for SPX option
3. Check if expiration day is included

**API Test**:
```python
from ibapi.client import EClient
# Request historical data for SPX260113C05900000
# Check if Jan 13 (expiration day) has bars
```

---

## Why This Matters

### If Databento HAS 0DTE (Just Different Access Method)

**Impact**:
- $25/month instead of $150/month
- **Saves $125/month** ($1,500/year)
- Already subscribed - no new signup
- Can download immediately

**Action**:
- Contact support (high priority)
- Test alternative symbols/schemas
- Update download scripts

### If Databento Doesn't Have 0DTE

**Impact**:
- Need alternative source
- ThetaData one-month strategy best option
- $150 one-time cost

**Action**:
- Subscribe to ThetaData
- Download 5 years
- Cancel after month 1

---

## My Hypothesis

### Most Likely Explanation

**Databento DOES have 0DTE, but**:
1. It's in the `trades` schema (not `ohlcv-1m`)
2. Or needs `SPXW` symbol (not `SPX`)
3. Or batch downloads exclude it (need streaming API)
4. Or there's a parameter we're missing

**Why This Makes Sense**:
- Professional data provider serving quant funds
- 0DTE is popular strategy (they'd have it)
- OPRA feeds include all trades (including expiration day)
- More likely we're querying wrong than data doesn't exist

### What to Do

**Before spending $150 on ThetaData**:
1. ✅ Email Databento support (takes 1 day)
2. ✅ Test SPXW symbols (takes 10 minutes)
3. ✅ Test trades schema (takes 10 minutes)
4. ✅ Check documentation more carefully (takes 30 minutes)

**If Databento confirms NO 0DTE**:
- Subscribe to ThetaData
- Download & cancel strategy
- $150 one-time

---

## Action Plan

### This Weekend (Before Subscribing to ThetaData)

**Saturday**:
1. Email Databento support
2. Test SPXW symbols
3. Test trades schema
4. Search Databento docs for "0DTE"

**Sunday/Monday**:
1. Wait for Databento response
2. Test any suggestions they provide
3. Verify if 0DTE is available

**If YES - Databento has it**:
- Update download scripts
- Download 5 years via Databento ($25/mo existing)
- Save $125 vs ThetaData

**If NO - Databento doesn't have it**:
- Subscribe to ThetaData
- Execute one-month download strategy
- Cancel before month 2

---

## Summary

### Why Doesn't Databento Have 0DTE?

**Possible Reasons**:
1. ❓ Different symbol (SPXW vs SPX)
2. ❓ Different schema (trades vs ohlcv-1m)
3. ❓ Different dataset (not OPRA.PILLAR)
4. ❓ Parameter we're missing
5. ❓ Intentionally excluded for data quality
6. ❓ Licensing restrictions

**Most Likely**: We're querying wrong - data exists but in different form

### Other Low-Cost Options

**Best Alternatives**:
1. **IBKR** - $10/month (if you have account)
2. **Databento** - $25/month (if they have it)
3. **Alpaca** - $99/month (need to verify)
4. **ThetaData** - $150 one-month (download & cancel)

### Recommended Next Steps

1. **Contact Databento** - Free, takes 1 day
2. **Test SPXW/trades** - Free, takes 30 minutes
3. **Wait for response** - Before spending $150

**If Databento has it**: Save $125/month
**If Databento doesn't**: ThetaData one-month strategy

---

**Created**: 2026-01-10
**Status**: INVESTIGATING - Contact Databento before ThetaData
**Potential Savings**: $125/month if Databento has 0DTE
