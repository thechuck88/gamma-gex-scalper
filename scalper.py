#!/usr/bin/env python3
# gex_scalper.py — FINAL 100% COMPLETE (Dec 10, 2025)
# Real GEX pin | Smart strikes | Real TP/SL | Dry-run | Full logging | Asymmetric IC exploit

import sys
print(f"[STARTUP] Scalper invoked at {__import__('datetime').datetime.now()}", flush=True)

import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")

import datetime, os, requests, json, csv, pytz, time, sys, math, fcntl
import yfinance as yf
import pandas as pd
from datetime import date

# ==================== CONFIG ====================
from config import (PAPER_ACCOUNT_ID, LIVE_ACCOUNT_ID, TRADIER_LIVE_KEY, TRADIER_SANDBOX_KEY,
                    DISCORD_ENABLED, DISCORD_WEBHOOK_URL,
                    DISCORD_DELAYED_ENABLED, DISCORD_DELAYED_WEBHOOK_URL, DISCORD_DELAY_SECONDS)
from threading import Timer

# ==================== RETRY LOGIC ====================
def retry_api_call(func, max_attempts=3, base_delay=2.0, description="API call"):
    """
    Retry API calls with exponential backoff.

    Args:
        func: Callable that returns requests.Response
        max_attempts: Maximum retry attempts (default 3)
        base_delay: Base delay in seconds for exponential backoff (default 2.0)
        description: Description of the call for logging

    Returns:
        requests.Response if successful
        None if all attempts failed
    """
    for attempt in range(1, max_attempts + 1):
        try:
            response = func()

            # Success on 2xx
            if 200 <= response.status_code < 300:
                if attempt > 1:
                    log(f"[RETRY] {description} succeeded on attempt {attempt}/{max_attempts}")
                return response

            # Server error (5xx) - retry
            if 500 <= response.status_code < 600:
                if attempt < max_attempts:
                    delay = base_delay * (2 ** (attempt - 1))
                    log(f"[RETRY] {description} got {response.status_code}, retrying in {delay}s (attempt {attempt}/{max_attempts})")
                    time.sleep(delay)
                    continue
                else:
                    log(f"[RETRY] {description} failed after {max_attempts} attempts: {response.status_code}")
                    return response

            # Client error (4xx) - don't retry
            log(f"[RETRY] {description} failed with {response.status_code} (no retry for 4xx)")
            return response

        except requests.exceptions.Timeout:
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                log(f"[RETRY] {description} timeout, retrying in {delay}s (attempt {attempt}/{max_attempts})")
                time.sleep(delay)
                continue
            else:
                log(f"[RETRY] {description} timeout after {max_attempts} attempts")
                return None

        except requests.exceptions.ConnectionError as e:
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                log(f"[RETRY] {description} connection error, retrying in {delay}s (attempt {attempt}/{max_attempts})")
                time.sleep(delay)
                continue
            else:
                log(f"[RETRY] {description} connection error after {max_attempts} attempts: {e}")
                return None

    return None

# ==================== DISCORD ALERTS ====================
def _send_to_webhook(url, msg):
    """Helper to send message to a webhook URL."""
    try:
        r = requests.post(url, json=msg, timeout=5)
        print(f"[DISCORD] Webhook sent: {r.status_code} - {msg['embeds'][0]['title']}")
    except Exception as e:
        print(f"[DISCORD] Alert failed: {e}")

def send_discord_skip_alert(reason, run_data=None):
    """Send alert when trade is skipped, including full run data."""
    if not DISCORD_ENABLED or not DISCORD_WEBHOOK_URL:
        return
    try:
        fields = []
        if run_data:
            if 'spx' in run_data:
                fields.append({"name": "SPX", "value": f"{run_data['spx']:.0f}", "inline": True})
            if 'vix' in run_data:
                fields.append({"name": "VIX", "value": f"{run_data['vix']:.2f}", "inline": True})
            if 'expected_move' in run_data:
                fields.append({"name": "Expected 2hr Move", "value": f"±{run_data['expected_move']:.1f} pts", "inline": True})
            if 'rsi' in run_data:
                fields.append({"name": "RSI", "value": f"{run_data['rsi']:.1f}", "inline": True})
            if 'consec_down' in run_data:
                fields.append({"name": "Down Days", "value": str(run_data['consec_down']), "inline": True})
            # REDACTED: GEX Pin, Distance, Setup (proprietary)

        # Redact pin and distance from skip reason (distance reveals pin)
        redacted_reason = reason
        if run_data:
            if 'pin' in run_data:
                redacted_reason = redacted_reason.replace(str(int(run_data['pin'])), '****')
            if 'distance' in run_data:
                redacted_reason = redacted_reason.replace(f"{int(run_data['distance'])}pts", "***pts")
        fields.append({"name": "Skip Reason", "value": f"❌ {redacted_reason}", "inline": False})

        msg = {
            "embeds": [{
                "title": "⏭️ GEX SCALP — NO TRADE",
                "color": 0x95a5a6,  # Gray
                "fields": fields,
                "timestamp": datetime.datetime.utcnow().isoformat()
            }]
        }
        _send_to_webhook(DISCORD_WEBHOOK_URL, msg)
    except Exception as e:
        print(f"Discord skip alert failed: {e}")

# Global dict to collect run data for Discord
run_data = {}

def send_discord_entry_alert(setup, credit, strikes, tp_pct, order_id):
    """Send trade entry alert to Discord (immediate + delayed). Strikes redacted."""
    if not DISCORD_ENABLED or not DISCORD_WEBHOOK_URL:
        return

    try:
        # Color based on strategy
        colors = {'CALL': 0xff6b6b, 'PUT': 0x4ecdc4, 'IC': 0xffe66d}
        color = colors.get(setup['strategy'], 0x95a5a6)

        tp_target = int((1 - tp_pct) * 100)
        dollar_credit = credit * 100

        msg = {
            "embeds": [{
                "title": f"🎯 GEX SCALP ENTRY — {setup['strategy']}",
                "color": color,
                "fields": [
                    {"name": "Strategy", "value": setup['strategy'], "inline": True},
                    {"name": "Direction", "value": setup['direction'], "inline": True},
                    {"name": "Confidence", "value": setup['confidence'], "inline": True},
                    {"name": "Strikes", "value": strikes, "inline": True},
                    {"name": "Credit", "value": f"${credit:.2f} (${dollar_credit:.0f})", "inline": True},
                    {"name": "TP Target", "value": f"{tp_target}%", "inline": True},
                    {"name": "Stop Loss", "value": "10%", "inline": True},
                ],
                "footer": {"text": f"0DTE SPX"},
                "timestamp": datetime.datetime.utcnow().isoformat()
            }]
        }

        # Send immediate alert
        _send_to_webhook(DISCORD_WEBHOOK_URL, msg)

        # Send delayed alert (7 min) to free tier - LIVE only
        if DISCORD_DELAYED_ENABLED and DISCORD_DELAYED_WEBHOOK_URL and mode == "REAL":
            msg_delayed = msg.copy()
            msg_delayed["embeds"] = [msg["embeds"][0].copy()]
            msg_delayed["embeds"][0]["title"] = f"⏰ GEX SCALP ENTRY — {setup['strategy']} (delayed)"
            timer = Timer(DISCORD_DELAY_SECONDS, _send_to_webhook, [DISCORD_DELAYED_WEBHOOK_URL, msg_delayed])
            timer.daemon = True  # Ensure thread cleans up (already default for Timer, but explicit is better)
            timer.start()

    except Exception as e:
        print(f"Discord alert failed: {e}")

# ==================== MODE & OVERRIDES ====================
mode = "PAPER"
pin_override = None
spx_override = None
dry_run = False

if len(sys.argv) > 1:
    arg1 = sys.argv[1].upper()
    if arg1 in ["REAL", "LIVE"]:
        mode = "REAL"
    elif arg1 == "PAPER":
        mode = "PAPER"
    elif arg1.replace(".", "").isdigit():
        dry_run = True
        pin_override = float(arg1)

if len(sys.argv) > 2 and sys.argv[2]:
    try:
        pin_override = float(sys.argv[2])
        dry_run = True
    except (ValueError, TypeError) as e:
        print(f"Warning: Invalid pin_override '{sys.argv[2]}': {e}")
        pass

if len(sys.argv) > 3 and sys.argv[3]:
    try:
        spx_override = float(sys.argv[3])
        dry_run = True
    except (ValueError, TypeError) as e:
        print(f"Warning: Invalid spx_override '{sys.argv[3]}': {e}")
        pass

TRADIER_ACCOUNT_ID = LIVE_ACCOUNT_ID if mode == "REAL" else PAPER_ACCOUNT_ID
TRADIER_KEY = TRADIER_LIVE_KEY if mode == "REAL" else TRADIER_SANDBOX_KEY
BASE_URL = "https://api.tradier.com/v1/" if mode == "REAL" else "https://sandbox.tradier.com/v1/"
HEADERS = {"Accept": "application/json", "Authorization": f"Bearer {TRADIER_KEY}"}

TRADE_LOG_FILE = "/root/gamma/data/trades.csv"
LOCK_FILE = "/tmp/gexscalper.lock"

ET = pytz.timezone('US/Eastern')
CUTOFF_HOUR = 14  # No new trades after 2 PM ET (was 3 PM)

# Import shared GEX strategy logic (single source of truth)
# This ensures backtest and live scalper use identical setup logic
from core.gex_strategy import get_gex_trade_setup as core_get_gex_trade_setup, round_to_5

print("=" * 70)
print(f"{'LIVE TRADING MODE — REAL MONEY' if mode == 'REAL' else 'PAPER TRADING MODE — 100% SAFE'}")
print(f"Using account: {TRADIER_ACCOUNT_ID}")
if dry_run: print("DRY RUN — NO ORDERS WILL BE SENT")
if pin_override: print(f"PIN OVERRIDE: {pin_override}")
if spx_override: print(f"SPX OVERRIDE: {spx_override}")
print("=" * 70)

def log(msg):
    print(f"[{datetime.datetime.now(ET).strftime('%H:%M:%S')}] {msg}")

print(f"[{datetime.datetime.now(ET).strftime('%H:%M:%S')}] Scalper starting...")

# Acquire exclusive lock using fcntl (atomic, no race condition)
# This prevents duplicate orders if multiple scalper instances start simultaneously
try:
    lock_fd = open(LOCK_FILE, 'w')
    # Try to acquire exclusive lock (non-blocking)
    # LOCK_EX = exclusive lock, LOCK_NB = non-blocking (fail immediately if locked)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # Write PID for debugging
    lock_fd.write(f"{os.getpid()}\n")
    lock_fd.flush()
    print(f"[{datetime.datetime.now(ET).strftime('%H:%M:%S')}] Lock acquired (PID: {os.getpid()})")
except BlockingIOError:
    # Another instance holds the lock
    print(f"[{datetime.datetime.now(ET).strftime('%H:%M:%S')}] Lock file exists — another instance running, exiting")
    exit(0)
except Exception as e:
    print(f"[{datetime.datetime.now(ET).strftime('%H:%M:%S')}] Failed to acquire lock: {e}")
    exit(1)

# ==============================================
#                  FUNCTIONS
# ==============================================

def get_price(symbol, use_live=False):
    """Fetch price from Tradier. Always uses LIVE API for accurate real-time data.

    Args:
        symbol: Ticker symbol
        use_live: If True, force LIVE API (default for market data)

    Returns:
        float: Price if available and valid
        None: If quote unavailable or invalid

    Note: NEVER returns invalid prices - all callers can safely assume
          a non-None return is a valid numeric price > 0
    """
    # Always use LIVE API for market data - sandbox is delayed/stale
    url = "https://api.tradier.com/v1/markets/quotes"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {TRADIER_LIVE_KEY}"}

    try:
        r = requests.get(url, headers=headers, params={"symbols": symbol}, timeout=10)

        # Validate response
        if r.status_code != 200:
            log(f"Tradier quote failed for {symbol}: HTTP {r.status_code}")
            return None

        data = r.json()
        q = data.get("quotes", {}).get("quote")

        if not q:
            log(f"Tradier quote empty for {symbol}")
            return None

        if isinstance(q, list):
            q = q[0]

        # Try to get price (last > bid > ask precedence)
        price = q.get("last") or q.get("bid") or q.get("ask")

        if price is None:
            log(f"Tradier quote has no price fields for {symbol}")
            return None

        # Convert to float and validate
        try:
            price_float = float(price)

            # Sanity check: price must be positive
            if price_float <= 0:
                log(f"Tradier quote for {symbol} has invalid price: {price_float}")
                return None

            return price_float

        except (ValueError, TypeError) as e:
            log(f"Tradier quote for {symbol} has non-numeric price '{price}': {e}")
            return None

    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        log(f"Tradier quote network error for {symbol}: {e}")
        return None
    except Exception as e:
        log(f"Tradier quote unexpected error for {symbol}: {e}")
        return None

def get_vix_yfinance():
    """Fetch VIX from Yahoo Finance as backup."""
    try:
        vix_data = yf.download("^VIX", period="1d", progress=False)
        if not vix_data.empty:
            close = vix_data['Close'].iloc[-1]
            if isinstance(close, pd.Series):
                close = close.iloc[0]
            return float(close)
    except Exception as e:
        log(f"yfinance VIX fetch failed: {e}")
    return None

# round_to_5 is imported from core.gex_strategy

def get_rsi(symbol="SPY", period=14):
    """Calculate RSI for SPY using last 30 days of data."""
    try:
        data = yf.download(symbol, period="30d", progress=False, auto_adjust=True)
        if data.empty:
            return 50  # Default to neutral
        close = data['Close']
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()

        # Handle edge cases to prevent division by zero
        # Standard RSI: If avg_loss = 0 (all gains), RSI = 100
        #               If avg_gain = 0 (all losses), RSI = 0
        avg_gain_val = avg_gain.iloc[-1]
        avg_loss_val = avg_loss.iloc[-1]

        if avg_loss_val == 0 or pd.isna(avg_loss_val):
            # No losses in period = maximum overbought
            rsi_val = 100.0
        elif avg_gain_val == 0 or pd.isna(avg_gain_val):
            # No gains in period = maximum oversold
            rsi_val = 0.0
        else:
            # Standard RSI calculation
            rs = avg_gain_val / avg_loss_val
            rsi_val = 100 - (100 / (1 + rs))

        return round(rsi_val, 1)
    except Exception as e:
        log(f"RSI calc error: {e}")
        return 50  # Default to neutral on error

def get_consecutive_down_days(symbol="SPY"):
    """Count consecutive down days (negative closes)."""
    try:
        data = yf.download(symbol, period="10d", progress=False, auto_adjust=True)
        if data.empty:
            return 0
        close = data['Close']
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        returns = close.pct_change().dropna()
        # Count consecutive down days from the end
        count = 0
        for ret in reversed(returns.tolist()):
            if ret < 0:
                count += 1
            else:
                break
        return count
    except Exception as e:
        log(f"Consecutive days calc error: {e}")
        return 0

def calculate_gex_pin(spx_price):
    """Calculate real GEX pin from options open interest and gamma data.

    Uses Tradier LIVE API (read-only) since sandbox has no options data.
    Returns the strike with highest positive GEX within 50 pts of spot.
    Returns None if GEX data unavailable - caller must handle this.
    """
    from collections import defaultdict

    try:
        # Must use LIVE API for options data (sandbox returns null)
        LIVE_URL = "https://api.tradier.com/v1/"
        LIVE_HEADERS = {"Accept": "application/json", "Authorization": f"Bearer {TRADIER_LIVE_KEY}"}

        today = date.today().strftime("%Y-%m-%d")

        # Get options chain with greeks
        r = requests.get(f"{LIVE_URL}/markets/options/chains", headers=LIVE_HEADERS,
            params={"symbol": "SPX", "expiration": today, "greeks": "true"}, timeout=15)

        if r.status_code != 200:
            log(f"GEX API failed: {r.status_code}")
            return None

        options = r.json().get("options", {})
        if not options:
            log("GEX API returned no options data")
            return None

        options = options.get("option", [])
        if not options:
            log("GEX API returned empty options list")
            return None

        # Calculate GEX by strike
        # GEX = gamma × open_interest × contract_multiplier × spot^2
        # Calls: positive GEX | Puts: negative GEX
        gex_by_strike = defaultdict(float)

        for opt in options:
            strike = opt.get('strike', 0)
            oi = opt.get('open_interest', 0)
            greeks = opt.get('greeks', {})
            gamma = greeks.get('gamma', 0) if greeks else 0
            opt_type = opt.get('option_type', '')

            if oi == 0 or gamma == 0:
                continue

            # GEX formula
            gex = gamma * oi * 100 * (spx_price ** 2)

            if opt_type == 'call':
                gex_by_strike[strike] += gex
            else:
                gex_by_strike[strike] -= gex

        if not gex_by_strike:
            log("No GEX data calculated")
            return None

        # Find strikes near current price with highest positive GEX
        near_strikes = [(s, g) for s, g in gex_by_strike.items() if abs(s - spx_price) < 50 and g > 0]

        if near_strikes:
            pin_strike, pin_gex = max(near_strikes, key=lambda x: x[1])
            log(f"GEX PIN calculated: {pin_strike} (GEX={pin_gex/1e9:.1f}B)")

            # Log top 3 for reference
            sorted_near = sorted(near_strikes, key=lambda x: x[1], reverse=True)[:3]
            for s, g in sorted_near:
                log(f"  GEX at {s}: {g/1e9:+.1f}B")

            return pin_strike
        else:
            # No positive GEX near spot, use highest absolute
            all_near = [(s, g) for s, g in gex_by_strike.items() if abs(s - spx_price) < 50]
            if all_near:
                pin_strike, _ = max(all_near, key=lambda x: abs(x[1]))
                log(f"GEX PIN (no positive near): {pin_strike}")
                return pin_strike

            log("No GEX strikes found near spot price")
            return None

    except Exception as e:
        log(f"GEX calculation error: {e}")
        return None

# RSI filter range
RSI_MIN = 50
RSI_MAX = 70

# Skip Fridays (day 4 = Friday)
SKIP_FRIDAY = True

# Skip after N consecutive down days
MAX_CONSEC_DOWN_DAYS = 2  # Skip if 3+ down days

def get_expected_credit(short_sym, long_sym):
    """Fetch expected credit from option quotes. Returns (credit, success)."""
    try:
        symbols = f"{short_sym},{long_sym}"
        r = requests.get(f"{BASE_URL}/markets/quotes", headers=HEADERS, params={"symbols": symbols}, timeout=10)
        data = r.json()
        quotes = data.get("quotes", {}).get("quote", [])
        if isinstance(quotes, dict):
            quotes = [quotes]
        if len(quotes) < 2:
            log(f"Warning: Only got {len(quotes)} quotes for {symbols}")
            return None
        short_bid = float(quotes[0].get("bid") or 0)
        short_ask = float(quotes[0].get("ask") or 0)
        long_bid = float(quotes[1].get("bid") or 0)
        long_ask = float(quotes[1].get("ask") or 0)
        short_mid = (short_bid + short_ask) / 2
        long_mid = (long_bid + long_ask) / 2
        credit = round(short_mid - long_mid, 2)
        log(f"Quote: {short_sym} bid/ask={short_bid}/{short_ask} | {long_sym} bid/ask={long_bid}/{long_ask} → credit=${credit:.2f}")
        return max(credit, 0.01)
    except Exception as e:
        log(f"Warning: get_expected_credit failed: {e}")
        return None

def get_gex_trade_setup(pin_price, spx_price, vix):
    """
    Wrapper for core.gex_strategy.get_gex_trade_setup

    GEX Pin Strategy: Price gravitates toward the PIN.
    - SPX above PIN → expect pullback → sell CALL spreads (bearish)
    - SPX below PIN → expect rally → sell PUT spreads (bullish)
    - SPX at PIN → expect pinning → sell Iron Condor (neutral)

    Uses shared module: core.gex_strategy (single source of truth)
    This ensures backtest and live scalper use IDENTICAL logic.
    """
    # Use core module (GEXTradeSetup dataclass)
    setup = core_get_gex_trade_setup(pin_price, spx_price, vix)

    # Convert dataclass to dict for backwards compatibility
    return {
        'strategy': setup.strategy,
        'strikes': setup.strikes,
        'direction': setup.direction,
        'distance': setup.distance,
        'confidence': setup.confidence,
        'description': setup.description
    }

# ==============================================
#                MAIN LOGIC
# ==============================================

try:
    now_et = datetime.datetime.now(ET)
    # Time cutoff only applies to LIVE trading - PAPER can trade anytime
    if mode == "REAL" and now_et.hour >= CUTOFF_HOUR:
        log(f"Time is {now_et.strftime('%H:%M')} ET — past cutoff. NO NEW TRADES.")
        log("Existing OCO brackets remain active.")
        send_discord_skip_alert("Past 3 PM ET cutoff", {'setup': 'Time cutoff'})
        raise SystemExit
    elif mode == "PAPER":
        log(f"PAPER MODE — no time restrictions (current: {now_et.strftime('%H:%M')} ET)")

    log("GEX Scalper started")

    # === FETCH PRICES (always from LIVE API for real-time data) ===
    # Get SPX directly - more accurate than SPY*10
    spx_raw = get_price("SPX")
    if spx_raw and spx_raw > 1000:
        spx = spx_override or round(spx_raw)
        log(f"SPX: {spx} (direct from Tradier LIVE)")
    else:
        # Fallback to SPY*10 if SPX quote unavailable
        spy = get_price("SPY")
        if not spy or spy < 100:
            log("FATAL: Could not fetch SPX or SPY price — aborting")
            send_discord_skip_alert("Could not fetch SPX/SPY price", run_data)
            raise SystemExit
        spx = spx_override or round(spy * 10)
        log(f"SPX: {spx} (estimated from SPY ${spy:.2f})")

    # VIX: Try Tradier LIVE first, then yfinance
    vix = get_price("VIX")
    if not vix or vix < 5:
        log("Tradier VIX unavailable, trying yfinance...")
        vix = get_vix_yfinance()
    if not vix or vix < 5:
        log("FATAL: Could not fetch VIX price from any source — aborting")
        send_discord_skip_alert("Could not fetch VIX price", run_data)
        raise SystemExit

    log(f"SPX: {spx} | VIX: {vix:.2f}")

    # Build run_data as we go
    run_data['spx'] = spx
    run_data['vix'] = vix

    # === EXPECTED MOVE FILTER ===
    # Calculate expected 2-hour move using VIX
    # VIX = annualized volatility, convert to 2-hour expected move
    # Formula: SPX * (VIX/100) * sqrt(hours / (252 trading days * 6.5 hours/day))
    HOURS_TO_TP = 2.0
    MIN_EXPECTED_MOVE = 10.0  # Minimum expected move in points to justify trade
    expected_move_2hr = spx * (vix / 100) * math.sqrt(HOURS_TO_TP / (252 * 6.5))
    log(f"Expected 2hr move: ±{expected_move_2hr:.1f} pts (1σ, 68% prob)")
    run_data['expected_move'] = expected_move_2hr

    if expected_move_2hr < MIN_EXPECTED_MOVE:
        log(f"Expected move {expected_move_2hr:.1f} pts < {MIN_EXPECTED_MOVE} pts — volatility too low for TP")
        log("NO TRADE — premium decay insufficient")
        send_discord_skip_alert(f"Expected move {expected_move_2hr:.1f} pts < {MIN_EXPECTED_MOVE} pts — volatility too low", run_data)
        raise SystemExit

    # === RSI FILTER (LIVE only) ===
    rsi = get_rsi("SPY")
    log(f"RSI (14-period): {rsi}")
    run_data['rsi'] = rsi
    if mode == "REAL" and (rsi < RSI_MIN or rsi > RSI_MAX):
        log(f"RSI {rsi} outside {RSI_MIN}-{RSI_MAX} range — NO TRADE TODAY")
        send_discord_skip_alert(f"RSI {rsi:.1f} outside {RSI_MIN}-{RSI_MAX} range", run_data)
        raise SystemExit
    elif mode == "PAPER":
        log(f"PAPER MODE — RSI filter bypassed")

    # === FRIDAY FILTER ===
    today = date.today()
    if SKIP_FRIDAY and today.weekday() == 4:
        if mode == "REAL":
            log("Friday — NO TRADE TODAY (historically underperforms)")
            send_discord_skip_alert("Friday — historically underperforms", run_data)
            raise SystemExit
        else:
            log("PAPER MODE — Friday filter bypassed")

    # === CONSECUTIVE DOWN DAYS FILTER ===
    consec_down = get_consecutive_down_days("SPY")
    log(f"Consecutive down days: {consec_down}")
    run_data['consec_down'] = consec_down
    if consec_down > MAX_CONSEC_DOWN_DAYS:
        log(f"{consec_down} consecutive down days (>{MAX_CONSEC_DOWN_DAYS}) — NO TRADE TODAY")
        send_discord_skip_alert(f"{consec_down} consecutive down days (>{MAX_CONSEC_DOWN_DAYS})", run_data)
        raise SystemExit

    # === TODAY'S 0DTE EXPIRATION ===
    if today.weekday() >= 5:
        log("Weekend — no 0DTE trading")
        log("NO TRADE TODAY")
        send_discord_skip_alert("Weekend — no 0DTE trading", run_data)
        raise SystemExit
    exp_short = today.strftime("%y%m%d")

    # === PIN (override or real GEX calc) ===
    if pin_override is not None:
        pin_price = pin_override
        log(f"Using PIN OVERRIDE: {pin_price}")
    else:
        log("Calculating real GEX pin from options data...")
        pin_price = calculate_gex_pin(spx)
        if pin_price is None:
            log("FATAL: Could not calculate GEX pin — NO TRADE")
            send_discord_skip_alert("GEX pin calculation failed — no trade without real GEX data", run_data)
            raise SystemExit
        log(f"REAL GEX PIN → {pin_price}")
    run_data['pin'] = pin_price
    run_data['distance'] = abs(spx - pin_price)

    # === SMART TRADE SETUP ===
    setup = get_gex_trade_setup(pin_price, spx, vix)
    log(f"Trade setup: {setup['description']} | Confidence: {setup['confidence']}")
    run_data['setup'] = f"{setup['description']} ({setup['confidence']})"

    if setup['strategy'] == 'SKIP':
        log("NO TRADE TODAY — conditions not met")
        send_discord_skip_alert(f"{setup.get('description', 'Conditions not met')}", run_data)
        raise SystemExit

    # === IC TIME RESTRICTION ===
    # Iron Condors need time for theta decay - don't place after 1 PM
    IC_CUTOFF_HOUR = 13
    if setup['strategy'] == 'IC' and now_et.hour >= IC_CUTOFF_HOUR:
        log(f"IC not allowed after {IC_CUTOFF_HOUR}:00 ET — switching to directional spread")
        # Convert IC to directional spread based on which side has more room
        distance = setup['distance']
        if abs(distance) <= 3:
            # Very close to pin - skip entirely, not enough edge
            log("Too close to pin for directional trade late in day — NO TRADE")
            send_discord_skip_alert("IC cutoff + too close to pin for directional", run_data)
            raise SystemExit
        elif distance > 0:
            # SPX above pin - sell calls
            setup = get_gex_trade_setup(pin_price, spx + 5, vix)  # Nudge to trigger call spread
        else:
            # SPX below pin - sell puts
            setup = get_gex_trade_setup(pin_price, spx - 5, vix)  # Nudge to trigger put spread
        log(f"Converted to: {setup['description']}")

    # === SHORT STRIKE PROXIMITY CHECK ===
    # Don't enter if short strike is too close to current SPX (gamma risk)
    MIN_SHORT_DISTANCE = 5  # Minimum points between SPX and short strike
    strikes = setup['strikes']
    if setup['strategy'] == 'IC':
        call_short, _, put_short, _ = strikes
        call_distance = call_short - spx
        put_distance = spx - put_short
        if call_distance < MIN_SHORT_DISTANCE:
            log(f"Short call {call_short} only {call_distance} pts from SPX {spx} — too close, NO TRADE")
            send_discord_skip_alert(f"Short call too close to SPX ({call_distance}pts)", run_data)
            raise SystemExit
        if put_distance < MIN_SHORT_DISTANCE:
            log(f"Short put {put_short} only {put_distance} pts from SPX {spx} — too close, NO TRADE")
            send_discord_skip_alert(f"Short put too close to SPX ({put_distance}pts)", run_data)
            raise SystemExit
    else:
        short_strike = strikes[0]
        if setup['strategy'] == 'CALL':
            distance = short_strike - spx
        else:  # PUT
            distance = spx - short_strike
        if distance < MIN_SHORT_DISTANCE:
            log(f"Short strike {short_strike} only {distance} pts from SPX {spx} — too close, NO TRADE")
            send_discord_skip_alert(f"Short strike too close to SPX ({distance}pts)", run_data)
            raise SystemExit

    # === DRY RUN MODE ===
    if dry_run:
        log("DRY RUN COMPLETE — No orders sent")
        raise SystemExit

    # === BUILD SYMBOLS & PLACE ORDER ===
    if setup['strategy'] == 'IC':
        call_short, call_long, put_short, put_long = strikes
        short_syms = [f"SPXW{exp_short}C{int(call_short*1000):08d}", f"SPXW{exp_short}P{int(put_short*1000):08d}"]
        long_syms  = [f"SPXW{exp_short}C{int(call_long*1000):08d}",  f"SPXW{exp_short}P{int(put_long*1000):08d}"]
        log(f"Placing IRON CONDOR: Calls {call_short}/{call_long} | Puts {put_short}/{put_long}")
    else:
        short_strike, long_strike = strikes
        is_call = setup['strategy'] == 'CALL'
        short_sym = f"SPXW{exp_short}{'C' if is_call else 'P'}{int(short_strike*1000):08d}"
        long_sym  = f"SPXW{exp_short}{'C' if is_call else 'P'}{int(long_strike*1000):08d}"
        log(f"Placing {setup['strategy']} SPREAD {short_strike}/{long_strike}{'C' if is_call else 'P'}")

    # === EXPECTED CREDIT + FULL DOLLAR DISPLAY ===
    if setup['strategy'] == 'IC':
        # IC: Get credit for BOTH spreads (calls + puts)
        call_credit = get_expected_credit(short_syms[0], long_syms[0])
        put_credit = get_expected_credit(short_syms[1], long_syms[1])
        if call_credit is None or put_credit is None:
            log("ERROR: Could not get IC option quotes — aborting trade")
            raise SystemExit
        expected_credit = round(call_credit + put_credit, 2)
        log(f"IC Credit: Calls ${call_credit:.2f} + Puts ${put_credit:.2f} = ${expected_credit:.2f}")
    else:
        expected_credit = get_expected_credit(short_sym, long_sym)
        if expected_credit is None:
            log("ERROR: Could not get option quotes — aborting trade")
            raise SystemExit

    # === MINIMUM CREDIT CHECK (scales by time of day) ===
    # Later in day = thinner premiums = need higher minimum to justify risk
    if now_et.hour < 12:
        MIN_CREDIT = 0.75   # Before noon: $0.75
    elif now_et.hour < 13:
        MIN_CREDIT = 1.00   # 12-1 PM: $1.00
    else:
        MIN_CREDIT = 1.50   # 1-2 PM: $1.50 (after 2 PM blocked anyway)

    if expected_credit < MIN_CREDIT:
        log(f"Credit ${expected_credit:.2f} below minimum ${MIN_CREDIT:.2f} for this time — NO TRADE")
        send_discord_skip_alert(f"Credit ${expected_credit:.2f} below ${MIN_CREDIT:.2f} minimum", run_data)
        raise SystemExit

    dollar_credit = expected_credit * 100
    # FAR OTM (MEDIUM confidence) uses 70% TP, others use 50%
    tp_pct = 0.30 if setup['confidence'] == 'MEDIUM' else 0.50
    tp_price = round(expected_credit * tp_pct, 2)
    sl_price = round(expected_credit * 1.10, 2)
    tp_profit = (expected_credit - tp_price) * 100
    sl_loss = (sl_price - expected_credit) * 100

    log(f"EXPECTED CREDIT ≈ ${expected_credit:.2f}  →  ${dollar_credit:.0f} per contract")
    log(f"{int((1-tp_pct)*100)}% PROFIT TARGET → Close at ${tp_price:.2f}  →  +${tp_profit:.0f} profit")
    log(f"10% STOP LOSS → Close at ${sl_price:.2f}  →  -${sl_loss:.0f} loss")

    # === REAL ENTRY ORDER ===
    entry_data = {
        "class": "multileg", "symbol": "SPXW", "type": "market", "duration": "day", "tag": "GEXENTRY",
        "side[0]": "sell_to_open", "quantity[0]": 1,
        "option_symbol[0]": short_syms[0] if setup['strategy']=='IC' else short_sym,
        "side[1]": "buy_to_open",  "quantity[1]": 1,
        "option_symbol[1]": long_syms[0] if setup['strategy']=='IC' else long_sym
    }
    if setup['strategy'] == 'IC':
        entry_data.update({
            "side[2]": "sell_to_open", "quantity[2]": 1, "option_symbol[2]": short_syms[1],
            "side[3]": "buy_to_open",  "quantity[3]": 1, "option_symbol[3]": long_syms[1]
        })

    log("Sending entry order...")
    r = retry_api_call(
        lambda: requests.post(f"{BASE_URL}accounts/{TRADIER_ACCOUNT_ID}/orders",
                              headers=HEADERS, data=entry_data, timeout=15),
        description="Entry order placement"
    )

    if r is None:
        log(f"ENTRY FAILED: No response after retries")
        raise SystemExit

    if r.status_code != 200:
        log(f"ENTRY FAILED: {r.status_code} {r.text}")
        raise SystemExit

    # Safe JSON access with validation (prevent orphaned orders)
    try:
        response_data = r.json()
        order_data = response_data.get("order")

        if not order_data:
            log(f"ERROR: No 'order' key in response: {response_data}")
            raise SystemExit("Order placement failed: Invalid API response format")

        order_id = order_data.get("id")

        if not order_id:
            log(f"ERROR: No 'id' in order data: {order_data}")
            raise SystemExit("Order placement failed: No order ID returned")

        log(f"ENTRY SUCCESS → Real Order ID: {order_id}")

    except (ValueError, TypeError) as e:
        log(f"ERROR: Failed to parse order response: {e}")
        log(f"Response text: {r.text}")
        raise SystemExit("Order placement failed: Cannot parse API response")

    # === REAL CREDIT + FINAL TP/SL ===
    # Wait briefly for fill, then fetch actual fill price
    time.sleep(1)
    credit = None
    for attempt in range(3):
        try:
            order_detail = requests.get(f"{BASE_URL}/accounts/{TRADIER_ACCOUNT_ID}/orders/{order_id}", headers=HEADERS, timeout=10).json()
            fill_price = order_detail.get("order", {}).get("avg_fill_price")
            status = order_detail.get("order", {}).get("status", "")
            log(f"Order status: {status}, avg_fill_price: {fill_price}")
            if fill_price is not None and fill_price != 0:
                # Credit spreads report negative fill price (we receive money)
                credit = abs(float(fill_price))
                break
            if status == "filled":
                # Filled but no price yet, wait and retry
                time.sleep(1)
        except Exception as e:
            log(f"Fill price fetch attempt {attempt+1} failed: {e}")
            time.sleep(1)

    if credit is None or credit == 0:
        log("FATAL: Could not determine fill price — position opened but credit unknown!")
        log("Manual intervention required — check Tradier for open position")
        # Still save to monitor with expected_credit so position can be tracked
        # But mark it as needing attention
        credit = expected_credit
        log(f"Using expected credit ${credit:.2f} for tracking ONLY — verify manually!")
    else:
        log(f"Real fill price captured: ${credit:.2f}")

    dollar_credit = credit * 100
    tp_price = round(credit * tp_pct, 2)
    sl_price = round(credit * 1.10, 2)
    tp_profit = (credit - tp_price) * 100
    sl_loss = (sl_price - credit) * 100

    log(f"ACTUAL CREDIT RECEIVED: ${credit:.2f}  →  ${dollar_credit:.0f} per contract")
    log(f"FINAL {int((1-tp_pct)*100)}% PROFIT TARGET → Close at ${tp_price:.2f}  →  +${tp_profit:.0f} profit")
    log(f"FINAL 10% STOP LOSS → Close at ${sl_price:.2f}  →  -${sl_loss:.0f} loss")

    # === DISCORD ENTRY ALERT ===
    send_discord_entry_alert(setup, credit, strikes, tp_pct, order_id)
    log("Discord entry alert sent" if DISCORD_ENABLED else "Discord alerts disabled")

    # NOTE: OCO/exit management handled by monitor.py - no bracket orders here

    # === LOGGING ===
    tp_target_pct = int((1 - tp_pct) * 100)  # 50% or 70%
    if not os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, 'w', newline='') as f:
            csv.writer(f).writerow(["Timestamp_ET","Trade_ID","Strategy","Strikes","Entry_Credit",
                                  "Confidence","TP%","Exit_Time","Exit_Value","P/L_$","P/L_%","Exit_Reason","Duration_Min"])
    with open(TRADE_LOG_FILE, 'a', newline='') as f:
        csv.writer(f).writerow([
            datetime.datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S'),
            order_id, setup['strategy'], "/".join(map(str, strikes)), f"{credit:.2f}",
            setup['confidence'], f"{tp_target_pct}%",
            "", "", "", "", "", ""
        ])

    # === SAVE ORDER FOR MONITOR TRACKING ===
    ORDERS_FILE = "/root/gamma/data/orders_paper.json" if mode == "PAPER" else "/root/gamma/data/orders_live.json"

    # Load existing orders
    existing_orders = []
    if os.path.exists(ORDERS_FILE):
        try:
            with open(ORDERS_FILE, 'r') as f:
                existing_orders = json.load(f)
        except (json.JSONDecodeError, IOError, ValueError) as e:
            log(f"Error loading existing orders from {ORDERS_FILE}: {e}")
            existing_orders = []

    # Add new order with all tracking info
    # Format: option_symbols = [shorts..., longs...], short_indices = indices of shorts
    if setup['strategy'] == 'IC':
        option_symbols = [short_syms[0], short_syms[1], long_syms[0], long_syms[1]]
        short_indices = [0, 1]  # First two are short
    else:
        option_symbols = [short_sym, long_sym]
        short_indices = [0]  # First one is short

    order_data = {
        "order_id": order_id,
        "entry_credit": credit,
        "entry_time": datetime.datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S'),
        "strategy": setup['strategy'],
        "strikes": "/".join(map(str, strikes)),
        "direction": setup['direction'],
        "confidence": setup['confidence'],
        "option_symbols": option_symbols,
        "short_indices": short_indices,
        "tp_price": tp_price,
        "sl_price": sl_price,
        "trailing_stop_active": False,
        "best_profit_pct": 0
    }
    existing_orders.append(order_data)

    with open(ORDERS_FILE, 'w') as f:
        json.dump(existing_orders, f, indent=2)
    log(f"Order {order_id} saved to monitor tracking file")

    log("Trade complete — monitor.py will handle TP/SL exits.")

except SystemExit:
    log("GEX Scalper finished — no action taken")
except Exception as e:
    log(f"FATAL ERROR: {e}")
finally:
    # Release lock (automatic on file close, but explicit is better)
    # IMPORTANT: Do NOT delete the lock file - fcntl locks are on file descriptors
    # Deleting the file creates a race condition where multiple processes can acquire
    # locks on different inodes of the same path
    try:
        if 'lock_fd' in globals() and lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            log("Lock released")
    except Exception as e:
        log(f"Error releasing lock: {e}")
