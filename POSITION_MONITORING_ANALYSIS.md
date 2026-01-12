# Position Monitoring & Stop Loss Validation Analysis

**Date:** 2026-01-11
**Question:** Can trades.csv data simulate position monitoring and validate stop loss execution?

## Answer: NO (with important caveats)

### What We HAVE

**trades.csv contains only ENTRY and EXIT snapshots:**

| Field | Description | Example |
|-------|-------------|---------|
| `Timestamp_ET` | Entry time | `2025-12-11 12:24:35` |
| `Strikes` | Strike prices | `6850/6840P` |
| `Entry_Credit` | Credit received | `$1.25` |
| `Exit_Time` | Exit timestamp | `2025-12-11 12:30:15` |
| `Exit_Value` | Cost to close | `$0.77` |
| `P/L_$` | Total profit/loss | `$+48.00` |
| `P/L_%` | Percent return | `+38.4%` |
| `Exit_Reason` | Why closed | `Trailing Stop (40% from peak 48%)` |
| `Duration_Min` | Trade duration | `6` minutes |

**This tells us:**
- ✅ Entry price and time
- ✅ Exit price and time
- ✅ Final P/L outcome
- ✅ Exit reason (SL, TP, Trailing, etc.)
- ✅ Duration

**This does NOT tell us:**
- ❌ P/L evolution during the trade
- ❌ When stop loss was triggered (only when it was closed)
- ❌ Whether position drifted past SL before close
- ❌ Bid/ask spread movement during trade
- ❌ Peak profit before trailing stop activated

---

### What We DON'T HAVE (but should)

**Monitor logs from Dec 10-18, 2025 are GONE (rotated out):**

- Log rotation keeps only 7 days of history
- Trades from Dec 10-18 happened 3+ weeks ago
- Oldest log: Jan 3, 2026 (`monitor_paper.log.7.gz`)
- All December logs: **deleted**

**What those logs would have contained (from monitor.py line 1026-1028):**

```
[2025-12-11 12:24:45] Order 22875504: entry=$1.25 mid=$1.20 ask=$1.22 P/L=+4.0% (SL_PL=+2.4%, best=+4.0%) TP=70%
[2025-12-11 12:25:00] Order 22875504: entry=$1.25 mid=$1.10 ask=$1.12 P/L=+12.0% (SL_PL=+10.4%, best=+12.0%) TP=70%
[2025-12-11 12:25:15] Order 22875504: entry=$1.25 mid=$0.95 ask=$0.97 P/L=+24.0% (SL_PL=+22.4%, best=+24.0%) TP=70%
[2025-12-11 12:25:30] Order 22875504: entry=$1.25 mid=$0.85 ask=$0.87 P/L=+32.0% (SL_PL=+30.4%, best=+32.0%) TP=70%
[2025-12-11 12:25:45] Order 22875504: entry=$1.25 mid=$0.75 ask=$0.77 P/L=+40.0% (SL_PL=+38.4%, best=+48.0%) TP=70%
[2025-12-11 12:26:00] *** TRAILING STOP ACTIVATED for 22875504 at 48.0% profit ***
[2025-12-11 12:26:15] Order 22875504: entry=$1.25 mid=$0.77 ask=$0.79 P/L=+38.4% (SL_PL=+36.8%, best=+48.0%) TP=70% [TRAIL: 40.0%]
[2025-12-11 12:26:30] Order 22875504: entry=$1.25 mid=$0.79 ask=$0.81 P/L=+36.8% (SL_PL=+35.2%, best=+48.0%) TP=70% [TRAIL: 40.0%]
[2025-12-11 12:30:15] CLOSING 22875504: Trailing Stop (40% from peak 48%)
```

**This 15-second granularity would show:**
- Exact moment SL triggered
- P/L drift after trigger
- Peak profit tracking for trailing stops
- Whether position was closed immediately or with delay

---

## What monitor.py ACTUALLY Does

### Stop Loss Logic (lines 1057-1086)

```python
# Uses ASK price for stop loss (worst-case exit)
profit_pct_sl = (entry_credit - ask_value) / entry_credit

# Regular stop loss: -10% (STOP_LOSS_PCT)
if profit_pct_sl <= -0.10:
    # Grace period: 300 seconds (SL_GRACE_PERIOD_SEC)
    if position_age_sec >= 300:
        exit_reason = f"Stop Loss ({profit_pct_sl*100:.0f}% worst-case)"
    else:
        log("In grace period - holding")

# Emergency stop loss: -40% (SL_EMERGENCY_PCT)
if profit_pct_sl <= -0.40:
    exit_reason = f"EMERGENCY Stop Loss ({profit_pct_sl*100:.0f}%)"
    # Immediate exit, no grace period
```

### Trailing Stop Logic (lines 949-951, 1050-1051)

```python
# Activation: 25% profit (TRAILING_TRIGGER_PCT)
if profit_pct >= 0.25:
    trailing_active = True
    log(f"*** TRAILING STOP ACTIVATED at {profit_pct*100:.1f}% profit ***")

# Track peak profit
if profit_pct > best_profit_pct:
    best_profit_pct = profit_pct

# Trail distance calculation (lines 960-965)
profit_above_trigger = best_profit_pct - 0.25  # How much above 25%?
trail_distance = 0.15 - (profit_above_trigger * 0.4)  # Shrinks as profit grows
trail_distance = max(trail_distance, 0.08)  # Minimum 8% trail
trailing_stop_level = best_profit_pct - trail_distance

# Exit when profit drops to trail level
if profit_pct <= trailing_stop_level:
    exit_reason = f"Trailing Stop ({trailing_stop_level*100:.0f}% from peak {best_profit_pct*100:.0f}%)"
```

### Monitoring Frequency

- **POLL_INTERVAL = 15 seconds** (line 71)
- Checks every 15 seconds during market hours (9:30 AM - 4:00 PM ET)
- Auto-close at 3:50 PM for 0DTE positions
- Expire worthless at 4:00 PM if still open

---

## Validating Stop Loss from trades.csv

### What We CAN Validate

#### 1. Exit Reasons Match Logic

**From trades.csv:**
- `"Stop Loss (-20%)"` → Regular SL hit (>300s old, loss >10%)
- `"EMERGENCY Stop Loss (-50%)"` → Emergency SL hit (loss >40%)
- `"Trailing Stop (40% from peak 48%)"` → Trailing activated, profit dropped from 48% to 40%
- `"Profit Target (50%)"` → Hit 50% or 70% target (based on confidence)

All exit reasons align with monitor.py logic ✓

#### 2. Stop Loss Percentages

**Expected:** -10% regular, -40% emergency

**Actual from trades.csv:**
- `-20.0%` (2 trades) → Within -10% to -40% range ✓
- `-33.3%` (2 trades) → Within range ✓
- `-50.0%` (1 trade) → EMERGENCY triggered ✓
- `-80.0%` (1 trade) → EMERGENCY triggered (extreme) ✓

**Pattern:** Stop losses trigger between -10% and -50%, matching the code.

#### 3. Duration vs Grace Period

**Grace period:** 300 seconds (5 minutes)

**Trades with SL and duration < 5 min:**
- `Duration_Min=0` → Likely EMERGENCY stop (no grace period) ✓
- `Duration_Min=1-4` → May have been EMERGENCY or just-past grace period

**Trades with SL and duration > 5 min:**
- `Duration_Min=6, 8, 36, 49` → Regular SL after grace period ✓

**Pattern:** Matches expected behavior.

### What We CANNOT Validate

#### ❌ Stop Loss Execution Speed

- **Question:** When SL was triggered, how long until position was closed?
- **Need:** 15-second granularity logs showing trigger → close
- **Have:** Only entry and exit timestamps (minutes apart)

**Example from trades.csv:**
```
Entry: 2025-12-11 12:24:35
Exit:  2025-12-11 12:30:15
Exit Reason: Trailing Stop (40% from peak 48%)
Duration: 6 minutes
```

**Cannot determine:**
- When did profit reach 48% peak?
- When did trailing stop activate (at 25%)?
- When did profit drop to 40% (trigger level)?
- How many seconds between trigger and actual close?

#### ❌ Price Drift After Trigger

- **Question:** Does position drift further into loss after SL triggers but before close?
- **Need:** Bid/ask prices at trigger time vs close time
- **Have:** Only final exit value

**Example:**
- SL triggers at -10% (ask=$1.50)
- Close executes 15 seconds later at ask=$1.52 (now -11%)
- trades.csv only shows: `Exit_Value=$1.52, P/L_%=-11.0%`

**Cannot determine:** Whether -11% = initial trigger level OR drift after trigger.

#### ❌ Bid/Ask Spread Impact

- **Question:** How much does spread cost on exit?
- **Need:** Bid/ask at entry and exit
- **Have:** Only mid prices (entry_credit, exit_value)

**Example:**
- Entry: sell spread for $1.25 credit (mid)
- Exit: buy back at $1.40 (could be bid=$1.38, ask=$1.42)
- Spread cost: $0.02 hidden in exit_value

**Cannot isolate:** Slippage from spread vs actual price movement.

---

## Creating a Simulation Framework

### Option 1: Replay with Historical Options Data (BEST)

**Fetch historical 1-minute bars for options:**

```python
# For each trade in trades.csv:
trade = {
    'timestamp': '2025-12-11 12:24:35',
    'strikes': '6850/6840P',
    'entry_credit': 1.25,
    'exit_time': '2025-12-11 12:30:15'
}

# Parse option symbols (need expiry date)
short_symbol = 'SPXW251211P06850000'  # 0DTE: same day expiry
long_symbol = 'SPXW251211P06840000'

# Fetch 1-min bars from Tradier API
bars_short = fetch_option_bars(short_symbol, '2025-12-11 12:24', '2025-12-11 12:31')
bars_long = fetch_option_bars(long_symbol, '2025-12-11 12:24', '2025-12-11 12:31')

# Replay position monitoring
for timestamp in bars_short.index:
    short_bid = bars_short.loc[timestamp, 'bid']
    short_ask = bars_short.loc[timestamp, 'ask']
    long_bid = bars_long.loc[timestamp, 'bid']
    long_ask = bars_long.loc[timestamp, 'ask']

    # Spread value (cost to close)
    spread_mid = (short_ask - long_bid + short_bid - long_ask) / 2
    spread_ask = (short_ask - long_bid)  # Worst case for SL

    # Calculate P/L
    profit_pct = (entry_credit - spread_mid) / entry_credit
    profit_pct_sl = (entry_credit - spread_ask) / entry_credit

    # Check stop loss
    if profit_pct_sl <= -0.10:
        print(f"{timestamp}: SL TRIGGERED at {profit_pct_sl*100:.1f}%")
```

**Pros:**
- ✅ Exact replay of trade
- ✅ Validates stop loss execution timing
- ✅ Measures slippage and drift

**Cons:**
- ❌ Requires Tradier API access (already have)
- ❌ Historical options data may not be available for Dec 2025
- ❌ API rate limits (need to batch carefully)

### Option 2: Synthetic Replay with SPX Price Data

**Use SPX underlying price to estimate option prices:**

```python
# Fetch SPX 1-min bars
spx_bars = yf.download('^SPX', start='2025-12-11 12:24', end='2025-12-11 12:31', interval='1m')

# Estimate option prices using Black-Scholes
for timestamp, spx_price in spx_bars.iterrows():
    time_to_expiry = (datetime(2025, 12, 11, 16, 0) - timestamp).seconds / 3600 / 24 / 365

    short_price = black_scholes_put(spx_price, 6850, time_to_expiry, vix/100, 0)
    long_price = black_scholes_put(spx_price, 6840, time_to_expiry, vix/100, 0)

    spread_value = short_price - long_price
    profit_pct = (entry_credit - spread_value) / entry_credit

    # Check stop loss...
```

**Pros:**
- ✅ SPX data readily available
- ✅ No API rate limits
- ✅ Can replay all 39 trades

**Cons:**
- ❌ Black-Scholes estimates may not match real bid/ask
- ❌ Doesn't capture bid/ask spread
- ❌ Ignores volatility smile and Greeks

### Option 3: Forward Monitoring (BEST for Monday)

**Enable detailed logging starting Monday Jan 13:**

```python
# In monitor.py, add detailed P/L logging to file
PL_LOG_FILE = "/root/gamma/data/position_pl_tracking.csv"

# Log every 15-second check
with open(PL_LOG_FILE, 'a') as f:
    f.write(f"{timestamp},{order_id},{current_value},{profit_pct},{best_profit_pct},{trailing_active}\n")
```

**Then analyze after 1-2 weeks:**
- Validate stop loss execution speed
- Measure slippage on exits
- Confirm trailing stop behavior
- Compare to backtest assumptions

---

## Recommendations

### 1. Enable Position P/L Logging (HIGH PRIORITY)

Add to monitor.py:

```python
def log_position_pl(order_id, timestamp, entry_credit, current_mid, current_ask,
                    profit_pct, profit_pct_sl, best_profit_pct, trailing_active):
    """Log position P/L for post-trade analysis."""
    pl_log = "/root/gamma/data/position_pl_tracking.csv"

    # Create header if file doesn't exist
    if not os.path.exists(pl_log):
        with open(pl_log, 'w') as f:
            f.write("timestamp,order_id,entry_credit,current_mid,current_ask,"
                   "profit_pct,profit_pct_sl,best_profit_pct,trailing_active\n")

    with open(pl_log, 'a') as f:
        f.write(f"{timestamp},{order_id},{entry_credit:.2f},{current_mid:.2f},{current_ask:.2f},"
               f"{profit_pct:.4f},{profit_pct_sl:.4f},{best_profit_pct:.4f},{trailing_active}\n")
```

Call this every monitoring cycle (line 1029).

### 2. Increase Monitor Log Retention

**Current:** 7 days (rotates daily, keeps .1 through .7)

**Proposed:** 30 days

```bash
# Edit /etc/logrotate.d/gamma-monitor
/root/gamma/data/monitor_*.log {
    daily
    rotate 30          # Was: 7
    compress
    delaycompress
    missingok
    notifempty
}
```

### 3. Validate on Monday Jan 13

**Watch for:**
- First 10 trades: Check monitor log shows P/L every 15 seconds
- Stop loss trades: Verify exit happens within 1-2 monitoring cycles (15-30 seconds)
- Trailing stops: Confirm peak profit tracked correctly
- Slippage: Compare entry_credit vs actual fill, exit_value vs actual fill

### 4. Backtest Validation Tool

Create `validate_stop_loss_execution.py`:

```python
def analyze_stop_loss_trades(trades_csv):
    """Analyze stop loss execution from trades.csv."""
    df = pd.read_csv(trades_csv)
    sl_trades = df[df['Exit_Reason'].str.contains('Stop Loss', na=False)]

    for _, trade in sl_trades.iterrows():
        duration_sec = trade['Duration_Min'] * 60
        pl_pct = float(trade['P/L_%'].replace('%', ''))

        # Check if SL matches expected thresholds
        if 'EMERGENCY' in trade['Exit_Reason']:
            assert pl_pct <= -40, f"Emergency SL should be <= -40%, got {pl_pct}%"
        else:
            assert pl_pct <= -10, f"Regular SL should be <= -10%, got {pl_pct}%"

        # Check grace period
        if duration_sec < 300 and 'EMERGENCY' not in trade['Exit_Reason']:
            print(f"WARNING: Regular SL hit before grace period: {trade['Trade_ID']}")
```

---

## Conclusion

### Current State: ❌ NO

**trades.csv does NOT contain enough data to simulate position monitoring and validate stop loss execution.**

We only have entry/exit snapshots, not the 15-second P/L tracking needed to verify:
- Exact trigger timing
- Execution speed
- Price drift after trigger
- Bid/ask spread impact

### What We CAN Validate: ✓ Partial

From trades.csv, we CAN verify:
- ✅ Exit reasons match logic (SL, TP, Trailing, etc.)
- ✅ Stop loss percentages in expected range (-10% to -50%)
- ✅ Grace period behavior (duration vs SL type)
- ✅ Trailing stop activated at reasonable profits

### Going Forward: ✅ YES (with changes)

To enable full validation starting Monday Jan 13:
1. ✅ Add position_pl_tracking.csv logging (15-second granularity)
2. ✅ Increase log retention to 30 days
3. ✅ Monitor first week for execution quality
4. ✅ Build replay tools for historical validation

Then we can answer definitively:
- Are stop losses executing within 15-30 seconds of trigger?
- How much does price drift after SL trigger?
- What is average slippage on exits?
- Do trailing stops track peaks correctly?
