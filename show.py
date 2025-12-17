#!/usr/bin/env python3
"""
show.py — Display current option positions and P/L status
Usage:
  python show.py         # Show paper account
  python show.py LIVE    # Show live account
  python show.py ALL     # Show both accounts
"""

import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")

import sys
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


def calculate_real_gex_pin(spx_price):
    """Calculate real GEX pin from options open interest and gamma data."""
    from datetime import date

    try:
        today = date.today().strftime("%Y-%m-%d")

        # Get options chain with greeks
        r = requests.get(f"{LIVE_URL}/markets/options/chains", headers=LIVE_HEADERS,
            params={"symbol": "SPX", "expiration": today, "greeks": "true"}, timeout=15)

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

            gex = gamma * oi * 100 * (spx_price ** 2)

            if opt_type == 'call':
                gex_by_strike[strike] += gex
            else:
                gex_by_strike[strike] -= gex

        if not gex_by_strike:
            return None

        # Find strikes near current price with highest positive GEX
        near_strikes = [(s, g) for s, g in gex_by_strike.items() if abs(s - spx_price) < 50 and g > 0]

        if near_strikes:
            pin_strike, _ = max(near_strikes, key=lambda x: x[1])
            return pin_strike
        else:
            all_near = [(s, g) for s, g in gex_by_strike.items() if abs(s - spx_price) < 50]
            if all_near:
                pin_strike, _ = max(all_near, key=lambda x: abs(x[1]))
                return pin_strike

        return None

    except Exception as e:
        return None


def get_gex_pin(spx_price):
    """Get GEX pin level - cached to file to avoid flip-flopping."""
    import time
    import json

    CACHE_FILE = '/tmp/gex_pin_cache.json'
    CACHE_DURATION = 1800  # 30 minutes

    now = time.time()

    # Try to read from cache
    try:
        with open(CACHE_FILE, 'r') as f:
            cache = json.load(f)
            if (now - cache.get('timestamp', 0)) < CACHE_DURATION:
                return cache['value']
    except Exception as e:
        pass

    # Calculate real GEX pin from options data
    pin = calculate_real_gex_pin(spx_price)

    if pin is None:
        return None  # No fallback - return None if GEX unavailable

    # Save to cache
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump({'value': pin, 'timestamp': now}, f)
    except Exception as e:
        pass

    return pin


def get_intraday_prices():
    """Fetch intraday SPY prices for sparkline chart."""
    try:
        # Get today's 5-min bars (suppress warnings)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            spy = yf.download("SPY", period="1d", interval="5m", progress=False)
        if spy.empty:
            return []
        # Convert to SPX and return as list
        closes = spy['Close'].values
        # Handle nested array from yfinance
        if hasattr(closes[0], '__iter__'):
            closes = [float(c[0]) for c in closes]
        else:
            closes = [float(c) for c in closes]
        # Convert SPY to SPX (multiply by 10)
        return [round(p * 10) for p in closes]
    except Exception as e:
        return []


def render_sparkline(prices, width=50, height=5, gex_pin=None, min_p=None, max_p=None):
    """Render a compact ASCII sparkline chart with time vertical, price horizontal."""
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
                elif price > gex_pin + 10 or price < gex_pin - 10:
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
    """Display current market data banner."""
    spx_raw = get_spx_price()
    vix = get_vix()

    if spx_raw:
        spx = round(spx_raw)
        gex_pin = get_gex_pin(spx)
        distance = (spx - gex_pin) if gex_pin else None

        # Calculate expected move
        if vix:
            hours_left = 2
            expected_move = spx * (vix/100) * math.sqrt(hours_left / (252 * 6.5))
        else:
            expected_move = 0
    else:
        spx, gex_pin, distance, expected_move = 0, None, None, 0

    now_et = datetime.now(ET)

    print(f"\n{'='*70}")
    print(f"  GAMMA SCALPER STATUS — {now_et.strftime('%Y-%m-%d %H:%M:%S')} ET")
    print(f"{'='*70}")

    if spx_raw and vix:
        # Get intraday prices for sparkline
        prices = get_intraday_prices()
        if prices and gex_pin:
            chart_prices = prices[-5:]  # Last 5 data points for compact view
            # Include GEX pin in range so it's always visible
            min_p = min(min(chart_prices), gex_pin - 5)
            max_p = max(max(chart_prices), gex_pin + 5)
            sparkline = render_sparkline(prices, width=50, height=5, gex_pin=gex_pin, min_p=min_p, max_p=max_p)

            # Calculate pin position for header
            price_range = max_p - min_p
            pin_pos = int((gex_pin - min_p) / price_range * 48) if price_range > 0 else 24

            # Print header with price range and pin marker
            header_line = " " * pin_pos + "▼"
            print(f"        {min_p:<6}{' '*18}PIN{' '*18}{max_p:>6}")
            print(f"        |{header_line:^48}|")

            # Print sparkline rows (time going down)
            for i, row in enumerate(sparkline):
                if i == len(sparkline) - 1:
                    print(f"  NOW → |{row}| ●={spx}")
                else:
                    print(f"        |{row}|")

        # Display market data line
        if gex_pin and distance is not None:
            # Color distance based on magnitude
            if abs(distance) <= 10:
                dist_color = "\033[32m"  # Green - near pin
            elif abs(distance) <= 25:
                dist_color = "\033[33m"  # Yellow - moderate
            else:
                dist_color = "\033[31m"  # Red - far from pin
            print(f"  SPX: {spx}  |  GEX Pin: {int(gex_pin)}  |  Distance: {dist_color}{int(distance):+d}\033[0m  |  VIX: {vix:.2f}")
        else:
            print(f"  SPX: {spx}  |  GEX Pin: \033[31mUNAVAILABLE\033[0m  |  VIX: {vix:.2f}")
        print(f"  Expected 2hr Move: ±{expected_move:.1f} pts (1σ)")
    else:
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
    """Format P/L with color."""
    if pl > 0:
        return f"\033[32m${pl:>+8.2f}\033[0m"  # Green
    elif pl < 0:
        return f"\033[31m${pl:>+8.2f}\033[0m"  # Red
    return f"${pl:>+8.2f}"

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
    """Display positions for an account."""
    positions = get_positions(account_id, api_key, base_url)
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

    # Group positions by date_acquired (spreads opened together)
    groups = defaultdict(list)
    for pos in positions:
        date_acquired = pos.get('date_acquired', '')
        _, key = parse_date_acquired(date_acquired)
        groups[key].append(pos)

    # Sort groups by time (most recent first)
    sorted_groups = sorted(groups.items(), key=lambda x: x[0], reverse=True)

    total_pl = 0

    print(f"\n  {'Symbol':<30} {'Qty':>5} {'Cost':>10} {'Current':>10} {'P/L':>12} {'Opened':<16}")
    print(f"  {'-'*30} {'-'*5} {'-'*10} {'-'*10} {'-'*12} {'-'*16}")

    for group_time, group_positions in sorted_groups:
        group_pl = 0
        group_entry_credit = 0  # Total credit received for spread
        group_current_value = 0  # Current cost to close spread
        group_symbols = []  # Collect symbols for order matching
        group_lines = []
        is_spread = len(group_positions) > 1

        for pos in group_positions:
            symbol = pos['symbol']
            group_symbols.append(symbol)
            qty = int(pos['quantity'])
            cost_basis = float(pos['cost_basis'])
            date_acquired = pos.get('date_acquired', '')
            opened_str, _ = parse_date_acquired(date_acquired)

            # Parse option details
            opt = parse_option_symbol(symbol)
            if opt:
                display = f"{opt['root']} {opt['expiry'][-5:]} ${opt['strike']:.0f}{opt['type'][0]}"
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

            group_lines.append(f"  {display:<30} {qty:>+5} ${cost_per:>8.2f} ${mid:>8.2f} {format_pl(pl)} {opened_str:<16}")

        # Print group
        for line in group_lines:
            print(line)

        # Print subtotal if more than one position in group (spread)
        if is_spread and group_entry_credit != 0:
            # profit % = P/L / entry_credit
            profit_pct = (group_pl / group_entry_credit) * 100
            # Current cost to close (per contract, divide by 100)
            current_cost = abs(group_current_value) / 100

            if profit_pct >= 0:
                pct_str = f"\033[32m{profit_pct:>+.0f}% profit\033[0m"
            else:
                pct_str = f"\033[31m{profit_pct:>.0f}% loss\033[0m"

            entry_per = group_entry_credit / 100  # Entry credit per contract
            print(f"  {'  └─ Subtotal':<30} {'':>5} ${entry_per:>8.2f} ${current_cost:>8.2f} {format_pl(group_pl)} ({pct_str})")

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
    print(f"  {'-'*30} {'-'*5} {'-'*10} {'-'*10} {'-'*12}")
    print(f"  {'TOTAL':<30} {'':>5} {'':>10} {'':>10} {format_pl(total_pl)}")

def show_closed_today():
    """Display trades closed today from trades.csv."""
    import csv
    import os

    trade_log = "/root/gamma/data/trades.csv"
    if not os.path.exists(trade_log):
        return

    today_str = datetime.now(ET).strftime('%Y-%m-%d')
    closed_trades = []

    try:
        with open(trade_log, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Check if closed today (Exit_Time starts with today's date)
                exit_time = row.get('Exit_Time', '')
                if exit_time.startswith(today_str):
                    closed_trades.append(row)
    except Exception as e:
        print(f"Error reading trade log: {e}")
        return

    if not closed_trades:
        return

    print(f"\n{'='*70}")
    print(f"  CLOSED TODAY")
    print(f"{'='*70}")

    print(f"\n  {'Opened':<14} {'Closed':<14} {'Strikes':<20} {'Entry':>6} {'Exit':>6} {'P/L':>8} {'%':>6} {'Dur':>5} {'Reason':<24}")
    print(f"  {'-'*14} {'-'*14} {'-'*20} {'-'*6} {'-'*6} {'-'*8} {'-'*6} {'-'*5} {'-'*24}")

    total_pl = 0
    wins = 0
    losses = 0

    for trade in closed_trades:
        strikes = trade.get('Strikes', 'N/A')[:20]
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
        print(f"  {time_str:<14} {exit_time_str:<14} {strikes:<20} {entry_str:>6} {exit_str:>6} {pl_colored} {pct_colored} {dur_str:>5} {reason_short:<24}")

    # Summary
    print(f"  {'-'*14} {'-'*14} {'-'*20} {'-'*6} {'-'*6} {'-'*8} {'-'*6} {'-'*5} {'-'*24}")

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

    print(f"  {'TOTAL':<14} {summary:<14} {'':>6} {'':>6} {total_colored}")

    # Intraday P/L chart if we have trades
    if len(closed_trades) >= 2:
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
    mode = sys.argv[1].upper() if len(sys.argv) > 1 else "PAPER"

    paper_url = "https://sandbox.tradier.com/v1"
    live_url = "https://api.tradier.com/v1"

    # Show market banner first
    show_market_banner()

    if mode == "ALL":
        show_account("PAPER", PAPER_ACCOUNT_ID, TRADIER_SANDBOX_KEY, paper_url)
        show_account("LIVE", LIVE_ACCOUNT_ID, TRADIER_LIVE_KEY, live_url)
    elif mode in ["LIVE", "REAL"]:
        show_account("LIVE", LIVE_ACCOUNT_ID, TRADIER_LIVE_KEY, live_url)
    else:
        show_account("PAPER", PAPER_ACCOUNT_ID, TRADIER_SANDBOX_KEY, paper_url)

    # Show closed trades for today
    show_closed_today()

    print()

if __name__ == "__main__":
    main()
