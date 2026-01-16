#!/usr/bin/env python3
# gex_scalper.py — FINAL 100% COMPLETE (Dec 10, 2025)
# Real GEX pin | Smart strikes | Real TP/SL | Dry-run | Full logging | Asymmetric IC exploit

import sys
print(f"[STARTUP] Scalper invoked at {__import__('datetime').datetime.now()}", flush=True)

import warnings
import logging
import os

# Configurable base directory (can be overridden via GAMMA_HOME env var)
GAMMA_HOME = os.environ.get('GAMMA_HOME', '/root/gamma')

# Security Fix (2026-01-04): Log yfinance warnings instead of ignoring
# This helps catch API breaking changes before they cause failures
logging.captureWarnings(True)
yfinance_logger = logging.getLogger('py.warnings')
yfinance_handler = logging.FileHandler(f'{GAMMA_HOME}/data/yfinance_warnings.log')
yfinance_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
yfinance_logger.addHandler(yfinance_handler)
yfinance_logger.setLevel(logging.WARNING)

import datetime, requests, json, csv, pytz, time, math, fcntl, tempfile
import yfinance as yf
import pandas as pd
from datetime import date
from decision_logger import DecisionLogger

# ==================== CONFIG ====================
from config import (PAPER_ACCOUNT_ID, LIVE_ACCOUNT_ID, TRADIER_LIVE_KEY, TRADIER_SANDBOX_KEY,
                    DISCORD_ENABLED, DISCORD_WEBHOOK_LIVE_URL, DISCORD_WEBHOOK_PAPER_URL,
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
        if r.status_code == 200 or r.status_code == 204:
            print(f"[DISCORD] Webhook sent: {r.status_code} - {msg['embeds'][0]['title']}")
        else:
            # Log failed webhooks with full error details
            print(f"[DISCORD] Webhook failed: {r.status_code} - {r.text}")
            print(f"[DISCORD] Failed message title: {msg['embeds'][0]['title']}")
    except requests.exceptions.Timeout:
        print(f"[DISCORD] Alert failed: Timeout after 5s - {msg['embeds'][0]['title']}")
    except requests.exceptions.ConnectionError as e:
        print(f"[DISCORD] Alert failed: Connection error - {e}")
    except Exception as e:
        print(f"[DISCORD] Alert failed: {e}")

def send_discord_skip_alert(reason, run_data=None):
    """Send alert when trade is skipped, including full run data."""
    if not DISCORD_ENABLED or not DISCORD_WEBHOOK_URL:
        return
    try:
        fields = []
        if run_data:
            if 'index_price' in run_data:
                fields.append({"name": INDEX_CONFIG.code, "value": f"{run_data['index_price']:.0f}", "inline": True})
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
                "footer": {"text": f"0DTE {INDEX_CONFIG.code}"},
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

# ==================== INDEX & MODE PARSING ====================
# Import index configuration
from index_config import get_index_config, get_supported_indices

# CRITICAL: Index parameter is REQUIRED
if len(sys.argv) < 2:
    print("ERROR: Index parameter required")
    print(f"Usage: python scalper.py <INDEX> [PAPER|LIVE] [pin_override] [price_override]")
    print(f"Supported indices: {', '.join(get_supported_indices())}")
    sys.exit(1)

# Parse index (arg 1)
index_arg = sys.argv[1].upper()
try:
    INDEX_CONFIG = get_index_config(index_arg)
    print(f"Trading index: {INDEX_CONFIG.name} ({INDEX_CONFIG.code})")
except ValueError as e:
    print(f"ERROR: {e}")
    print(f"Usage: python scalper.py <INDEX> [PAPER|LIVE]")
    sys.exit(1)

# Parse mode (arg 2, default: PAPER)
mode = "PAPER"
if len(sys.argv) > 2:
    arg2 = sys.argv[2].upper()
    if arg2 in ["REAL", "LIVE"]:
        mode = "REAL"
    elif arg2 == "PAPER":
        mode = "PAPER"

# Parse overrides (args 3-4)
pin_override = None
price_override = None  # Renamed from spx_override (index-agnostic)
dry_run = False

if len(sys.argv) > 3 and sys.argv[3]:
    try:
        pin_override = float(sys.argv[3])
        dry_run = True
    except (ValueError, TypeError) as e:
        print(f"Warning: Invalid pin_override '{sys.argv[3]}': {e}")
        pass

if len(sys.argv) > 4 and sys.argv[4]:
    try:
        price_override = float(sys.argv[4])
        dry_run = True
    except (ValueError, TypeError) as e:
        print(f"Warning: Invalid price_override '{sys.argv[4]}': {e}")
        pass

TRADIER_ACCOUNT_ID = LIVE_ACCOUNT_ID if mode == "REAL" else PAPER_ACCOUNT_ID
TRADIER_KEY = TRADIER_LIVE_KEY if mode == "REAL" else TRADIER_SANDBOX_KEY
BASE_URL = "https://api.tradier.com/v1/" if mode == "REAL" else "https://sandbox.tradier.com/v1/"
HEADERS = {"Accept": "application/json", "Authorization": f"Bearer {TRADIER_KEY}"}

# Set Discord webhook URL based on mode
DISCORD_WEBHOOK_URL = DISCORD_WEBHOOK_LIVE_URL if mode == "REAL" else DISCORD_WEBHOOK_PAPER_URL

TRADE_LOG_FILE = f"{GAMMA_HOME}/data/trades.csv"

# BUGFIX (2026-01-12): Make lock file unique per index/mode combination
# Previously all 4 cron jobs (SPX PAPER, SPX LIVE, NDX PAPER, NDX LIVE) fought over same lock
# Now each combination gets its own lock file
LOCK_FILE = f"/tmp/gexscalper_{INDEX_CONFIG.code.lower()}_{mode.lower()}.lock"

# Maximum lock age before considered stale (seconds)
# Normal run takes ~30s, order fill timeout is 300s, so 600s (10 min) is very conservative
LOCK_MAX_AGE_SECONDS = 600

ET = pytz.timezone('US/Eastern')
CUTOFF_HOUR = 13  # No new trades after 1 PM ET (optimized for afternoon degradation)

# Import shared GEX strategy logic (single source of truth)
# This ensures backtest and live scalper use identical setup logic
from core.gex_strategy import get_gex_trade_setup as core_get_gex_trade_setup
from core.broken_wing_ic_calculator import BrokenWingICCalculator

print("=" * 70)
print(f"Index: {INDEX_CONFIG.name} ({INDEX_CONFIG.code})")
print(f"{'LIVE TRADING MODE — REAL MONEY' if mode == 'REAL' else 'PAPER TRADING MODE — 100% SAFE'}")
print(f"Using account: {TRADIER_ACCOUNT_ID}")
if dry_run: print("DRY RUN — NO ORDERS WILL BE SENT")
if pin_override: print(f"PIN OVERRIDE: {pin_override}")
if price_override: print(f"PRICE OVERRIDE: {price_override}")
print("=" * 70)

def log(msg):
    print(f"[{datetime.datetime.now(ET).strftime('%H:%M:%S')}] {msg}")

def is_process_running(pid):
    """Check if a process with given PID is still running."""
    try:
        os.kill(pid, 0)  # Signal 0 doesn't kill, just checks existence
        return True
    except OSError:
        return False

def check_and_remove_stale_lock():
    """
    Check if lock file is stale and remove it if so.

    A lock is considered stale if:
    1. The PID in the lock file is not running, OR
    2. The lock file is older than LOCK_MAX_AGE_SECONDS

    Returns True if stale lock was removed, False otherwise.
    """
    if not os.path.exists(LOCK_FILE):
        return False

    try:
        # Check lock file age
        lock_age = time.time() - os.path.getmtime(LOCK_FILE)

        # Read PID from lock file
        with open(LOCK_FILE, 'r') as f:
            lock_pid_str = f.read().strip()

        lock_pid = int(lock_pid_str) if lock_pid_str.isdigit() else None

        # Check if stale due to dead process
        if lock_pid and not is_process_running(lock_pid):
            log(f"STALE LOCK DETECTED: PID {lock_pid} is not running (lock age: {lock_age:.0f}s)")
            log(f"Removing stale lock file: {LOCK_FILE}")
            # HIGH-2 FIX (2026-01-13): Handle race condition if another process removed lock first
            try:
                os.remove(LOCK_FILE)
            except FileNotFoundError:
                log("Lock file already removed by another process")
            return True

        # Check if stale due to age (even if process somehow still exists)
        if lock_age > LOCK_MAX_AGE_SECONDS:
            log(f"STALE LOCK DETECTED: Lock age {lock_age:.0f}s exceeds max {LOCK_MAX_AGE_SECONDS}s")
            log(f"PID {lock_pid} may be hung — removing stale lock file: {LOCK_FILE}")
            # HIGH-2 FIX (2026-01-13): Handle race condition if another process removed lock first
            try:
                os.remove(LOCK_FILE)
            except FileNotFoundError:
                log("Lock file already removed by another process")
            return True

        # Lock appears valid
        log(f"Lock held by PID {lock_pid} (age: {lock_age:.0f}s) — appears valid")
        return False

    except Exception as e:
        log(f"Error checking stale lock: {e}")
        # If we can't read/parse the lock file, try to remove it
        try:
            os.remove(LOCK_FILE)
            log(f"Removed unreadable lock file: {LOCK_FILE}")
            return True
        except:
            return False

log(f"Scalper starting... (lock file: {LOCK_FILE})")

# BUGFIX (2026-01-12): Check for stale locks before attempting to acquire
# This handles cases where previous process crashed without releasing lock
stale_removed = check_and_remove_stale_lock()
if stale_removed:
    log("Stale lock removed — proceeding with lock acquisition")

# Acquire exclusive lock using fcntl (atomic, no race condition)
# This prevents duplicate orders if multiple scalper instances start simultaneously
lock_fd = None
try:
    lock_fd = open(LOCK_FILE, 'w')
    # Try to acquire exclusive lock (non-blocking)
    # LOCK_EX = exclusive lock, LOCK_NB = non-blocking (fail immediately if locked)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # Write PID and timestamp for debugging and stale detection
    lock_fd.write(f"{os.getpid()}\n")
    lock_fd.flush()
    log(f"Lock acquired (PID: {os.getpid()})")
except BlockingIOError:
    # Another instance holds the lock — check PID for better logging
    try:
        with open(LOCK_FILE, 'r') as f:
            holder_pid = f.read().strip()
        log(f"Lock held by PID {holder_pid} — another instance running, exiting")
    except:
        log("Lock held by another instance (could not read PID) — exiting")
    if lock_fd:
        lock_fd.close()
    exit(0)
except Exception as e:
    log(f"Failed to acquire lock: {e}")
    if lock_fd:
        lock_fd.close()
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
        # Use retry wrapper for reliability
        r = retry_api_call(
            lambda: requests.get(url, headers=headers, params={"symbols": symbol}, timeout=10),
            max_attempts=3,
            base_delay=1.0,
            description=f"Tradier quote for {symbol}"
        )

        # Handle retry failure
        if r is None:
            log(f"Tradier quote failed for {symbol}: All retry attempts exhausted")
            return None

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

def calculate_gap_size():
    """Calculate overnight gap as percentage of previous close.

    PROFIT ENHANCEMENT 2026-01-10: Large gaps (>0.5%) have 12.5% WR and -$1,774 P&L
    in 180-day backtest. This filter saves +$3,548/year by avoiding catastrophic trades.

    Returns:
        float: Absolute gap percentage (e.g., 0.5 for 0.5% gap)
    """
    try:
        # Get last 2 days (yesterday close, today open)
        data = yf.download("SPY", period="2d", progress=False, auto_adjust=True)
        if len(data) < 2:
            log("Gap calculation: insufficient data (< 2 days)")
            return 0.0

        prev_close = data['Close'].iloc[-2]
        today_open = data['Open'].iloc[-1]

        # Handle pandas Series returns
        if isinstance(prev_close, pd.Series):
            prev_close = prev_close.iloc[0]
        if isinstance(today_open, pd.Series):
            today_open = today_open.iloc[0]

        gap_pct = abs((float(today_open) - float(prev_close)) / float(prev_close)) * 100
        log(f"Gap calculation: prev_close={prev_close:.2f}, today_open={today_open:.2f}, gap={gap_pct:.2f}%")
        return gap_pct
    except Exception as e:
        log(f"Gap calculation error: {e}")
        return 0.0  # Default to no filter on error

def store_gex_polarity(nearby_peaks):
    """Calculate GEX polarity from peaks and store in run_data for BWIC decisions.

    Args:
        nearby_peaks: List of (strike, gex_value) tuples
    """
    if not nearby_peaks:
        run_data['gex_polarity_index'] = 0.0
        run_data['gex_magnitude'] = 0
        return

    # Use BWIC calculator to compute polarity
    polarity = BrokenWingICCalculator.calculate_gex_polarity(nearby_peaks)
    run_data['gex_polarity_index'] = polarity.gpi
    run_data['gex_magnitude'] = polarity.magnitude
    run_data['gex_direction'] = polarity.direction
    run_data['gex_confidence'] = polarity.confidence

    log(f"GEX Polarity: GPI={polarity.gpi:+.3f} ({polarity.direction}), "
        f"Magnitude={polarity.magnitude/1e9:.1f}B ({polarity.confidence})")

def calculate_gex_pin(index_price):
    """Calculate real GEX pin from options open interest and gamma data (index-agnostic).

    Uses Tradier LIVE API (read-only) since sandbox has no options data.
    Returns the strike with highest positive GEX within appropriate distance of spot.
    Returns None if GEX data unavailable - caller must handle this.
    """
    from collections import defaultdict

    try:
        # Must use LIVE API for options data (sandbox returns null)
        LIVE_URL = "https://api.tradier.com/v1/"
        LIVE_HEADERS = {"Accept": "application/json", "Authorization": f"Bearer {TRADIER_LIVE_KEY}"}

        today = date.today().strftime("%Y-%m-%d")

        # Get options chain with greeks (use retry wrapper for reliability)
        r = retry_api_call(
            lambda: requests.get(
                f"{LIVE_URL}/markets/options/chains",
                headers=LIVE_HEADERS,
                params={"symbol": INDEX_CONFIG.index_symbol, "expiration": today, "greeks": "true"},
                timeout=15
            ),
            max_attempts=3,
            base_delay=2.0,
            description="GEX API (options chain)"
        )

        # Handle retry failure
        if r is None:
            log("GEX API failed: All retry attempts exhausted")
            return None

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
            gex = gamma * oi * 100 * (index_price ** 2)

            if opt_type == 'call':
                gex_by_strike[strike] += gex
            else:
                gex_by_strike[strike] -= gex

        if not gex_by_strike:
            log("No GEX data calculated")
            return None

        # PROXIMITY-WEIGHTED PEAK SELECTION (2026-01-12)
        # Research shows proximity matters more than absolute GEX size for 0DTE intraday moves
        # SpotGamma: "Close to strike = stronger hedging activity"
        # MenthorQ: "ATM or 1-2 strikes OTM is optimal (30-50 delta)"
        # Academic: Gamma decays with distance² (Black-Scholes)

        # Step 1: Filter to peaks within realistic intraday move
        # SPX: 1.5% (~90pts), NDX: 2.0% (~420pts) based on typical 0DTE ranges
        max_distance_pct = 0.015 if INDEX_CONFIG.code == 'SPX' else 0.020
        max_distance = index_price * max_distance_pct

        nearby_peaks = [(s, g) for s, g in gex_by_strike.items()
                        if abs(s - index_price) < max_distance and g > 0]

        if not nearby_peaks:
            log(f"No positive GEX within {max_distance_pct*100:.1f}% move ({max_distance:.0f}pts) - checking wider range")
            # Fallback to wider range (old logic) but still filter for positive GEX
            nearby_peaks = [(s, g) for s, g in gex_by_strike.items()
                           if abs(s - index_price) < INDEX_CONFIG.far_max and g > 0]

        if nearby_peaks:
            # Step 2: Score peaks by proximity-weighted GEX
            # Score = GEX / (distance_pct⁵ + 1e-12)
            # Using quintic (5th power) distance penalty for 0DTE
            # Research shows proximity matters MORE than absolute GEX for intraday moves
            def score_peak(strike, gex):
                distance_pct = abs(strike - index_price) / index_price
                # For 0DTE near expiration, gamma decays EXTREMELY steeply with distance
                # Quintic (5th power) penalty ensures closer peaks win even if smaller
                # Virtually zero epsilon (1e-12) to avoid div/0 but not dominate scoring
                return gex / (distance_pct ** 5 + 1e-12)

            scored_peaks = [(s, g, score_peak(s, g)) for s, g in nearby_peaks]

            # Log top 3 scored peaks BEFORE competing peaks detection
            sorted_scored = sorted(scored_peaks, key=lambda x: x[2], reverse=True)[:3]
            log(f"Top 3 proximity-weighted peaks:")
            for s, g, score in sorted_scored:
                dist = abs(s - index_price)
                dist_pct = dist / index_price * 100
                log(f"  {s}: GEX={g/1e9:+.1f}B, dist={dist:.0f}pts ({dist_pct:.2f}%), score={score/1e9:.1f}")

            # COMPETING PEAKS DETECTION (2026-01-12)
            # When price is between two comparable peaks, use IC instead of directional
            # Research: "Caged" volatility between gamma walls (SpotGamma/Bookmap)
            if len(sorted_scored) >= 2:
                peak1_strike, peak1_gex, peak1_score = sorted_scored[0]
                peak2_strike, peak2_gex, peak2_score = sorted_scored[1]

                # Check if peaks are competing:
                # 1. Comparable strength (score within 2x) → similar magnetic pull
                # 2. On opposite sides of price → opposing forces
                # 3. Price reasonably centered (within 40% of equidistant)
                score_ratio = min(peak1_score, peak2_score) / max(peak1_score, peak2_score)
                opposite_sides = (peak1_strike < index_price < peak2_strike) or \
                                 (peak2_strike < index_price < peak1_strike)

                distance1 = abs(peak1_strike - index_price)
                distance2 = abs(peak2_strike - index_price)
                distance_ratio = min(distance1, distance2) / max(distance1, distance2)
                reasonably_centered = distance_ratio > 0.4

                if score_ratio > 0.5 and opposite_sides and reasonably_centered:
                    # COMPETING PEAKS DETECTED
                    log(f"⚠️  COMPETING PEAKS DETECTED:")
                    log(f"   Peak 1: {peak1_strike} ({peak1_gex/1e9:.1f}B GEX, {distance1:.0f}pts away)")
                    log(f"   Peak 2: {peak2_strike} ({peak2_gex/1e9:.1f}B GEX, {distance2:.0f}pts away)")
                    log(f"   Score ratio: {score_ratio:.2f} (comparable strength)")
                    log(f"   Price between peaks → IC strategy (profit from cage)")

                    # Use midpoint for IC setup (triggers IC in get_gex_trade_setup)
                    midpoint = (peak1_strike + peak2_strike) / 2
                    pin_strike = INDEX_CONFIG.round_strike(midpoint)

                    log(f"GEX PIN (adjusted for competing peaks): {pin_strike}")
                    log(f"   Midpoint between {peak1_strike} and {peak2_strike}")
                    log(f"   Strategy: Iron Condor (profit from caged volatility)")

                    store_gex_polarity(nearby_peaks)
                    return pin_strike

            # No competing peaks - use top peak (normal case)
            pin_strike, pin_gex, pin_score = sorted_scored[0]

            distance = abs(pin_strike - index_price)
            distance_pct = distance / index_price * 100
            log(f"GEX PIN (proximity-weighted): {pin_strike} (GEX={pin_gex/1e9:.1f}B, {distance_pct:.2f}% away)")

            store_gex_polarity(nearby_peaks)
            return pin_strike
        else:
            # No positive GEX near spot, use highest absolute
            all_near = [(s, g) for s, g in gex_by_strike.items() if abs(s - index_price) < INDEX_CONFIG.far_max]
            if all_near:
                pin_strike, _ = max(all_near, key=lambda x: abs(x[1]))
                log(f"GEX PIN (no positive near): {pin_strike}")
                store_gex_polarity([])  # Neutral polarity (fallback mode)
                return pin_strike

            log("No GEX strikes found near spot price")
            store_gex_polarity([])  # Neutral polarity
            return None

    except Exception as e:
        log(f"GEX calculation error: {e}")
        store_gex_polarity([])  # Neutral polarity on error
        return None

# RSI filter range (FIX 2026-01-10: Widened from 50-70 to 30-80, then raised floor to 40)
# PROFIT ENHANCEMENT 2026-01-10: RSI 30-40 has 0% WR in backtest (-$510), raised to 40
RSI_MIN = 40  # Was 30 (0% WR zone), originally 50 (too restrictive)
RSI_MAX = 80  # Was 70 (too restrictive)

# Skip Fridays (day 4 = Friday)
SKIP_FRIDAY = False  # User requested: Allow Friday trading (2026-01-16)

# Skip after N consecutive down days (FIX 2026-01-10: Increased from 2 to 5)
MAX_CONSEC_DOWN_DAYS = 5  # Skip if 6+ down days (was 2 - too conservative)

# Maximum concurrent positions (risk management)
MAX_DAILY_POSITIONS = 3  # Limit concurrent open positions to prevent unbounded risk

# ========== AUTOSCALING CONFIGURATION (2026-01-10) ==========
AUTOSCALING_ENABLED = True          # Enable Half-Kelly position sizing
STARTING_CAPITAL = 20000             # Starting account balance ($20k for conservative start)
MAX_CONTRACTS_PER_TRADE = 1          # RAMP-UP: Start with 1 contract (2026-01-12), increase after 1 month of live trading
ACCOUNT_BALANCE_FILE = f"{GAMMA_HOME}/data/account_balance.json"  # Track balance across restarts

# INDEX-SPECIFIC BOOTSTRAP STATISTICS (2026-01-14)
# Scale based on spread width: SPX (5pt) vs NDX (25pt spread = 5x wider)
# SPX base values from realistic backtest
_SPREAD_SCALE = INDEX_CONFIG.base_spread_width / 5  # 1.0 for SPX, 6.0 for NDX
STOP_LOSS_PER_CONTRACT = int(150 * _SPREAD_SCALE)   # SPX: $150, NDX: $900

# Bootstrap statistics (from realistic backtest until we have real data)
BOOTSTRAP_WIN_RATE = 0.582           # 58.2% win rate (realistic mode, same for both)
BOOTSTRAP_AVG_WIN = int(266 * _SPREAD_SCALE)        # SPX: $266, NDX: $1596 (scales with spread width)
BOOTSTRAP_AVG_LOSS = int(109 * _SPREAD_SCALE)       # SPX: $109, NDX: $654 (scales with spread width)

def load_account_balance():
    """Load account balance from file. Returns (balance, trade_stats dict)."""
    if not os.path.exists(ACCOUNT_BALANCE_FILE):
        # First time - initialize with starting capital
        data = {
            'balance': STARTING_CAPITAL,
            'last_updated': datetime.datetime.now().isoformat(),
            'trades': [],  # Store last 50 trades for rolling stats
            'total_trades': 0
        }
        save_account_balance(data)
        return STARTING_CAPITAL, data

    try:
        with open(ACCOUNT_BALANCE_FILE, 'r') as f:
            data = json.load(f)
        balance = data.get('balance', STARTING_CAPITAL)
        return balance, data
    except Exception as e:
        log(f"Error loading account balance: {e}, using starting capital")
        return STARTING_CAPITAL, {'balance': STARTING_CAPITAL, 'trades': [], 'total_trades': 0}

def save_account_balance(data):
    """Save account balance to file using atomic write."""
    try:
        data['last_updated'] = datetime.datetime.now().isoformat()

        # BUGFIX (2026-01-10): Use atomic write to prevent corruption
        # Write to temp file first, then atomic rename
        temp_fd, temp_path = tempfile.mkstemp(
            dir=os.path.dirname(ACCOUNT_BALANCE_FILE),
            prefix='.account_balance_',
            suffix='.tmp'
        )
        try:
            with os.fdopen(temp_fd, 'w') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Force write to disk

            # Atomic rename (POSIX guarantees atomicity)
            os.replace(temp_path, ACCOUNT_BALANCE_FILE)
        except:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except:
                pass
            raise
    except Exception as e:
        log(f"Error saving account balance: {e}")

def calculate_position_size_kelly(account_balance, trade_stats):
    """
    Calculate position size using Half-Kelly criterion.

    Kelly formula: f = (p*W - (1-p)*L) / W
    where:
        p = win probability
        W = avg win amount
        L = avg loss amount
        f = fraction of capital to risk

    Uses Half-Kelly (50% of Kelly) for more conservative sizing.

    Returns: int (number of contracts, 1 to MAX_CONTRACTS_PER_TRADE)
    """
    if not AUTOSCALING_ENABLED:
        return 1  # Fixed size if autoscaling disabled

    # Stop trading if account drops below 50% of starting capital
    if account_balance < STARTING_CAPITAL * 0.5:
        log(f"⚠️  Account below 50% of starting capital (${account_balance:,.0f} < ${STARTING_CAPITAL * 0.5:,.0f})")
        return 0

    trades = trade_stats.get('trades', [])

    # Use rolling statistics if we have enough trades
    if len(trades) >= 10:
        wins = [t['pnl'] for t in trades if t['pnl'] > 0]
        losses = [abs(t['pnl']) for t in trades if t['pnl'] <= 0]

        if len(wins) >= 5 and len(losses) >= 2:
            win_rate = len(wins) / len(trades)
            avg_win = sum(wins[-50:]) / len(wins[-50:])  # Use last 50 wins
            avg_loss = sum(losses[-50:]) / len(losses[-50:])  # Use last 50 losses
        else:
            # Not enough data, use bootstrap
            win_rate = BOOTSTRAP_WIN_RATE
            avg_win = BOOTSTRAP_AVG_WIN
            avg_loss = BOOTSTRAP_AVG_LOSS
    else:
        # Bootstrap with baseline stats
        win_rate = BOOTSTRAP_WIN_RATE
        avg_win = BOOTSTRAP_AVG_WIN
        avg_loss = BOOTSTRAP_AVG_LOSS

    # Kelly fraction
    # CRITICAL-3 FIX (2026-01-13): Prevent division by zero if all trades were losses
    if avg_win > 0:
        kelly_f = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
    else:
        kelly_f = 0  # No positive trades, use minimum position
        log("⚠️  CRITICAL-3: avg_win=0, using minimum position size")

    # Use half-Kelly for safety
    half_kelly = kelly_f * 0.5

    # Calculate contracts based on account size and stop loss per contract
    contracts = int((account_balance * half_kelly) / STOP_LOSS_PER_CONTRACT)

    # Enforce bounds: minimum 1, maximum MAX_CONTRACTS_PER_TRADE
    contracts = max(1, min(contracts, MAX_CONTRACTS_PER_TRADE))

    log(f"📊 Position sizing: Balance=${account_balance:,.0f}, WR={win_rate:.1%}, AvgW=${avg_win:.0f}, AvgL=${avg_loss:.0f} → {contracts} contracts")

    return contracts

def get_expected_credit(short_sym, long_sym):
    """Fetch expected credit from option quotes. Returns (credit, success)."""
    try:
        symbols = f"{short_sym},{long_sym}"

        # Use retry wrapper for reliability
        r = retry_api_call(
            lambda: requests.get(f"{BASE_URL}/markets/quotes", headers=HEADERS, params={"symbols": symbols}, timeout=10),
            max_attempts=3,
            base_delay=1.0,
            description=f"Option quotes for {symbols}"
        )

        # Handle retry failure
        if r is None:
            log(f"Warning: get_expected_credit failed for {symbols}: All retry attempts exhausted")
            return None

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

def check_spread_quality(short_sym, long_sym, expected_credit):
    """
    FIX #4: Check if bid/ask spread is tight enough for safe entry.

    Returns True if spread is acceptable, False if too wide.

    Logic:
    - Calculate net spread: (short_ask - short_bid) - (long_ask - long_bid)
    - If net spread > 25% of expected credit, too risky
    - Example: $2.00 credit → max $0.50 net spread

    Prevents instant stops from entry slippage.
    """
    try:
        symbols = f"{short_sym},{long_sym}"
        r = retry_api_call(
            lambda: requests.get(f"{BASE_URL}/markets/quotes", headers=HEADERS,
                               params={"symbols": symbols}, timeout=10),
            max_attempts=2,
            base_delay=0.5,
            description=f"Spread quality check for {symbols}"
        )

        if r is None or r.status_code != 200:
            log(f"Warning: Could not check spread quality for {symbols}")
            return True  # Don't block trade on quote fetch failure

        data = r.json()
        quotes = data.get("quotes", {}).get("quote", [])
        if isinstance(quotes, dict):
            quotes = [quotes]
        if len(quotes) < 2:
            log(f"Warning: Incomplete quotes for spread quality check")
            return True

        # Short leg
        short_bid = float(quotes[0].get("bid") or 0)
        short_ask = float(quotes[0].get("ask") or 0)
        short_spread = short_ask - short_bid

        # Long leg
        long_bid = float(quotes[1].get("bid") or 0)
        long_ask = float(quotes[1].get("ask") or 0)
        long_spread = long_ask - long_bid

        # Net spread (what we pay in slippage)
        net_spread = short_spread - long_spread  # Short spread costs us, long spread saves us
        net_spread = abs(net_spread)  # Take absolute value

        # Maximum acceptable spread: Use index-specific tolerance (SPX 25%, NDX 30%)
        max_spread = expected_credit * INDEX_CONFIG.max_spread_pct

        log(f"Spread quality: short {short_spread:.2f}, long {long_spread:.2f}, net {net_spread:.2f}")
        log(f"Max acceptable spread: ${max_spread:.2f} ({INDEX_CONFIG.max_spread_pct*100:.0f}% of ${expected_credit:.2f} credit)")

        if net_spread > max_spread:
            log(f"❌ Spread too wide: ${net_spread:.2f} > ${max_spread:.2f} (instant slippage would trigger emergency stop)")
            return False

        log(f"✅ Spread acceptable: ${net_spread:.2f} ≤ ${max_spread:.2f}")
        return True

    except Exception as e:
        log(f"Error checking spread quality: {e}")
        return True  # Don't block trade on error

def is_in_blackout_period(now_et):
    """
    Return True if current time is in a high-volatility blackout period.

    IMPROVED (2026-01-16): Timing filters based on backtest analysis:
    - Before 10:00 AM: Block early morning volatility (9:30-9:59)
    - After 11:30 AM: Block afternoon choppy periods (12:00+)

    ALLOWED ENTRY TIMES: 10:00, 10:30, 11:00, 11:30 only

    Backtest Results (with improvements):
    - 10:00 AM: 100% WR, +$421 total (BEST)
    - 10:30 AM: 77.8% WR, +$247 total
    - 11:00 AM: 77.8% WR, +$268 total
    - 11:30 AM: 87.5% WR, +$318 total
    - 12:00 PM: 77.8% WR, +$141 total (weak, skip)
    - 12:30 PM: 55.6% WR, +$2 total (break-even, skip)
    """
    hour = now_et.hour
    minute = now_et.minute

    # Block before 10:00 AM (early morning volatility)
    if hour < 10:
        return True, "Before 10:00 AM - early volatility blocked"

    # Block after 11:30 AM (afternoon chop)
    if hour >= 12:
        return True, "After noon - low performance period blocked"

    return False, None

def check_vix_spike(current_vix, lookback_minutes=5):
    """
    Check if VIX spiked recently (indicates panic/volatility surge).

    Returns (is_safe, message):
    - (True, None) if safe to trade
    - (False, reason) if VIX spiking too fast

    Threshold: 5% increase in 5 minutes indicates volatility spike.
    Example: VIX 15.0 → 15.8 in 5 min = +5.3% = skip trade

    Analysis: Would catch sudden volatility surges that trigger quick stop-outs.
    """
    try:
        # Download recent VIX data (1 day, 5-min intervals)
        vix_data = yf.download("^VIX", period="1d", interval="5m", progress=False)

        if len(vix_data) < 2:
            log("VIX spike check: insufficient data, assuming safe")
            return True, None  # Can't check, assume safe

        # Get VIX from 5 minutes ago
        recent_vix = float(vix_data['Close'].iloc[-2])
        vix_change_pct = (current_vix - recent_vix) / recent_vix

        log(f"VIX spike check: {recent_vix:.2f} → {current_vix:.2f} ({vix_change_pct*100:+.1f}% in 5min)")

        # Threshold: 5% spike in 5 minutes
        VIX_SPIKE_THRESHOLD = 0.05
        if vix_change_pct > VIX_SPIKE_THRESHOLD:
            reason = f"VIX spiked {vix_change_pct*100:.1f}% in 5min ({recent_vix:.2f}→{current_vix:.2f})"
            log(f"❌ VIX spike detected: {reason}")
            return False, reason

        log(f"✅ VIX stable: {vix_change_pct*100:+.1f}% change < {VIX_SPIKE_THRESHOLD*100:.0f}% threshold")
        return True, None

    except Exception as e:
        log(f"VIX spike check failed: {e}, assuming safe")
        return True, None  # On error, don't block trade

def check_realized_volatility(index_symbol="SPX", lookback_minutes=30):
    """
    Check if recent intraday volatility is abnormally high.

    Measures actual SPX/NDX bar ranges vs historical baseline to detect
    choppy/whipsaw conditions that VIX doesn't capture.

    Returns (is_safe, message):
    - (True, None) if volatility is normal
    - (False, reason) if recent volatility too high (choppy market)

    Why this matters: VIX measures EXPECTED volatility. On days like 2026-01-15,
    VIX was calm (13-15) but SPX whipsawed hard intraday, causing 3 quick stops.
    This filter catches that by measuring ACTUAL bar-by-bar movement.

    Threshold: 2.5x normal 5-min bar range indicates choppy conditions
    Example: Normal bar range 5pts, recent avg 13pts = skip trade
    """
    try:
        # Use index-specific ticker
        ticker_map = {
            'SPX': '^GSPC',
            'NDX': '^NDX'
        }
        ticker = ticker_map.get(index_symbol, '^GSPC')

        # Download recent 5-min bars (need lookback + 1 day for baseline)
        data = yf.download(ticker, period="2d", interval="5m", progress=False, auto_adjust=True)

        if len(data) < 20:
            log("Realized vol check: insufficient data, assuming safe")
            return True, None  # Can't check, assume safe

        # Calculate bar ranges (High - Low)
        data['bar_range'] = data['High'] - data['Low']

        # Get recent bars (last N minutes)
        bars_needed = lookback_minutes // 5  # 30 min = 6 bars
        recent_bars = data.tail(bars_needed)
        recent_avg_range = recent_bars['bar_range'].mean()

        # Calculate baseline normal volatility (previous day's bars)
        # Use day before today to avoid contaminating with current choppy session
        baseline_bars = data.iloc[:-bars_needed]  # Everything except recent
        baseline_avg_range = baseline_bars['bar_range'].mean()

        # Threshold: 2.5x normal indicates choppy/whipsaw market
        VOLATILITY_MULTIPLIER = 2.5
        threshold = baseline_avg_range * VOLATILITY_MULTIPLIER

        log(f"Realized vol check: Recent {recent_avg_range:.1f}pts avg vs baseline {baseline_avg_range:.1f}pts")
        log(f"  Threshold: {threshold:.1f}pts ({VOLATILITY_MULTIPLIER}x baseline)")

        if recent_avg_range > threshold:
            ratio = recent_avg_range / baseline_avg_range
            reason = (f"Intraday volatility {recent_avg_range:.1f}pts is {ratio:.1f}x baseline "
                     f"({baseline_avg_range:.1f}pts) - market too choppy")
            log(f"❌ High realized volatility: {reason}")
            return False, reason

        ratio = recent_avg_range / baseline_avg_range
        log(f"✅ Realized volatility OK: {ratio:.1f}x baseline (< {VOLATILITY_MULTIPLIER}x threshold)")
        return True, None

    except Exception as e:
        log(f"Realized vol check failed: {e}, assuming safe")
        return True, None  # On error, don't block trade

def apply_bwic_to_ic(setup, index_price, vix):
    """
    Apply Broken Wing Iron Condor (BWIC) logic to IC setups.

    Args:
        setup: Dict with IC setup data (from get_gex_trade_setup)
        index_price: Current index price
        vix: Current VIX level

    Returns:
        Modified setup dict with BWIC strikes if applicable, otherwise original setup
    """
    # Only apply BWIC to Iron Condor setups
    if setup['strategy'] != 'IC':
        return setup

    # Get GEX polarity from run_data (populated by calculate_gex_pin)
    gpi = run_data.get('gex_polarity_index', 0.0)
    gex_magnitude = run_data.get('gex_magnitude', 0)

    # Decide if we should use BWIC
    should_use, reason = BrokenWingICCalculator.should_use_bwic(
        gex_magnitude=gex_magnitude,
        gpi=gpi,
        has_competing_peaks=False,
        vix=vix
    )

    if not should_use:
        log(f"IC: Using symmetric wings — {reason}")
        return setup

    # Calculate BWIC wing widths
    widths = BrokenWingICCalculator.get_bwic_wing_widths(
        gpi=gpi,
        vix=vix,
        gex_magnitude=gex_magnitude,
        use_bwic=True
    )

    # Extract current strikes
    call_short, call_long, put_short, put_long = setup['strikes']
    current_call_width = call_long - call_short
    current_put_width = put_short - put_long

    # Calculate new strikes using BWIC widths
    # Maintain the same short strikes, adjust long strikes
    call_short_new = call_short
    call_long_new = call_short_new + widths.call_width
    put_short_new = put_short
    put_long_new = put_short_new - widths.put_width

    # Round to strike increments
    call_short_new = INDEX_CONFIG.round_strike(call_short_new)
    call_long_new = INDEX_CONFIG.round_strike(call_long_new)
    put_short_new = INDEX_CONFIG.round_strike(put_short_new)
    put_long_new = INDEX_CONFIG.round_strike(put_long_new)

    # Validate the new strikes
    is_valid, validation_msg = BrokenWingICCalculator.validate_bwic_strikes(
        call_short=call_short_new,
        call_long=call_long_new,
        put_short=put_short_new,
        put_long=put_long_new,
        current_price=index_price,
        is_bwic=True
    )

    if not is_valid:
        log(f"IC: BWIC validation failed ({validation_msg}), using symmetric wings")
        return setup

    # Update setup with BWIC strikes
    setup['strikes'] = [call_short_new, call_long_new, put_short_new, put_long_new]
    setup['description'] = (
        f"BWIC: {call_short_new}/{call_long_new}C ({widths.call_width}pt) + "
        f"{put_short_new}/{put_long_new}P ({widths.put_width}pt) "
        f"[{widths.rationale}]"
    )

    log(f"✅ BWIC Applied: {widths.rationale}")
    log(f"   Calls: {call_short}/{call_long} → {call_short_new}/{call_long_new}")
    log(f"   Puts: {put_short}/{put_long} → {put_short_new}/{put_long_new}")

    return setup

def get_gex_trade_setup(pin_price, index_price, vix, index_symbol='SPX'):
    """
    Wrapper for core.gex_strategy.get_gex_trade_setup (index-agnostic)

    GEX Pin Strategy: Price gravitates toward the PIN.
    - Index above PIN → expect pullback → sell CALL spreads (bearish)
    - Index below PIN → expect rally → sell PUT spreads (bullish)
    - Index at PIN → expect pinning → sell Iron Condor (neutral)

    Uses shared module: core.gex_strategy (single source of truth)
    This ensures backtest and live scalper use IDENTICAL logic.

    Args:
        pin_price: GEX pin price level
        index_price: Current index price (SPX or NDX)
        vix: Current VIX level
        index_symbol: 'SPX' or 'NDX' (for logging/reporting)
    """
    # Use core module (GEXTradeSetup dataclass) with default vix_threshold=20.0
    # CRITICAL-1 FIX (2026-01-13): Pass vix_threshold (float) not INDEX_CONFIG (object)
    # VIX >= 20 skips trading (too volatile for 0DTE)
    setup = core_get_gex_trade_setup(pin_price, index_price, vix, vix_threshold=20.0, index_symbol=index_symbol)

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

    # FIX #1: Time cutoff applies to BOTH LIVE and PAPER (same risk profile)
    if now_et.hour >= CUTOFF_HOUR:
        log(f"Time is {now_et.strftime('%H:%M')} ET — past {CUTOFF_HOUR}:00 PM cutoff. NO NEW TRADES.")
        log("Existing positions remain active for TP/SL management.")
        send_discord_skip_alert(f"Past {CUTOFF_HOUR}:00 PM ET cutoff", {'setup': 'Time cutoff'})
        raise SystemExit

    # FIX #2: ABSOLUTE CUTOFF - No trades in last hour of 0DTE (expiration risk)
    ABSOLUTE_CUTOFF_HOUR = 15  # 3:00 PM ET - last hour before 4 PM expiration
    if now_et.hour >= ABSOLUTE_CUTOFF_HOUR:
        log(f"Time is {now_et.strftime('%H:%M')} ET — within last hour of 0DTE expiration")
        log("NO TRADES — bid/ask spreads too wide, gamma risk too high")
        send_discord_skip_alert(f"Last hour before 0DTE expiration ({now_et.strftime('%H:%M')} ET)", run_data)
        raise SystemExit

    log("GEX Scalper started")

    # Initialize decision logger for this run
    decision_logger = DecisionLogger()

    # === TIMING BLACKOUT FILTER ===
    # OPTIMIZATION (2026-01-13): Avoid market open volatility (9:30-10:00 AM)
    # Analysis: 12/18 10:00 trade (-33%) stopped in 4 minutes during opening volatility
    in_blackout, blackout_reason = is_in_blackout_period(now_et)
    if in_blackout:
        log(f"In volatility blackout period: {blackout_reason}")
        log("NO TRADE — timing filter prevents entry during high-volatility windows")
        send_discord_skip_alert(f"Volatility blackout: {blackout_reason}", run_data)
        raise SystemExit

    # === FETCH PRICES (always from LIVE API for real-time data) ===
    # Get index price directly - more accurate than ETF conversion
    index_raw = get_price(INDEX_CONFIG.index_symbol)
    if index_raw and index_raw > (INDEX_CONFIG.index_symbol == 'DJX' and 100 or 1000):
        index_price = price_override or round(index_raw)
        log(f"{INDEX_CONFIG.code}: {index_price} (direct from Tradier LIVE)")
    else:
        # Fallback to ETF * multiplier if index quote unavailable
        etf_price = get_price(INDEX_CONFIG.etf_symbol)
        if not etf_price or etf_price < 10:
            log(f"FATAL: Could not fetch {INDEX_CONFIG.index_symbol} or {INDEX_CONFIG.etf_symbol} price — aborting")
            send_discord_skip_alert(f"Could not fetch {INDEX_CONFIG.code}/{INDEX_CONFIG.etf_symbol} price", run_data)
            raise SystemExit
        index_price = price_override or round(etf_price * INDEX_CONFIG.etf_multiplier)
        log(f"{INDEX_CONFIG.code}: {index_price} (estimated from {INDEX_CONFIG.etf_symbol} ${etf_price:.2f})")

    # VIX: Try Tradier LIVE first, then yfinance
    vix = get_price("VIX")
    if not vix or vix < 5:
        log("Tradier VIX unavailable, trying yfinance...")
        vix = get_vix_yfinance()
    if not vix or vix < 5:
        log("FATAL: Could not fetch VIX price from any source — aborting")
        send_discord_skip_alert("Could not fetch VIX price", run_data)
        raise SystemExit

    log(f"{INDEX_CONFIG.code}: {index_price} | VIX: {vix:.2f}")

    # Build run_data as we go
    run_data['index_price'] = index_price
    run_data['vix'] = vix

    # OPTIMIZATION #5: VIX Floor Filter - don't trade when volatility too low
    VIX_FLOOR = 13.0
    if vix < VIX_FLOOR:
        log(f"VIX {vix:.2f} below floor ({VIX_FLOOR}) — insufficient volatility for premium")
        send_discord_skip_alert(f"VIX {vix:.2f} below {VIX_FLOOR} floor", run_data)
        raise SystemExit

    # === VIX SPIKE FILTER ===
    # OPTIMIZATION (2026-01-13): Detect sudden volatility surges
    # Analysis: 12/16 12:00 trade (-21%) may have been caused by VIX spike
    # Catches panic/volatility that timing filters miss
    vix_safe, vix_spike_reason = check_vix_spike(vix)
    if not vix_safe:
        log(f"VIX spike detected: {vix_spike_reason}")
        log("NO TRADE — VIX rising too fast indicates unstable conditions")
        send_discord_skip_alert(f"VIX spike: {vix_spike_reason}", run_data)
        raise SystemExit

    # === REALIZED VOLATILITY FILTER ===
    # OPTIMIZATION (2026-01-15): Detect choppy intraday conditions
    # Analysis: 2026-01-15 had 3 quick stops despite calm VIX (13-15)
    # VIX measures EXPECTED volatility, this measures ACTUAL bar-by-bar movement
    # Catches whipsaw/choppy days where GEX pin effect fails
    rvol_safe, rvol_reason = check_realized_volatility(INDEX_CONFIG.code, lookback_minutes=30)
    if not rvol_safe:
        log(f"High realized volatility: {rvol_reason}")
        log("NO TRADE — Market too choppy, GEX pin unreliable in whipsaw conditions")
        send_discord_skip_alert(f"Choppy market: {rvol_reason}", run_data)
        raise SystemExit

    # === EXPECTED MOVE FILTER ===
    # Calculate expected 2-hour move using VIX
    # VIX = annualized volatility, convert to 2-hour expected move
    # Formula: SPX * (VIX/100) * sqrt(hours / (252 trading days * 6.5 hours/day))
    HOURS_TO_TP = 2.0
    # INDEX-SPECIFIC MINIMUM MOVE (2026-01-14)
    # Scale based on spread width: SPX 10pts (5pt spread × 2), NDX 60pts (25pt spread × 2.4)
    MIN_EXPECTED_MOVE = 10.0 * (INDEX_CONFIG.base_spread_width / 5)  # Scale by spread width
    expected_move_2hr = index_price * (vix / 100) * math.sqrt(HOURS_TO_TP / (252 * 6.5))
    log(f"Expected 2hr move: ±{expected_move_2hr:.1f} pts (1σ, 68% prob)")
    run_data['expected_move'] = expected_move_2hr

    if expected_move_2hr < MIN_EXPECTED_MOVE:
        log(f"Expected move {expected_move_2hr:.1f} pts < {MIN_EXPECTED_MOVE:.1f} pts — volatility too low for TP")
        log("NO TRADE — premium decay insufficient")
        decision_logger.log_rejected(f"Expected 2hr move {expected_move_2hr:.1f}pts < {MIN_EXPECTED_MOVE:.1f}pts (volatility too low)")
        send_discord_skip_alert(f"Expected move {expected_move_2hr:.1f} pts < {MIN_EXPECTED_MOVE:.1f} pts — volatility too low", run_data)
        raise SystemExit

    # === RSI FILTER (LIVE only) ===
    rsi = get_rsi("SPY")
    log(f"RSI (14-period): {rsi}")
    run_data['rsi'] = rsi
    if rsi < RSI_MIN or rsi > RSI_MAX:
        log(f"RSI {rsi} outside {RSI_MIN}-{RSI_MAX} range — NO TRADE")
        decision_logger.log_rejected(f"RSI {rsi:.1f} outside {RSI_MIN}-{RSI_MAX} range")
        send_discord_skip_alert(f"RSI {rsi:.1f} outside {RSI_MIN}-{RSI_MAX} range", run_data)
        raise SystemExit

    # === FRIDAY FILTER ===
    today = date.today()
    if SKIP_FRIDAY and today.weekday() == 4:
        if mode == "REAL":
            log("Friday — NO TRADE TODAY (historically underperforms)")
            decision_logger.log_rejected("Friday - historically underperforms (0DTE skipped)")
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
        decision_logger.log_rejected(f"{consec_down} consecutive down days (>{MAX_CONSEC_DOWN_DAYS})")
        send_discord_skip_alert(f"{consec_down} consecutive down days (>{MAX_CONSEC_DOWN_DAYS})", run_data)
        raise SystemExit

    # === GAP SIZE FILTER ===
    # PROFIT ENHANCEMENT 2026-01-10: Large gaps (>0.5%) destroy GEX pin edge
    # Backtest data: 40 trades with 12.5% WR and -$1,774 P&L (only losing category)
    # Filtering saves +$3,548/year by avoiding catastrophic overnight news events
    MAX_GAP_PCT = 0.5  # Skip if overnight gap exceeds 0.5%
    gap_pct = calculate_gap_size()
    run_data['gap_pct'] = gap_pct
    if gap_pct > MAX_GAP_PCT:
        log(f"Gap {gap_pct:.2f}% exceeds {MAX_GAP_PCT}% — NO TRADE TODAY")
        log("Large gaps disrupt GEX pin dynamics — historically 12.5% WR, -$1,774 P&L")
        decision_logger.log_rejected(f"Gap {gap_pct:.2f}% > {MAX_GAP_PCT}% limit (GEX pin disrupted)")
        send_discord_skip_alert(f"Gap {gap_pct:.2f}% > {MAX_GAP_PCT}% limit", run_data)
        raise SystemExit

    # === TODAY'S 0DTE EXPIRATION ===
    if today.weekday() >= 5:
        log("Weekend — no 0DTE trading")
        log("NO TRADE TODAY")
        decision_logger.log_rejected("Weekend - no 0DTE trading (market closed)")
        send_discord_skip_alert("Weekend — no 0DTE trading", run_data)
        raise SystemExit
    exp_short = today.strftime("%y%m%d")

    # === PIN (override or real GEX calc) ===
    if pin_override is not None:
        pin_price = pin_override
        log(f"Using PIN OVERRIDE: {pin_price}")
    else:
        log("Calculating real GEX pin from options data...")
        pin_price = calculate_gex_pin(index_price)
        if pin_price is None:
            log("FATAL: Could not calculate GEX pin — NO TRADE")
            decision_logger.log_rejected("GEX pin calculation failed (options data unavailable)")
            send_discord_skip_alert("GEX pin calculation failed — no trade without real GEX data", run_data)
            raise SystemExit
        log(f"REAL GEX PIN → {pin_price}")
    run_data['pin'] = pin_price
    run_data['distance'] = abs(index_price - pin_price)

    # === SMART TRADE SETUP ===
    setup = get_gex_trade_setup(pin_price, index_price, vix, index_symbol=INDEX_CONFIG.code)

    # === APPLY BWIC (Broken Wing IC) if conditions met ===
    setup = apply_bwic_to_ic(setup, index_price, vix)

    log(f"Trade setup: {setup['description']} | Confidence: {setup['confidence']}")
    run_data['setup'] = f"{setup['description']} ({setup['confidence']})"

    if setup['strategy'] == 'SKIP':
        log("NO TRADE TODAY — GEX conditions not met, checking OTM spread fallback...")
        decision_logger.log_rejected(setup.get('description', 'Conditions not favorable for GEX strategy'))

        # Try OTM single-sided spread fallback when GEX has no setup
        try:
            sys.path.insert(0, GAMMA_HOME)
            from otm_spreads import find_single_sided_spread

            # Find single-sided spread strikes using GEX directional bias
            spread_strikes = find_single_sided_spread(index_price, pin_price, vix, skip_time_check=False)

            if spread_strikes:
                # Get option chain for the appropriate side
                option_type = 'put' if spread_strikes['side'] == 'PUT' else 'call'
                chain_df = get_option_chain(index_symbol, option_type)

                if chain_df is not None and not chain_df.empty:
                    # Get short strike quote (sell)
                    short_row = chain_df[chain_df['strike'] == spread_strikes['short_strike']]
                    long_row = chain_df[chain_df['strike'] == spread_strikes['long_strike']]

                    if not short_row.empty and not long_row.empty:
                        short_bid = short_row.iloc[0]['bid']
                        long_ask = long_row.iloc[0]['ask']

                        # Net credit = sell bid - buy ask
                        credit = short_bid - long_ask

                        # Minimum credit requirement ($0.20 for 10-pt spread = 2% of width)
                        MIN_CREDIT = 0.20

                        if credit >= MIN_CREDIT:
                            log("✓ SINGLE-SIDED OTM SPREAD OPPORTUNITY FOUND")
                            log(f"  Direction: {spread_strikes['direction']} (GEX pin {pin_price} vs SPX {index_price})")
                            log(f"  Side: {spread_strikes['side']} spread")
                            log(f"  Strikes: {spread_strikes['short_strike']}/{spread_strikes['long_strike']}")
                            log(f"  Distance OTM: {spread_strikes['distance_otm']:.0f} points")
                            log(f"  Credit: ${credit:.2f}")
                            log(f"  Max profit: ${credit * 100:.0f} per contract")

                            # Override setup with single-sided OTM spread
                            if spread_strikes['side'] == 'PUT':
                                setup = {
                                    'strategy': 'OTM_SINGLE_SIDED',
                                    'confidence': 'MEDIUM',
                                    'description': f"OTM Fallback: {spread_strikes['direction']} PUT spread {spread_strikes['short_strike']}/{spread_strikes['long_strike']}",
                                    'call_short': None,
                                    'call_long': None,
                                    'put_short': spread_strikes['short_strike'],
                                    'put_long': spread_strikes['long_strike'],
                                    'expected_credit': credit,
                                    'distance': spread_strikes['distance_otm'],
                                    'direction': spread_strikes['direction'],
                                    'side': 'PUT'
                                }
                            else:  # CALL
                                setup = {
                                    'strategy': 'OTM_SINGLE_SIDED',
                                    'confidence': 'MEDIUM',
                                    'description': f"OTM Fallback: {spread_strikes['direction']} CALL spread {spread_strikes['short_strike']}/{spread_strikes['long_strike']}",
                                    'call_short': spread_strikes['short_strike'],
                                    'call_long': spread_strikes['long_strike'],
                                    'put_short': None,
                                    'put_long': None,
                                    'expected_credit': credit,
                                    'distance': spread_strikes['distance_otm'],
                                    'direction': spread_strikes['direction'],
                                    'side': 'CALL'
                                }

                            log("Proceeding with single-sided OTM spread instead of GEX...")
                            run_data['setup'] = f"OTM SS {spread_strikes['direction']}"
                        else:
                            log(f"✗ Credit too low: ${credit:.2f} < ${MIN_CREDIT:.2f}")
                            send_discord_skip_alert(f"OTM credit too low (${credit:.2f})", run_data)
                            raise SystemExit
                    else:
                        log("✗ Could not get quotes for OTM strikes")
                        send_discord_skip_alert("OTM quotes unavailable", run_data)
                        raise SystemExit
                else:
                    log("✗ Option chain unavailable")
                    send_discord_skip_alert("Option chain unavailable", run_data)
                    raise SystemExit
            else:
                log("✗ No valid single-sided OTM opportunity (time/window constraints)")
                send_discord_skip_alert("OTM time/window constraints not met", run_data)
                raise SystemExit

        except Exception as e:
            log(f"OTM fallback check failed: {e}")
            import traceback
            traceback.print_exc()
            send_discord_skip_alert(f"OTM fallback error: {e}", run_data)
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
            # INDEX-AWARE NUDGE (2026-01-14): Use strike_increment to move 1 strike
            nudge = INDEX_CONFIG.strike_increment
            setup = get_gex_trade_setup(pin_price, index_price + nudge, vix, index_symbol=INDEX_CONFIG.code)  # Nudge by 1 strike to trigger call spread
        else:
            # SPX below pin - sell puts
            # INDEX-AWARE NUDGE (2026-01-14): Use strike_increment to move 1 strike
            nudge = INDEX_CONFIG.strike_increment
            setup = get_gex_trade_setup(pin_price, index_price - nudge, vix, index_symbol=INDEX_CONFIG.code)  # Nudge by 1 strike to trigger put spread
        log(f"Converted to: {setup['description']}")

    # === SHORT STRIKE PROXIMITY CHECK ===
    # Don't enter if short strike is too close to current index price (gamma risk)
    # Scale with strike increment: SPX=5pts, NDX=25pts
    MIN_SHORT_DISTANCE = INDEX_CONFIG.strike_increment  # Minimum points between index and short strike
    strikes = setup['strikes']
    if setup['strategy'] == 'IC':
        call_short, _, put_short, _ = strikes
        call_distance = call_short - index_price
        put_distance = index_price - put_short
        if call_distance < MIN_SHORT_DISTANCE:
            log(f"Short call {call_short} only {call_distance} pts from SPX {index_price} — too close, NO TRADE")
            send_discord_skip_alert(f"Short call too close to SPX ({call_distance}pts)", run_data)
            raise SystemExit
        if put_distance < MIN_SHORT_DISTANCE:
            log(f"Short put {put_short} only {put_distance} pts from SPX {index_price} — too close, NO TRADE")
            send_discord_skip_alert(f"Short put too close to SPX ({put_distance}pts)", run_data)
            raise SystemExit
    else:
        short_strike = strikes[0]
        if setup['strategy'] == 'CALL':
            distance = short_strike - index_price
        else:  # PUT
            distance = index_price - short_strike
        if distance < MIN_SHORT_DISTANCE:
            log(f"Short strike {short_strike} only {distance} pts from SPX {index_price} — too close, NO TRADE")
            send_discord_skip_alert(f"Short strike too close to SPX ({distance}pts)", run_data)
            raise SystemExit

    # === DRY RUN MODE ===
    if dry_run:
        log("DRY RUN COMPLETE — No orders sent")
        raise SystemExit

    # === BUILD SYMBOLS & PLACE ORDER ===
    if setup['strategy'] == 'IC':
        call_short, call_long, put_short, put_long = strikes
        # Validate strikes are numeric before building symbols
        try:
            call_short_int = int(float(call_short) * 1000)
            call_long_int = int(float(call_long) * 1000)
            put_short_int = int(float(put_short) * 1000)
            put_long_int = int(float(put_long) * 1000)
        except (ValueError, TypeError) as e:
            log(f"FATAL: Invalid strike prices for IC: {strikes} - {e}")
            raise SystemExit
        short_syms = [INDEX_CONFIG.format_option_symbol(exp_short, 'C', call_short),
                      INDEX_CONFIG.format_option_symbol(exp_short, 'P', put_short)]
        long_syms  = [INDEX_CONFIG.format_option_symbol(exp_short, 'C', call_long),
                      INDEX_CONFIG.format_option_symbol(exp_short, 'P', put_long)]
        log(f"Placing IRON CONDOR: Calls {call_short}/{call_long} | Puts {put_short}/{put_long}")
    else:
        short_strike, long_strike = strikes
        # Validate strikes are numeric before building symbols
        try:
            short_strike_int = int(float(short_strike) * 1000)
            long_strike_int = int(float(long_strike) * 1000)
        except (ValueError, TypeError) as e:
            log(f"FATAL: Invalid strike prices for spread: {strikes} - {e}")
            raise SystemExit
        # Determine option type
        if setup['strategy'] == 'OTM_SINGLE_SIDED':
            is_call = setup['side'] == 'CALL'
        else:
            is_call = setup['strategy'] == 'CALL'
        opt_type = 'C' if is_call else 'P'
        short_sym = INDEX_CONFIG.format_option_symbol(exp_short, opt_type, short_strike)
        long_sym  = INDEX_CONFIG.format_option_symbol(exp_short, opt_type, long_strike)
        log(f"Placing {setup['strategy']} SPREAD {short_strike}/{long_strike}{'C' if is_call else 'P'}")

    # === EXPECTED CREDIT FETCHING (must happen BEFORE spread quality check) ===
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

    # === SPREAD QUALITY CHECK (now that we have expected_credit) ===
    # FIX #4: Check bid/ask spread quality to prevent instant slippage stops
    if setup['strategy'] == 'IC':
        log("Checking IC spread quality...")
        call_spread_quality = check_spread_quality(short_syms[0], long_syms[0], call_credit)
        put_spread_quality = check_spread_quality(short_syms[1], long_syms[1], put_credit)
        if not call_spread_quality or not put_spread_quality:
            log("IC spread quality check failed — NO TRADE")
            send_discord_skip_alert("Bid/ask spreads too wide (high slippage risk)", run_data)
            raise SystemExit
    else:
        log("Checking spread quality...")
        spread_quality = check_spread_quality(short_sym, long_sym, expected_credit)
        if not spread_quality:
            log("Spread quality check failed — NO TRADE")
            send_discord_skip_alert("Bid/ask spreads too wide (high slippage risk)", run_data)
            raise SystemExit

    # === MINIMUM CREDIT CHECK (index-aware, scales automatically) ===
    # FIX 2026-01-11: Use INDEX_CONFIG.get_min_credit() for proper scaling
    # SPX: $0.40-$0.65 (realistic 0DTE), NDX: $2.00-$3.25 (5× SPX)
    # Previous hardcoded values were based on weekly options, not 0DTE
    min_credit = INDEX_CONFIG.get_min_credit(now_et.hour)

    if expected_credit < min_credit:
        log(f"Credit ${expected_credit:.2f} below minimum ${min_credit:.2f} for {now_et.strftime('%H:%M')} ET ({INDEX_CONFIG.code}) — NO TRADE")
        send_discord_skip_alert(f"Credit ${expected_credit:.2f} below ${min_credit:.2f} minimum for {now_et.strftime('%H:%M')} ET ({INDEX_CONFIG.code})", run_data)
        raise SystemExit

    dollar_credit = expected_credit * 100
    # OPTIMIZATION #3: MEDIUM confidence 60% TP (was 70%) - captures profit before reversals
    # FAR OTM (MEDIUM confidence) uses 60% TP, others use 50%
    tp_pct = 0.40 if setup['confidence'] == 'MEDIUM' else 0.50
    tp_price = round(expected_credit * tp_pct, 2)
    sl_price = round(expected_credit * 1.10, 2)
    tp_profit = (expected_credit - tp_price) * 100
    sl_loss = (sl_price - expected_credit) * 100

    log(f"EXPECTED CREDIT ≈ ${expected_credit:.2f}  →  ${dollar_credit:.0f} per contract")
    log(f"{int((1-tp_pct)*100)}% PROFIT TARGET → Close at ${tp_price:.2f}  →  +${tp_profit:.0f} profit")
    log(f"10% STOP LOSS → Close at ${sl_price:.2f}  →  -${sl_loss:.0f} loss")

    # FIX #7: Use limit order instead of market (prevent entry slippage)
    # Accept up to 5% worse than mid-price to ensure fill
    limit_price = round(expected_credit * 0.95, 2)
    log(f"Limit order price: ${limit_price:.2f} (5% worse than mid ${expected_credit:.2f})")

    # === CRITICAL FIX-1: CHECK POSITION LIMIT *BEFORE* PLACING ORDER ===
    # This prevents orphaned positions (order live but not tracked)
    ORDERS_FILE = f"{GAMMA_HOME}/data/orders_paper.json" if mode == "PAPER" else f"{GAMMA_HOME}/data/orders_live.json"

    # Load existing orders to check position limit
    existing_orders = []
    if os.path.exists(ORDERS_FILE):
        try:
            with open(ORDERS_FILE, 'r') as f:
                existing_orders = json.load(f)
        except (json.JSONDecodeError, IOError, ValueError) as e:
            log(f"Error loading existing orders from {ORDERS_FILE}: {e}")
            existing_orders = []

    # CRITICAL: Check max position limit BEFORE placing order
    active_positions = len(existing_orders)
    if active_positions >= MAX_DAILY_POSITIONS:
        log(f"⛔ Position limit reached: {active_positions}/{MAX_DAILY_POSITIONS} active positions")
        log(f"Will NOT open new position — risk management limit")
        log(f"Active order IDs: {[o.get('order_id') for o in existing_orders]}")
        send_discord_skip_alert(
            f"Position limit reached ({active_positions}/{MAX_DAILY_POSITIONS})",
            {**run_data, 'active_positions': active_positions}
        )
        raise SystemExit  # Exit BEFORE placing order (safe)

    log(f"Position limit check passed: {active_positions}/{MAX_DAILY_POSITIONS} positions")

    # === CALCULATE POSITION SIZE (AUTOSCALING) ===
    account_balance, trade_stats = load_account_balance()
    position_size = calculate_position_size_kelly(account_balance, trade_stats)

    if position_size == 0:
        log(f"⚠️  ZERO position size calculated - account below safety threshold")
        send_discord_skip_alert("Account below 50% of starting capital (safety halt)", run_data)
        raise SystemExit

    log(f"💰 Position size: {position_size} contract(s) @ ${expected_credit:.2f} each = ${expected_credit * position_size * 100:.0f} total premium")

    # === REAL ENTRY ORDER ===
    entry_data = {
        "class": "multileg", "symbol": INDEX_CONFIG.index_symbol,
        "type": "credit", "price": limit_price, "duration": "day", "tag": "GEXENTRY",
        "option_requirement": "aon",  # CRITICAL FIX-3: All-or-None (prevents partial fills / naked positions)
        "side[0]": "sell_to_open", "quantity[0]": position_size,
        "option_symbol[0]": short_syms[0] if setup['strategy']=='IC' else short_sym,
        "side[1]": "buy_to_open",  "quantity[1]": position_size,
        "option_symbol[1]": long_syms[0] if setup['strategy']=='IC' else long_sym
    }
    if setup['strategy'] == 'IC':
        entry_data.update({
            "side[2]": "sell_to_open", "quantity[2]": position_size, "option_symbol[2]": short_syms[1],
            "side[3]": "buy_to_open",  "quantity[3]": position_size, "option_symbol[3]": long_syms[1]
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
    # UNFILLED ORDER TIMEOUT LOGIC (2026-01-10):
    # Monitor order for up to 5 minutes, checking every 10 seconds
    # Cancel if not filled within timeout to prevent late fills without monitoring
    FILL_TIMEOUT = 300  # 5 minutes
    CHECK_INTERVAL = 10  # Check every 10 seconds
    max_checks = FILL_TIMEOUT // CHECK_INTERVAL

    log(f"Monitoring order {order_id} for fill (timeout: {FILL_TIMEOUT}s)")
    credit = None
    order_filled = False

    for check_num in range(max_checks):
        time.sleep(CHECK_INTERVAL)
        elapsed = (check_num + 1) * CHECK_INTERVAL

        try:
            order_detail = requests.get(f"{BASE_URL}/accounts/{TRADIER_ACCOUNT_ID}/orders/{order_id}", headers=HEADERS, timeout=10).json()
            fill_price = order_detail.get("order", {}).get("avg_fill_price")
            status = order_detail.get("order", {}).get("status", "")

            log(f"[{elapsed}s] Order status: {status}, fill_price: {fill_price}")

            # Check if order was canceled or rejected
            if status in ["canceled", "rejected", "expired"]:
                log(f"Order {status} by broker — no trade")
                raise SystemExit(f"Order {status} — exiting without position")

            # CRITICAL: Verify all legs filled (prevent naked positions)
            legs = order_detail.get("order", {}).get("leg", [])
            if isinstance(legs, dict):
                legs = [legs]  # Single leg, wrap in list

            if legs:
                total_legs = len(legs)
                filled_legs = sum(1 for leg in legs if leg.get("status") == "filled")

                if filled_legs < total_legs and status in ["filled", "partially_filled"]:
                    log(f"CRITICAL: Partial fill detected! {filled_legs}/{total_legs} legs filled")
                    log(f"MANUAL INTERVENTION REQUIRED: Check Tradier for order {order_id}")
                    raise SystemExit("Partial fill detected - aborting to prevent naked position")

                if filled_legs == total_legs and status == "filled":
                    # All legs filled - order complete
                    log(f"✓ Order filled: {filled_legs}/{total_legs} legs")
                    order_filled = True

            if fill_price is not None and fill_price != 0 and order_filled:
                # Credit spreads report negative fill price (we receive money)
                credit = abs(float(fill_price))
                log(f"✓ Fill confirmed at ${credit:.2f} after {elapsed}s")
                break

        except SystemExit:
            raise  # Re-raise SystemExit for partial fills or cancellations
        except Exception as e:
            log(f"Fill check error at {elapsed}s: {e}")
            # Continue checking - might be temporary API issue

    # If not filled after timeout, cancel the order
    if credit is None or not order_filled:
        log(f"⏱️ Order NOT filled after {FILL_TIMEOUT}s — CANCELING to prevent late fill")
        try:
            cancel_response = requests.delete(
                f"{BASE_URL}/accounts/{TRADIER_ACCOUNT_ID}/orders/{order_id}",
                headers=HEADERS,
                timeout=10
            )
            if cancel_response.status_code == 200:
                log(f"✓ Order {order_id} canceled successfully")
            else:
                log(f"⚠️ Cancel request returned status {cancel_response.status_code}")
                log(f"Response: {cancel_response.text}")
        except Exception as e:
            log(f"ERROR: Failed to cancel order {order_id}: {e}")
            log(f"MANUAL INTERVENTION REQUIRED: Cancel order manually in Tradier")

        log("No trade taken — unfilled order canceled")
        send_discord_skip_alert(
            f"Order unfilled after {FILL_TIMEOUT}s — canceled",
            {**run_data, 'order_id': order_id, 'limit_price': limit_price}
        )
        raise SystemExit("Order unfilled and canceled")

    # Verify we got a valid credit
    if credit is None or credit == 0:
        log("FATAL: Order filled but could not determine fill price!")
        log("Manual intervention required — check Tradier for open position")
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

    # Log the successful placement decision
    reason = f"{setup['description']} | Pin at {int(pin_price)}, SPX at {int(index_price)}, VIX {vix:.1f}"
    decision_logger.log_placed(setup['confidence'], credit, reason)

    # === DISCORD ENTRY ALERT ===
    send_discord_entry_alert(setup, credit, strikes, tp_pct, order_id)
    log("Discord entry alert sent" if DISCORD_ENABLED else "Discord alerts disabled")

    # NOTE: OCO/exit management handled by monitor.py - no bracket orders here

    # === LOGGING ===
    tp_target_pct = int((1 - tp_pct) * 100)  # 50% or 70%
    if not os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, 'w', newline='') as f:
            csv.writer(f).writerow(["Timestamp_ET","Trade_ID","Account_ID","Strategy","Strikes","Entry_Credit",
                                  "Confidence","TP%","Exit_Time","Exit_Value","P/L_$","P/L_%","Exit_Reason","Duration_Min"])
    with open(TRADE_LOG_FILE, 'a', newline='') as f:
        csv.writer(f).writerow([
            datetime.datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S'),
            order_id, TRADIER_ACCOUNT_ID, setup['strategy'], "/".join(map(str, strikes)), f"{credit:.2f}",
            setup['confidence'], f"{tp_target_pct}%",
            "", "", "", "", "", ""
        ])

    # === SAVE ORDER FOR MONITOR TRACKING ===
    # Note: existing_orders and ORDERS_FILE already loaded during position limit check above

    # Add new order with all tracking info
    # Format: option_symbols = [shorts..., longs...], short_indices = indices of shorts
    if setup['strategy'] == 'IC':
        option_symbols = [short_syms[0], short_syms[1], long_syms[0], long_syms[1]]
        short_indices = [0, 1]  # First two are short
    else:
        option_symbols = [short_sym, long_sym]
        short_indices = [0]  # First one is short

    # Calculate entry distance (OTM distance at entry) for progressive hold strategy
    if setup['strategy'] == 'CALL':
        # CALL spread: short strike is lower, we profit if SPX stays below
        entry_distance = min(strikes) - index_price
    elif setup['strategy'] == 'PUT':
        # PUT spread: short strike is higher, we profit if SPX stays above
        entry_distance = index_price - max(strikes)
    else:  # IC
        # Iron condor: strikes = [call_short, call_long, put_short, put_long]
        # Distance to nearest short strike (call_short above, put_short below)
        call_short = strikes[0]
        put_short = strikes[2]
        entry_distance = min(call_short - index_price, index_price - put_short)

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
        "best_profit_pct": 0,
        "entry_distance": entry_distance,
        "index_entry": index_price,
        "index_code": INDEX_CONFIG.code,  # Track which index this trade is for
        "vix_entry": vix,
        "position_size": position_size,  # Number of contracts (autoscaling)
        "account_balance": account_balance  # Track balance at entry for P/L calculation
    }
    existing_orders.append(order_data)

    with open(ORDERS_FILE, 'w') as f:
        json.dump(existing_orders, f, indent=2)
    log(f"Order {order_id} saved to monitor tracking file")

    log("Trade complete — monitor.py will handle TP/SL exits.")

    # === CHECK FOR OTM SPREAD OPPORTUNITY (ALONGSIDE GEX TRADE) ===
    # After GEX trade placed, check if we can also place an OTM spread
    log("Checking for additional OTM spread opportunity...")

    try:
        # Reload orders file (GEX trade was just saved)
        with open(ORDERS_FILE, 'r') as f:
            existing_orders = json.load(f)

        sys.path.insert(0, GAMMA_HOME)
        from otm_spreads import check_otm_opportunity

        # Create quote function for OTM module
        def get_otm_quotes(short_strike, long_strike, option_type):
            """Get quote for OTM spread."""
            try:
                chain_df = get_option_chain(index_symbol, option_type)
                if chain_df is None or chain_df.empty:
                    return 0.0

                short_row = chain_df[chain_df['strike'] == short_strike]
                if short_row.empty:
                    return 0.0
                short_bid = short_row.iloc[0]['bid']

                long_row = chain_df[chain_df['strike'] == long_strike]
                if long_row.empty:
                    return 0.0
                long_ask = long_row.iloc[0]['ask']

                credit = short_bid - long_ask
                return max(0.0, credit)

            except Exception as e:
                log(f"Error getting OTM quotes: {e}")
                return 0.0

        # Check for OTM opportunity
        otm_setup = check_otm_opportunity(index_price, vix, get_otm_quotes)

        if otm_setup and otm_setup.get('valid'):
            log("✓ OTM SPREAD OPPORTUNITY FOUND (alongside GEX trade)")
            log(f"  {otm_setup['summary']}")
            log(f"  Total credit: ${otm_setup['total_credit']:.2f}")

            # Check position limit (should have room for 1 more)
            if len(existing_orders) >= MAX_OPEN_POSITIONS:
                log(f"✗ Cannot place OTM: Already at max {MAX_OPEN_POSITIONS} positions")
            else:
                log("Placing OTM spread as second position...")

                # Generate OTM order
                strikes_info = otm_setup['strikes']
                otm_order_id = f"otm_{datetime.datetime.now(ET).strftime('%Y%m%d_%H%M%S')}"

                # Build OTM iron condor order
                otm_strikes = [
                    strikes_info['call_spread']['short'],
                    strikes_info['call_spread']['long'],
                    strikes_info['put_spread']['short'],
                    strikes_info['put_spread']['long']
                ]

                log(f"OTM Iron Condor: {otm_strikes[2]}/{otm_strikes[3]} × {otm_strikes[0]}/{otm_strikes[1]}")

                # Save OTM order to monitor
                otm_order_data = {
                    "order_id": otm_order_id,
                    "entry_credit": otm_setup['total_credit'],
                    "entry_time": datetime.datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S'),
                    "strategy": "OTM_IRON_CONDOR",
                    "strikes": "/".join(map(str, otm_strikes)),
                    "direction": "NEUTRAL",
                    "confidence": "MEDIUM",
                    "option_symbols": [],  # Monitor will handle with strikes
                    "short_indices": [0, 2],  # Call short and put short
                    "tp_price": 0,  # Not used for OTM (holds to expiration)
                    "sl_price": 0,  # Not used (monitor handles stops)
                    "trailing_stop_active": False,
                    "best_profit_pct": 0,
                    "entry_distance": strikes_info['strike_distance'],
                    "index_entry": index_price,
                    "index_code": INDEX_CONFIG.code,
                    "vix_entry": vix,
                    "position_size": position_size,
                    "account_balance": account_balance,
                    "otm_lock_in_active": False  # For 50% lock-in tracking
                }

                existing_orders.append(otm_order_data)

                with open(ORDERS_FILE, 'w') as f:
                    json.dump(existing_orders, f, indent=2)

                log(f"✓ OTM order {otm_order_id} added to monitor tracking")
                log(f"Total positions: {len(existing_orders)}/{MAX_OPEN_POSITIONS}")

        else:
            log("✗ No valid OTM opportunity alongside GEX trade")

    except Exception as e:
        log(f"OTM alongside check failed (non-fatal): {e}")
        import traceback
        traceback.print_exc()

except SystemExit as e:
    # SystemExit is raised for normal exits (e.g., time cutoff, filters)
    exit_msg = str(e) if str(e) else "no action taken"
    log(f"GEX Scalper finished — {exit_msg}")
except Exception as e:
    log(f"FATAL ERROR: {e}")
    import traceback
    traceback.print_exc()
finally:
    # CRITICAL: ALWAYS release the lock, no matter what
    # This finally block runs even on:
    # - Normal exit
    # - SystemExit
    # - Unhandled exceptions
    # - Keyboard interrupt (Ctrl+C)
    # - SIGTERM (kill command)
    #
    # NOTE: Does NOT run on SIGKILL (kill -9) or system crash
    # For those cases, the stale lock detection at startup will handle cleanup
    try:
        if 'lock_fd' in globals() and lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except Exception as unlock_err:
                log(f"Warning: Error unlocking: {unlock_err}")
            try:
                lock_fd.close()
            except Exception as close_err:
                log(f"Warning: Error closing lock file: {close_err}")
            log(f"Lock released (PID: {os.getpid()})")
        else:
            log("No lock to release (lock_fd not acquired)")
    except Exception as e:
        log(f"Error in lock cleanup: {e}")
