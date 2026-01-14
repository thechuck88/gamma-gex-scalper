# Interactive Brokers (IBKR) - Market Data Access Requirements

**Date**: 2026-01-10
**Goal**: Understand IBKR requirements for historical options data access

---

## Account Requirements

### Opening an Account

**Minimum Deposit**:
- **$0 minimum** for most account types (US residents)
- Can open account without funding initially
- Some account types may require $2,000-25,000 depending on features

**Account Types**:
- Individual account: $0 minimum
- Margin account: $2,000 minimum (Reg T requirement)
- Portfolio Margin: $110,000 minimum

---

## Market Data Subscription Requirements

### Real-Time Market Data

**US Securities Snapshot and Futures Value Bundle**: ~$10/month

**Requirements to Access**:
1. ✅ Active IBKR account (opened and approved)
2. ❓ Funded account OR
3. ❓ Generate commissions ($30/month in trades) OR
4. ❌ Pay market data fees ($10/month)

**Common Policy** (varies by data feed):
- If you generate $30+ in commissions/month → Market data FREE
- If you don't trade enough → Pay $10/month for data
- Some require minimum balance ($500-2,000) to waive fees

### Historical Market Data

**Via TWS API**:
- Included with account (no separate fee)
- Rate limited (60 requests per 10 minutes typical)
- Depth varies by instrument (1-2 years for options typical)

**Requirements**:
- Active funded account (even $100 may be enough)
- TWS or IB Gateway running
- API access enabled in account settings

---

## Unknown: Does IBKR Have 0DTE Historical Data?

**Status**: ❓ **NEEDS TESTING**

**What We Know**:
- IBKR provides historical data via API
- Options historical data available
- Typical depth: 1-2 years

**What We Don't Know**:
- Does historical data include expiration-day trading (0DTE)?
- What granularity? (1-min bars, tick data, snapshots?)
- How far back does options history go?

**To Test**:
1. Open IBKR account (can be $0 to start)
2. Fund with small amount ($100-500)
3. Enable TWS API access
4. Query historical bars for 0DTE option on past expiration day
5. Check if data returned includes expiration-day trading

---

## Opening an IBKR Account - Steps

### Step 1: Apply Online (15 minutes)

**URL**: https://www.interactivebrokers.com/en/home.php

**Information Needed**:
- SSN / Tax ID
- Employment information
- Financial information (net worth, income)
- Trading experience (be honest)

**Account Approval**: 1-3 business days typical

### Step 2: Fund Account (Optional Initially)

**Minimum to Test Market Data**: $100-500 suggested

**Funding Methods**:
- ACH transfer (free, 3-5 days)
- Wire transfer ($0-25 fee, same day)
- Check (slow, 5-10 days)

**Can Skip**: You can open account first, test later after funding

### Step 3: Enable API Access

**TWS Settings**:
- Download TWS (Trader Workstation) or IB Gateway
- Enable API connections in settings
- Configure ports and permissions

### Step 4: Test Historical Data

**Python Example**:
```python
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract

# Connect to TWS
app = IBApi()
app.connect("127.0.0.1", 7497, clientId=1)

# Request historical data for SPX option
contract = Contract()
contract.symbol = "SPX"
contract.secType = "OPT"
contract.lastTradeDateOrContractMonth = "20260113"  # Jan 13 expiration
contract.strike = 5900
contract.right = "C"
contract.exchange = "SMART"

# Request bars on expiration day (the key test!)
app.reqHistoricalData(
    reqId=1,
    contract=contract,
    endDateTime="20260113 16:00:00 US/Eastern",
    durationStr="1 D",
    barSizeSetting="1 min",
    whatToShow="TRADES",
    useRTH=1,
    formatDate=1
)

# Check if data returned for expiration day trading
```

---

## Cost Comparison

### IBKR Path

**Upfront**:
- Account opening: $0
- Initial deposit: $100-500 (to test)
- Setup time: 1-3 days approval + 3-5 days funding

**Monthly**:
- Market data: $10/month (or free if trade $30/month)
- Account maintenance: $0 ($10/mo if inactive, but waived if $100k+ balance)

**Total First Month**: $100-500 deposit + $10 data = $110-510

**Ongoing**: $0-10/month depending on trading activity

### vs ThetaData (ruled out)

ThetaData interface issue makes this not an option anymore.

### vs Databento (waiting on response)

Databento may have 0DTE via API - waiting on support response.

### vs Tradier Collection (deployed, free)

Already running - builds dataset over 30-60 days for $0.

---

## Alternative: Polygon.io

**Cost**: $79-99/month for options data

**Features**:
- REST API + WebSockets
- Historical options data
- Real-time + delayed
- Good documentation

**API Access**: ✅ YES - Real REST API

**0DTE Availability**: ❓ Unknown - needs verification

**To Test**: Free tier available with delayed data

**URL**: https://polygon.io/pricing

---

## Alternative: FirstRate Data

**Cost**: $300-1,000 one-time (per symbol, per timeframe)

**Features**:
- Historical options data only
- One-time purchase (not subscription)
- Download CSV files
- SPX/SPY 1 year: ~$300
- SPX/SPY 5 years: ~$1,000

**API Access**: ❌ NO - CSV downloads only

**0DTE Availability**: ✅ Likely included (need to confirm)

**URL**: https://firstratedata.com/

**Good For**: One-time backtest, not ongoing

---

## Alternative: QuantConnect

**Cost**: $8-20/month

**Features**:
- Cloud backtesting platform
- Historical options data included
- Must use their platform (can't download easily)
- Python/C# backtests

**API Access**: ⚠️ Platform-based (not traditional API)

**0DTE Availability**: ❓ Unknown

**Limitation**: Must backtest in cloud, limited local export

**URL**: https://www.quantconnect.com/pricing

---

## Recommended Path Forward

### Option A: IBKR Testing (Recommended)

**Week 1**:
1. Open IBKR account today (application takes 15 min)
2. Wait for approval (1-3 days)
3. Fund with $100-500 (ACH, 3-5 days)

**Week 2**:
1. Enable API access
2. Download TWS or IB Gateway
3. Test historical data query for 0DTE option on past expiration day
4. Check if expiration-day data returned

**Week 3**:
- If YES: Download 1-2 years available, cost $10/mo
- If NO: Continue to Option B

**Total Cost**: $100-500 deposit + $10/mo data = **$110-510 first month**

### Option B: Wait for Databento Response

**Timeline**: 1-2 business days for support email response

**Cost**: $0 (already subscribed at $25/mo)

**Outcome**:
- If they have 0DTE via API: Use existing subscription
- If they don't: Move to Option A (IBKR) or Option C

### Option C: Continue with Free Tradier Collection

**Timeline**: 30-60 days to build usable dataset

**Cost**: $0 forever

**Status**: ✅ Already deployed, starts Monday

**Good For**: Patient approach, zero cost

### Option D: Polygon.io ($79-99/mo)

**If IBKR and Databento both fail**

**Pros**:
- ✅ Real REST API (not interface-based)
- ✅ Good documentation
- ✅ Professional data quality

**Cons**:
- ❌ $79-99/month ongoing
- ❓ Need to verify 0DTE availability

**Test**: Try free tier first with delayed data

---

## Summary: IBKR Eligibility

### Your Questions Answered

**Q: If I just sign up for IBKR, am I eligible?**

**A**: You can OPEN an account with $0, but to ACCESS market data you likely need:
- Fund account with some amount ($100-500 minimum suggested)
- OR generate $30/month in commissions (trade actively)
- Account must be approved and active

**Q: Do I have to deposit funds?**

**A**:
- To open account: **NO** (can apply with $0)
- To access market data: **PROBABLY YES** ($100-500 minimum suggested)
- Exact requirement varies by data feed

**Recommendation**:
1. Open account (free, takes 1-3 days approval)
2. Fund with $100-500 to test (can withdraw later if doesn't work)
3. Test historical 0DTE data availability
4. If it works: Keep account, $10/mo data cost
5. If it doesn't: Withdraw funds, fall back to free Tradier collection

---

## Next Steps

### Immediate (Today)

**1. Apply for IBKR account**
- URL: https://www.interactivebrokers.com
- Application: 15 minutes
- No deposit required to apply

**2. Send Databento support email**
- Template: `email_databento_support.txt`
- May have 0DTE via API even if batch doesn't

### This Week

**3. Fund IBKR account** (once approved)
- Minimum: $100-500
- Method: ACH (free, 3-5 days)

**4. Wait for Databento response**
- Expected: 1-2 business days
- May save you $10/mo if they have 0DTE

### Next Week

**5. Test IBKR historical data**
- Query 0DTE option on past expiration day
- Check if data includes expiration-day trading
- If YES: Best option at $10/mo
- If NO: Continue with free Tradier

### Ongoing

**6. Monitor Tradier collection** (already deployed)
- Starts: Monday Jan 13, 2026
- Cost: $0 forever
- Fallback option if IBKR doesn't work

---

**Created**: 2026-01-10
**ThetaData Status**: ❌ Ruled out (interface not API-based)
**IBKR Status**: ⏳ Can open account, needs funding to test
**Databento Status**: ⏳ Awaiting support response
**Tradier Status**: ✅ Deployed, starting Monday (free)

