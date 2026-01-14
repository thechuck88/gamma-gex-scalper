# ThetaData One-Month Download Strategy

## Objective

Subscribe to ThetaData for ONE month, download 5 years of 0DTE historical data for SPX and NDX, store locally, then cancel.

**Total Cost**: $150 (one month only)
**Data Acquired**: 5 years of 0DTE options (worth $9,000 if paid monthly)
**ROI**: 60× savings ($9,000 / $150)

---

## ThetaData Pricing & Policies

### Standard Plan ($150/month)

**What's Included**:
- ✓ Full historical options data
- ✓ Tick-level data (1-second resolution)
- ✓ 0DTE data explicitly included
- ✓ Unlimited API calls
- ✓ Unlimited downloads
- ✓ Data going back 5+ years
- ✓ **Cancel anytime** (no contract)

**Source**: https://thetadata.net/pricing

### Cancellation Policy

**Per ThetaData Website**:
- Month-to-month billing
- Cancel anytime
- No cancellation fees
- Access until end of billing period

**Strategy**: Subscribe on Day 1, download everything, cancel on Day 25 (before next billing)

---

## Data Volume Estimate

### 0DTE Options Data (5 Years)

**SPX 0DTE**:
- Days: Mon/Wed/Fri × 52 weeks × 5 years = ~780 trading days
- Options per day: 200-400 contracts (ATM ± 10 strikes, calls + puts)
- Bars per option: 390 minutes (6.5 hours × 60 minutes)
- Total bars: 780 days × 300 options × 390 bars = **91 million bars**

**NDX 0DTE**:
- Similar calculation: **~91 million bars**

**Total**: **~180 million bars** (SPX + NDX combined)

### Storage Requirements

**Per Bar** (1-minute OHLCV):
- Symbol: 20 bytes
- Datetime: 20 bytes
- OHLC: 4 × 8 bytes = 32 bytes
- Volume: 8 bytes
- Total: ~80 bytes/bar

**Total Storage**:
- 180M bars × 80 bytes = 14.4 GB
- With compression (SQLite): ~5-7 GB

**Conclusion**: Easily fits on disk

---

## Download Timeline

### Week 1: Setup & API Testing

**Day 1-2**:
- Subscribe to ThetaData
- Get API credentials
- Test API endpoints
- Write download script
- Test with 1 day of data

**Day 3-4**:
- Optimize download script
- Add rate limiting
- Add error handling
- Add progress tracking
- Test with 1 week of data

### Week 2-3: Bulk Download

**Download Strategy**:
- Download by month (60 months × 5 years)
- Parallelize where possible (2-4 concurrent downloads)
- Rate limiting to avoid API throttling
- Checkpointing (resume if interrupted)

**Estimated Download Time**:
- ThetaData API: 1,000-5,000 bars/second (typical)
- 180M bars ÷ 5,000 bars/sec = 36,000 seconds = **10 hours**
- With overhead: **12-24 hours total**

**Strategy**: Run overnight downloads, 2-3 nights total

### Week 4: Validation & Cancellation

**Day 22-24**:
- Validate downloaded data
- Check for gaps
- Re-download any missing data
- Test backtest with real data

**Day 25**:
- **Cancel subscription** (before Day 30 renewal)
- Data remains in your database
- Use forever with no additional cost

---

## ThetaData API Overview

### REST API Endpoints

**Historical Bars** (OHLCV):
```
GET /hist/option/quote
Parameters:
  - root: SPX or NDX
  - exp: expiration date (YYYYMMDD)
  - strike: strike price
  - right: C or P
  - start_date: YYYYMMDD
  - end_date: YYYYMMDD
  - ivl: interval (60000 = 1-minute)
```

**Bulk Download**:
```
GET /bulk/option/ohlc
Parameters:
  - root: SPX
  - start_date: 20210101
  - end_date: 20251231
  - ivl: 60000 (1-minute)
  - use_csv: true
```

**Response Format**:
- CSV or JSON
- Compressed (gzip)
- Pagination for large results

### Rate Limits

**Standard Plan**:
- No hard rate limit
- Fair usage policy: "Reasonable" number of requests
- Bulk downloads encouraged (more efficient)

**Best Practices**:
- Use bulk endpoints when available
- Download by month (not by day)
- Add 1-2 second delays between requests
- Download overnight (less server load)

---

## Download Script Architecture

### Script: `download_thetadata_bulk.py`

**Features**:
1. **Download by Month** - 60 months over 5 years
2. **Parallel Downloads** - 2-4 months at a time
3. **Checkpointing** - Resume if interrupted
4. **Progress Tracking** - ETA and % complete
5. **Error Handling** - Retry on failure
6. **Data Validation** - Check for gaps

**Pseudocode**:
```python
for year in range(2021, 2026):
    for month in range(1, 13):
        # Download SPX 0DTE for this month
        download_0dte_month('SPX', year, month)

        # Download NDX 0DTE for this month
        download_0dte_month('NDX', year, month)

        # Store in database
        store_in_db(data)

        # Checkpoint
        mark_completed(year, month)

        # Rate limiting
        sleep(2)
```

**Output**: SQLite database with 180M bars

---

## Implementation Plan

### Phase 1: Subscribe & Test (Days 1-4)

**Step 1: Subscribe to ThetaData**
```
1. Go to https://thetadata.net/pricing
2. Click "Subscribe" on Standard plan ($150/mo)
3. Enter payment details
4. Get API key from dashboard
```

**Step 2: Test API**
```bash
# Export API key
export THETADATA_API_KEY="your_key_here"

# Test endpoint
curl -H "Authorization: Bearer $THETADATA_API_KEY" \
  "https://api.thetadata.net/hist/option/quote?root=SPX&exp=20260113&strike=5900&right=C&start_date=20260113&end_date=20260113"
```

**Step 3: Write Download Script**
- Create `download_thetadata_bulk.py`
- Test with 1 day of data
- Validate data format
- Confirm 0DTE filtering works

### Phase 2: Bulk Download (Days 5-20)

**Download Schedule**:
```
Night 1 (Day 5): 2021 data (12 months × 2 symbols)
Night 2 (Day 6): 2022 data (12 months × 2 symbols)
Night 3 (Day 7): 2023 data (12 months × 2 symbols)
Night 4 (Day 8): 2024 data (12 months × 2 symbols)
Night 5 (Day 9): 2025 data (12 months × 2 symbols)
```

**Each Night**:
- Start at 6 PM (after market close)
- Download overnight (~10-12 hours)
- Complete by 6 AM next morning
- Validate during day

**Total**: 5 nights of downloads

### Phase 3: Validation (Days 21-24)

**Check Data Quality**:
```sql
-- Count bars by year
SELECT
    substr(datetime, 1, 4) as year,
    COUNT(*) as bars
FROM option_bars_0dte
GROUP BY year;

-- Expected:
-- 2021: ~36M bars
-- 2022: ~36M bars
-- 2023: ~36M bars
-- 2024: ~36M bars
-- 2025: ~12M bars (partial year)
```

**Check for Gaps**:
```python
# Verify all Mon/Wed/Fri are present
expected_days = get_mon_wed_fri_between('2021-01-01', '2025-12-31')
actual_days = get_unique_trade_dates_from_db()
missing_days = expected_days - actual_days
print(f"Missing {len(missing_days)} trading days")
```

**Re-download Missing Data**:
- Identify gaps
- Re-run download for specific dates
- Validate completeness

### Phase 4: Cancel (Day 25)

**Before Day 30**:
1. Log into ThetaData account
2. Go to Billing
3. Click "Cancel Subscription"
4. Confirm cancellation
5. Download confirmation email

**Result**:
- Charged $150 for first month
- No charge for month 2
- Data remains in your database forever
- Can re-subscribe anytime if needed

---

## Cost-Benefit Analysis

### Option 1: ThetaData One-Month (Recommended)

**Cost**: $150 (one month)
**Data**: 5 years of 0DTE (SPX + NDX)
**Timeline**: 4 weeks (1 week setup, 2 weeks download, 1 week validation)
**Result**: Complete historical dataset forever

**Cost per Year of Data**: $30/year
**Cost per Trading Day**: $0.19/day

### Option 2: Collect via Tradier (Current Plan)

**Cost**: $0
**Data**: 0DTE going forward only
**Timeline**: 30-60 days to build usable dataset
**Result**: Dataset grows over time

**Cost**: Free
**Limitation**: No historical data

### Option 3: ThetaData Long-Term

**Cost**: $150/month ongoing
**Data**: 5 years + continuous updates
**Timeline**: Immediate + ongoing
**Result**: Always current dataset

**Cost per Year**: $1,800/year

### Comparison

| Option | Cost | Timeline | Historical Data | Ongoing Data |
|--------|------|----------|-----------------|--------------|
| **ThetaData 1-Month** | **$150** | **4 weeks** | ✅ **5 years** | ❌ No |
| Tradier Collection | $0 | 30-60 days | ❌ No | ✅ Yes |
| ThetaData Ongoing | $1,800/yr | Immediate | ✅ 5 years | ✅ Yes |

**Best Strategy**: ThetaData one-month + Tradier ongoing
- Cost: $150 (one-time)
- Get: 5 years historical + future data
- Total savings: $1,650/year vs ongoing ThetaData

---

## Hybrid Strategy (Recommended)

### Combination Approach

**Month 1** (Now):
- Subscribe to ThetaData ($150)
- Download 5 years of historical 0DTE
- Validate backtest with real data
- Optimize parameters
- Cancel subscription

**Ongoing** (Month 2+):
- Use Tradier collection (free)
- Collect new 0DTE data daily
- Keep dataset current
- $0 ongoing cost

**Result**:
- ✅ 5 years historical validation
- ✅ Ongoing data collection
- ✅ Total cost: $150 one-time
- ✅ Complete dataset forever

---

## Download Script Template

### High-Level Structure

```python
#!/usr/bin/env python3
"""
download_thetadata_bulk.py - Download 5 Years of 0DTE Data

Downloads SPX and NDX 0DTE options data from ThetaData.
Designed to run for one month, then cancel subscription.

Usage:
  export THETADATA_API_KEY="your_key"
  python3 download_thetadata_bulk.py --start 2021-01-01 --end 2025-12-31

Author: Claude Code (2026-01-10)
"""

import requests
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import time

API_KEY = os.environ['THETADATA_API_KEY']
BASE_URL = 'https://api.thetadata.net'

def download_month_0dte(symbol, year, month):
    """Download 0DTE options for a specific month."""

    # Get 0DTE trading days (Mon/Wed/Fri)
    trading_days = get_0dte_days(year, month)

    all_data = []

    for date in trading_days:
        # Download option chain for this expiration
        data = download_0dte_chain(symbol, date)
        all_data.extend(data)

        # Rate limiting
        time.sleep(1)

    return all_data

def download_0dte_chain(symbol, expiration_date):
    """Download all options for a 0DTE expiration."""

    url = f"{BASE_URL}/bulk/option/ohlc"

    params = {
        'root': symbol,
        'exp': expiration_date.strftime('%Y%m%d'),
        'start_date': expiration_date.strftime('%Y%m%d'),
        'end_date': expiration_date.strftime('%Y%m%d'),
        'ivl': 60000,  # 1-minute
        'use_csv': True
    }

    headers = {
        'Authorization': f'Bearer {API_KEY}'
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        df = pd.read_csv(io.StringIO(response.text))
        return df
    else:
        raise Exception(f"API Error: {response.status_code}")

def store_in_database(data):
    """Store downloaded data in SQLite."""
    conn = sqlite3.connect('market_data.db')
    data.to_sql('option_bars_0dte', conn, if_exists='append', index=False)
    conn.close()

# Main loop
for year in range(2021, 2026):
    for month in range(1, 13):
        print(f"Downloading {year}-{month:02d}...")

        # Download SPX
        spx_data = download_month_0dte('SPX', year, month)
        store_in_database(spx_data)

        # Download NDX
        ndx_data = download_month_0dte('NDX', year, month)
        store_in_database(ndx_data)

        print(f"✓ Completed {year}-{month:02d}")
```

---

## Expected Results

### After One Month

**Database**:
- Table: `option_bars_0dte`
- Rows: ~180 million bars
- Size: ~5-7 GB (compressed)
- Coverage: 2021-2025 (5 years)

**Data Quality**:
- 1-minute OHLCV bars
- All 0DTE expirations (Mon/Wed/Fri)
- SPX and NDX
- Complete time series

**Cost**:
- Subscription: $150 (cancelled, no recurring charge)
- Storage: $0 (local disk)
- Total: **$150 one-time**

**Value**:
- Equivalent to 60 months at $150/mo = $9,000
- **Savings: $8,850** (98% discount)

---

## Risks & Mitigations

### Risk 1: Terms of Service Violation

**Concern**: Does ThetaData allow bulk download and cancel?

**Investigation Needed**:
- Read ThetaData Terms of Service
- Check if bulk download is prohibited
- Verify cancellation policy

**Mitigation**:
- Email ThetaData support: "Can I download historical data and cancel?"
- Get written confirmation
- Ensure compliance

### Risk 2: Download Incomplete

**Concern**: What if download fails mid-way?

**Mitigation**:
- Implement checkpointing (save progress)
- Resume capability (skip completed months)
- Validation scripts (check for gaps)
- Re-subscribe for 1 day if needed ($5 pro-rated)

### Risk 3: API Rate Limits

**Concern**: Downloads might be throttled or blocked

**Mitigation**:
- Follow fair usage guidelines
- Add rate limiting (1-2 sec delays)
- Download overnight (less server load)
- Contact support if issues

### Risk 4: Data Format Changes

**Concern**: ThetaData API might change

**Mitigation**:
- Download and store locally ASAP
- Convert to your own schema
- Independent of ThetaData after download

---

## Decision Matrix

### Should You Subscribe to ThetaData for One Month?

**YES - If:**
- ✓ Want immediate validation (can't wait 30-60 days)
- ✓ Want 5 years of historical data
- ✓ $150 is acceptable cost
- ✓ Want to optimize across multiple years
- ✓ Want highest confidence in backtest

**NO - If:**
- ✗ Budget is tight ($0 vs $150)
- ✗ Can wait 30-60 days for Tradier collection
- ✗ Only need basic validation (not multi-year)
- ✗ Strategy not yet proven in paper trading

---

## Recommended Timeline

### Immediate (This Weekend)

**Day 0**: Decide if $150 investment is worth it
**Day 1**: Subscribe to ThetaData
**Day 2**: Get API key, test endpoints

### Week 1 (Setup)

**Day 3-4**: Write download script
**Day 5-6**: Test with 1 week of data
**Day 7**: Validate test data

### Week 2-3 (Download)

**Day 8-12**: Bulk download (5 nights × ~12 hours)
**Day 13-14**: Catch up any missing data

### Week 4 (Validation & Cancel)

**Day 15-20**: Validate complete dataset
**Day 21-24**: Run backtests with real data
**Day 25**: **Cancel subscription**

### Result

**Day 26-30**: Use data forever with no additional cost

---

## Next Steps

### If You Decide to Subscribe

**Step 1**: Create download script (I can help)
**Step 2**: Subscribe to ThetaData
**Step 3**: Run bulk download (automated)
**Step 4**: Validate data
**Step 5**: Cancel subscription
**Step 6**: Use data forever

**Total Time**: 4 weeks
**Total Cost**: $150 one-time

### If You Stick with Tradier

**Current Plan**: Already deployed ✅
- Free forever
- Builds dataset over 30-60 days
- Sufficient for validation

**No action needed** - system runs automatically

---

## Summary

### Can You Download 5 Years in One Month?

**YES** ✅

**Strategy**:
1. Subscribe ($150)
2. Bulk download over 2-3 weeks
3. Cancel before month 2
4. Keep data forever

**Savings**: $8,850 (60 months × $150 - $150)

**Worth It If**:
- Want immediate validation
- Want multi-year optimization
- $150 is acceptable investment
- Can't wait 30-60 days for free collection

**Alternative**:
- Stick with free Tradier collection
- Wait 30-60 days
- $0 cost

---

**Created**: 2026-01-10
**Cost**: $150 one-time (vs $9,000 if paid monthly)
**Data**: 5 years of 0DTE (SPX + NDX)
**Recommendation**: Subscribe, download, cancel - excellent ROI
