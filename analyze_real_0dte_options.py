#!/usr/bin/env python3
"""
Analyze Real 0DTE Options Data from Tradier API

This script fetches live SPX and NDX 0DTE options chains and analyzes:
1. Realistic credit ranges for 5pt and 25pt spreads
2. Time-of-day premium variation
3. VIX impact on pricing
4. Validates backtest credit assumptions

Usage:
    python analyze_real_0dte_options.py [SPX|NDX|BOTH]
"""

import sys
import requests
from datetime import date, datetime
import pytz
from collections import defaultdict
from config import TRADIER_LIVE_KEY

ET = pytz.timezone('US/Eastern')
LIVE_URL = "https://api.tradier.com/v1"
LIVE_HEADERS = {"Accept": "application/json", "Authorization": f"Bearer {TRADIER_LIVE_KEY}"}


def get_current_price(symbol):
    """Fetch current underlying price."""
    try:
        r = requests.get(f"{LIVE_URL}/markets/quotes", headers=LIVE_HEADERS,
                        params={"symbols": symbol}, timeout=10)
        data = r.json()
        q = data.get("quotes", {}).get("quote")
        if q:
            price = q.get("last") or q.get("bid") or q.get("ask")
            if price:
                return float(price)
    except Exception as e:
        print(f"Error fetching {symbol} price: {e}")
    return None


def get_vix():
    """Fetch current VIX."""
    try:
        r = requests.get(f"{LIVE_URL}/markets/quotes", headers=LIVE_HEADERS,
                        params={"symbols": "$VIX.X"}, timeout=10)
        data = r.json()
        q = data.get("quotes", {}).get("quote")
        if q and q.get("last"):
            return float(q["last"])
    except Exception as e:
        print(f"Error fetching VIX: {e}")
    return None


def get_0dte_options_chain(symbol):
    """Fetch 0DTE options chain for symbol."""
    today = date.today().strftime("%Y-%m-%d")

    try:
        r = requests.get(f"{LIVE_URL}/markets/options/chains", headers=LIVE_HEADERS,
            params={"symbol": symbol, "expiration": today, "greeks": "true"}, timeout=15)

        if r.status_code != 200:
            print(f"API Error {r.status_code}: {r.text}")
            return None

        options = r.json().get("options", {})
        if not options:
            print(f"No options data returned for {symbol}")
            return None

        options = options.get("option", [])
        if not options:
            print(f"No 0DTE options found for {symbol} expiring {today}")
            return None

        return options

    except Exception as e:
        print(f"Error fetching {symbol} options chain: {e}")
        return None


def find_credit_spreads(options, underlying_price, spread_width, option_type):
    """Find all possible credit spreads of given width.

    Args:
        options: List of option contracts
        underlying_price: Current underlying price
        spread_width: Width of spread (5 for SPX, 25 for NDX)
        option_type: 'call' or 'put'

    Returns:
        List of dicts with spread details
    """
    # Filter by option type
    opts = [o for o in options if o.get('option_type', '').lower() == option_type.lower()]

    # Build strike -> option mapping
    by_strike = {}
    for opt in opts:
        strike = opt.get('strike', 0)
        bid = opt.get('bid', 0)
        ask = opt.get('ask', 0)
        mid = (bid + ask) / 2 if bid and ask else 0

        if mid > 0:  # Only include options with valid pricing
            by_strike[strike] = {
                'symbol': opt.get('symbol', ''),
                'bid': bid,
                'ask': ask,
                'mid': mid,
                'volume': opt.get('volume', 0),
                'open_interest': opt.get('open_interest', 0),
                'greeks': opt.get('greeks', {})
            }

    spreads = []

    # For credit spreads:
    # CALL: sell lower strike, buy higher strike (bearish - expect price to stay below short strike)
    # PUT: sell higher strike, buy lower strike (bullish - expect price to stay above short strike)

    for short_strike in sorted(by_strike.keys()):
        if option_type.lower() == 'call':
            long_strike = short_strike + spread_width
        else:  # put
            long_strike = short_strike - spread_width

        if long_strike not in by_strike:
            continue

        short_opt = by_strike[short_strike]
        long_opt = by_strike[long_strike]

        # Credit = sell short (receive premium) - buy long (pay premium)
        # Use mid prices for realistic estimate
        credit = short_opt['mid'] - long_opt['mid']

        # Skip if not actually a credit
        if credit <= 0:
            continue

        # Calculate distance from current price
        if option_type.lower() == 'call':
            # For call spreads, short strike is resistance
            distance_otm = short_strike - underlying_price
        else:
            # For put spreads, short strike is support
            distance_otm = underlying_price - short_strike

        spreads.append({
            'short_strike': short_strike,
            'long_strike': long_strike,
            'credit': credit,
            'credit_pct': (credit / spread_width) * 100,
            'distance_otm': distance_otm,
            'short_bid': short_opt['bid'],
            'short_ask': short_opt['ask'],
            'long_bid': long_opt['bid'],
            'long_ask': long_opt['ask'],
            'spread_bid_ask': (short_opt['bid'] - long_opt['ask']) if short_opt['bid'] and long_opt['ask'] else 0,
            'short_volume': short_opt['volume'],
            'short_oi': short_opt['open_interest'],
            'long_volume': long_opt['volume'],
            'long_oi': long_opt['open_interest']
        })

    return spreads


def analyze_index(symbol, spread_width):
    """Analyze 0DTE options for an index."""
    print(f"\n{'='*80}")
    print(f"  {symbol} 0DTE OPTIONS ANALYSIS")
    print(f"{'='*80}")

    # Get current data
    price = get_current_price(symbol)
    if not price:
        print(f"Could not fetch {symbol} price")
        return

    print(f"\nCurrent {symbol} Price: {price:.2f}")

    # Get options chain
    options = get_0dte_options_chain(symbol)
    if not options:
        return

    print(f"Total 0DTE Options Available: {len(options)}")

    # Analyze CALL spreads
    print(f"\n{'-'*80}")
    print(f"  CALL SPREADS ({spread_width}-point width)")
    print(f"{'-'*80}")

    call_spreads = find_credit_spreads(options, price, spread_width, 'call')

    if call_spreads:
        # Show spreads at different distances OTM
        print(f"\nFound {len(call_spreads)} possible CALL credit spreads")
        print(f"\n{'Short':>6} {'Long':>6} {'OTM':>6} {'Credit':>7} {'%Width':>7} {'S.Vol':>6} {'S.OI':>6} {'Spread':>7}")
        print(f"{'-'*6} {'-'*6} {'-'*6} {'-'*7} {'-'*7} {'-'*6} {'-'*6} {'-'*7}")

        # Sort by distance OTM
        call_spreads.sort(key=lambda x: abs(x['distance_otm']))

        # Show representative spreads at different OTM distances
        distances = [10, 20, 30, 50, 75, 100, 150]
        for target_dist in distances:
            nearby = [s for s in call_spreads if abs(s['distance_otm'] - target_dist) < 5]
            if nearby:
                s = nearby[0]
                print(f"{s['short_strike']:>6.0f} {s['long_strike']:>6.0f} {s['distance_otm']:>+6.0f} "
                      f"${s['credit']:>6.2f} {s['credit_pct']:>6.1f}% {s['short_volume']:>6} "
                      f"{s['short_oi']:>6} ${s['spread_bid_ask']:>6.2f}")

        # Summary statistics
        credits = [s['credit'] for s in call_spreads]
        otm_50_credits = [s['credit'] for s in call_spreads if 40 <= s['distance_otm'] <= 60]
        otm_100_credits = [s['credit'] for s in call_spreads if 90 <= s['distance_otm'] <= 110]

        print(f"\nCALL Spread Credit Statistics:")
        print(f"  All spreads:      ${min(credits):.2f} - ${max(credits):.2f} (avg ${sum(credits)/len(credits):.2f})")
        if otm_50_credits:
            print(f"  50pts OTM:        ${min(otm_50_credits):.2f} - ${max(otm_50_credits):.2f} (avg ${sum(otm_50_credits)/len(otm_50_credits):.2f})")
        if otm_100_credits:
            print(f"  100pts OTM:       ${min(otm_100_credits):.2f} - ${max(otm_100_credits):.2f} (avg ${sum(otm_100_credits)/len(otm_100_credits):.2f})")

    # Analyze PUT spreads
    print(f"\n{'-'*80}")
    print(f"  PUT SPREADS ({spread_width}-point width)")
    print(f"{'-'*80}")

    put_spreads = find_credit_spreads(options, price, spread_width, 'put')

    if put_spreads:
        print(f"\nFound {len(put_spreads)} possible PUT credit spreads")
        print(f"\n{'Short':>6} {'Long':>6} {'OTM':>6} {'Credit':>7} {'%Width':>7} {'S.Vol':>6} {'S.OI':>6} {'Spread':>7}")
        print(f"{'-'*6} {'-'*6} {'-'*6} {'-'*7} {'-'*7} {'-'*6} {'-'*6} {'-'*7}")

        # Sort by distance OTM
        put_spreads.sort(key=lambda x: abs(x['distance_otm']))

        # Show representative spreads
        for target_dist in distances:
            nearby = [s for s in put_spreads if abs(s['distance_otm'] - target_dist) < 5]
            if nearby:
                s = nearby[0]
                print(f"{s['short_strike']:>6.0f} {s['long_strike']:>6.0f} {s['distance_otm']:>+6.0f} "
                      f"${s['credit']:>6.2f} {s['credit_pct']:>6.1f}% {s['short_volume']:>6} "
                      f"{s['short_oi']:>6} ${s['spread_bid_ask']:>6.2f}")

        # Summary statistics
        credits = [s['credit'] for s in put_spreads]
        otm_50_credits = [s['credit'] for s in put_spreads if 40 <= s['distance_otm'] <= 60]
        otm_100_credits = [s['credit'] for s in put_spreads if 90 <= s['distance_otm'] <= 110]

        print(f"\nPUT Spread Credit Statistics:")
        print(f"  All spreads:      ${min(credits):.2f} - ${max(credits):.2f} (avg ${sum(credits)/len(credits):.2f})")
        if otm_50_credits:
            print(f"  50pts OTM:        ${min(otm_50_credits):.2f} - ${max(otm_50_credits):.2f} (avg ${sum(otm_50_credits)/len(otm_50_credits):.2f})")
        if otm_100_credits:
            print(f"  100pts OTM:       ${min(otm_100_credits):.2f} - ${max(otm_100_credits):.2f} (avg ${sum(otm_100_credits)/len(otm_100_credits):.2f})")


def compare_to_backtest_assumptions():
    """Compare real market data to backtest credit assumptions."""
    vix = get_vix()
    now_et = datetime.now(ET)
    hour = now_et.hour

    print(f"\n{'='*80}")
    print(f"  BACKTEST ASSUMPTION VALIDATION")
    print(f"{'='*80}")
    print(f"\nCurrent Market Conditions:")
    print(f"  Time:  {now_et.strftime('%Y-%m-%d %H:%M:%S')} ET")
    print(f"  VIX:   {vix:.2f}")

    # Show what backtest would predict for current conditions
    print(f"\nBacktest Predicted Credits (based on current VIX {vix:.2f}):")
    print(f"\n  SPX (5-point spread):")

    if vix < 15:
        print(f"    Range: $0.20 - $0.40")
    elif vix < 22:
        print(f"    Range: $0.35 - $0.65")
    elif vix < 30:
        print(f"    Range: $0.55 - $0.95")
    else:
        print(f"    Range: $0.80 - $1.20")

    print(f"\n  NDX (25-point spread):")

    if vix < 15:
        print(f"    Range: $1.00 - $2.00")
    elif vix < 22:
        print(f"    Range: $1.80 - $3.20")
    elif vix < 30:
        print(f"    Range: $3.00 - $5.00")
    else:
        print(f"    Range: $4.50 - $7.50")

    # Time-of-day adjustment
    if hour < 10:
        print(f"\n  Time Adjustment: +10% (morning premium)")
    elif hour < 12:
        print(f"\n  Time Adjustment: baseline (mid-day)")
    else:
        print(f"\n  Time Adjustment: -10% (afternoon theta decay)")

    print(f"\nCompare these predictions to the REAL market data above.")
    print(f"Look for spreads approximately 50-100 points OTM (typical GEX distance).")


def main():
    """Main entry point."""
    # Determine which indices to analyze
    if len(sys.argv) > 1:
        mode = sys.argv[1].upper()
    else:
        mode = "BOTH"

    print("\n" + "="*80)
    print("  REAL 0DTE OPTIONS ANALYSIS - Live Market Data from Tradier API")
    print("="*80)

    if mode in ["SPX", "BOTH"]:
        analyze_index("SPX", spread_width=5)

    if mode in ["NDX", "BOTH"]:
        analyze_index("NDX", spread_width=25)

    # Show comparison
    compare_to_backtest_assumptions()

    print("\n" + "="*80)
    print("  Analysis complete. Review credits above and compare to backtest assumptions.")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
