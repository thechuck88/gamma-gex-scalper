# 1-Minute Data Sources for SPX/NDX Backtesting

## Overview

For realistic 0DTE backtesting, we need 1-minute intraday bars for SPX/NDX. Since these are indexes (not directly tradable), we use ETF proxies:

- **SPX** → **SPY** × 10.0
- **NDX** → **QQQ** × 42.5

## Available Data Sources

### 1. Alpaca (⭐ RECOMMENDED - FREE)

**Features:**
- ✅ **5 years** of 1-minute data
- ✅ **Free** tier available
- ✅ No rate limits on historical data
- ✅ SPY, QQQ, and all US equities
- ✅ Easy API integration

**Limitations:**
- ❌ US markets only (no international indexes)
- ❌ Requires account signup

**Setup:**

```bash
# Install Alpaca SDK
pip install alpaca-trade-api

# Set environment variables
export APCA_API_KEY_ID="your_key_here"
export APCA_API_SECRET_KEY="your_secret_here"
export APCA_API_BASE_URL="https://paper-api.alpaca.markets"  # Paper trading
```

**Get API Keys:**
1. Sign up at https://alpaca.markets
2. Create a paper trading account (free)
3. Go to "Your API Keys" in dashboard
4. Copy Key ID and Secret Key

**Usage:**

```bash
# Run backtest with Alpaca 1-min data
python backtest_parallel.py NDX --use-1min --workers 30 --auto-scale
```

### 2. Yahoo Finance (LIMITED - FREE)

**Features:**
- ✅ **Free** (no account needed)
- ✅ SPY, QQQ available
- ✅ No API keys required

**Limitations:**
- ❌ **Only 7 days** of 1-minute history
- ❌ Rate limiting (429 errors common)
- ❌ Unreliable for large backtests

**Usage:**

The parallel backtest automatically falls back to Yahoo Finance if Alpaca is unavailable:

```bash
# Will use Yahoo Finance (7 days only)
python backtest_parallel.py NDX --use-1min --days 7
```

### 3. Tradier (YOUR EXISTING ACCOUNT)

**Features:**
- ✅ Real-time and historical 1-minute data
- ✅ You already have an account
- ✅ SPY, QQQ available
- ✅ Reliable API

**Limitations:**
- ❌ **35 days** of 1-minute history (not 5 years)
- ❌ Rate limits apply

**Setup:**

Your Tradier API key is already in `/etc/gamma.env`. To use it:

```python
# Add to backtest_parallel.py:

def fetch_1min_data_tradier(symbol, start_date, end_date):
    """Fetch 1-minute bars from Tradier (35 days max)."""
    import requests
    from datetime import datetime

    API_TOKEN = os.environ.get('TRADIER_API_TOKEN')
    if not API_TOKEN:
        return None

    # Tradier time series endpoint
    url = 'https://api.tradier.com/v1/markets/timesales'

    params = {
        'symbol': symbol,
        'interval': '1min',
        'start': start_date.strftime('%Y-%m-%d'),
        'end': end_date.strftime('%Y-%m-%d'),
        'session_filter': 'all'
    }

    headers = {
        'Authorization': f'Bearer {API_TOKEN}',
        'Accept': 'application/json'
    }

    response = requests.get(url, params=params, headers=headers)

    if response.status_code != 200:
        return None

    data = response.json()
    bars = data.get('series', {}).get('data', [])

    if not bars:
        return None

    df = pd.DataFrame(bars)
    df['datetime'] = pd.to_datetime(df['time'])
    df = df.rename(columns={'close': 'Close', 'high': 'High', 'low': 'Low', 'open': 'Open'})

    return df
```

### 4. Polygon.io (PAID - $200/month)

**Features:**
- ✅ **Unlimited** historical 1-minute data
- ✅ SPX, NDX, SPY, QQQ all available
- ✅ Real-time data included
- ✅ Professional-grade API

**Limitations:**
- ❌ **$200/month** for Stocks Starter plan
- ❌ $99/month for lower tier (limited history)

**Not recommended** unless you need real-time data or are already paying for Polygon.

### 5. Interactive Brokers (REQUIRES ACCOUNT)

**Features:**
- ✅ **Years** of 1-minute data
- ✅ SPX, NDX directly (not just ETFs)
- ✅ No additional cost if you have IB account

**Limitations:**
- ❌ Requires live IB account
- ❌ Complex API setup (TWS/Gateway)
- ❌ Not worth it just for backtesting

## Comparison Table

| Source | History | Cost | SPY/QQQ | SPX/NDX | Setup | Recommended |
|--------|---------|------|---------|---------|-------|-------------|
| **Alpaca** | 5 years | Free | ✅ | via ETF | Easy | ⭐⭐⭐⭐⭐ |
| **Yahoo Finance** | 7 days | Free | ✅ | via ETF | None | ⭐ |
| **Tradier** | 35 days | Free* | ✅ | via ETF | Easy | ⭐⭐⭐ |
| **Polygon.io** | Unlimited | $200/mo | ✅ | ✅ | Medium | ⭐⭐ |
| **IB** | Years | Account | ✅ | ✅ | Hard | ⭐⭐ |

*Tradier: Free sandbox, live account costs apply

## Recommended Setup (Alpaca)

### Step 1: Sign Up for Alpaca

1. Go to https://alpaca.markets
2. Click "Sign Up" → Select "Individual" account
3. Complete identity verification (required, takes 1-2 days)
4. Activate **Paper Trading** (free, unlimited)

### Step 2: Get API Keys

1. Log in to Alpaca dashboard
2. Navigate to "Paper Trading" section
3. Click "Your API Keys"
4. Copy:
   - API Key ID
   - Secret Key

### Step 3: Configure Environment

Add to your shell profile (`~/.bashrc` or `~/.zshrc`):

```bash
# Alpaca API credentials (paper trading)
export APCA_API_KEY_ID="PK..."
export APCA_API_SECRET_KEY="..."
export APCA_API_BASE_URL="https://paper-api.alpaca.markets"
```

Or create `/etc/alpaca.env`:

```bash
APCA_API_KEY_ID=PK...
APCA_API_SECRET_KEY=...
APCA_API_BASE_URL=https://paper-api.alpaca.markets
```

Then source it before running:

```bash
source /etc/alpaca.env
python backtest_parallel.py NDX --use-1min --workers 30
```

### Step 4: Install SDK

```bash
pip install alpaca-trade-api
```

### Step 5: Test

```bash
# Test 1-minute data fetch
python3 << EOF
from alpaca_trade_api.rest import REST, TimeFrame
import os

api = REST(
    os.environ['APCA_API_KEY_ID'],
    os.environ['APCA_API_SECRET_KEY'],
    base_url=os.environ['APCA_API_BASE_URL']
)

# Fetch 1 day of QQQ 1-minute data
bars = api.get_bars('QQQ', TimeFrame.Minute, limit=390).df
print(f"Fetched {len(bars)} bars")
print(bars.head())
EOF
```

Expected output:
```
Fetched 390 bars
                                  open     high      low    close    volume  ...
2026-01-09 09:30:00-05:00  530.25  530.50  530.10  530.35  1234567  ...
...
```

### Step 6: Run Full Backtest

```bash
# 1-year backtest with 30 parallel workers using real 1-min data
python backtest_parallel.py NDX --use-1min --workers 30 --auto-scale --days 252
```

## Performance Comparison

### Synthetic 30-Min Bars (Current)
- **Pros**: Fast, no external dependencies
- **Cons**: Less realistic, misses intraday volatility

### Real 1-Min Bars (Alpaca)
- **Pros**: Much more realistic, captures real intraday moves
- **Cons**: Slower download (5 years = ~500k bars), requires Alpaca account

**Expected difference**:
- Synthetic: 446 trades, $326k profit (from earlier run)
- Real 1-min: **TBD** (likely 10-20% more stop losses due to real volatility)

## Troubleshooting

### "Alpaca API keys not found"

Check environment variables:
```bash
echo $APCA_API_KEY_ID
echo $APCA_API_SECRET_KEY
```

If empty, add to `~/.bashrc` and reload:
```bash
source ~/.bashrc
```

### "No 1-minute data source available"

Fall back to synthetic:
```bash
# Remove --use-1min flag
python backtest_parallel.py NDX --workers 30 --auto-scale
```

### "Rate limit exceeded" (Yahoo Finance)

Switch to Alpaca (free) or reduce backtest period:
```bash
# Only test 7 days with Yahoo
python backtest_parallel.py NDX --use-1min --days 7
```

## Next Steps

1. **Sign up for Alpaca** (recommended): 5 years of data, free
2. **Run comparison**: Synthetic vs real 1-min data
3. **Validate results**: Check if real data increases stop loss rate
4. **Paper trade**: Test strategy live before deploying capital

---

**Generated**: 2026-01-10
**For**: Gamma GEX scalper backtest optimization
