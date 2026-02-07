#!/usr/bin/env python3
"""
gex_monitor.py — Production GEX Position Monitor (Dec 11, 2025)

Features:
  - Monitors open GEX spread positions every 30 seconds
  - Fetches REAL spread values from Tradier quotes API
  - 50% profit target / 15% stop loss (configurable)
  - 3:50 PM auto-close for 0DTE positions
  - Full trade logging with P/L tracking
  - Paper/Live mode support

Works with: gex_scalper7.py

Usage:
  python gex_monitor.py              # Paper trading
  python gex_monitor.py LIVE         # Live trading

Author: Claude + Human collaboration
"""

import datetime
import os
import sys
import time
import json
import csv
import requests
import pytz
import numpy as np
import tempfile  # BUGFIX (2026-01-10): For atomic file writes

# ============================================================================
#                              CONFIGURATION
# ============================================================================

# Import index configuration for multi-index support
from index_config import get_index_config

# Configurable base directory (can be overridden via GAMMA_HOME env var)
GAMMA_HOME = os.environ.get('GAMMA_HOME', '/root/gamma')

from config import (
    PAPER_ACCOUNT_ID,
    LIVE_ACCOUNT_ID,
    TRADIER_LIVE_KEY,
    TRADIER_SANDBOX_KEY,
    DISCORD_ENABLED,
    DISCORD_WEBHOOK_LIVE_URL,
    DISCORD_WEBHOOK_PAPER_URL,
    DISCORD_DELAYED_ENABLED,
    DISCORD_DELAYED_WEBHOOK_URL,
    DISCORD_DELAY_SECONDS,
    HEALTHCHECK_LIVE_URL,
    HEALTHCHECK_PAPER_URL,
    DISCORD_AUTODELETE_ENABLED,
    DISCORD_AUTODELETE_STORAGE,
    DISCORD_TTL_SIGNALS,
    DISCORD_TTL_CRASHES,
    DISCORD_TTL_HEARTBEAT,
    DISCORD_TTL_DEFAULT
)
from threading import Timer
from discord_autodelete import DiscordAutoDelete

# Timezone
ET = pytz.timezone('America/New_York')

# File paths
ORDERS_FILE_PAPER = f"{GAMMA_HOME}/data/orders_paper.json"
ORDERS_FILE_LIVE = f"{GAMMA_HOME}/data/orders_live.json"
TRADE_LOG_FILE = f"{GAMMA_HOME}/data/trades.csv"
LOG_FILE_PAPER = f"{GAMMA_HOME}/data/monitor_paper.log"
LOG_FILE_LIVE = f"{GAMMA_HOME}/data/monitor_live.log"

# Monitor settings
# OPTIMIZATION (2026-01-19): Reduced from 15s to 3s for 0DTE options
# 0DTE options can move 50-100% in 15 seconds, causing stop violations
# 3-second polling catches stops at intended prices, prevents $10-20 extra loss per contract
POLL_INTERVAL = 3               # Seconds between checks (ultra-tight for 0DTE fast moves)
PROFIT_TARGET_PCT = 0.50        # Close at 50% profit
STOP_LOSS_PCT = 0.15            # OPTIMIZATION: 15% stop loss (allows breathing room for 0DTE gamma swings)
AUTO_CLOSE_HOUR = 15            # Auto-close at 3:30 PM ET (was 3:50)
AUTO_CLOSE_MINUTE = 30          # Earlier close avoids final 30-min chaos

# Trailing stop settings (IMPROVED 2026-01-16)
TRAILING_STOP_ENABLED = True
TRAILING_TRIGGER_PCT = 0.30     # OPTIMIZATION: Activate at 30% profit (was 20%) - hold winners longer
TRAILING_LOCK_IN_PCT = 0.20     # OPTIMIZATION: Lock in 20% profit (was 12%) - proportionally adjusted
TRAILING_DISTANCE_MIN = 0.10    # Minimum trail distance as profit rises (10%, was 8%)
TRAILING_TIGHTEN_RATE = 0.4     # How fast it tightens (0.4 = every 2.5% gain, trail tightens 1%)

# Stop loss grace period - let positions settle before triggering SL
SL_GRACE_PERIOD_SEC = 540       # OPTIMIZATION #2: 9 minutes grace (allows 0DTE to work through initial gamma volatility)
SL_EMERGENCY_PCT = 0.25         # OPTIMIZATION: Emergency stop at 25% (was 40%) - tighter risk control
SL_ENTRY_SETTLE_SEC = 60        # FIX #3 (2026-02-04): Entry settle period - wait 60s before emergency stop can trigger

# Smart settle period - early exit conditions (FIX #4: 2026-02-04)
SL_SETTLE_SPREAD_NORMALIZED = 0.15    # Override if spread < 15%
SL_SETTLE_QUOTE_STABLE_SEC = 10       # Override if quote stable for 10s
SL_SETTLE_CATASTROPHIC_PCT = 0.35     # Override if loss > 35%
SL_SETTLE_QUOTE_CHANGE_THRESHOLD = 0.05  # Quote unchanged if within 5 cents

# Progressive hold-to-expiration settings (2026-01-10)
PROGRESSIVE_HOLD_ENABLED = True   # Enable progressive hold strategy
HOLD_PROFIT_THRESHOLD = 0.80      # Must reach 80% profit to qualify for hold
HOLD_VIX_MAX = 17                 # VIX must be < 17
HOLD_MIN_TIME_LEFT_HOURS = 1.0    # At least 1 hour to expiration
HOLD_MIN_ENTRY_DISTANCE = 8       # At least 8 pts OTM at entry

# Progressive TP schedule: (hours_after_entry, tp_threshold)
PROGRESSIVE_TP_SCHEDULE = [
    (0.0, 0.50),   # Start: 50% TP
    (1.0, 0.55),   # 1 hour: 55% TP
    (2.0, 0.60),   # 2 hours: 60% TP
    (3.0, 0.70),   # 3 hours: 70% TP
    (4.0, 0.80),   # 4+ hours: 80% TP
]

# ============================================================================
#                           MODE DETECTION
# ============================================================================

def get_mode():
    """
    Detect trading mode from command line args first, then sentinel file.
    BUGFIX (2026-01-24): Prioritize explicit command line args over sentinel
    to allow running both LIVE and PAPER bots simultaneously.
    """
    import sys

    # PRIORITY 1: Explicit command line argument (highest priority)
    if len(sys.argv) > 1:
        arg = sys.argv[1].upper()
        if arg in ['LIVE', 'REAL']:
            print(f"📋 Gamma Trading Mode: 🔴 LIVE MODE (explicit arg)")
            return 'REAL'
        elif arg in ['PAPER', 'DEMO']:
            print(f"📋 Gamma Trading Mode: 🟢 PAPER MODE (explicit arg)")
            return 'PAPER'

    # PRIORITY 2: Sentinel file (fallback)
    try:
        sys.path.insert(0, '/root/topstocks')
        from core.trading_mode import get_trading_mode

        mode = get_trading_mode(bot='GAMMA')
        if mode == 'LIVE':
            print(f"📋 Gamma Trading Mode: 🔴 LIVE MODE (from sentinel)")
            return 'REAL'
        else:  # DEMO
            print(f"📋 Gamma Trading Mode: 🟢 DEMO MODE (from sentinel)")
            return 'PAPER'
    except Exception as e:
        print(f"WARNING: Could not read GAMMA_TRADING_MODE sentinel: {e}")

    # PRIORITY 3: Default to PAPER (safest)
    print(f"📋 Gamma Trading Mode: 🟢 PAPER MODE (default)")
    return 'PAPER'

MODE = get_mode()
TRADIER_ACCOUNT_ID = LIVE_ACCOUNT_ID if MODE == 'REAL' else PAPER_ACCOUNT_ID
TRADIER_KEY = TRADIER_LIVE_KEY if MODE == 'REAL' else TRADIER_SANDBOX_KEY
BASE_URL = "https://api.tradier.com/v1" if MODE == 'REAL' else "https://sandbox.tradier.com/v1"
ORDERS_FILE = ORDERS_FILE_LIVE if MODE == 'REAL' else ORDERS_FILE_PAPER
LOG_FILE = LOG_FILE_LIVE if MODE == 'REAL' else LOG_FILE_PAPER

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {TRADIER_KEY}"
}

# Initialize Discord auto-delete with separate storage per mode
discord_autodelete = None

# Use separate storage files and webhooks for LIVE and PAPER to avoid race conditions
if MODE == 'REAL':
    DISCORD_STORAGE_FILE = f"{GAMMA_HOME}/data/discord_messages_live.json"
    DISCORD_WEBHOOK_URL = DISCORD_WEBHOOK_LIVE_URL
    HEALTHCHECK_URL = HEALTHCHECK_LIVE_URL
else:
    DISCORD_STORAGE_FILE = f"{GAMMA_HOME}/data/discord_messages_paper.json"
    DISCORD_WEBHOOK_URL = DISCORD_WEBHOOK_PAPER_URL
    HEALTHCHECK_URL = HEALTHCHECK_PAPER_URL

# Enable healthcheck if URL is configured
HEALTHCHECK_ENABLED = bool(HEALTHCHECK_URL)

if DISCORD_AUTODELETE_ENABLED:
    try:
        discord_autodelete = DiscordAutoDelete(
            storage_file=DISCORD_STORAGE_FILE,
            default_ttl=DISCORD_TTL_DEFAULT
        )
        discord_autodelete.start_cleanup_thread()
        print(f"[STARTUP] ✅ Discord auto-delete enabled ({MODE} mode, TTL: {DISCORD_TTL_DEFAULT}s)")
        print(f"[STARTUP] ✅ Storage: {DISCORD_STORAGE_FILE}")
    except Exception as e:
        print(f"[STARTUP] ❌ Failed to initialize Discord auto-delete: {e}")
        import traceback
        traceback.print_exc()
        discord_autodelete = None
else:
    print(f"[STARTUP] Discord auto-delete disabled")

# ============================================================================
#                              LOGGING
# ============================================================================

# Ensure log directory exists
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

def log(msg):
    """Print timestamped log message to stdout and log file."""
    timestamp = datetime.datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

# ============================================================================
#                           RETRY LOGIC
# ============================================================================

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

# ============================================================================
#                           DISCORD ALERTS
# ============================================================================

def _send_to_webhook(url, msg, message_type="general"):
    """Helper to send message to a webhook URL with auto-delete support."""
    # Use auto-delete if available
    if discord_autodelete:
        # Determine TTL based on message type
        ttl_map = {
            'crash': DISCORD_TTL_CRASHES,
            'heartbeat': DISCORD_TTL_HEARTBEAT,
            'signal': DISCORD_TTL_SIGNALS,
            'general': DISCORD_TTL_DEFAULT
        }
        ttl = ttl_map.get(message_type, DISCORD_TTL_DEFAULT)

        message_id = discord_autodelete.send_message(
            webhook_url=url,
            message_data=msg,
            ttl_seconds=ttl,
            message_type=message_type
        )
        if message_id:
            log(f"[DISCORD] Webhook sent (auto-delete in {ttl}s) - {msg['embeds'][0]['title']}")
        else:
            log(f"[DISCORD] Webhook failed - {msg['embeds'][0]['title']}")
    else:
        # Fallback to regular POST without auto-delete
        try:
            r = requests.post(url, json=msg, timeout=5)
            if r.status_code == 200 or r.status_code == 204:
                log(f"[DISCORD] Webhook sent: {r.status_code} - {msg['embeds'][0]['title']}")
            else:
                # Log failed webhooks with full error details
                log(f"[DISCORD] Webhook failed: {r.status_code} - {r.text}")
                log(f"[DISCORD] Failed message title: {msg['embeds'][0]['title']}")
        except requests.exceptions.Timeout:
            log(f"[DISCORD] Alert failed: Timeout after 5s - {msg['embeds'][0]['title']}")
        except requests.exceptions.ConnectionError as e:
            log(f"[DISCORD] Alert failed: Connection error - {e}")
        except Exception as e:
            log(f"[DISCORD] Alert failed: {e}")

def send_heartbeat():
    """Send heartbeat ping to healthchecks.io to prove monitor is alive."""
    if not HEALTHCHECK_ENABLED or not HEALTHCHECK_URL:
        return
    try:
        r = requests.get(HEALTHCHECK_URL, timeout=10)
        if r.status_code == 200:
            log("[HEARTBEAT] Ping sent OK")
        else:
            log(f"[HEARTBEAT] Ping failed: {r.status_code}")
    except Exception as e:
        log(f"[HEARTBEAT] Error: {e}")

def send_discord_exit_alert(order_id, strategy, strikes, entry_credit, exit_value, exit_reason, profit_pct):
    """Send trade exit alert to Discord (immediate + delayed). Strikes redacted."""
    if not DISCORD_ENABLED or not DISCORD_WEBHOOK_URL:
        return

    try:
        # Color based on result
        if profit_pct >= 0:
            color = 0x2ecc71  # Green for profit
            emoji = "✅"
        else:
            color = 0xe74c3c  # Red for loss
            emoji = "❌"

        # P/L calculation: Both entry_credit and exit_value are per-contract prices
        # Multiply by 100 (option multiplier) to get dollar P&L for 1 contract
        # For credit spreads: profit when exit_value < entry_credit
        pl_dollar = (entry_credit - exit_value) * 100

        msg = {
            "embeds": [{
                "title": f"{emoji} GEX SCALP EXIT — {exit_reason}",
                "description": f"**Strikes:** {strikes}",
                "color": color,
                "fields": [
                    {"name": "Strategy", "value": strategy, "inline": True},
                    {"name": "Entry Credit", "value": f"${entry_credit:.2f}", "inline": True},
                    {"name": "Exit Value", "value": f"${exit_value:.2f}", "inline": True},
                    {"name": "P/L $", "value": f"${pl_dollar:+.2f}", "inline": True},
                    {"name": "P/L %", "value": f"{profit_pct*100:+.1f}%", "inline": True},
                ],
                "footer": {"text": f"0DTE SPX"},
                "timestamp": datetime.datetime.utcnow().isoformat()
            }]
        }

        # Send immediate alert
        _send_to_webhook(DISCORD_WEBHOOK_URL, msg, message_type="signal")

        # Send delayed alert (7 min) to free tier - LIVE only
        if DISCORD_DELAYED_ENABLED and DISCORD_DELAYED_WEBHOOK_URL and MODE == "REAL":
            msg_delayed = {"embeds": [msg["embeds"][0].copy()]}
            msg_delayed["embeds"][0]["title"] = f"⏰ {emoji} GEX SCALP EXIT — {exit_reason} (delayed)"
            timer = Timer(DISCORD_DELAY_SECONDS, _send_to_webhook, [DISCORD_DELAYED_WEBHOOK_URL, msg_delayed, "signal"])
            timer.daemon = True  # Prevent thread leak - thread dies with main process
            timer.start()

    except Exception as e:
        log(f"Discord exit alert failed: {e}")

def send_discord_daily_summary(trades_today):
    """Send daily performance summary to Discord (immediate + delayed)."""
    if not DISCORD_ENABLED or not DISCORD_WEBHOOK_URL:
        return

    try:
        total_pl = sum(t['pl_dollar'] for t in trades_today)
        winners = len([t for t in trades_today if t['pl_dollar'] > 0])
        losers = len(trades_today) - winners
        win_rate = (winners / len(trades_today) * 100) if trades_today else 0

        color = 0x2ecc71 if total_pl >= 0 else 0xe74c3c

        msg = {
            "embeds": [{
                "title": "📊 GEX SCALPER — Daily Summary",
                "color": color,
                "fields": [
                    {"name": "Total Trades", "value": str(len(trades_today)), "inline": True},
                    {"name": "Winners", "value": str(winners), "inline": True},
                    {"name": "Losers", "value": str(losers), "inline": True},
                    {"name": "Win Rate", "value": f"{win_rate:.0f}%", "inline": True},
                    {"name": "Total P/L", "value": f"${total_pl:+.2f}", "inline": True},
                ],
                "footer": {"text": datetime.datetime.now(ET).strftime('%Y-%m-%d')},
                "timestamp": datetime.datetime.utcnow().isoformat()
            }]
        }

        # Send immediate alert
        _send_to_webhook(DISCORD_WEBHOOK_URL, msg, message_type="signal")

        # Send delayed alert (7 min) to free tier - LIVE only
        if DISCORD_DELAYED_ENABLED and DISCORD_DELAYED_WEBHOOK_URL and MODE == "REAL":
            msg_delayed = {"embeds": [msg["embeds"][0].copy()]}
            msg_delayed["embeds"][0]["title"] = "⏰ 📊 GEX SCALPER — Daily Summary (delayed)"
            timer = Timer(DISCORD_DELAY_SECONDS, _send_to_webhook, [DISCORD_DELAYED_WEBHOOK_URL, msg_delayed, "signal"])
            timer.daemon = True  # Prevent thread leak - thread dies with main process
            timer.start()

    except Exception as e:
        log(f"Discord daily summary failed: {e}")

# ============================================================================
#                           ORDERS FILE MANAGEMENT
# ============================================================================

def load_orders():
    """Load tracked orders from JSON file with file locking (multi-index support)."""
    import fcntl
    if not os.path.exists(ORDERS_FILE):
        return []
    try:
        with open(ORDERS_FILE, 'r') as f:
            # Use shared lock for reading (multiple readers allowed)
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                content = f.read().strip()
                if not content:
                    return []
                orders = json.loads(content)

                # ENHANCEMENT: Add IndexConfig to each order for multi-index support
                for order in orders:
                    index_code = order.get('index_code', 'SPX')  # Default to SPX for legacy orders
                    try:
                        order['_config'] = get_index_config(index_code)
                    except ValueError:
                        log(f"Warning: Unknown index_code '{index_code}' for order {order.get('order_id')}, defaulting to SPX")
                        order['_config'] = get_index_config('SPX')

                return orders
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except (json.JSONDecodeError, Exception) as e:
        log(f"Warning: Could not load orders file: {e}")
        return []

def save_orders(orders):
    """Save tracked orders to JSON file with file locking."""
    import fcntl
    os.makedirs(os.path.dirname(ORDERS_FILE), exist_ok=True)

    # Use exclusive lock to prevent concurrent writes
    with open(ORDERS_FILE, 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            # BUGFIX (2026-01-12): Remove _config before JSON serialization
            # _config is IndexConfig object (not JSON serializable), only used in memory
            orders_serializable = []
            for order in orders:
                order_copy = order.copy()
                order_copy.pop('_config', None)  # Remove _config if present
                orders_serializable.append(order_copy)
            json.dump(orders_serializable, f, indent=2)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

def add_order(order_data):
    """Add a new order to tracking."""
    orders = load_orders()
    orders.append(order_data)
    save_orders(orders)
    log(f"Added order {order_data['order_id']} to tracking")

def verify_position_closed_at_broker(order_data):
    """
    Verify that a position is actually closed at Tradier (not just tracking removed).

    CRITICAL SAFETY (2026-02-04): Prevents silent position abandonment.
    Returns True ONLY if Tradier confirms the position no longer exists.

    Args:
        order_data: Order dict with option_symbols

    Returns:
        bool: True if position is confirmed closed, False if still open or error
    """
    try:
        symbols = order_data.get('option_symbols', [])
        if not symbols:
            log(f"⚠️  Cannot verify closure: no symbols in order data")
            return False

        # Query Tradier positions
        r = requests.get(
            f"{BASE_URL}/accounts/{TRADIER_ACCOUNT_ID}/positions",
            headers=HEADERS,
            timeout=10
        )

        if r.status_code != 200:
            log(f"⚠️  Cannot verify closure: API error HTTP {r.status_code}")
            return False

        data = r.json()
        positions = data.get('positions')

        # No positions at all = definitely closed
        if not positions or positions == 'null':
            return True

        position_list = positions.get('position', [])
        if not isinstance(position_list, list):
            position_list = [position_list]

        # Check if any of our symbols still exist in positions
        open_symbols = [p.get('symbol') for p in position_list]

        for symbol in symbols:
            if symbol in open_symbols:
                log(f"⚠️  Position still OPEN at broker: {symbol}")
                return False

        # All symbols confirmed closed
        return True

    except Exception as e:
        log(f"⚠️  Error verifying closure: {e}")
        return False

def remove_order(order_id, verified_closed_at_broker=False, reason="unknown"):
    """
    Remove an order from tracking.

    CRITICAL SAFETY (2026-02-04): Positions should ONLY be removed after verifying
    they're actually closed at the broker. Silent removals caused $1,822 loss.

    Args:
        order_id: Order ID to remove
        verified_closed_at_broker: MUST be True to remove (safety check)
        reason: Why this position is being removed (for logging)
    """
    if not verified_closed_at_broker:
        log(f"🚨 CRITICAL: Attempted to remove order {order_id} WITHOUT broker verification!")
        log(f"   Reason: {reason}")
        log(f"   This is BLOCKED to prevent silent position abandonment.")
        log(f"   Use verified_closed_at_broker=True ONLY after confirming closure at Tradier.")
        return False

    orders = load_orders()
    original_count = len(orders)
    orders = [o for o in orders if o.get('order_id') != order_id]

    if len(orders) < original_count:
        save_orders(orders)
        log(f"🗑️  POSITION REMOVED FROM TRACKING: {order_id}")
        log(f"   ✅ Verified closed at broker: YES")
        log(f"   Reason: {reason}")
        log(f"   Remaining positions: {len(orders)}")
        return True
    else:
        log(f"⚠️  Order {order_id} not found in tracking (already removed?)")
        return False

# ============================================================================
#                           MARKET HOURS VALIDATION
# ============================================================================

def is_market_open():
    """
    Check if market is open for trading (9:30 AM - 4:00 PM ET, Mon-Fri).

    Returns:
        bool: True if market is open, False otherwise
    """
    now = datetime.datetime.now(ET)

    # Check if weekend (Saturday=5, Sunday=6)
    if now.weekday() >= 5:
        return False

    # Check if within trading hours (9:30 AM - 4:00 PM)
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)

    return market_open <= now < market_close

# ============================================================================
#                           TRADIER API FUNCTIONS
# ============================================================================

def get_quotes(symbols):
    """
    Fetch quotes for multiple option symbols.
    Returns dict keyed by symbol.
    """
    if isinstance(symbols, list):
        symbols_str = ",".join(symbols)
    else:
        symbols_str = symbols
    
    try:
        r = retry_api_call(
            lambda: requests.get(
                f"{BASE_URL}/markets/quotes",
                headers=HEADERS,
                params={"symbols": symbols_str, "greeks": "false"},
                timeout=15
            ),
            description=f"Quote fetch ({symbols_str[:50]}...)"
        )

        if r is None:
            log(f"Quotes API error: No response after retries")
            return None

        if r.status_code != 200:
            log(f"Quotes API error: {r.status_code}")
            return None
        
        data = r.json()
        quotes = data.get("quotes", {}).get("quote", [])
        
        if isinstance(quotes, dict):
            quotes = [quotes]
        
        return {q['symbol']: q for q in quotes}
        
    except Exception as e:
        log(f"Quotes fetch error: {e}")
        return None

def get_positions():
    """Fetch current account positions."""
    try:
        r = requests.get(
            f"{BASE_URL}/accounts/{TRADIER_ACCOUNT_ID}/positions",
            headers=HEADERS,
            timeout=15
        )
        
        if r.status_code != 200:
            log(f"Positions API error: {r.status_code}")
            return None
        
        data = r.json()
        positions = data.get("positions", {})
        
        if positions == "null" or not positions:
            return []
        
        pos_list = positions.get("position", [])
        if isinstance(pos_list, dict):
            pos_list = [pos_list]
        
        return pos_list
        
    except Exception as e:
        log(f"Positions fetch error: {e}")
        return None

def close_spread(order_data):
    """
    Close a spread position by placing opposite multileg order.

    order_data should contain:
        - option_symbols: list of OCC symbols
        - short_indices: list of indices that were sold (need to buy back)
    """
    symbols = order_data.get('option_symbols', [])
    short_indices = order_data.get('short_indices', [])

    if not symbols:
        log("No symbols in order data — cannot close")
        return False

    # Validate market is open before placing order
    if not is_market_open():
        log("WARNING: Attempted to close position outside market hours — order will fail")
        # Still attempt the order (broker will reject it cleanly)
        # This allows the caller to handle post-market scenarios
    
    # Build closing legs
    legs = []
    for i, symbol in enumerate(symbols):
        if i in short_indices:
            # Was short → buy to close
            side = "buy_to_close"
        else:
            # Was long → sell to close
            side = "sell_to_close"
        
        legs.append({
            'option_symbol': symbol,
            'side': side,
            'quantity': order_data.get('position_size', 1)
        })
    
    # Build order data (use index-specific option root)
    # HIGH-1 FIX (2026-01-13): Validate config retrieval, handle errors
    try:
        config = order_data.get('_config') or get_index_config(order_data.get('index_code', 'SPX'))
    except ValueError as e:
        log(f"ERROR HIGH-1: Invalid index config for order {order_id}: {e}")
        log(f"  Defaulting to SPX config for exit")
        config = get_index_config('SPX')  # Safe fallback

    data = {
        "class": "multileg",
        "symbol": config.option_root,  # SPXW or NDXW
        "type": "market",
        "duration": "day",
        "tag": "GEXEXIT"
    }
    
    for i, leg in enumerate(legs):
        data[f"option_symbol[{i}]"] = leg['option_symbol']
        data[f"side[{i}]"] = leg['side']
        data[f"quantity[{i}]"] = leg['quantity']
    
    try:
        r = retry_api_call(
            lambda: requests.post(
                f"{BASE_URL}/accounts/{TRADIER_ACCOUNT_ID}/orders",
                headers=HEADERS,
                data=data,
                timeout=15
            ),
            description=f"Exit order for {symbol}"
        )

        if r is None:
            log(f"Close order failed: No response after retries")
            return False

        if r.status_code == 200:
            result = r.json()
            close_order_id = result.get("order", {}).get("id")
            log(f"Close order placed: {close_order_id}")
            return True
        else:
            # Log full error response (don't truncate - critical for debugging)
            log(f"Close order failed: {r.status_code} - {r.text}")

            # CRITICAL: Fallback to leg-by-leg closing
            log(f"⚠️  Multi-leg close failed - attempting individual leg closes to prevent stop loss bypass")

            # Close short legs first (risk reduction priority)
            short_legs = [leg for i, leg in enumerate(legs) if i in short_indices]
            long_legs = [leg for i, leg in enumerate(legs) if i not in short_indices]

            all_legs_closed = True
            for leg in short_legs + long_legs:
                try:
                    individual_data = {
                        "class": "option",
                        "symbol": leg['option_symbol'],
                        "side": leg['side'],
                        "quantity": leg['quantity'],
                        "type": "market",
                        "duration": "day",
                        "tag": "GEXEXIT_EMERGENCY"
                    }

                    leg_response = requests.post(
                        f"{BASE_URL}/accounts/{TRADIER_ACCOUNT_ID}/orders",
                        headers=HEADERS,
                        data=individual_data,
                        timeout=15
                    )

                    if leg_response.status_code == 200:
                        leg_order_id = leg_response.json().get("order", {}).get("id")
                        log(f"✓ Individual leg closed: {leg['option_symbol']} (order {leg_order_id})")
                    else:
                        log(f"✗ Failed to close leg {leg['option_symbol']}: {leg_response.status_code}")
                        all_legs_closed = False

                except Exception as leg_error:
                    log(f"✗ Error closing leg {leg.get('option_symbol', 'unknown')}: {leg_error}")
                    all_legs_closed = False

            if all_legs_closed:
                log(f"✓ All legs closed individually via emergency fallback")
                return True
            else:
                log(f"⚠️  Some legs failed to close - MANUAL INTERVENTION REQUIRED")
                return False

    except Exception as e:
        log(f"Close order error: {e}")
        return False

# ============================================================================
#                        SPREAD VALUE CALCULATION
# ============================================================================

def get_spread_value(order_data):
    """
    Calculate current mid-price value of the spread.
    
    For a credit spread:
        - Value = what we'd pay to close = (buy back shorts) - (sell longs)
        - If value < entry_credit, we have profit
        - If value > entry_credit, we have loss
    
    Returns: (current_value, bid_value, ask_value) or (None, None, None)
    """
    symbols = order_data.get('option_symbols', [])
    short_indices = order_data.get('short_indices', [])
    
    if not symbols:
        return None, None, None
    
    quotes = get_quotes(symbols)
    
    if not quotes:
        return None, None, None
    
    mid_value = 0.0
    bid_value = 0.0  # Best case (we'd pay this to close)
    ask_value = 0.0  # Worst case
    
    for i, symbol in enumerate(symbols):
        if symbol not in quotes:
            log(f"Missing quote for {symbol}")
            return None, None, None
        
        q = quotes[symbol]
        bid = float(q.get('bid') or 0)
        ask = float(q.get('ask') or 0)
        mid = (bid + ask) / 2
        
        if i in short_indices:
            # Short leg: we need to buy back at ask (worst) or bid (best)
            mid_value += mid
            bid_value += bid    # Best case
            ask_value += ask    # Worst case
        else:
            # Long leg: we sell at bid (worst) or ask (best)
            mid_value -= mid
            bid_value -= ask    # Best case (sell at ask)
            ask_value -= bid    # Worst case (sell at bid)
    
    return round(mid_value, 2), round(bid_value, 2), round(ask_value, 2)

# ============================================================================
#                           TRADE LOG UPDATE
# ============================================================================

def update_trade_log(order_id, exit_value, exit_reason, entry_credit, entry_time_str, position_size=1):
    """Update the CSV trade log with exit information."""
    if not os.path.exists(TRADE_LOG_FILE):
        log(f"Trade log file not found: {TRADE_LOG_FILE}")
        return

    try:
        rows = []
        with open(TRADE_LOG_FILE, 'r') as f:
            rows = list(csv.reader(f))

        updated = False
        for row in rows[1:]:  # Skip header
            if row and len(row) > 1 and row[1] == str(order_id):
                exit_time = datetime.datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')

                # Calculate duration
                # Security Fix (2026-01-04): Standardize timezone handling
                try:
                    # Try ISO 8601 with timezone first (new standard format)
                    if 'T' in entry_time_str and ('+' in entry_time_str or 'Z' in entry_time_str):
                        entry_time = datetime.datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
                        # Convert to ET for duration calculation
                        entry_time = entry_time.astimezone(ET)
                    else:
                        # Legacy format: assume ET timezone
                        entry_time = datetime.datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S')
                        entry_time = ET.localize(entry_time)

                    duration_min = (datetime.datetime.now(ET) - entry_time).total_seconds() / 60
                except (ValueError, TypeError, AttributeError) as e:
                    log(f"Error parsing entry time '{entry_time_str}': {e}")
                    duration_min = 0

                # Calculate P/L
                # BUGFIX (2026-01-10): position_size now passed as parameter instead of using undefined 'order' variable
                pl_dollar_per_contract = (entry_credit - exit_value) * 100  # Per contract
                pl_dollar = pl_dollar_per_contract * position_size  # Total P/L
                pl_pct = ((entry_credit - exit_value) / entry_credit) * 100 if entry_credit > 0 else 0

                # Update account balance (autoscaling)
                try:
                    balance_file = f"{GAMMA_HOME}/data/account_balance.json"
                    if os.path.exists(balance_file):
                        with open(balance_file, 'r') as f:
                            balance_data = json.load(f)

                        # Update balance
                        balance_data['balance'] = balance_data.get('balance', 20000) + pl_dollar

                        # Add trade to rolling statistics (keep last 50)
                        trades = balance_data.get('trades', [])
                        trades.append({'pnl': pl_dollar_per_contract, 'timestamp': datetime.datetime.now().isoformat()})
                        balance_data['trades'] = trades[-50:]  # Keep last 50
                        balance_data['total_trades'] = balance_data.get('total_trades', 0) + 1
                        balance_data['last_updated'] = datetime.datetime.now().isoformat()

                        # BUGFIX (2026-01-10): Use atomic write to prevent corruption
                        temp_fd, temp_path = tempfile.mkstemp(
                            dir=os.path.dirname(balance_file),
                            prefix='.account_balance_',
                            suffix='.tmp'
                        )
                        try:
                            with os.fdopen(temp_fd, 'w') as f:
                                json.dump(balance_data, f, indent=2)
                                f.flush()
                                os.fsync(f.fileno())  # Force write to disk
                            # Atomic rename
                            os.replace(temp_path, balance_file)
                        except:
                            try:
                                os.unlink(temp_path)
                            except:
                                pass
                            raise

                        log(f"Account balance updated: ${balance_data['balance']:,.0f} ({pl_dollar:+.2f} from {position_size}x contracts)")
                except Exception as e:
                    log(f"Error updating account balance: {e}")
                
                # Update row: Exit_Time, Exit_Value, P/L_$, P/L_%, Exit_Reason, Duration_Min
                # New CSV format with Account_ID at index 2, exit fields start at 8
                if len(row) >= 14:
                    # New format: with Account_ID column (14 total columns)
                    row[8] = exit_time
                    row[9] = f"{exit_value:.2f}"
                    row[10] = f"{pl_dollar:+.2f}"
                    row[11] = f"{pl_pct:+.1f}%"
                    row[12] = exit_reason
                    row[13] = f"{duration_min:.0f}"
                    updated = True
                elif len(row) >= 13:
                    # Old format without Account_ID (13 total columns) - backward compatibility
                    row[7] = exit_time
                    row[8] = f"{exit_value:.2f}"
                    row[9] = f"{pl_dollar:+.2f}"
                    row[10] = f"{pl_pct:+.1f}%"
                    row[11] = exit_reason
                    row[12] = f"{duration_min:.0f}"
                    updated = True
                elif len(row) >= 11:
                    # Very old format fallback
                    row[5] = exit_time
                    row[6] = f"{exit_value:.2f}"
                    row[7] = f"{pl_dollar:+.2f}"
                    row[8] = f"{pl_pct:+.1f}%"
                    row[9] = exit_reason
                    row[10] = f"{duration_min:.0f}"
                    updated = True
                else:
                    # Row too short - log error and skip update
                    log(f"ERROR: CSV row for order {order_id} has insufficient columns ({len(row)} < 11), skipping update")
                    log(f"Row contents: {row}")
                    updated = False

                if updated:
                    log(f"Trade log updated: {order_id} | {exit_reason} | P/L ${pl_dollar:+.2f} ({pl_pct:+.1f}%)")
                break
        
        if updated:
            with open(TRADE_LOG_FILE, 'w', newline='') as f:
                csv.writer(f).writerows(rows)
        else:
            log(f"Order {order_id} not found in trade log")
            
    except Exception as e:
        log(f"Error updating trade log: {e}")

# ============================================================================
#                           MONITOR LOGIC
# ============================================================================

def should_override_settle_period(entry_credit, current_value, bid_value, ask_value,
                                  profit_pct_sl, order, position_age_sec):
    """
    FIX #4 (2026-02-04): Smart settle period - override early exit conditions.

    Check if settle period should be overridden to allow emergency stop.
    Instead of blindly waiting 60 seconds, exit early if:
    1. Bid-ask spread normalized (< 15%)
    2. Quote stable for 10+ seconds (no significant change)
    3. Catastrophic loss (< -35%)

    Args:
        entry_credit: Entry credit received
        current_value: Current mid price
        bid_value: Current bid price
        ask_value: Current ask price
        profit_pct_sl: Current P&L percentage (stop loss calc)
        order: Order dictionary with tracking data
        position_age_sec: Seconds since position entry

    Returns:
        (should_override, reason) - tuple of bool and string
    """
    now = datetime.datetime.now(ET)

    # Condition 1: Bid-ask spread normalized (tight spread = reliable quote)
    if bid_value > 0 and ask_value > 0:
        mid_price = (ask_value + bid_value) / 2
        if mid_price > 0:
            spread_pct = (ask_value - bid_value) / mid_price
            if spread_pct < SL_SETTLE_SPREAD_NORMALIZED:
                return True, f"spread normalized ({spread_pct*100:.1f}%)"

    # Condition 2: Quote stability (no movement = position settled)
    # Track last quote and timestamp in order dict
    last_quote_value = order.get('last_quote_value')
    last_quote_time_str = order.get('last_quote_time')

    if last_quote_value is not None and last_quote_time_str is not None:
        try:
            # Parse ISO format timestamp back to datetime
            last_quote_time = datetime.datetime.fromisoformat(last_quote_time_str)
            if last_quote_time.tzinfo is None:
                # Assume ET if no timezone
                last_quote_time = ET.localize(last_quote_time)
            else:
                # Convert to ET
                last_quote_time = last_quote_time.astimezone(ET)

            # Check if quote changed significantly
            quote_change = abs(current_value - last_quote_value)
            quote_unchanged = quote_change < SL_SETTLE_QUOTE_CHANGE_THRESHOLD

            # Calculate time since last quote change
            time_unchanged = (now - last_quote_time).total_seconds()

            if quote_unchanged and time_unchanged >= SL_SETTLE_QUOTE_STABLE_SEC:
                return True, f"quotes stable for {time_unchanged:.0f}s"
        except (ValueError, TypeError, AttributeError) as e:
            # If parsing fails, skip this check
            pass

    # Condition 3: Catastrophic loss (override for extreme moves)
    if profit_pct_sl <= -SL_SETTLE_CATASTROPHIC_PCT:
        return True, f"catastrophic loss ({profit_pct_sl*100:.0f}%)"

    # No override conditions met
    return False, ""

def check_and_close_positions():
    """
    Main monitoring logic:
    1. Load tracked orders
    2. For each order, fetch current spread value
    3. Check profit target / stop loss / trailing stop / time-based exit
    4. Close if conditions met
    """
    orders = load_orders()

    if not orders:
        return

    now = datetime.datetime.now(ET)
    orders_modified = False

    for order in orders[:]:  # Copy list for safe removal
        order_id = order.get('order_id')
        entry_credit = float(order.get('entry_credit', 0))
        entry_time = order.get('entry_time', '')
        trailing_active = order.get('trailing_stop_active', False)
        best_profit_pct = order.get('best_profit_pct', 0)

        if entry_credit <= 0:
            log(f"Invalid entry credit for {order_id} — skipping")
            continue

        # BUGFIX (2026-02-07): Skip positions already pending closure to prevent infinite loop.
        # Previously, positions that failed broker verification would be re-evaluated every
        # 3-second cycle, triggering duplicate close attempts and duplicate balance updates.
        # Bug C: Position 25278940 accumulated 4,400+ duplicate $2820 balance updates.
        if order.get('pending_closure'):
            closure_attempts = order.get('closure_attempts', 0)
            max_closure_attempts = 5  # Max retry attempts before giving up

            if closure_attempts >= max_closure_attempts:
                log(f"⚠️  Position {order_id} ABANDONED after {closure_attempts} close attempts")
                log(f"   MANUAL INTERVENTION REQUIRED - check broker directly")
                # Send Discord alert for manual intervention
                if DISCORD_ENABLED and DISCORD_WEBHOOK_URL:
                    msg = {
                        "embeds": [{
                            "title": f"🚨 POSITION STUCK - MANUAL CLOSE REQUIRED",
                            "description": f"Order {order_id} failed to close after {closure_attempts} attempts.\n"
                                           f"**Check Tradier directly and close manually.**",
                            "color": 0xff0000,
                            "timestamp": datetime.datetime.utcnow().isoformat()
                        }]
                    }
                    _send_to_webhook(DISCORD_WEBHOOK_URL, msg, message_type="crash")
                continue

            log(f"⏳ Position {order_id} pending closure (attempt {closure_attempts}/{max_closure_attempts})")
            # Re-verify with broker
            verified = verify_position_closed_at_broker(order)

            # BUGFIX (2026-02-07): For after-hours 0DTE, force removal after 4:15 PM
            if not verified and now.hour >= 16:
                minutes_after_close = (now.hour - 16) * 60 + now.minute
                if minutes_after_close >= 15:
                    log(f"⏰ Post-market override: {order_id} expired 0DTE, forcing removal")
                    verified = True

            if verified:
                # BUGFIX (2026-02-07): Now update trade log ONLY on confirmed closure
                # This is the deferred update from when close was first attempted
                closure_exit_reason = order.get('closure_exit_reason', 'pending_closure_verified')
                closure_exit_value = order.get('closure_exit_value', 0)
                position_size = order.get('position_size', 1)
                update_trade_log(order_id, closure_exit_value, closure_exit_reason,
                                 entry_credit, entry_time, position_size)
                # Send Discord exit alert (deferred)
                closure_profit_pct = order.get('closure_profit_pct', 0)
                strategy = order.get('strategy', 'SPREAD')
                strikes = order.get('strikes', 'N/A')
                send_discord_exit_alert(order_id, strategy, strikes, entry_credit,
                                        closure_exit_value, closure_exit_reason, closure_profit_pct)
                remove_order(order_id, verified_closed_at_broker=True, reason="pending_closure_verified")
                log(f"Position {order_id} confirmed closed at broker after retry")
            else:
                order['closure_attempts'] = closure_attempts + 1
                orders_modified = True
                log(f"⚠️  Position {order_id} still open at broker (attempt {closure_attempts + 1})")
            continue

        # Get current spread value
        current_value, bid_value, ask_value = get_spread_value(order)

        if current_value is None:
            log(f"Could not get value for {order_id} — will retry")
            continue

        # CRITICAL: Check ITM risk (short strikes breached)
        try:
            # Fetch current SPX price
            spx_quote = requests.get(f"{BASE_URL}/markets/quotes",
                                    params={"symbols": "SPX"},
                                    headers=HEADERS,
                                    timeout=10).json()
            spx_price = float(spx_quote.get('quotes', {}).get('quote', {}).get('last', 0))

            if spx_price > 0:
                # BUGFIX (2026-01-10): Parse strikes string to list
                strikes_raw = order.get('strikes', [])
                if isinstance(strikes_raw, str) and '/' in strikes_raw:
                    strikes = [float(s.strip()) for s in strikes_raw.split('/')]
                elif isinstance(strikes_raw, list):
                    strikes = strikes_raw
                else:
                    strikes = []

                short_indices = order.get('short_indices', [])

                # Check if any short strikes are breached
                for idx in short_indices:
                    if idx < len(strikes):
                        short_strike = strikes[idx]
                        # For puts: ITM if SPX < strike; for calls: ITM if SPX > strike
                        # Assuming strategy contains 'put' or 'call' indicator
                        strategy = order.get('strategy', '').lower()

                        itm_depth = 0
                        if 'put' in strategy and spx_price < short_strike:
                            itm_depth = short_strike - spx_price
                        elif 'call' in strategy and spx_price > short_strike:
                            itm_depth = spx_price - short_strike

                        # Alert if ITM depth exceeds threshold (5 points = significant risk)
                        if itm_depth > 5:
                            log(f"⚠️  CRITICAL: Short strike ${short_strike} breached by ${itm_depth:.2f}!")
                            log(f"   SPX={spx_price:.2f}, Strategy={strategy}")
                            # Emergency exit condition - add to exit_reason check below
                            # This will be checked in the exit conditions
        except Exception as e:
            log(f"ITM check failed for {order_id}: {e}")

        # Calculate profit/loss percentage
        # Profit = entry_credit - current_value (we sold for X, now costs Y to buy back)
        # Use mid-price for display and profit target (optimistic)
        profit_pct = (entry_credit - current_value) / entry_credit

        # CRITICAL: For stop loss, use ask_value (worst-case closing cost)
        # This prevents late stop loss triggers when bid/ask spread widens
        profit_pct_sl = (entry_credit - ask_value) / entry_credit

        # Track best profit for trailing stop (use mid-price for profit target)
        if profit_pct > best_profit_pct:
            order['best_profit_pct'] = profit_pct
            best_profit_pct = profit_pct
            orders_modified = True

        # FIX #4 (2026-02-04): Track quote stability for smart settle period
        last_quote = order.get('last_quote_value')
        if last_quote is None or abs(current_value - last_quote) >= SL_SETTLE_QUOTE_CHANGE_THRESHOLD:
            # Quote changed significantly - reset tracking
            order['last_quote_value'] = current_value
            order['last_quote_time'] = now.isoformat()  # Store as ISO string for JSON serialization
            orders_modified = True

        # Check if trailing stop should activate
        trailing_status = ""
        trailing_stop_level = None

        if TRAILING_STOP_ENABLED and not trailing_active and profit_pct >= TRAILING_TRIGGER_PCT:
            order['trailing_stop_active'] = True
            trailing_active = True
            orders_modified = True
            log(f"*** TRAILING STOP ACTIVATED for {order_id} at {profit_pct*100:.1f}% profit ***")

        if trailing_active:
            # Calculate dynamic trailing distance - starts by locking in profit, then tightens
            # At trigger: trail_distance = trigger - lock_in (e.g., 25% - 10% = 15%)
            # As profit rises: trail_distance tightens down to minimum
            initial_trail_distance = TRAILING_TRIGGER_PCT - TRAILING_LOCK_IN_PCT
            profit_above_trigger = best_profit_pct - TRAILING_TRIGGER_PCT
            trail_distance = initial_trail_distance - (profit_above_trigger * TRAILING_TIGHTEN_RATE)
            trail_distance = max(trail_distance, TRAILING_DISTANCE_MIN)

            # Trailing stop level = best profit minus trail distance
            trailing_stop_level = best_profit_pct - trail_distance
            trailing_status = f" [TRAIL SL={trailing_stop_level*100:.0f}%]"

        # Calculate progressive TP threshold based on time elapsed
        progressive_tp_pct = PROFIT_TARGET_PCT  # Default to 50%
        hold_qualified = False

        if PROGRESSIVE_HOLD_ENABLED:
            try:
                # Parse entry time to calculate time elapsed
                if 'T' in entry_time and ('+' in entry_time or 'Z' in entry_time):
                    entry_dt = datetime.datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
                    entry_dt = entry_dt.astimezone(ET)
                else:
                    entry_dt = datetime.datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S')
                    entry_dt = ET.localize(entry_dt)

                hours_elapsed = (now - entry_dt).total_seconds() / 3600.0

                # Interpolate progressive TP threshold
                schedule_times = [t for t, _ in PROGRESSIVE_TP_SCHEDULE]
                schedule_tps = [tp for _, tp in PROGRESSIVE_TP_SCHEDULE]
                progressive_tp_pct = np.interp(hours_elapsed, schedule_times, schedule_tps)

                # Check hold qualification if profit reached 80%
                if profit_pct >= HOLD_PROFIT_THRESHOLD:
                    # Get current VIX
                    # HIGH-3 FIX (2026-01-13): Log exceptions instead of silently swallowing them
                    # FIX (2026-01-22): Use VIX symbol (not $VIX.X) for real-time quotes
                    try:
                        vix_quote = requests.get(f"{BASE_URL}/markets/quotes",
                                               params={"symbols": "VIX"},
                                               headers=HEADERS,
                                               timeout=10).json()
                        current_vix = float(vix_quote.get('quotes', {}).get('quote', {}).get('last', 99))
                    except Exception as e:
                        log(f"⚠️  HIGH-3: VIX fetch failed for hold check: {e}")
                        current_vix = 99  # If can't fetch, assume high VIX (don't hold)

                    # Calculate time left to expiration (assume 4 PM expiration)
                    expiry_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
                    hours_to_expiry = (expiry_time - now).total_seconds() / 3600.0

                    # Get entry distance from order (calculated at entry)
                    entry_distance = order.get('entry_distance', 0)

                    # Check all hold qualification rules
                    if (current_vix < HOLD_VIX_MAX and
                        hours_to_expiry >= HOLD_MIN_TIME_LEFT_HOURS and
                        entry_distance >= HOLD_MIN_ENTRY_DISTANCE):

                        hold_qualified = True
                        order['hold_to_expiry'] = True
                        orders_modified = True
                        log(f"🎯 HOLD-TO-EXPIRY QUALIFIED: {order_id} (VIX={current_vix:.1f}, hrs_left={hours_to_expiry:.1f}h, dist={entry_distance:.0f}pts)")

            except Exception as e:
                log(f"Error calculating progressive TP for {order_id}: {e}")
                progressive_tp_pct = PROFIT_TARGET_PCT

        # Check if position is marked for hold-to-expiry
        is_holding = order.get('hold_to_expiry', False)
        hold_status = " [HOLD]" if is_holding else ""

        # OTM spread: Check for 50% profit lock-in (both IC and single-sided)
        strategy = order.get('strategy', 'SPREAD')
        otm_lock_in_active = order.get('otm_lock_in_active', False)

        is_otm_strategy = strategy in ['OTM_IRON_CONDOR', 'OTM_SINGLE_SIDED']

        if is_otm_strategy and not otm_lock_in_active and profit_pct >= 0.50:
            order['otm_lock_in_active'] = True
            otm_lock_in_active = True
            orders_modified = True
            log(f"*** OTM 50% LOCK-IN ACTIVATED for {order_id} at {profit_pct*100:.1f}% profit ***")

        otm_status = ""
        if is_otm_strategy:
            if profit_pct >= 0.70:
                otm_status = " [OTM: >70%, HOLDING TO EXPIRATION]"
            elif otm_lock_in_active:
                otm_status = " [OTM: 50% locked in]"

        log(f"Order {order_id}: entry=${entry_credit:.2f} mid=${current_value:.2f} ask=${ask_value:.2f} "
            f"P/L={profit_pct*100:+.1f}% (SL_PL={profit_pct_sl*100:+.1f}%, best={best_profit_pct*100:.1f}%) "
            f"TP={progressive_tp_pct*100:.0f}%{trailing_status}{hold_status}{otm_status}")

        exit_reason = None

        # OTM spreads: Special exit logic (both IC and single-sided)
        if is_otm_strategy:
            # If profit >= 70%, hold to expiration (only exit on emergency stop)
            if profit_pct >= 0.70:
                # Check emergency stop only (with settle period protection)
                if profit_pct_sl <= -SL_EMERGENCY_PCT:
                    # FIX #3: Calculate position age for settle period
                    try:
                        if 'T' in entry_time and ('+' in entry_time or 'Z' in entry_time):
                            entry_dt = datetime.datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
                            entry_dt = entry_dt.astimezone(ET)
                        else:
                            entry_dt = datetime.datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S')
                            entry_dt = ET.localize(entry_dt)
                        position_age_sec = (now - entry_dt).total_seconds()
                    except (ValueError, TypeError, AttributeError) as e:
                        log(f"Error parsing entry time for settle check: {e}")
                        position_age_sec = 9999  # Default to old position

                    # FIX #4 (2026-02-04): Smart settle period with early exit conditions
                    should_override, override_reason = should_override_settle_period(
                        entry_credit, current_value, bid_value, ask_value,
                        profit_pct_sl, order, position_age_sec)

                    if position_age_sec < SL_ENTRY_SETTLE_SEC and not should_override:
                        settle_remaining = SL_ENTRY_SETTLE_SEC - position_age_sec
                        log(f"  ⏳ EMERGENCY stop triggered but position just entered "
                            f"({position_age_sec:.0f}s ago, settle: {settle_remaining:.0f}s remaining)")
                        log(f"     Current loss: {profit_pct_sl*100:.0f}% (allowing quotes to settle)")
                    else:
                        override_msg = f" [override: {override_reason}]" if should_override else ""
                        exit_reason = f"EMERGENCY Stop Loss ({profit_pct_sl*100:.0f}% worst-case){override_msg}"
                # Check expiration
                elif now.hour >= 16:
                    current_value = 0.0
                    exit_reason = "OTM Hold-to-Expiry: Full Credit Collected"
                # Otherwise hold (skip all other exits)

            # If 50% lock-in active but profit < 70%, protect the 50%
            elif otm_lock_in_active:
                # Exit if drops below 50% locked-in level
                if profit_pct < 0.50:
                    exit_reason = f"OTM 50% Lock-In Stop (from peak {best_profit_pct*100:.0f}%)"
                # Check emergency stop (with settle period protection)
                elif profit_pct_sl <= -SL_EMERGENCY_PCT:
                    # FIX #3: Calculate position age for settle period
                    try:
                        if 'T' in entry_time and ('+' in entry_time or 'Z' in entry_time):
                            entry_dt = datetime.datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
                            entry_dt = entry_dt.astimezone(ET)
                        else:
                            entry_dt = datetime.datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S')
                            entry_dt = ET.localize(entry_dt)
                        position_age_sec = (now - entry_dt).total_seconds()
                    except (ValueError, TypeError, AttributeError) as e:
                        log(f"Error parsing entry time for settle check: {e}")
                        position_age_sec = 9999

                    # FIX #4 (2026-02-04): Smart settle period with early exit conditions
                    should_override, override_reason = should_override_settle_period(
                        entry_credit, current_value, bid_value, ask_value,
                        profit_pct_sl, order, position_age_sec)

                    if position_age_sec < SL_ENTRY_SETTLE_SEC and not should_override:
                        settle_remaining = SL_ENTRY_SETTLE_SEC - position_age_sec
                        log(f"  ⏳ EMERGENCY stop triggered but position just entered "
                            f"({position_age_sec:.0f}s ago, settle: {settle_remaining:.0f}s remaining)")
                    else:
                        override_msg = f" [override: {override_reason}]" if should_override else ""
                        exit_reason = f"EMERGENCY Stop Loss ({profit_pct_sl*100:.0f}% worst-case){override_msg}"
                # Check expiration
                elif now.hour >= 16:
                    current_value = 0.0
                    exit_reason = "OTM Expiration: Collecting Credit"

            # Below 50% profit: Use normal stop loss logic
            else:
                # Calculate position age for grace period
                try:
                    if 'T' in entry_time and ('+' in entry_time or 'Z' in entry_time):
                        entry_dt = datetime.datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
                        entry_dt = entry_dt.astimezone(ET)
                    else:
                        entry_dt = datetime.datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S')
                        entry_dt = ET.localize(entry_dt)
                    position_age_sec = (now - entry_dt).total_seconds()
                except (ValueError, TypeError, AttributeError) as e:
                    log(f"Error parsing entry time '{entry_time}' for SL check: {e}")
                    position_age_sec = 9999

                # Check stop losses (FIX #3: Emergency stop respects settle period)
                if profit_pct_sl <= -SL_EMERGENCY_PCT:
                    # Skip emergency stop during settle period
                    # FIX #4 (2026-02-04): Smart settle period with early exit conditions
                    should_override, override_reason = should_override_settle_period(
                        entry_credit, current_value, bid_value, ask_value,
                        profit_pct_sl, order, position_age_sec)

                    if position_age_sec < SL_ENTRY_SETTLE_SEC and not should_override:
                        settle_remaining = SL_ENTRY_SETTLE_SEC - position_age_sec
                        log(f"  ⏳ EMERGENCY stop triggered but position just entered "
                            f"({position_age_sec:.0f}s ago, settle: {settle_remaining:.0f}s remaining)")
                    else:
                        override_msg = f" [override: {override_reason}]" if should_override else ""
                        exit_reason = f"EMERGENCY Stop Loss ({profit_pct_sl*100:.0f}% worst-case){override_msg}"
                elif profit_pct_sl <= -STOP_LOSS_PCT and position_age_sec >= SL_GRACE_PERIOD_SEC:
                    exit_reason = f"Stop Loss ({profit_pct_sl*100:.0f}% worst-case)"
                elif profit_pct_sl <= -STOP_LOSS_PCT:
                    grace_remaining = SL_GRACE_PERIOD_SEC - position_age_sec
                    log(f"  ⏳ SL triggered but in grace period ({grace_remaining:.0f}s remaining) - holding")
                # Check expiration
                elif now.hour >= 16:
                    current_value = 0.0
                    exit_reason = "OTM Expiration"

        # GEX spreads: Use existing logic
        elif now.hour == AUTO_CLOSE_HOUR and now.minute >= AUTO_CLOSE_MINUTE and not is_holding:
            exit_reason = "Auto-close 3:50 PM (0DTE)"

        # Check after 4 PM — assume expired worthless if still open
        elif now.hour >= 16:
            current_value = 0.0
            if is_holding:
                exit_reason = "Hold-to-Expiry: Worthless"
            else:
                exit_reason = "0DTE Expiration"

        # Check profit target (use progressive threshold)
        elif profit_pct >= progressive_tp_pct and not is_holding:
            exit_reason = f"Profit Target ({progressive_tp_pct*100:.0f}%)"

        # Check trailing stop - if activated and profit drops below trailing level
        elif trailing_active and trailing_stop_level is not None and profit_pct <= trailing_stop_level:
            exit_reason = f"Trailing Stop ({trailing_stop_level*100:.0f}% from peak {best_profit_pct*100:.0f}%)"

        # Check regular stop loss (only if trailing not active)
        # Grace period: don't trigger SL immediately, let position settle
        # Exception: emergency stop if loss exceeds 40%
        # CRITICAL: Use profit_pct_sl (based on ask price) for risk management
        elif not trailing_active and profit_pct_sl <= -STOP_LOSS_PCT:
            # Calculate position age
            # Security Fix (2026-01-04): Standardize timezone handling
            try:
                # Try ISO 8601 with timezone first (new standard format)
                if 'T' in entry_time and ('+' in entry_time or 'Z' in entry_time):
                    entry_dt = datetime.datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
                    # Convert to ET for duration calculation
                    entry_dt = entry_dt.astimezone(ET)
                else:
                    # Legacy format: assume ET timezone
                    entry_dt = datetime.datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S')
                    entry_dt = ET.localize(entry_dt)

                position_age_sec = (now - entry_dt).total_seconds()
            except (ValueError, TypeError, AttributeError) as e:
                log(f"Error parsing entry time '{entry_time}' for SL check: {e}")
                position_age_sec = 9999  # If can't parse, assume old enough

            # Emergency stop - FIX #4 (2026-02-04): Smart settle period with early exit
            if profit_pct_sl <= -SL_EMERGENCY_PCT:
                should_override, override_reason = should_override_settle_period(
                    entry_credit, current_value, bid_value, ask_value,
                    profit_pct_sl, order, position_age_sec)

                if position_age_sec < SL_ENTRY_SETTLE_SEC and not should_override:
                    settle_remaining = SL_ENTRY_SETTLE_SEC - position_age_sec
                    log(f"  ⏳ EMERGENCY stop triggered but position just entered "
                        f"({position_age_sec:.0f}s ago, settle: {settle_remaining:.0f}s remaining)")
                    log(f"     Current loss: {profit_pct_sl*100:.0f}% (allowing quotes to settle)")
                else:
                    override_msg = f" [override: {override_reason}]" if should_override else ""
                    exit_reason = f"EMERGENCY Stop Loss ({profit_pct_sl*100:.0f}% worst-case){override_msg}"
            # Normal stop loss - only after grace period
            elif position_age_sec >= SL_GRACE_PERIOD_SEC:
                exit_reason = f"Stop Loss ({profit_pct_sl*100:.0f}% worst-case)"
            else:
                # In grace period - log but don't exit yet
                grace_remaining = SL_GRACE_PERIOD_SEC - position_age_sec
                log(f"  ⏳ SL triggered but in grace period ({grace_remaining:.0f}s remaining) - holding")

        # Execute close if needed
        if exit_reason:
            log(f"CLOSING {order_id}: {exit_reason}")

            is_after_hours = now.hour >= 16
            if is_after_hours:
                # After market — just log as expired
                success = True
            else:
                success = close_spread(order)

            if success:
                # BUGFIX (2026-02-07): Verify BEFORE updating balance to prevent duplicate updates.
                # Previously, update_trade_log() was called before verification. If verification
                # failed, the position stayed in tracking, and the next loop iteration would call
                # update_trade_log() AGAIN, adding duplicate P&L to the account balance.
                # Bug C: This caused $5.8M phantom balance from 4,400+ duplicate $2820 updates.
                log(f"Verifying position {order_id} actually closed at broker...")
                time.sleep(2)  # Give broker 2 seconds to process close

                verified = verify_position_closed_at_broker(order)

                # BUGFIX (2026-02-07): For after-hours 0DTE expiration, positions may still
                # show in broker's system even though they're worthless expired options.
                # Allow removal after 4:15 PM without strict broker verification.
                if not verified and is_after_hours:
                    minutes_after_close = (now.hour - 16) * 60 + now.minute
                    if minutes_after_close >= 15:
                        log(f"⏰ Post-market override: {order_id} expired 0DTE, forcing removal "
                            f"(market closed {minutes_after_close} min ago)")
                        verified = True

                if verified:
                    # Only update trade log and balance AFTER successful verification
                    position_size = order.get('position_size', 1)
                    update_trade_log(order_id, current_value, exit_reason, entry_credit, entry_time, position_size)
                    # Send Discord exit alert
                    strategy = order.get('strategy', 'SPREAD')
                    strikes = order.get('strikes', 'N/A')
                    send_discord_exit_alert(order_id, strategy, strikes, entry_credit, current_value, exit_reason, profit_pct)
                    remove_order(order_id, verified_closed_at_broker=True, reason=exit_reason)
                    log(f"Position {order_id} closed and removed from tracking")
                else:
                    log(f"⚠️  Position {order_id} NOT VERIFIED closed at broker")
                    log(f"   Keeping in tracking for safety (will retry via pending_closure)")
                    # Mark as pending closure - the pending_closure check at top of loop
                    # will handle retries WITHOUT re-triggering balance updates
                    order['pending_closure'] = True
                    order['closure_attempt_time'] = now.isoformat()
                    order['closure_attempts'] = 1
                    order['closure_exit_reason'] = exit_reason
                    order['closure_exit_value'] = current_value
                    order['closure_profit_pct'] = profit_pct
                    orders_modified = True
            else:
                log(f"Failed to close {order_id} — will retry")

    # Save orders if trailing stop status was updated
    if orders_modified:
        save_orders(orders)

def print_startup_banner():
    """Print monitor startup information to stdout and log file."""
    if TRAILING_STOP_ENABLED:
        trailing_info = f"Trailing stop: ON (at {int(TRAILING_TRIGGER_PCT*100)}% locks {int(TRAILING_LOCK_IN_PCT*100)}%, trails to {int(TRAILING_DISTANCE_MIN*100)}% behind)"
    else:
        trailing_info = "Trailing stop: OFF"

    if PROGRESSIVE_HOLD_ENABLED:
        progressive_info = f"Progressive hold: ON (80% profit + VIX<{HOLD_VIX_MAX} + {HOLD_MIN_TIME_LEFT_HOURS}h left + {HOLD_MIN_ENTRY_DISTANCE}pts OTM)"
    else:
        progressive_info = "Progressive hold: OFF"

    banner = [
        "=" * 70,
        f"GEX POSITION MONITOR — {'LIVE' if MODE == 'REAL' else 'PAPER'} MODE",
        f"Account: {TRADIER_ACCOUNT_ID}",
        f"Orders file: {ORDERS_FILE}",
        f"Log file: {LOG_FILE}",
        f"Poll interval: {POLL_INTERVAL}s",
        f"Profit target: {PROFIT_TARGET_PCT*100:.0f}% (progressive TP schedule)",
        f"Stop loss: {STOP_LOSS_PCT*100:.0f}% (after {SL_GRACE_PERIOD_SEC}s grace, emergency at {SL_EMERGENCY_PCT*100:.0f}%)",
        trailing_info,
        progressive_info,
        f"Auto-close: {AUTO_CLOSE_HOUR}:{AUTO_CLOSE_MINUTE:02d} ET",
        "=" * 70
    ]
    for line in banner:
        print(line)
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')

# ============================================================================
#                              MAIN LOOP
# ============================================================================

def get_todays_trades():
    """Read today's trades from the trade log CSV."""
    trades = []
    today_str = datetime.datetime.now(ET).strftime('%Y-%m-%d')

    if not os.path.exists(TRADE_LOG_FILE):
        return trades

    try:
        with open(TRADE_LOG_FILE, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('Timestamp_ET', '').startswith(today_str) and row.get('P/L_$'):
                    try:
                        pl_dollar = float(row['P/L_$'].replace('$', '').replace('+', ''))
                        trades.append({'pl_dollar': pl_dollar})
                    except (ValueError, TypeError, AttributeError) as e:
                        log(f"Error parsing P/L from row: {e}")
                        pass
    except Exception as e:
        log(f"Error reading trade log: {e}")

    return trades

def reconcile_positions_with_broker():
    """
    CRITICAL SAFETY (2026-02-04): Reconcile tracking with actual broker positions.

    Runs every 5 minutes to catch:
    1. Positions open at broker but not tracked (orphaned) - ADD TO TRACKING
    2. Positions tracked but closed at broker (stale) - REMOVE FROM TRACKING
    3. Positions marked "pending_closure" - RETRY VERIFICATION

    This prevents the $1,822 loss scenario where positions were silently abandoned.
    """
    log(f"🔄 RECONCILIATION: Verifying tracking matches broker reality...")

    try:
        # Get actual positions from Tradier
        r = requests.get(
            f"{BASE_URL}/accounts/{TRADIER_ACCOUNT_ID}/positions",
            headers=HEADERS,
            timeout=10
        )

        if r.status_code != 200:
            log(f"⚠️  Reconciliation failed: API error HTTP {r.status_code}")
            return

        data = r.json()
        positions = data.get('positions')

        broker_positions = []
        if positions and positions != 'null':
            position_list = positions.get('position', [])
            if not isinstance(position_list, list):
                position_list = [position_list]
            broker_positions = position_list

        # BUGFIX (2026-02-06): Filter to option positions ONLY
        # Non-option positions (ETF holdings like TDAQ, TSPY, QDTE) were causing
        # false-positive orphan warnings every 5 minutes for 6+ hours.
        # Option symbols start with known roots (SPXW, NDXP); equity symbols do not.
        OPTION_ROOTS = ('SPXW', 'NDXP')
        option_positions = [p for p in broker_positions if p.get('symbol', '').startswith(OPTION_ROOTS)]
        equity_positions = [p for p in broker_positions if not p.get('symbol', '').startswith(OPTION_ROOTS)]

        if equity_positions:
            equity_syms = [p.get('symbol') for p in equity_positions]
            log(f"ℹ️  Ignoring {len(equity_positions)} non-option positions: {', '.join(equity_syms)}")

        broker_symbols = set(p.get('symbol') for p in option_positions)

        # Get tracked positions
        orders = load_orders()
        tracked_symbols = set()
        for order in orders:
            symbols = order.get('option_symbols', [])
            tracked_symbols.update(symbols)

        # Check for orphaned positions (at broker but not tracked)
        orphaned = broker_symbols - tracked_symbols
        if orphaned:
            log(f"🚨 CRITICAL: Found {len(orphaned)} ORPHANED option positions at broker!")
            for symbol in orphaned:
                log(f"   - {symbol} (open at broker, NOT TRACKED)")
            log(f"   These positions have NO STOP LOSS PROTECTION!")
            log(f"   Manual intervention required or add orphan auto-tracking")

        # Check for stale tracking (tracked but closed at broker)
        orders_modified = False
        for order in orders[:]:
            order_symbols = set(order.get('option_symbols', []))
            still_open = order_symbols & broker_symbols

            if not still_open:
                # Position is tracked but closed at broker
                order_id = order.get('order_id')
                log(f"✅ Position {order_id} verified CLOSED at broker (cleaning stale tracking)")
                remove_order(order_id, verified_closed_at_broker=True, reason="reconciliation_cleanup")
                orders_modified = True

            # Check pending closures
            if order.get('pending_closure'):
                order_id = order.get('order_id')
                log(f"🔄 Retrying verification for pending closure: {order_id}")
                verified = verify_position_closed_at_broker(order)
                if verified:
                    remove_order(order_id, verified_closed_at_broker=True, reason="pending_closure_verified")
                    orders_modified = True
                else:
                    log(f"⚠️  Position {order_id} still open at broker after close attempt")

        if not orphaned and not orders_modified:
            log(f"✅ Reconciliation complete: tracking matches broker ({len(option_positions)} option positions, {len(equity_positions)} equity positions ignored)")

    except Exception as e:
        log(f"⚠️  Reconciliation error: {e}")
        import traceback
        traceback.print_exc()

def reconcile_orphaned_positions():
    """
    BUGFIX (2026-01-20): Reconcile orphaned positions at startup.

    Checks for option positions in Tradier account that aren't tracked in orders file.
    Adds them to tracking with emergency stop loss protection.

    This prevents scenarios where scalper crashes after placing order but before
    writing to tracking file, leaving position without stop loss protection.
    """
    log("=" * 70)
    log("POSITION RECONCILIATION CHECK")
    log("=" * 70)

    try:
        # Get current positions from Tradier
        positions = get_positions()
        if positions is None:
            log("⚠️  Could not fetch positions from Tradier - skipping reconciliation")
            return

        # Filter to option positions only (not underlying stock)
        option_positions = []
        for pos in positions:
            symbol = pos.get('symbol', '')
            # Option symbols have format like SPXW260120P06850000 or NDXP260120P25150000
            if symbol and (symbol.startswith('SPXW') or symbol.startswith('NDXP')):
                option_positions.append(pos)

        if not option_positions:
            log("✓ No open option positions found in Tradier")
            return

        log(f"Found {len(option_positions)} open option position(s) in Tradier:")
        for pos in option_positions:
            log(f"  - {pos.get('symbol')} qty={pos.get('quantity')}")

        # Load tracked orders
        tracked_orders = load_orders()
        tracked_symbols = set()
        for order in tracked_orders:
            for sym in order.get('option_symbols', []):
                tracked_symbols.add(sym)

        log(f"Currently tracking {len(tracked_orders)} order(s) with {len(tracked_symbols)} option legs")

        # Find orphaned positions (in Tradier but not tracked)
        orphaned = []
        for pos in option_positions:
            sym = pos.get('symbol')
            if sym not in tracked_symbols:
                orphaned.append(pos)

        if not orphaned:
            log("✓ All option positions are being tracked - no orphans detected")
            return

        # CRITICAL: Orphaned positions detected!
        log("=" * 70)
        log(f"⚠️  CRITICAL: {len(orphaned)} ORPHANED POSITION(S) DETECTED!")
        log("=" * 70)

        for pos in orphaned:
            sym = pos.get('symbol')
            qty = float(pos.get('quantity', 0))
            cost = float(pos.get('cost_basis', 0))
            log(f"  ⚠️  {sym}: qty={qty:.0f}, cost=${abs(cost):.2f}")

        log("")
        log("These positions were likely created by scalper crash before tracking save.")
        log("Adding emergency tracking with conservative stop loss...")
        log("")

        # Group orphaned legs into spreads (2-leg or 4-leg)
        # For simplicity, assume they're all part of one spread
        if len(orphaned) == 2 or len(orphaned) == 4:
            # Create emergency tracking order
            symbols = [pos.get('symbol') for pos in orphaned]
            quantities = [float(pos.get('quantity', 0)) for pos in orphaned]

            # Identify shorts (negative quantity) vs longs (positive quantity)
            short_indices = [i for i, qty in enumerate(quantities) if qty < 0]

            # Estimate entry credit from position costs
            # For a credit spread: short premium - long premium = credit
            total_credit = 0.0
            for i, pos in enumerate(orphaned):
                qty = abs(float(pos.get('quantity', 0)))
                cost = abs(float(pos.get('cost_basis', 0)))
                price_per_contract = cost / (qty * 100) if qty > 0 else 0

                if i in short_indices:
                    total_credit += price_per_contract  # Short leg adds credit
                else:
                    total_credit -= price_per_contract  # Long leg subtracts credit

            total_credit = abs(total_credit)

            # Extract strikes from symbols (e.g., SPXW260120P06850000 -> 6850)
            strikes = []
            for sym in symbols:
                # Last 8 digits are strike * 1000 (e.g., 06850000 = 6850.00)
                if len(sym) >= 8:
                    strike_str = sym[-8:]
                    try:
                        strike = float(strike_str) / 1000
                        strikes.append(int(strike))
                    except:
                        strikes.append(0)

            # Determine strategy from number of legs
            if len(orphaned) == 4:
                strategy = "IC"
            elif quantities[0] < 0:  # Short first leg
                # Check if PUT or CALL from symbol
                if 'P' in symbols[0]:
                    strategy = "PUT"
                else:
                    strategy = "CALL"
            else:
                strategy = "SPREAD"

            # Create emergency order tracking
            emergency_order = {
                "order_id": f"ORPHAN_{int(time.time())}",
                "entry_credit": total_credit,
                "entry_time": datetime.datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S'),
                "strategy": strategy,
                "strikes": "/".join(map(str, strikes)),
                "direction": "UNKNOWN",
                "confidence": "EMERGENCY",
                "option_symbols": symbols,
                "short_indices": short_indices,
                "tp_price": total_credit * 0.5,  # 50% TP
                "sl_price": total_credit * 1.15,  # 15% SL
                "trailing_stop_active": False,
                "best_profit_pct": 0,
                "entry_distance": 0,
                "index_entry": 0,
                "index_code": "SPX" if symbols[0].startswith('SPXW') else "NDX",
                "vix_entry": 0,
                "position_size": int(abs(quantities[0])),
                "account_balance": 0,
                "orphan_recovery": True  # Flag for identification
            }

            # Add to tracking
            tracked_orders.append(emergency_order)
            save_orders(tracked_orders)

            log(f"✓ Emergency tracking added for order {emergency_order['order_id']}")
            log(f"  Strategy: {strategy}")
            log(f"  Strikes: {'/'.join(map(str, strikes))}")
            log(f"  Entry Credit (estimated): ${total_credit:.2f}")
            log(f"  Stop Loss: ${emergency_order['sl_price']:.2f} (15%)")
            log(f"  Profit Target: ${emergency_order['tp_price']:.2f} (50%)")
            log("")
            log("⚠️  STOP LOSS PROTECTION NOW ACTIVE ⚠️")

            # Send Discord alert
            if DISCORD_ENABLED and DISCORD_WEBHOOK_URL:
                msg = {
                    "embeds": [{
                        "title": "⚠️ ORPHANED POSITION RECOVERED",
                        "description": f"Found untracked {strategy} spread in Tradier account.\n**Emergency stop loss protection activated.**",
                        "color": 0xff9900,  # Orange
                        "fields": [
                            {"name": "Strikes", "value": "/".join(map(str, strikes)), "inline": True},
                            {"name": "Entry Credit", "value": f"${total_credit:.2f} (estimated)", "inline": True},
                            {"name": "Stop Loss", "value": f"${emergency_order['sl_price']:.2f} (15%)", "inline": True},
                        ],
                        "footer": {"text": f"{MODE} mode - Orphan recovery activated"},
                        "timestamp": datetime.datetime.utcnow().isoformat()
                    }]
                }
                _send_to_webhook(DISCORD_WEBHOOK_URL, msg, message_type="crash")
        else:
            log(f"⚠️  Cannot auto-recover: Expected 2 or 4 legs, found {len(orphaned)}")
            log("⚠️  MANUAL INTERVENTION REQUIRED - Close positions manually in Tradier")

    except Exception as e:
        log(f"Error during position reconciliation: {e}")
        import traceback
        traceback.print_exc()

    log("=" * 70)
    log("")

def main():
    print_startup_banner()
    log("Monitor started — watching for positions...")

    # BUGFIX (2026-01-20): Check for orphaned positions at startup
    reconcile_orphaned_positions()

    daily_summary_sent = False
    heartbeat_counter = 0
    reconciliation_counter = 0
    HEARTBEAT_INTERVAL = 100  # Send heartbeat every 100 cycles (5 min at 3s poll)
    RECONCILIATION_INTERVAL = 100  # Reconcile every 100 cycles (5 min at 3s poll)

    while True:
        try:
            now = datetime.datetime.now(ET)

            # Send heartbeat every N cycles (24/7 monitoring)
            heartbeat_counter += 1
            if heartbeat_counter >= HEARTBEAT_INTERVAL:
                send_heartbeat()
                heartbeat_counter = 0

            # CRITICAL SAFETY (2026-02-04): Reconcile with broker every 5 minutes
            # Catches orphaned positions and stale tracking (prevents $1,822 loss scenario)
            reconciliation_counter += 1
            if reconciliation_counter >= RECONCILIATION_INTERVAL:
                reconcile_positions_with_broker()
                reconciliation_counter = 0

            # Check if we should send daily summary (4:05 PM, after market close)
            if now.hour == 16 and now.minute >= 5 and now.minute < 10 and not daily_summary_sent:
                trades_today = get_todays_trades()
                if trades_today:
                    send_discord_daily_summary(trades_today)
                    log(f"Daily summary sent: {len(trades_today)} trades")
                daily_summary_sent = True

            # Reset summary flag at midnight
            if now.hour == 0:
                daily_summary_sent = False

            check_and_close_positions()
        except KeyboardInterrupt:
            log("Monitor stopped by user")
            break
        except Exception as e:
            log(f"Error in monitor loop: {e}")
            import traceback
            traceback.print_exc()

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
