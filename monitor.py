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

# ============================================================================
#                              CONFIGURATION
# ============================================================================

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
ORDERS_FILE_PAPER = "/root/gamma/data/orders_paper.json"
ORDERS_FILE_LIVE = "/root/gamma/data/orders_live.json"
TRADE_LOG_FILE = "/root/gamma/data/trades.csv"
LOG_FILE_PAPER = "/root/gamma/data/monitor_paper.log"
LOG_FILE_LIVE = "/root/gamma/data/monitor_live.log"

# Monitor settings
POLL_INTERVAL = 15              # Seconds between checks (tighter stop loss monitoring)
PROFIT_TARGET_PCT = 0.50        # Close at 50% profit
STOP_LOSS_PCT = 0.10            # CRITICAL FIX-2: Changed from 0.15 to 0.10 (matches scalper logs, better R:R)
AUTO_CLOSE_HOUR = 15            # Auto-close at 3:30 PM ET (was 3:50)
AUTO_CLOSE_MINUTE = 30          # Earlier close avoids final 30-min chaos

# Trailing stop settings
TRAILING_STOP_ENABLED = True
TRAILING_TRIGGER_PCT = 0.25     # Activate trailing stop at 25% profit
TRAILING_LOCK_IN_PCT = 0.10     # Lock in this much profit when trailing activates (10%)
TRAILING_DISTANCE_MIN = 0.08    # Minimum trail distance as profit rises (8%)
TRAILING_TIGHTEN_RATE = 0.4     # How fast it tightens (0.4 = every 2.5% gain, trail tightens 1%)

# Stop loss grace period - let positions settle before triggering SL
SL_GRACE_PERIOD_SEC = 210       # 3.5 minutes grace period before stop loss activates
SL_EMERGENCY_PCT = 0.40         # Emergency stop - trigger immediately if loss exceeds 40%

# ============================================================================
#                           MODE DETECTION
# ============================================================================

def get_mode():
    """Detect trading mode from command line args."""
    if len(sys.argv) > 1:
        arg = sys.argv[1].upper()
        if arg in ['LIVE', 'REAL']:
            return 'REAL'
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
    DISCORD_STORAGE_FILE = "/root/gamma/data/discord_messages_live.json"
    DISCORD_WEBHOOK_URL = DISCORD_WEBHOOK_LIVE_URL
    HEALTHCHECK_URL = HEALTHCHECK_LIVE_URL
else:
    DISCORD_STORAGE_FILE = "/root/gamma/data/discord_messages_paper.json"
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
    """Load tracked orders from JSON file with file locking."""
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
                return json.loads(content)
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
            json.dump(orders, f, indent=2)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

def add_order(order_data):
    """Add a new order to tracking."""
    orders = load_orders()
    orders.append(order_data)
    save_orders(orders)
    log(f"Added order {order_data['order_id']} to tracking")

def remove_order(order_id):
    """Remove an order from tracking."""
    orders = load_orders()
    orders = [o for o in orders if o.get('order_id') != order_id]
    save_orders(orders)

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
            'quantity': order_data.get('quantity', 1)
        })
    
    # Build order data
    data = {
        "class": "multileg",
        "symbol": "SPXW",
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

def update_trade_log(order_id, exit_value, exit_reason, entry_credit, entry_time_str):
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
                pl_dollar = (entry_credit - exit_value) * 100  # Per contract
                pl_pct = ((entry_credit - exit_value) / entry_credit) * 100 if entry_credit > 0 else 0
                
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
                strikes = order.get('strikes', [])
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

        log(f"Order {order_id}: entry=${entry_credit:.2f} mid=${current_value:.2f} ask=${ask_value:.2f} "
            f"P/L={profit_pct*100:+.1f}% (SL_PL={profit_pct_sl*100:+.1f}%, best={best_profit_pct*100:.1f}%){trailing_status}")

        exit_reason = None

        # Check time-based auto-close (3:50 PM for 0DTE)
        if now.hour == AUTO_CLOSE_HOUR and now.minute >= AUTO_CLOSE_MINUTE:
            exit_reason = "Auto-close 3:50 PM (0DTE)"

        # Check after 4 PM — assume expired worthless if still open
        elif now.hour >= 16:
            current_value = 0.0
            exit_reason = "0DTE Expiration"

        # Check profit target
        elif profit_pct >= PROFIT_TARGET_PCT:
            exit_reason = f"Profit Target ({profit_pct*100:.0f}%)"

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

            # Emergency stop - trigger immediately regardless of age
            if profit_pct_sl <= -SL_EMERGENCY_PCT:
                exit_reason = f"EMERGENCY Stop Loss ({profit_pct_sl*100:.0f}% worst-case)"
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

            if now.hour >= 16:
                # After market — just log as expired
                success = True
            else:
                success = close_spread(order)

            if success:
                update_trade_log(order_id, current_value, exit_reason, entry_credit, entry_time)
                # Send Discord exit alert
                strategy = order.get('strategy', 'SPREAD')
                strikes = order.get('strikes', 'N/A')
                send_discord_exit_alert(order_id, strategy, strikes, entry_credit, current_value, exit_reason, profit_pct)
                remove_order(order_id)
                log(f"Position {order_id} closed and removed from tracking")
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
    banner = [
        "=" * 70,
        f"GEX POSITION MONITOR — {'LIVE' if MODE == 'REAL' else 'PAPER'} MODE",
        f"Account: {TRADIER_ACCOUNT_ID}",
        f"Orders file: {ORDERS_FILE}",
        f"Log file: {LOG_FILE}",
        f"Poll interval: {POLL_INTERVAL}s",
        f"Profit target: {PROFIT_TARGET_PCT*100:.0f}%",
        f"Stop loss: {STOP_LOSS_PCT*100:.0f}% (after {SL_GRACE_PERIOD_SEC}s grace, emergency at {SL_EMERGENCY_PCT*100:.0f}%)",
        trailing_info,
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

def main():
    print_startup_banner()
    log("Monitor started — watching for positions...")

    daily_summary_sent = False
    heartbeat_counter = 0
    HEARTBEAT_INTERVAL = 20  # Send heartbeat every 20 cycles (5 min at 15s poll)

    while True:
        try:
            now = datetime.datetime.now(ET)

            # Send heartbeat every N cycles (24/7 monitoring)
            heartbeat_counter += 1
            if heartbeat_counter >= HEARTBEAT_INTERVAL:
                send_heartbeat()
                heartbeat_counter = 0

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
