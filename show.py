#!/usr/bin/env python3
"""
show.py — Display current option positions and P/L status

ARCHITECTURE: Broker API is authoritative source for open positions
- Positions are queried directly from Tradier broker API
- Orders tracking file is used only for metadata (TP/SL, confidence, trailing stop)
- Ensures display always reflects true account state, even if tracking out of sync
- Prevents "phantom" positions from being displayed if reconciliation recovered them

Usage:
  python show.py                    # Show paper account (from broker API)
  python show.py LIVE               # Show live account (from broker API)
  python show.py ALL                # Show both accounts
  python show.py --history 7        # Show last 7 days of closed trades
  python show.py --history 30       # Show last 30 days
  python show.py --history all      # Show all history
  python show.py LIVE --history 7   # Combine account + history options
"""

import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")

import sys
import argparse
import requests
from collections import defaultdict
from datetime import datetime
import pytz
import yfinance as yf
import math

from config import (PAPER_ACCOUNT_ID, LIVE_ACCOUNT_ID,
                    TRADIER_SANDBOX_KEY, TRADIER_LIVE_KEY)

ET = pytz.timezone('US/Eastern')
LIVE_URL = "https://api.tradier.com/v1"
LIVE_HEADERS = {"Accept": "application/json", "Authorization": f"Bearer {TRADIER_LIVE_KEY}"}


def get_spx_price():
    """Fetch SPX price directly from Tradier LIVE API."""
    try:
        r = requests.get(f"{LIVE_URL}/markets/quotes", headers=LIVE_HEADERS,
                        params={"symbols": "SPX"}, timeout=10)
        data = r.json()
        q = data.get("quotes", {}).get("quote")
        if q:
            price = q.get("last") or q.get("bid") or q.get("ask")
            if price and float(price) > 1000:
                return float(price)
    except Exception as e:
        pass
    # Fallback to SPY * 10
    try:
        r = requests.get(f"{LIVE_URL}/markets/quotes", headers=LIVE_HEADERS,
                        params={"symbols": "SPY"}, timeout=10)
        data = r.json()
        q = data.get("quotes", {}).get("quote")
        if q:
            spy = float(q.get("last") or q.get("bid") or q.get("ask"))
            return spy * 10
    except Exception as e:
        pass
    return None


def get_ndx_price():
    """Fetch NDX price directly from Tradier LIVE API."""
    try:
        r = requests.get(f"{LIVE_URL}/markets/quotes", headers=LIVE_HEADERS,
                        params={"symbols": "NDX"}, timeout=10)
        data = r.json()
        q = data.get("quotes", {}).get("quote")
        if q:
            price = q.get("last") or q.get("bid") or q.get("ask")
            if price and float(price) > 1000:
                return float(price)
    except Exception as e:
        pass
    # Fallback to QQQ * 50 (approximate multiplier)
    try:
        r = requests.get(f"{LIVE_URL}/markets/quotes", headers=LIVE_HEADERS,
                        params={"symbols": "QQQ"}, timeout=10)
        data = r.json()
        q = data.get("quotes", {}).get("quote")
        if q:
            qqq = float(q.get("last") or q.get("bid") or q.get("ask"))
            return qqq * 50  # NDX is roughly 50x QQQ
    except Exception as e:
        pass
    return None


def get_vix():
    """Fetch VIX - try Tradier first, then yfinance."""
    # Try Tradier
    try:
        r = requests.get(f"{LIVE_URL}/markets/quotes", headers=LIVE_HEADERS,
                        params={"symbols": "VIX"}, timeout=10)
        data = r.json()
        q = data.get("quotes", {}).get("quote")
        if q and q.get("last"):
            return float(q["last"])
    except Exception as e:
        pass
    # Fallback to yfinance
    try:
        vix_data = yf.download("^VIX", period="1d", progress=False)
        if not vix_data.empty:
            close = vix_data['Close'].iloc[-1]
            if hasattr(close, 'iloc'):
                close = close.iloc[0]
            return float(close)
    except Exception as e:
        pass
    return None


def calculate_real_gex_pin(index_price, symbol="SPX", search_range=50):
    """Calculate real GEX pin from options open interest and gamma data.

    Args:
        index_price: Current price of the underlying
        symbol: Index symbol ("SPX" or "NDX")
        search_range: How many points around current price to search for pin
    """
    from datetime import date

    try:
        today = date.today().strftime("%Y-%m-%d")

        # Get options chain with greeks
        r = requests.get(f"{LIVE_URL}/markets/options/chains", headers=LIVE_HEADERS,
            params={"symbol": symbol, "expiration": today, "greeks": "true"}, timeout=15)

        if r.status_code != 200:
            return None

        options = r.json().get("options", {})
        if not options:
            return None

        options = options.get("option", [])
        if not options:
            return None

        # Calculate GEX by strike
        gex_by_strike = defaultdict(float)

        for opt in options:
            strike = opt.get('strike', 0)
            oi = opt.get('open_interest', 0)
            greeks = opt.get('greeks', {})
            gamma = greeks.get('gamma', 0) if greeks else 0
            opt_type = opt.get('option_type', '')

            if oi == 0 or gamma == 0:
                continue

            gex = gamma * oi * 100 * (index_price ** 2)

            if opt_type == 'call':
                gex_by_strike[strike] += gex
            else:
                gex_by_strike[strike] -= gex

        if not gex_by_strike:
            return None

        # Find strikes near current price with highest positive GEX
        near_strikes = [(s, g) for s, g in gex_by_strike.items() if abs(s - index_price) < search_range and g > 0]

        if near_strikes:
            pin_strike, _ = max(near_strikes, key=lambda x: x[1])
            return pin_strike
        else:
            all_near = [(s, g) for s, g in gex_by_strike.items() if abs(s - index_price) < search_range]
            if all_near:
                pin_strike, _ = max(all_near, key=lambda x: abs(x[1]))
                return pin_strike

        return None

    except Exception as e:
        return None


def get_gex_pin(index_price, symbol="SPX", cache_duration_sec=1800):
    """Get GEX pin level - cached to file to avoid flip-flopping.

    Args:
        index_price: Current index price (SPX or NDX)
        symbol: Index symbol ("SPX" or "NDX")
        cache_duration_sec: Cache validity duration in seconds (default 1800 = 30 min)
                           Set to 0 to disable caching (always recalculate)
    """
    import time
    import json

    CACHE_FILE = f'/tmp/gex_pin_cache_{symbol.lower()}.json'

    now = time.time()

    # Try to read from cache (skip if caching disabled)
    if cache_duration_sec > 0:
        try:
            with open(CACHE_FILE, 'r') as f:
                cache = json.load(f)
                if (now - cache.get('timestamp', 0)) < cache_duration_sec:
                    return cache['value']
        except Exception as e:
            pass

    # Calculate real GEX pin from options data
    # Use appropriate search range: SPX uses 50 pts, NDX uses 200 pts (higher priced)
    search_range = 200 if symbol == "NDX" else 50
    pin = calculate_real_gex_pin(index_price, symbol=symbol, search_range=search_range)

    if pin is None:
        return None  # No fallback - return None if GEX unavailable

    # Save to cache
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump({'value': pin, 'timestamp': now}, f)
    except Exception as e:
        pass

    return pin


def get_intraday_prices(symbol="SPY", multiplier=10):
    """Fetch intraday prices for sparkline chart.

    Args:
        symbol: ETF to fetch ("SPY" for SPX, "QQQ" for NDX)
        multiplier: Multiplier to convert ETF to index (10 for SPX, 50 for NDX)
    """
    try:
        # Get today's 5-min bars (suppress warnings)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            data = yf.download(symbol, period="1d", interval="5m", progress=False)
        if data.empty:
            return []
        # Convert to index and return as list
        closes = data['Close'].values
        # Handle nested array from yfinance
        if hasattr(closes[0], '__iter__'):
            closes = [float(c[0]) for c in closes]
        else:
            closes = [float(c) for c in closes]
        # Convert ETF to index
        return [round(p * multiplier) for p in closes]
    except Exception as e:
        return []


def render_sparkline(prices, width=50, height=5, gex_pin=None, min_p=None, max_p=None, far_threshold=10):
    """Render a compact ASCII sparkline chart with time vertical, price horizontal.

    Args:
        prices: List of prices to plot
        width: Chart width in characters
        height: Number of time points to show
        gex_pin: GEX pin level to mark on chart
        min_p: Min price for chart range (calculated if None)
        max_p: Max price for chart range (calculated if None)
        far_threshold: Distance from pin to color red (10 for SPX, 40 for NDX)
    """
    if not prices or len(prices) < 2:
        return []

    # Use last N prices to fit height (time is vertical now)
    prices = prices[-height:]

    # Use provided min/max or calculate from prices
    if min_p is None:
        min_p = min(prices)
    if max_p is None:
        max_p = max(prices)
    price_range = max_p - min_p if max_p != min_p else 1

    # Calculate pin position in chart width
    pin_pos = None
    if gex_pin and min_p <= gex_pin <= max_p:
        pin_pos = int((gex_pin - min_p) / price_range * (width - 1))

    # Build chart rows (each row is a time point)
    rows = []
    for i, price in enumerate(prices):
        is_last = (i == len(prices) - 1)
        # Calculate horizontal position for this price
        pos = int((price - min_p) / price_range * (width - 1))

        line = ""
        for x in range(width):
            if x == pos:
                if is_last:
                    line += "\033[33m●\033[0m"  # Yellow dot for current
                elif price > gex_pin + far_threshold or price < gex_pin - far_threshold:
                    line += "\033[31m●\033[0m"  # Red when far from pin
                else:
                    line += "\033[32m●\033[0m"  # Green when near pin
            elif pin_pos is not None and x == pin_pos:
                line += "\033[90m│\033[0m"  # Gray line for GEX pin
            else:
                line += "─"
        rows.append(line)

    return rows


def show_market_banner():
    """Display current market data banner with both SPX and NDX charts."""
    spx_raw = get_spx_price()
    ndx_raw = get_ndx_price()
    vix = get_vix()

    now_et = datetime.now(ET)

    print(f"\n{'='*70}")
    print(f"  GAMMA SCALPER STATUS — {now_et.strftime('%Y-%m-%d %H:%M:%S')} ET")
    print(f"{'='*70}")

    # Display SPX chart
    if spx_raw:
        spx = round(spx_raw)
        gex_pin_spx = get_gex_pin(spx, symbol="SPX")
        distance_spx = (spx - gex_pin_spx) if gex_pin_spx else None

        print(f"\n  SPX CHART (SPY-based):")

        # Get intraday prices for sparkline
        prices_spx = get_intraday_prices(symbol="SPY", multiplier=10)
        if prices_spx and gex_pin_spx:
            chart_prices = prices_spx[-5:]  # Last 5 data points for compact view
            # Include GEX pin in range so it's always visible
            min_p = min(min(chart_prices), gex_pin_spx - 5)
            max_p = max(max(chart_prices), gex_pin_spx + 5)
            sparkline = render_sparkline(prices_spx, width=50, height=5, gex_pin=gex_pin_spx, min_p=min_p, max_p=max_p, far_threshold=10)

            # Calculate pin position for header (match chart width of 50)
            price_range = max_p - min_p
            pin_pos = int((gex_pin_spx - min_p) / price_range * 49) if price_range > 0 else 24

            # Print header with price range and pin marker (build exact 50-char string)
            header_line = " " * pin_pos + "▼" + " " * (49 - pin_pos)
            print(f"        {min_p:<6}{' '*18}PIN{' '*18}{max_p:>6}")
            print(f"        |{header_line}|")

            # Print sparkline rows (time going down)
            for i, row in enumerate(sparkline):
                if i == len(sparkline) - 1:
                    print(f"  NOW → |{row}| ●={spx}")
                else:
                    print(f"        |{row}|")

        # Display SPX data line
        if gex_pin_spx and distance_spx is not None:
            # Color distance based on magnitude (SPX: 10/25 pts)
            if abs(distance_spx) <= 10:
                dist_color = "\033[32m"  # Green - near pin
            elif abs(distance_spx) <= 25:
                dist_color = "\033[33m"  # Yellow - moderate
            else:
                dist_color = "\033[31m"  # Red - far from pin
            print(f"  SPX: {spx}  |  GEX Pin: {int(gex_pin_spx)}  |  Distance: {dist_color}{int(distance_spx):+d}\033[0m")
        else:
            print(f"  SPX: {spx}  |  GEX Pin: \033[31mUNAVAILABLE\033[0m")

    # Display NDX chart
    if ndx_raw:
        ndx = round(ndx_raw)
        gex_pin_ndx = get_gex_pin(ndx, symbol="NDX")
        distance_ndx = (ndx - gex_pin_ndx) if gex_pin_ndx else None

        print(f"\n  NDX CHART (QQQ-based):")

        # Get intraday prices for sparkline
        prices_ndx = get_intraday_prices(symbol="QQQ", multiplier=50)
        if prices_ndx and gex_pin_ndx:
            chart_prices = prices_ndx[-5:]  # Last 5 data points for compact view
            # Include GEX pin in range so it's always visible
            min_p = min(min(chart_prices), gex_pin_ndx - 20)
            max_p = max(max(chart_prices), gex_pin_ndx + 20)
            sparkline = render_sparkline(prices_ndx, width=50, height=5, gex_pin=gex_pin_ndx, min_p=min_p, max_p=max_p, far_threshold=40)

            # Calculate pin position for header (match chart width of 50)
            price_range = max_p - min_p
            pin_pos = int((gex_pin_ndx - min_p) / price_range * 49) if price_range > 0 else 24

            # Print header with price range and pin marker (build exact 50-char string)
            header_line = " " * pin_pos + "▼" + " " * (49 - pin_pos)
            print(f"        {min_p:<6}{' '*18}PIN{' '*18}{max_p:>6}")
            print(f"        |{header_line}|")

            # Print sparkline rows (time going down)
            for i, row in enumerate(sparkline):
                if i == len(sparkline) - 1:
                    print(f"  NOW → |{row}| ●={ndx}")
                else:
                    print(f"        |{row}|")

        # Display NDX data line
        if gex_pin_ndx and distance_ndx is not None:
            # Color distance based on magnitude (NDX: 40/100 pts - scaled for higher price)
            if abs(distance_ndx) <= 40:
                dist_color = "\033[32m"  # Green - near pin
            elif abs(distance_ndx) <= 100:
                dist_color = "\033[33m"  # Yellow - moderate
            else:
                dist_color = "\033[31m"  # Red - far from pin
            print(f"  NDX: {ndx}  |  GEX Pin: {int(gex_pin_ndx)}  |  Distance: {dist_color}{int(distance_ndx):+d}\033[0m")
        else:
            print(f"  NDX: {ndx}  |  GEX Pin: \033[31mUNAVAILABLE\033[0m")

    # Display VIX and expected moves for both indices
    if vix and spx_raw and ndx_raw:
        hours_left = 2
        expected_move_spx = spx * (vix/100) * math.sqrt(hours_left / (252 * 6.5))
        expected_move_ndx = ndx * (vix/100) * math.sqrt(hours_left / (252 * 6.5))
        print(f"\n  VIX: {vix:.2f}  |  Expected 2hr Move: ±{expected_move_spx:.1f} pts (SPX), ±{expected_move_ndx:.1f} pts (NDX)")
    elif vix:
        print(f"\n  VIX: {vix:.2f}")

    if not spx_raw and not ndx_raw:
        print(f"  Market data unavailable")

def get_positions(account_id, api_key, base_url):
    """Fetch positions from Tradier."""
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    try:
        r = requests.get(f"{base_url}/accounts/{account_id}/positions",
                        headers=headers, timeout=10)
        data = r.json()
        positions = data.get("positions", {})
        if positions == "null" or not positions:
            return []
        pos_list = positions.get("position", [])
        if isinstance(pos_list, dict):
            pos_list = [pos_list]
        return pos_list
    except Exception as e:
        print(f"Error fetching positions: {e}")
        return []

def get_quotes(symbols, api_key, base_url):
    """Fetch quotes for symbols."""
    if not symbols:
        return {}
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    try:
        r = requests.get(f"{base_url}/markets/quotes",
                        headers=headers,
                        params={"symbols": ",".join(symbols)},
                        timeout=10)
        data = r.json()
        quotes = data.get("quotes", {}).get("quote", [])
        if isinstance(quotes, dict):
            quotes = [quotes]
        return {q['symbol']: q for q in quotes}
    except Exception as e:
        print(f"Error fetching quotes: {e}")
        return {}

def parse_option_symbol(symbol):
    """Parse OCC option symbol like SPXW251211P06840000."""
    try:
        if len(symbol) < 15:
            return None
        root = symbol[:-15]
        date_str = symbol[-15:-9]
        opt_type = symbol[-9]
        strike = int(symbol[-8:]) / 1000
        exp_date = f"20{date_str[:2]}-{date_str[2:4]}-{date_str[4:6]}"
        return {
            'root': root,
            'expiry': exp_date,
            'type': 'CALL' if opt_type == 'C' else 'PUT',
            'strike': strike
        }
    except Exception as e:
        return None

def parse_date_acquired(date_acquired):
    """Parse and convert date to ET."""
    if not date_acquired:
        return '', ''
    try:
        dt = datetime.fromisoformat(date_acquired.replace('Z', '+00:00'))
        dt_et = dt.astimezone(ET)
        display = dt_et.strftime('%m/%d %H:%M ET')
        key = dt.strftime('%Y-%m-%d %H:%M')
        return display, key
    except Exception as e:
        return date_acquired[:16], date_acquired[:16]

def format_pl(pl):
    """Format P/L with color (12 visible chars to match P/L column width)."""
    if pl > 0:
        return f"\033[32m${pl:>+11.2f}\033[0m"  # Green ($ + 11 chars = 12 total)
    elif pl < 0:
        return f"\033[31m${pl:>+11.2f}\033[0m"  # Red ($ + 11 chars = 12 total)
    return f"${pl:>+11.2f}"  # 12 visible chars ($ + 11 for number with sign)

def load_orders(name):
    """Load tracked orders from JSON file."""
    import json
    orders_file = f"/root/gamma/data/orders_{name.lower()}.json"
    try:
        with open(orders_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        return []


def find_order_for_symbols(orders, symbols):
    """Find matching order by option symbols."""
    symbol_set = set(symbols)
    for order in orders:
        order_symbols = set(order.get('option_symbols', []))
        if order_symbols and order_symbols == symbol_set:
            return order
    return None


def show_account(name, account_id, api_key, base_url):
    """Display positions for an account.

    ARCHITECTURE: Broker API is the source of truth for open positions
    - positions: Fetched directly from broker API (authoritative)
    - orders: Loaded from tracking file (metadata only: TP/SL, confidence, etc.)

    This ensures show.py always displays the true account state from the broker,
    even if the tracking file is out of sync (e.g., orphaned positions that were
    recovered by the monitor's reconciliation system).
    """
    # Fetch positions directly from broker API (source of truth)
    positions = get_positions(account_id, api_key, base_url)

    # Load tracked orders for metadata matching (TP/SL targets, confidence, trailing stop status)
    # If a position exists in broker but not in orders, we still display it (won't have metadata)
    orders = load_orders(name)

    print(f"\n{'='*70}")
    print(f"  {name} ACCOUNT: {account_id}")
    print(f"{'='*70}")

    if not positions:
        print("  No open positions")
        return

    # Get quotes for all position symbols
    symbols = [p['symbol'] for p in positions]
    quotes = get_quotes(symbols, api_key, base_url)

    # Group positions by date_acquired and symbol root (spreads opened together on same index)
    groups = defaultdict(list)
    for pos in positions:
        date_acquired = pos.get('date_acquired', '')
        _, key = parse_date_acquired(date_acquired)

        # Extract symbol root for sub-grouping (e.g., NDXP or SPXW)
        symbol = pos['symbol']
        opt = parse_option_symbol(symbol)
        symbol_root = opt['root'] if opt else symbol.split()[0]

        # Create group key as (time, symbol_root)
        group_key = (key, symbol_root)
        groups[group_key].append(pos)

    # Sort groups by time (most recent first), then by symbol root
    sorted_groups = sorted(groups.items(), key=lambda x: (x[0][0], x[0][1]), reverse=True)

    total_pl = 0

    print(f"\n  {'Symbol':<30} {'Qty':>5} {'Cost':>10} {'Current':>10} {'P/L':>12} {'% P/L':>7} {'Opened':<16}")
    print(f"  {'-'*30} {'-'*5} {'-'*10} {'-'*10} {'-'*12} {'-'*7} {'-'*16}")

    for (group_time, symbol_root), group_positions in sorted_groups:
        group_pl = 0
        group_entry_credit = 0  # Total credit received for spread
        group_current_value = 0  # Current cost to close spread
        group_symbols = []  # Collect symbols for order matching
        group_strikes = []  # Collect strikes for spread width calculation
        group_lines = []
        num_contracts = 0  # Number of contracts in spread
        is_spread = len(group_positions) > 1

        for pos in group_positions:
            symbol = pos['symbol']
            group_symbols.append(symbol)
            qty = int(pos['quantity'])
            num_contracts = max(num_contracts, abs(qty))  # Track contract size
            cost_basis = float(pos['cost_basis'])
            date_acquired = pos.get('date_acquired', '')
            opened_str, _ = parse_date_acquired(date_acquired)

            # Parse option details
            opt = parse_option_symbol(symbol)
            if opt:
                display = f"{opt['root']} {opt['expiry'][-5:]} ${opt['strike']:.0f}{opt['type'][0]}"
                group_strikes.append(opt['strike'])  # Track strikes for spread width
            else:
                display = symbol

            # Get current price
            quote = quotes.get(symbol, {})
            bid = float(quote.get('bid') or 0)
            ask = float(quote.get('ask') or 0)
            last = float(quote.get('last') or 0)
            mid = (bid + ask) / 2 if bid and ask else last

            # Calculate P/L (options have 100 multiplier)
            is_option = opt is not None
            multiplier = 100 if is_option else 1
            current_value = mid * qty * multiplier
            pl = current_value - cost_basis
            cost_per = abs(cost_basis / qty / multiplier) if qty != 0 else 0

            # Calculate percent change
            if cost_basis != 0:
                pl_pct = (pl / abs(cost_basis)) * 100
            else:
                pl_pct = 0

            # Color code the percentage
            if pl_pct >= 0:
                pct_color_str = f"\033[32m{pl_pct:>+6.1f}%\033[0m"
            else:
                pct_color_str = f"\033[31m{pl_pct:>6.1f}%\033[0m"

            # Track entry credit and current value for spread (options only)
            if is_option:
                # Short positions: cost_basis is negative (credit received)
                # Long positions: cost_basis is positive (debit paid)
                # Net credit = -cost_basis for shorts + (-cost_basis) for longs = -total_cost_basis
                group_entry_credit -= cost_basis
                # Current value: negative for shorts (cost to buy back), positive for longs (can sell)
                group_current_value += current_value

            group_pl += pl
            total_pl += pl

            # For spreads, hide individual leg P/L and percentages
            # Only show P/L and % at the spread subtotal level
            if is_spread:
                # Spreads: suppress individual leg P/L and %
                pl_str = " " * 12  # Blank spaces for P/L column
                pct_color_str = ""
            else:
                # Single leg: show P/L normally
                pl_str = format_pl(pl)

            group_lines.append(f"  {display:<30} {qty:>+5} ${cost_per:>8.2f} ${mid:>8.2f} {pl_str} {pct_color_str:<7} {opened_str:<16}")

        # Print group
        for line in group_lines:
            print(line)

        # Print subtotal if more than one position in group (spread)
        if is_spread and group_entry_credit != 0:
            # Identify spread type (CALL, PUT, or IC)
            spread_type = "SPREAD"
            call_count = 0
            put_count = 0

            for pos in group_positions:
                symbol = pos['symbol']
                opt = parse_option_symbol(symbol)
                if opt:
                    if opt['type'] == 'CALL':
                        call_count += 1
                    elif opt['type'] == 'PUT':
                        put_count += 1

            # Classify spread type
            if call_count > 0 and put_count > 0:
                spread_type = "IC"  # Iron Condor (has both calls and puts)
            elif call_count > 0:
                spread_type = "CALL"  # Call spread
            elif put_count > 0:
                spread_type = "PUT"  # Put spread

            # For spread, show the net credit/debit per contract per share
            # group_entry_credit is in dollars (sum of all positions)
            # Divide by number of contracts and 100 to get per-share price
            if num_contracts > 0:
                entry_per = group_entry_credit / num_contracts / 100  # Per-contract, per-share price
                current_spread_value = abs(group_current_value) / num_contracts / 100  # Per-contract, per-share price
            else:
                entry_per = 0
                current_spread_value = 0

            # Calculate % of max risk (more intuitive than % of credit)
            # Max risk = spread width - credit received per share
            if group_strikes and len(group_strikes) >= 2:
                spread_width = abs(max(group_strikes) - min(group_strikes))  # Width in points
                max_loss_per_share = spread_width - entry_per  # Max loss per share (in dollars)
                max_loss_total = max_loss_per_share * num_contracts * 100  # Total max loss

                if max_loss_total > 0:
                    # Current loss as % of max possible loss
                    # If profit, show positive; if loss, show negative
                    profit_pct = (group_pl / max_loss_total) * 100
                else:
                    profit_pct = 0
            else:
                # Fallback: show as % of credit
                if group_entry_credit != 0:
                    profit_pct = (group_pl / group_entry_credit) * 100
                else:
                    profit_pct = 0

            if profit_pct >= 0:
                pct_str = f"\033[32m{profit_pct:>+6.1f}%\033[0m"
            else:
                pct_str = f"\033[31m{profit_pct:>6.1f}%\033[0m"

            subtotal_label = f"  └─ {symbol_root} {spread_type}"
            print(f"  {subtotal_label:<30} {'':>5} ${entry_per:>8.2f} ${current_spread_value:>8.2f} {format_pl(group_pl)} {pct_str}")

            # Find matching order and show TP/SL targets
            order = find_order_for_symbols(orders, group_symbols)
            if order:
                tp_price = order.get('tp_price', 0)
                sl_price = order.get('sl_price', 0)
                trailing_active = order.get('trailing_stop_active', False)
                best_pct = order.get('best_profit_pct', 0) * 100

                if trailing_active:
                    # Calculate current trailing stop level
                    TRAILING_TRIGGER = 0.25
                    TRAILING_LOCK_IN = 0.10
                    TRAILING_MIN = 0.08
                    TRAILING_RATE = 0.4
                    initial_trail = TRAILING_TRIGGER - TRAILING_LOCK_IN
                    profit_above = (best_pct/100) - TRAILING_TRIGGER
                    trail_dist = initial_trail - (profit_above * TRAILING_RATE)
                    trail_dist = max(trail_dist, TRAILING_MIN)
                    trail_level = (best_pct/100) - trail_dist
                    trail_price = entry_per * (1 - trail_level)
                    status = f"\033[33mTRAILING\033[0m (peak {best_pct:.0f}%, exit @ ${trail_price:.2f})"
                else:
                    status = f"TP @ ${tp_price:.2f} | SL @ ${sl_price:.2f}"

                print(f"  {'  └─ Targets':<30} {'':>5} {'':>10} {'':>10} {status}")
            print()

    # Grand total
    print(f"  {'-'*30} {'-'*5} {'-'*10} {'-'*10} {'-'*12} {'-'*7}")
    print(f"  {'TOTAL':<30} {'':>5} {'':>10} {'':>10} {format_pl(total_pl)} {'':>7}")

def show_closed_trades(days=None, account_mode="PAPER", account_id=None):
    """Display closed trades from trades.csv.

    Args:
        days: Number of days to show (None=today only, 'all'=all history, N=last N days)
        account_mode: Which account was shown (PAPER, LIVE, ALL)
        account_id: Account ID to display in header
    """
    import csv
    import os
    from datetime import timedelta

    trade_log = "/root/gamma/data/trades.csv"
    if not os.path.exists(trade_log):
        return

    now_et = datetime.now(ET)
    today_str = now_et.strftime('%Y-%m-%d')
    closed_trades = []

    # Calculate date cutoff and date range string
    if days is None:
        # Today only (default)
        cutoff_date = None
        date_range = today_str
    elif days == 'all':
        # All history
        cutoff_date = datetime(2000, 1, 1).replace(tzinfo=ET)
        date_range = "All Time"
    else:
        # Last N days
        try:
            cutoff_date = (now_et - timedelta(days=int(days))).replace(hour=0, minute=0, second=0, microsecond=0)
            start_date = cutoff_date.strftime('%Y-%m-%d')
            date_range = f"{start_date} to {today_str}"
        except ValueError:
            cutoff_date = None
            date_range = today_str

    try:
        with open(trade_log, 'r') as f:
            lines = f.readlines()

        for line in lines:
            # Parse CSV line to handle both old (14-field) and new (15-field) formats
            fields = line.strip().split(',')

            # Old format (14 fields): TP%, Exit_Time, Exit_Value, ...
            # New format (15 fields): TP%, Contracts, Exit_Time, Exit_Value, ...
            if len(fields) < 10:
                continue

            if len(fields) == 14:
                # Old format - insert None for Contracts field
                fieldnames = ['Timestamp_ET','Trade_ID','Account_ID','Strategy','Strikes',
                             'Entry_Credit','Confidence','TP%','Exit_Time','Exit_Value',
                             'P/L_$','P/L_%','Exit_Reason','Duration_Min']
                row = {k: v for k, v in zip(fieldnames, fields)}
                row['Contracts'] = '10'  # Assume old trades were 10 contracts (default)
            elif len(fields) == 15:
                # New format with Contracts field
                fieldnames = ['Timestamp_ET','Trade_ID','Account_ID','Strategy','Strikes',
                             'Entry_Credit','Confidence','TP%','Contracts','Exit_Time','Exit_Value',
                             'P/L_$','P/L_%','Exit_Reason','Duration_Min']
                row = {k: v for k, v in zip(fieldnames, fields)}
            else:
                continue  # Skip malformed rows

            exit_time = row.get('Exit_Time', '')
            if not exit_time:
                continue

            # Filter by account_id (if mode is not ALL)
            if account_mode != "ALL" and account_id:
                row_account_id = row.get('Account_ID', '')
                if row_account_id and row_account_id != account_id:
                    continue  # Skip trades from other accounts

            # Filter by date range
            if cutoff_date is None:
                # Today only
                if exit_time.startswith(today_str):
                    closed_trades.append(row)
            else:
                # Date range or all
                try:
                    exit_dt = datetime.strptime(exit_time, '%Y-%m-%d %H:%M:%S').replace(tzinfo=ET)
                    if exit_dt >= cutoff_date:
                        closed_trades.append(row)
                except Exception as e:
                    pass
    except Exception as e:
        print(f"Error reading trade log: {e}")
        return

    if not closed_trades:
        if days == 'all' or (days and int(days) > 1):
            print(f"\n{'='*70}")
            if account_mode == "ALL":
                print(f"  CLOSED TRADES (ALL ACCOUNTS) - {date_range}")
            else:
                acct_display = f"{account_mode}: {account_id}" if account_id else account_mode
                print(f"  CLOSED TRADES ({acct_display}) - {date_range}")
            print(f"{'='*70}")
            print("  No trades found in history")
        return

    # Build header with account and date range
    print(f"\n{'='*70}")
    if account_mode == "ALL":
        print(f"  CLOSED TRADES (ALL ACCOUNTS)")
    else:
        acct_display = f"{account_mode}: {account_id}" if account_id else account_mode
        print(f"  CLOSED TRADES ({acct_display})")
    print(f"  Period: {date_range}")
    print(f"{'='*70}")

    print(f"\n  {'Opened':<14} {'Closed':<14} {'Type':<8} {'Cts':>3} {'Strikes':<18} {'Entry':>6} {'Exit':>6} {'P/L':>8} {'%':>6} {'Dur':>5} {'Reason':<18}")
    print(f"  {'-'*14} {'-'*14} {'-'*8} {'-'*3} {'-'*18} {'-'*6} {'-'*6} {'-'*8} {'-'*6} {'-'*5} {'-'*18}")

    total_pl = 0
    wins = 0
    losses = 0

    for trade in closed_trades:
        strikes = trade.get('Strikes', 'N/A')[:16]
        strategy = trade.get('Strategy', 'N/A').upper()[:4]  # PUT, CALL, IC
        contracts = trade.get('Contracts', '?')  # Number of contracts

        # Determine underlying symbol from strike price
        try:
            first_strike = float(strikes.split('/')[0])
            underlying = 'NDX' if first_strike >= 10000 else 'SPX'
        except:
            underlying = '?'

        entry = trade.get('Entry_Credit', '0')
        exit_val = trade.get('Exit_Value', '0')
        open_time = trade.get('Timestamp_ET', '')
        exit_time = trade.get('Exit_Time', '')
        pl_str = trade.get('P/L_$', '$0')
        pl_pct = trade.get('P/L_%', '0%')
        duration = trade.get('Duration_Min', '-')
        reason = trade.get('Exit_Reason', 'N/A')

        # Format open time (MM/DD HH:MM)
        try:
            if open_time:
                dt = datetime.strptime(open_time, '%Y-%m-%d %H:%M:%S')
                time_str = dt.strftime('%m/%d %H:%M')
            else:
                time_str = '-'
        except Exception as e:
            time_str = open_time[:14] if open_time else '-'

        # Format exit time (HH:MM or EXPIRED)
        exit_time_str = '-'
        if exit_time:
            # Check if reason indicates expiration
            if 'Expiration' in reason or 'expir' in reason.lower():
                exit_time_str = '\033[33mEXPIRED\033[0m'  # Yellow
            else:
                try:
                    dt = datetime.strptime(exit_time, '%Y-%m-%d %H:%M:%S')
                    exit_time_str = dt.strftime('%H:%M')
                except Exception as e:
                    exit_time_str = exit_time.split(' ')[1][:5] if ' ' in exit_time else exit_time[:5]

        # Shorten reason and highlight expiration
        if 'Expiration' in reason:
            reason_short = '\033[33m0DTE EXPIRED\033[0m'
        else:
            reason_short = reason[:24]

        # Format duration
        try:
            dur_min = int(float(duration))
            if dur_min >= 60:
                dur_str = f"{dur_min//60}h{dur_min%60:02d}"
            else:
                dur_str = f"{dur_min}m"
        except Exception as e:
            dur_str = "-"

        # Parse P/L for coloring and totals
        try:
            pl = float(pl_str.replace('$', '').replace('+', '').replace(',', ''))
            total_pl += pl
            if pl > 0:
                wins += 1
            elif pl < 0:
                losses += 1
        except Exception as e:
            pl = 0

        # Format entry and exit with proper alignment (6 chars total including $)
        entry_str = f"${float(entry):>5.2f}"  # "$2.40" = 6 chars
        exit_str = f"${float(exit_val):>5.2f}"  # "$2.90" = 6 chars

        # Format P/L with color - pad BEFORE adding ANSI codes
        # Format: "$    -50" or "$  +240" (8 chars visible)
        pl_text = f"$ {pl:>+6.0f}"  # Build the 8-char string first
        if pl > 0:
            pl_colored = f"\033[32m{pl_text}\033[0m"
        elif pl < 0:
            pl_colored = f"\033[31m{pl_text}\033[0m"
        else:
            pl_colored = pl_text

        # Color the percentage - pad BEFORE adding ANSI codes
        # Format: "  +50%" or "  -21%" (6 chars visible)
        try:
            pct_val = float(pl_pct.replace('%', '').replace('+', ''))
            pct_text = f"{pct_val:>+5.0f}%"  # Build the 6-char string first
            if pct_val > 0:
                pct_colored = f"\033[32m{pct_text}\033[0m"
            elif pct_val < 0:
                pct_colored = f"\033[31m{pct_text}\033[0m"
            else:
                pct_colored = pct_text
        except Exception as e:
            pct_colored = f"{pl_pct:>6}"

        # Print with proper alignment (no additional padding for colored fields)
        type_label = f"{underlying} {strategy}"
        print(f"  {time_str:<14} {exit_time_str:<14} {type_label:<8} {contracts:>3} {strikes:<18} {entry_str:>6} {exit_str:>6} {pl_colored} {pct_colored} {dur_str:>5} {reason_short:<18}")

    # Summary
    print(f"  {'-'*14} {'-'*14} {'-'*8} {'-'*3} {'-'*18} {'-'*6} {'-'*6} {'-'*8} {'-'*6} {'-'*5} {'-'*18}")

    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

    summary = f"{wins}W/{losses}L ({win_rate:.0f}%)"

    # Format total P/L
    if total_pl > 0:
        total_colored = f"\033[32m${total_pl:>+6.0f}\033[0m"
    elif total_pl < 0:
        total_colored = f"\033[31m${total_pl:>+6.0f}\033[0m"
    else:
        total_colored = f"${total_pl:>+6.0f}"

    print(f"  {'TOTAL':<14} {summary:<14} {'':>8} {'':>3} {'':>18} {'':>6} {'':>6} {total_colored}")

    # Extended stats for multi-day history
    if days and days != 'today':
        # Calculate average P/L per trade
        avg_pl = total_pl / total_trades if total_trades > 0 else 0
        avg_win = sum(float(t.get('P/L_$', '0').replace('$', '').replace('+', '').replace(',', ''))
                     for t in closed_trades
                     if float(t.get('P/L_$', '0').replace('$', '').replace('+', '').replace(',', '')) > 0) / wins if wins > 0 else 0
        avg_loss = sum(float(t.get('P/L_$', '0').replace('$', '').replace('+', '').replace(',', ''))
                      for t in closed_trades
                      if float(t.get('P/L_$', '0').replace('$', '').replace('+', '').replace(',', '')) < 0) / losses if losses > 0 else 0

        # Calculate average duration
        durations = []
        for t in closed_trades:
            try:
                dur = float(t.get('Duration_Min', '0'))
                durations.append(dur)
            except:
                pass
        avg_duration = sum(durations) / len(durations) if durations else 0

        # Calculate profit factor
        total_wins = sum(float(t.get('P/L_$', '0').replace('$', '').replace('+', '').replace(',', ''))
                        for t in closed_trades
                        if float(t.get('P/L_$', '0').replace('$', '').replace('+', '').replace(',', '')) > 0)
        total_losses = abs(sum(float(t.get('P/L_$', '0').replace('$', '').replace('+', '').replace(',', ''))
                              for t in closed_trades
                              if float(t.get('P/L_$', '0').replace('$', '').replace('+', '').replace(',', '')) < 0))
        profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')

        print(f"\n  PERIOD STATISTICS:")
        print(f"  {'-'*70}")
        print(f"  Avg P/L per trade: {format_pl(avg_pl)}")
        print(f"  Avg Winner: {format_pl(avg_win)}  |  Avg Loser: {format_pl(avg_loss)}")
        if avg_duration >= 60:
            print(f"  Avg Duration: {int(avg_duration // 60)}h {int(avg_duration % 60):02d}m")
        else:
            print(f"  Avg Duration: {int(avg_duration)}m")
        if profit_factor == float('inf'):
            print(f"  Profit Factor: ∞ (no losses)")
        else:
            print(f"  Profit Factor: {profit_factor:.2f}")

    # Intraday P/L chart if we have trades (only for single-day view)
    if len(closed_trades) >= 2 and (not days or days == 'today'):
        show_intraday_chart(closed_trades)

def show_intraday_chart(trades):
    """Display ASCII chart of cumulative P/L through the day."""
    # Parse trades with exit times and P/L
    data_points = []
    for trade in trades:
        exit_time = trade.get('Exit_Time', '')
        pl_str = trade.get('P/L_$', '0')
        try:
            pl = float(pl_str.replace('$', '').replace('+', '').replace(',', ''))
            # Parse time (format: 2025-12-11 11:46:45)
            if exit_time:
                time_part = exit_time.split(' ')[1] if ' ' in exit_time else exit_time
                hour_min = time_part[:5]  # HH:MM
                data_points.append((hour_min, pl))
        except Exception as e:
            pass

    if len(data_points) < 2:
        return

    # Sort by time
    data_points.sort(key=lambda x: x[0])

    # Calculate cumulative P/L
    cumulative = []
    running_total = 0
    for time_str, pl in data_points:
        running_total += pl
        cumulative.append((time_str, running_total))

    # Find min/max for scaling
    values = [v for _, v in cumulative]
    min_val = min(min(values), 0)
    max_val = max(max(values), 0)
    val_range = max_val - min_val if max_val != min_val else 1

    # Chart dimensions
    chart_height = 8
    chart_width = len(cumulative)

    print(f"\n  Intraday P/L")
    print(f"  {'-'*40}")

    # Build chart rows
    for row in range(chart_height, -1, -1):
        threshold = min_val + (val_range * row / chart_height)

        # Y-axis label
        if row == chart_height:
            label = f"${max_val:>+6.0f}"
        elif row == 0:
            label = f"${min_val:>+6.0f}"
        elif abs(threshold) < 1:
            label = f"     $0"
        else:
            label = "       "

        line = f"  {label} |"

        for i, (time_str, val) in enumerate(cumulative):
            if row == 0 and threshold <= 0 <= val:
                line += "─"
            elif val >= threshold > 0:
                line += "\033[32m█\033[0m"  # Green above zero
            elif val <= threshold < 0:
                line += "\033[31m█\033[0m"  # Red below zero
            elif threshold <= 0 <= val or threshold >= 0 >= val:
                line += "─"
            else:
                line += " "

        print(line)

    # X-axis with times
    print(f"         +{'-'*len(cumulative)}")
    times_line = "          "
    for i, (time_str, _) in enumerate(cumulative):
        if i == 0 or i == len(cumulative) - 1:
            times_line = f"        {cumulative[0][0]}" + " " * (len(cumulative) - 10) + cumulative[-1][0]
            break
    print(f"  {times_line}")

def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description='Display Tradier account positions and trade history')
    parser.add_argument('account', nargs='?', default='PAPER',
                       help='Account to show: PAPER (default), LIVE, or ALL')
    parser.add_argument('--history', '-H', metavar='DAYS',
                       help='Show trade history: number of days (e.g., 7, 30) or "all" for complete history')

    args = parser.parse_args()

    mode = args.account.upper()
    history_days = args.history

    paper_url = "https://sandbox.tradier.com/v1"
    live_url = "https://api.tradier.com/v1"

    # Show market banner first
    show_market_banner()

    # Track which account(s) to show in history
    account_id_for_history = None

    if mode == "ALL":
        show_account("PAPER", PAPER_ACCOUNT_ID, TRADIER_SANDBOX_KEY, paper_url)
        show_account("LIVE", LIVE_ACCOUNT_ID, TRADIER_LIVE_KEY, live_url)
        account_id_for_history = None  # ALL mode
    elif mode in ["LIVE", "REAL"]:
        show_account("LIVE", LIVE_ACCOUNT_ID, TRADIER_LIVE_KEY, live_url)
        account_id_for_history = LIVE_ACCOUNT_ID
    else:
        show_account("PAPER", PAPER_ACCOUNT_ID, TRADIER_SANDBOX_KEY, paper_url)
        account_id_for_history = PAPER_ACCOUNT_ID

    # Show closed trades with optional history
    show_closed_trades(days=history_days, account_mode=mode, account_id=account_id_for_history)

    print()

if __name__ == "__main__":
    main()
