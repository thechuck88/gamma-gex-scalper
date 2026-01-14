# 0DTE Data Source - Decision Matrix

**Date**: 2026-01-10
**Goal**: Get 5 years of SPX/NDX 0DTE options data for backtest validation
**Budget**: $0-150 one-time preferred

---

## The Problem

Your backtest estimates **$1-2 credit** for 0DTE spreads, but you need real historical data to validate this assumption before going live.

**Current Status**:
- ✅ Databento subscription: $25/mo (already have)
- ❌ Databento has NO 0DTE data (batch downloads exclude expiration day)
- ✅ Tradier collection deployed (free, but forward-only, starts Monday)
- ❓ Need historical 0DTE data for validation

---

## Decision Tree

```
START: Need 5 years of 0DTE historical data
  │
  ├─→ Can you wait 30-60 days for free collection?
  │   │
  │   ├─→ YES: Use Tradier collection (FREE)
  │   │         - Already deployed ✅
  │   │         - Starts Monday Jan 13, 2026
  │   │         - 30-min snapshots (sufficient for validation)
  │   │         - After 30 days: Initial validation
  │   │         - After 60 days: Full validation
  │   │         - Cost: $0
  │   │
  │   └─→ NO: Continue below...
  │
  ├─→ Do you have IBKR account?
  │   │
  │   ├─→ YES: Test IBKR market data ($10/mo)
  │   │         - Subscribe to market data
  │   │         - Test if 0DTE available
  │   │         - If YES: Cheapest option!
  │   │         - If NO: Continue to ThetaData
  │   │
  │   └─→ NO: Continue below...
  │
  ├─→ Wait for Databento support response?
  │   │
  │   ├─→ Already emailed: Wait 1-2 days
  │   │         - If they have 0DTE: Use existing $25/mo subscription
  │   │         - If they don't: Continue to ThetaData
  │   │
  │   └─→ Not yet emailed: Send email now (template provided)
  │         - See: email_databento_support.txt
  │
  └─→ Default: ThetaData one-month strategy
              - Cost: $150 one-time
              - Download 5 years in 10-24 hours
              - Cancel before month 2
              - Best historical data quality
              - Proven reliable
```

---

## Option Comparison

### Option 1: Tradier Collection (FREE) ✅ DEPLOYED

**Cost**: $0

**Timeline**: 30-60 days to build dataset

**Pros**:
- ✅ Free forever
- ✅ Already deployed (starts Monday)
- ✅ Real market data (not estimated)
- ✅ Ongoing collection (stays current)
- ✅ No subscription or cancellation needed

**Cons**:
- ❌ No historical data (forward-only)
- ❌ Must wait 30-60 days for sufficient data
- ❌ Snapshots only (not true OHLCV bars)
- ❌ 30-min granularity (not 1-minute)

**Best For**:
- Budget-conscious traders
- Can wait 1-2 months for validation
- Don't need multi-year optimization
- Want zero ongoing costs

**Action**: Wait for Monday, monitor collection
**Status**: ✅ Already deployed

---

### Option 2: Interactive Brokers (IBKR) - $10/mo

**Cost**: $10/month market data subscription

**Timeline**: Immediate (if they have 0DTE)

**Pros**:
- ✅ Cheapest ongoing option
- ✅ 1-2 years of history available
- ✅ Real-time + historical via API
- ✅ Can integrate with live trading later

**Cons**:
- ❌ Requires IBKR account (free but need to open)
- ❌ Complex API (need to write wrapper)
- ❌ Shorter history than ThetaData (1-2 years vs 5 years)
- ❌ Rate limits on historical data requests
- ❓ Unknown if they have 0DTE (need to test)

**Best For**:
- Already have IBKR account
- Want ongoing access to data
- Can tolerate 1-2 years of history
- Want to potentially trade via IBKR later

**Action**: Test IBKR historical data API for 0DTE availability
**Status**: ❓ Needs testing

---

### Option 3: Databento via API - $25/mo ⏳ WAITING

**Cost**: $25/month (already subscribed)

**Timeline**: Unknown (awaiting support response)

**Pros**:
- ✅ Already subscribed (no new cost)
- ✅ Professional data quality
- ✅ 5+ years of history
- ✅ Excellent API documentation

**Cons**:
- ❌ Batch downloads confirmed NO 0DTE
- ❓ API access unknown (symbology issues)
- ⏳ Waiting for support response (1-2 days)

**Best For**:
- If Databento confirms 0DTE via streaming API
- Want to stay with current provider
- Saves $125/mo vs ThetaData

**Action**: Email support (template: `email_databento_support.txt`)
**Status**: ⏳ Awaiting response

---

### Option 4: ThetaData One-Month - $150 ⭐ BEST IMMEDIATE SOLUTION

**Cost**: $150 one-time (subscribe, download, cancel)

**Timeline**: 4 weeks total (1 setup, 2 download, 1 validate)

**Pros**:
- ✅ Confirmed 0DTE availability
- ✅ 5+ years of history
- ✅ Best data quality (1-second aggregated to 1-minute)
- ✅ Includes Greeks and IV
- ✅ ~180M bars (comprehensive)
- ✅ Download once, use forever
- ✅ No recurring charges (cancel after month 1)

**Cons**:
- ❌ Upfront cost ($150)
- ❌ Need to manually download and store
- ❌ No ongoing updates after cancellation

**Best For**:
- Need immediate historical validation
- Want 5 years for robust optimization
- Can afford $150 one-time investment
- Want highest quality data

**Action**: Subscribe, bulk download, cancel (see `THETADATA_ONE_MONTH_STRATEGY.md`)
**Status**: ⭐ Ready to execute

---

### Option 5: Hybrid Strategy (RECOMMENDED) 🏆

**Combine free + paid for best value**

**Phase 1** (Now - Week 4):
- Subscribe to ThetaData ($150)
- Download 5 years historical (Week 1-3)
- Validate backtest with real data (Week 4)
- Optimize parameters across 5 years
- Cancel subscription before Day 30

**Phase 2** (Ongoing):
- Use free Tradier collection (already deployed)
- Collect new 0DTE data daily (Mon/Wed/Fri)
- Keep dataset current (free forever)

**Total Cost**: $150 one-time + $0 ongoing

**Benefits**:
- ✅ 5 years historical validation (ThetaData)
- ✅ Ongoing data collection (Tradier free)
- ✅ Complete dataset forever
- ✅ No recurring costs

**Best For**:
- Serious about validating before going live
- Want both historical and future data
- Can afford $150 upfront
- Want optimal long-term setup

**Action**: Execute ThetaData strategy + monitor Tradier
**Status**: 🏆 Recommended approach

---

## Cost-Benefit Analysis

### 5-Year Validation Value

**Your backtest shows**: $9,350 profit (216 days, 63.7% win rate)

**Risk without validation**:
- Go live with untested $1-2 credit assumption
- If real credits are lower → strategy unprofitable
- If slippage higher → strategy unprofitable
- Potential loss: Unknown (could be thousands)

**Value of validation**:
- Confirm credit assumption accurate
- Test across multiple market regimes
- Optimize parameters with real data
- Go live with confidence

**Cost to validate**:
- Free option: $0 (wait 60 days)
- IBKR: $10/mo (if they have it)
- Databento: $25/mo (if API has it)
- ThetaData: $150 one-time

**ROI Calculation**:
- Strategy profit: $43/day × 252 days/year = **$10,836/year**
- Validation cost: $150
- ROI if strategy works: **72× return** ($10,836 / $150)
- ROI if strategy fails: Avoided potential losses (priceless)

**Conclusion**: $150 is reasonable insurance for $10k+/year strategy

---

## Recommended Action Plan

### Week 1: Test Free/Cheap Options First

**Monday (Today)**:
1. ✅ Email Databento support (template provided)
2. ❓ Test IBKR if you have account
3. ✅ Monitor Tradier collection (starts Monday)

**Tuesday-Wednesday**:
1. ⏳ Wait for Databento response
2. ✅ Verify Tradier cron jobs working
3. ❓ If IBKR tested, evaluate results

### Week 2: Make Final Decision

**IF Databento says YES**:
- Use existing $25/mo subscription
- Download 5 years via API
- **Total cost**: $0 additional

**IF IBKR works**:
- Subscribe to market data ($10/mo)
- Download available history (1-2 years)
- **Total cost**: $10/mo ongoing

**IF both NO**:
- Subscribe to ThetaData ($150)
- Execute one-month download strategy
- Cancel before Day 30
- **Total cost**: $150 one-time

### Ongoing: Tradier Collection

**Regardless of choice above**:
- ✅ Tradier collection already running (free)
- ✅ Builds dataset going forward
- ✅ Zero cost forever

---

## Quick Decision Guide

**Choose Tradier Collection (FREE) if**:
- ⏱️ Can wait 30-60 days for validation
- 💰 Budget is $0
- 📊 Don't need multi-year optimization

**Choose IBKR ($10/mo) if**:
- ✅ Already have IBKR account
- ⏱️ Need validation within 1-2 weeks
- 📊 1-2 years of history is enough
- ❓ They have 0DTE (need to verify)

**Choose ThetaData ($150) if**:
- ⏱️ Need validation NOW (within 4 weeks)
- 📊 Want 5 years for robust testing
- 💯 Want highest quality data
- 💰 Can afford $150 upfront

**Choose Hybrid (ThetaData + Tradier) if**:
- 🏆 Want best of both worlds
- 💰 Can afford $150 upfront
- 📊 Want 5 years historical + ongoing
- ✅ Serious about optimizing strategy

---

## Files to Reference

| File | Purpose |
|------|---------|
| `DATABENTO_0DTE_TEST_RESULTS.md` | Complete test results and findings |
| `WHY_NO_0DTE_IN_DATABENTO.md` | Investigation into Databento limitations |
| `THETADATA_ONE_MONTH_STRATEGY.md` | Complete ThetaData download plan |
| `0DTE_COLLECTION_DEPLOYED.md` | Tradier collection setup (already done) |
| `TRADIER_OPTIONS_GRANULARITY.md` | Tradier limitations and capabilities |
| `email_databento_support.txt` | Email template for Databento support |
| `test_databento_0dte_methods.py` | Test scripts (already run) |
| `test_databento_0dte_direct.py` | Direct symbol tests (already run) |

---

## Summary

**Problem**: Need 5 years of 0DTE data to validate $1-2 credit assumption

**Finding**: Databento (current provider) has NO 0DTE data in batch downloads

**Options**:
1. **Free**: Tradier collection (wait 60 days) ✅ Deployed
2. **$10/mo**: IBKR (if they have 0DTE) ❓ Needs testing
3. **$25/mo**: Databento via API (if available) ⏳ Awaiting response
4. **$150**: ThetaData one-month ⭐ Best immediate solution
5. **$150 + $0**: Hybrid (ThetaData + Tradier) 🏆 Recommended

**Recommendation**:
- **This weekend**: Email Databento, test IBKR if available
- **Next week**: If no alternatives, subscribe to ThetaData
- **Ongoing**: Use free Tradier collection (already deployed)

**Expected Cost**: $0-150 depending on provider availability

---

**Created**: 2026-01-10
**Status**: Ready to execute
**Next Action**: Email Databento support and/or subscribe to ThetaData

