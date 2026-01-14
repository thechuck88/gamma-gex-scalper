# IBKR Windows Setup Guide - Download SPX Options Data

## Step-by-Step Instructions

### Step 1: Install IB Gateway (5 minutes)

**Option A: IB Gateway (Recommended - lightweight, no GUI needed)**

1. Download IB Gateway:
   - Go to: https://www.interactivebrokers.com/en/trading/ibgateway-stable.php
   - Click "Download IB Gateway (Stable)"
   - Choose "Windows" version

2. Install:
   - Run the installer
   - Accept default settings
   - **DO NOT** start it yet

**Option B: TWS (Full platform with GUI)**

1. Download TWS:
   - Go to: https://www.interactivebrokers.com/en/trading/tws.php
   - Download "Trader Workstation"

2. Install and skip for now

### Step 2: Configure API Access (3 minutes)

1. **Start IB Gateway or TWS**

2. **Log in** with your credentials:
   - Username: `thechuck77`
   - Password: `mugvyr-donwiz-peqtI5`

3. **Enable API access:**

   **For IB Gateway:**
   - Click "Configure" → "Settings"
   - Go to "API" → "Settings"
   - Check "Enable ActiveX and Socket Clients"
   - Set "Socket port" to `7497` (for paper trading)
   - Uncheck "Read-Only API"
   - Click "OK"

   **For TWS:**
   - Go to: File → Global Configuration → API → Settings
   - Same settings as above

4. **Important:** Leave IB Gateway/TWS running!

### Step 3: Install Python Library (1 minute)

Open Command Prompt (Windows key + R, type `cmd`, press Enter):

```bash
pip install ib_insync pandas
```

### Step 4: Download the Python Script (1 minute)

1. **Download from server:**

On your Windows machine, open Command Prompt and run:

```bash
scp root@your-server-ip:/gamma-scalper/ibkr_download_spx_options.py C:\Users\%USERNAME%\Downloads\
```

Or just create a new file `ibkr_download_spx_options.py` and copy/paste the script.

### Step 5: Run the Script (5-15 minutes)

1. **Navigate to the script location:**

```bash
cd C:\Users\%USERNAME%\Downloads
```

2. **Run the script:**

```bash
python ibkr_download_spx_options.py
```

3. **What it does:**

The script will:
- Connect to IB Gateway/TWS on your machine
- Fetch SPX option chains
- Download 1-minute bars for the last 5 trading days
- For each day, get 4 option contracts:
  - ATM Call (sell leg)
  - ATM+5 Call (buy leg)
  - ATM Put (sell leg)
  - ATM-5 Put (buy leg)
- Save CSV files to `ibkr_spx_data/` folder

4. **Expected output:**

```
================================================================================
CONNECTING TO INTERACTIVE BROKERS
================================================================================
Port: 7497 (Paper Trading)
✓ Connected!
Account(s): ['DU123456']

================================================================================
FETCHING SPX OPTION CHAINS
================================================================================
✓ Found 1 option chain(s)

Current SPX price: 5900.50

Will attempt to download 5 days:
  - 2026-01-05 Monday
  - 2026-01-06 Tuesday
  - 2026-01-07 Wednesday
  - 2026-01-08 Thursday
  - 2026-01-09 Friday

================================================================================
Downloading 2026-01-05 (expiration: 20260105)
ATM Strike: 5900.0
================================================================================

Qualifying contracts...
  ✓ atm_call: Strike 5900.0 C
  ✓ atm_put: Strike 5900.0 P
  ✓ otm_call: Strike 5905.0 C
  ✓ otm_put: Strike 5895.0 P

Fetching atm_call...
  ✓ Retrieved 390 bars

Fetching atm_put...
  ✓ Retrieved 390 bars

Fetching otm_call...
  ✓ Retrieved 390 bars

Fetching otm_put...
  ✓ Retrieved 390 bars

Merging data...
✓ Merged dataset: 390 rows, 17 columns

✓ Saved: ibkr_spx_data/spx_options_20260105.csv

[... repeats for other days ...]

================================================================================
DOWNLOAD COMPLETE
================================================================================

Successfully downloaded 5 files:
  - ibkr_spx_data/spx_options_20260105.csv (156.3 KB)
  - ibkr_spx_data/spx_options_20260106.csv (152.8 KB)
  - ibkr_spx_data/spx_options_20260107.csv (149.2 KB)
  - ibkr_spx_data/spx_options_20260108.csv (147.5 KB)
  - ibkr_spx_data/spx_options_20260109.csv (151.1 KB)
```

### Step 6: Upload to Linux Server (1 minute)

From Windows Command Prompt:

```bash
cd C:\Users\%USERNAME%\Downloads
scp ibkr_spx_data\*.csv root@your-server-ip:/gamma-scalper/databento/ibkr/
```

Or use WinSCP (GUI tool) to upload the files.

### Step 7: Verify on Server

SSH into your server and check:

```bash
ls -lh /gamma-scalper/databento/ibkr/
```

You should see:
```
spx_options_20260105.csv
spx_options_20260106.csv
spx_options_20260107.csv
spx_options_20260108.csv
spx_options_20260109.csv
```

## Troubleshooting

### "Connection refused" error

**Problem:** IB Gateway/TWS is not running

**Solution:**
1. Start IB Gateway or TWS
2. Make sure you're logged in
3. Wait 10 seconds for it to fully start
4. Try the script again

### "No data returned" for some contracts

**Problem:** Historical data not available for that contract

**Reasons:**
- Option didn't trade that day
- Strike too far OTM (no liquidity)
- Weekend/holiday (no trading)

**Solution:** Script will skip and continue

### "API connection limit exceeded"

**Problem:** IBKR limits historical data requests

**Solution:**
- Wait 10 minutes and try again
- Or reduce `DAYS_TO_DOWNLOAD` in the script (line 39)

### Authentication issues

**Problem:** Login credentials rejected

**Solution:**
1. Verify username/password in IBKR portal
2. Check if paper trading is enabled
3. Try resetting password

## Configuration Options

Edit the script to customize:

```python
# Line 35: Paper trading vs Live
PAPER_TRADING = True  # Set False for live account

# Line 39: Number of days to download
DAYS_TO_DOWNLOAD = 5  # Change to 10, 20, etc.
```

## Data Format

Each CSV file contains 1-minute bars with columns:

- `date` - Timestamp (YYYY-MM-DD HH:MM:SS)
- `atm_call_open`, `atm_call_high`, `atm_call_low`, `atm_call_close`, `atm_call_volume`
- `atm_put_open`, `atm_put_high`, `atm_put_low`, `atm_put_close`, `atm_put_volume`
- `otm_call_open`, `otm_call_high`, `otm_call_low`, `otm_call_close`, `otm_call_volume`
- `otm_put_open`, `otm_put_high`, `otm_put_low`, `otm_put_close`, `otm_put_volume`

**Perfect for credit spread backtesting!**

## Next Steps

After uploading to server:
1. Run backtest with proper stop loss monitoring
2. Compare to Databento data (which had no 0DTE)
3. Validate your strategy assumptions

## Important Notes

- **IBKR Rate Limits:** Max 60 requests per 10 minutes for historical data
- **Market Data Subscription:** You may need to subscribe to OPRA data in your IBKR account
- **Paper Trading:** Free, no real money required
- **API Permissions:** Must be enabled in account settings

## Cost

- **IB Gateway/TWS:** Free
- **Paper Trading Account:** Free
- **Historical Data Requests:** Free (within rate limits)
- **Market Data Subscription:** May require ~$1-10/month for real-time OPRA quotes

Check your IBKR account → Market Data Subscriptions to see if you need to add OPRA.

---

**Total Setup Time: ~15-30 minutes**

**Expected Data Volume: ~750 KB for 5 days (1-minute bars, 4 contracts)**

Good luck! 🚀
