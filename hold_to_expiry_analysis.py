#!/usr/bin/env python3
"""
Hold-to-Expiry Analysis — Would holding have been more profitable?
==================================================================
For each historical trade that exited early (trailing stop, profit target),
check whether SPX ever breached the short strike before 4:00 PM.

If not → the spread expired worthless → 100% of credit collected.
Compare actual P&L to theoretical hold-to-expiry P&L.

Uses Tradier historical intraday data (1-min bars) — no Haiku calls needed.
"""

import csv
import sys
import time
import requests
import datetime
import pytz
from pathlib import Path

ET = pytz.timezone('America/New_York')

# Tradier API for historical SPX data
def _load_tradier_live_key():
    for env_file in ['/etc/gamma.env']:
        if Path(env_file).exists():
            with open(env_file) as f:
                for line in f:
                    if line.startswith('TRADIER_LIVE_KEY='):
                        return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None

API_KEY = _load_tradier_live_key()
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"}
BASE_URL = "https://api.tradier.com/v1"

# Tradier timesales only goes back ~30 days. For older dates, use daily high/low.
TIMESALES_CUTOFF = "2026-02-13"


def get_spx_data(date_str):
    """Get SPX price data for a date. Uses 1-min timesales if available, daily high/low otherwise."""
    if date_str >= TIMESALES_CUTOFF:
        try:
            resp = requests.get(f"{BASE_URL}/markets/timesales",
                                params={"symbol": "SPX", "interval": "1min",
                                        "start": f"{date_str} 09:30",
                                        "end": f"{date_str} 16:00"},
                                headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                series = data.get('series', {})
                if series:
                    ticks = series.get('data', [])
                    if isinstance(ticks, dict):
                        ticks = [ticks]
                    bars = []
                    for t in ticks:
                        bars.append({
                            'time': t.get('time', ''),
                            'high': float(t.get('high', 0)),
                            'low': float(t.get('low', 0)),
                            'close': float(t.get('close', t.get('price', 0))),
                            'open': float(t.get('open', 0)),
                        })
                    if bars:
                        return bars, '1min'
        except Exception:
            pass

    # Fallback: daily high/low (conservative — can confirm NO breach but not exact time)
    try:
        resp = requests.get(f"{BASE_URL}/markets/history",
                            params={"symbol": "SPX", "interval": "daily",
                                    "start": date_str, "end": date_str},
                            headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            history = data.get('history', {})
            if history:
                day = history.get('day', {})
                if isinstance(day, list):
                    day = day[0] if day else {}
                if day:
                    return [{
                        'time': f"{date_str} 09:30:00",
                        'high': float(day.get('high', 0)),
                        'low': float(day.get('low', 0)),
                        'close': float(day.get('close', 0)),
                        'open': float(day.get('open', 0)),
                    }], 'daily'
    except Exception:
        pass

    return None, None


def parse_strikes(strikes_str, strategy):
    """Parse strikes string and return (short_strikes, is_call, is_put, is_ic, spread_width).

    Returns dict with call_short, call_long, put_short, put_long as applicable.
    """
    parts = strikes_str.replace('C', '').replace('P', '').split('/')
    vals = [float(p) for p in parts]

    if strategy == 'IC' and len(vals) >= 4:
        # IC: call_short/call_long/put_short/put_long
        return {
            'is_ic': True, 'is_call': False, 'is_put': False,
            'call_short': vals[0], 'call_long': vals[1],
            'put_short': vals[2], 'put_long': vals[3],
            'spread_width': max(abs(vals[1] - vals[0]), abs(vals[2] - vals[3])),
        }
    elif strategy == 'CALL':
        return {
            'is_ic': False, 'is_call': True, 'is_put': False,
            'call_short': vals[0], 'call_long': vals[1] if len(vals) > 1 else vals[0] + 10,
            'spread_width': abs(vals[1] - vals[0]) if len(vals) > 1 else 10,
        }
    else:  # PUT
        return {
            'is_ic': False, 'is_call': False, 'is_put': True,
            'put_short': vals[0], 'put_long': vals[1] if len(vals) > 1 else vals[0] - 10,
            'spread_width': abs(vals[0] - vals[1]) if len(vals) > 1 else 10,
        }


def check_strike_breach(bars, strikes_info, entry_time_str):
    """Check if SPX breached any short strike after entry time.

    For CALL: breach = SPX high >= call_short
    For PUT: breach = SPX low <= put_short
    For IC: breach on either side

    Returns (breached: bool, breach_time: str, breach_price: float, max_danger: float)
    """
    # Parse entry time
    try:
        entry_dt = datetime.datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S')
        entry_dt = ET.localize(entry_dt)
    except (ValueError, TypeError):
        entry_dt = None

    breached = False
    breach_time = None
    breach_price = 0
    max_danger = 0  # Closest approach to strike without breaching

    for bar in bars:
        # Parse bar time
        bar_time_str = bar['time']
        try:
            if 'T' in bar_time_str:
                bar_dt = datetime.datetime.fromisoformat(bar_time_str)
            else:
                bar_dt = datetime.datetime.strptime(bar_time_str, '%Y-%m-%d %H:%M:%S')
            if bar_dt.tzinfo is None:
                bar_dt = ET.localize(bar_dt)
        except (ValueError, TypeError):
            continue

        # Only check bars after entry
        if entry_dt and bar_dt < entry_dt:
            continue

        # Check breach
        if strikes_info.get('is_ic'):
            call_short = strikes_info['call_short']
            put_short = strikes_info['put_short']

            # CALL side breach
            if bar['high'] >= call_short:
                breached = True
                breach_time = bar_time_str
                breach_price = bar['high']
                break

            # PUT side breach
            if bar['low'] <= put_short:
                breached = True
                breach_time = bar_time_str
                breach_price = bar['low']
                break

            # Track closest approach
            call_dist = call_short - bar['high']
            put_dist = bar['low'] - put_short
            closest = min(call_dist, put_dist)
            max_danger = max(max_danger, -closest) if closest < 0 else max_danger

        elif strikes_info.get('is_call'):
            call_short = strikes_info['call_short']
            if bar['high'] >= call_short:
                breached = True
                breach_time = bar_time_str
                breach_price = bar['high']
                break
            dist = call_short - bar['high']
            if dist < max_danger or max_danger == 0:
                max_danger = dist

        else:  # PUT
            put_short = strikes_info['put_short']
            if bar['low'] <= put_short:
                breached = True
                breach_time = bar_time_str
                breach_price = bar['low']
                break
            dist = bar['low'] - put_short
            if dist < max_danger or max_danger == 0:
                max_danger = dist

    return breached, breach_time, breach_price, max_danger


def analyze_trades():
    """Main analysis: compare actual exits to hold-to-expiry outcomes."""
    trades_file = '/root/gamma/data/trades.csv'

    with open(trades_file) as f:
        reader = csv.DictReader(f)
        trades = list(reader)

    print(f"\n{'='*100}")
    print(f"HOLD-TO-EXPIRY ANALYSIS — Would holding have been more profitable?")
    print(f"{'='*100}")

    # Only analyze SPX trades (not NDX) with completed exits
    spx_trades = []
    for t in trades:
        strikes = t.get('Strikes', '')
        # Skip NDX trades (strikes > 20000)
        try:
            first_strike = float(strikes.replace('C','').replace('P','').split('/')[0])
            if first_strike > 20000:
                continue
        except (ValueError, IndexError):
            continue

        if not t.get('Exit_Time'):
            continue
        if not t.get('Exit_Reason'):
            continue

        spx_trades.append(t)

    print(f"\nTotal SPX trades with exits: {len(spx_trades)}")

    # Cache SPX data by date
    spx_cache = {}
    total_actual_pl = 0
    total_hold_pl = 0
    total_missed = 0
    results = []

    # Categorize
    early_exits = []  # Trailing stop / profit target
    stop_losses = []  # Emergency / regular stop

    for t in spx_trades:
        reason = t.get('Exit_Reason', '')
        if 'Trailing Stop' in reason or 'Profit Target' in reason:
            early_exits.append(t)
        elif 'Stop Loss' in reason or 'EMERGENCY' in reason:
            stop_losses.append(t)

    print(f"Early exits (trailing/TP): {len(early_exits)}")
    print(f"Stop losses: {len(stop_losses)}")
    print(f"Other: {len(spx_trades) - len(early_exits) - len(stop_losses)}")

    print(f"\n{'─'*100}")
    print(f"{'Date':<12} {'Strategy':<6} {'Strikes':<20} {'Credit':>7} {'Actual P/L':>11} "
          f"{'Hold P/L':>10} {'Missed':>10} {'Breached?':<10} {'Min Dist':>9}")
    print(f"{'─'*100}")

    for t in early_exits:
        date_str = t['Timestamp_ET'][:10]
        strategy = t['Strategy']
        strikes_str = t['Strikes']
        entry_credit = float(t['Entry_Credit'])
        actual_pl_str = t.get('P/L_$', '0').replace('+', '')
        actual_pl = float(actual_pl_str) if actual_pl_str else 0

        # Get SPX intraday data
        if date_str not in spx_cache:
            bars, resolution = get_spx_data(date_str)
            spx_cache[date_str] = (bars, resolution)
            time.sleep(0.5)  # Rate limit
        else:
            bars, resolution = spx_cache[date_str]

        if not bars:
            print(f"{date_str:<12} {strategy:<6} {strikes_str:<20} ${entry_credit:>5.2f}  "
                  f"${actual_pl:>+8.0f}   {'NO DATA':>10} {'':>10} {'':>10}")
            continue

        # Parse strikes
        try:
            strikes_info = parse_strikes(strikes_str, strategy)
        except (ValueError, IndexError) as e:
            print(f"{date_str:<12} {strategy:<6} {strikes_str:<20} PARSE ERROR: {e}")
            continue

        # Check if strike was ever breached after entry
        breached, breach_time, breach_price, min_dist = check_strike_breach(
            bars, strikes_info, t['Timestamp_ET'])

        # Infer position size from actual P/L vs percentage
        pl_pct_str = t.get('P/L_%', '0').replace('+', '').replace('%', '')
        pl_pct_val = float(pl_pct_str) / 100 if pl_pct_str else 0
        if abs(pl_pct_val) > 0.01 and abs(actual_pl) > 0:
            position_size = max(1, round(actual_pl / (entry_credit * pl_pct_val * 100)))
        else:
            position_size = 1

        # Calculate hold-to-expiry P&L (scaled to position size)
        if breached:
            # Worst case: max loss
            max_loss = (strikes_info['spread_width'] - entry_credit) * 100 * position_size
            hold_pl = -max_loss
            breach_str = f"YES"
        else:
            # Expired worthless: full credit collected
            hold_pl = entry_credit * 100 * position_size
            breach_str = "NO"

        missed = hold_pl - actual_pl
        total_actual_pl += actual_pl
        total_hold_pl += hold_pl
        total_missed += missed

        results.append({
            'date': date_str, 'strategy': strategy, 'strikes': strikes_str,
            'credit': entry_credit, 'actual_pl': actual_pl, 'hold_pl': hold_pl,
            'missed': missed, 'breached': breached, 'min_dist': min_dist,
        })

        dist_str = f"{min_dist:.0f}pts" if min_dist != 0 else "N/A"
        print(f"{date_str:<12} {strategy:<6} {strikes_str:<20} ${entry_credit:>5.2f}  "
              f"${actual_pl:>+8.0f}   ${hold_pl:>+8.0f}  ${missed:>+8.0f}  "
              f"{breach_str:<10} {dist_str:>9}")

    # Summary
    print(f"\n{'='*100}")
    print(f"SUMMARY — Early Exits Only (Trailing Stop + Profit Target)")
    print(f"{'='*100}")
    print(f"Total trades analyzed:     {len(results)}")

    winners_held = [r for r in results if not r['breached']]
    losers_held = [r for r in results if r['breached']]

    print(f"Would expire worthless:    {len(winners_held)} ({len(winners_held)/max(len(results),1)*100:.0f}%)")
    print(f"Would have been breached:  {len(losers_held)} ({len(losers_held)/max(len(results),1)*100:.0f}%)")
    print(f"")
    print(f"Actual P&L (early exits):  ${total_actual_pl:>+,.0f}")
    print(f"Hold-to-expiry P&L:        ${total_hold_pl:>+,.0f}")
    print(f"Money left on table:       ${total_missed:>+,.0f}")
    print(f"")

    if winners_held:
        avg_missed = sum(r['missed'] for r in winners_held) / len(winners_held)
        print(f"Avg missed per safe trade: ${avg_missed:>+,.0f}")

    # Stop loss analysis
    print(f"\n{'='*100}")
    print(f"STOP LOSS TRADES — Would holding have helped?")
    print(f"{'='*100}")
    print(f"{'Date':<12} {'Strategy':<6} {'Strikes':<20} {'Credit':>7} {'Actual P/L':>11} "
          f"{'Hold P/L':>10} {'Diff':>10} {'Breached?':<10}")
    print(f"{'─'*100}")

    sl_actual = 0
    sl_hold = 0

    for t in stop_losses:
        date_str = t['Timestamp_ET'][:10]
        strategy = t['Strategy']
        strikes_str = t['Strikes']
        entry_credit = float(t['Entry_Credit'])
        actual_pl_str = t.get('P/L_$', '0').replace('+', '')
        actual_pl = float(actual_pl_str) if actual_pl_str else 0

        # Skip NDX
        try:
            first_strike = float(strikes_str.replace('C','').replace('P','').split('/')[0])
            if first_strike > 20000:
                continue
        except (ValueError, IndexError):
            continue

        if date_str not in spx_cache:
            bars, resolution = get_spx_data(date_str)
            spx_cache[date_str] = (bars, resolution)
            time.sleep(0.5)
        else:
            bars, resolution = spx_cache[date_str]

        if not bars:
            continue

        try:
            strikes_info = parse_strikes(strikes_str, strategy)
        except (ValueError, IndexError):
            continue

        breached, _, _, _ = check_strike_breach(bars, strikes_info, t['Timestamp_ET'])

        # Infer position size
        pl_pct_str = t.get('P/L_%', '0').replace('+', '').replace('%', '')
        pl_pct_val = float(pl_pct_str) / 100 if pl_pct_str else 0
        if abs(pl_pct_val) > 0.01 and abs(actual_pl) > 0:
            position_size = max(1, round(actual_pl / (entry_credit * pl_pct_val * 100)))
        else:
            position_size = 1

        if breached:
            max_loss = (strikes_info['spread_width'] - entry_credit) * 100 * position_size
            hold_pl = -max_loss
        else:
            hold_pl = entry_credit * 100 * position_size

        diff = hold_pl - actual_pl
        sl_actual += actual_pl
        sl_hold += hold_pl
        breach_str = "YES" if breached else "NO"

        print(f"{date_str:<12} {strategy:<6} {strikes_str:<20} ${entry_credit:>5.2f}  "
              f"${actual_pl:>+8.0f}   ${hold_pl:>+8.0f}  ${diff:>+8.0f}  {breach_str:<10}")

    print(f"\n{'─'*100}")
    print(f"Stop loss actual P&L:      ${sl_actual:>+,.0f}")
    print(f"Stop loss hold-to-expiry:  ${sl_hold:>+,.0f}")
    print(f"Difference:                ${sl_hold - sl_actual:>+,.0f}")

    # Grand total
    grand_actual = total_actual_pl + sl_actual
    grand_hold = total_hold_pl + sl_hold
    print(f"\n{'='*100}")
    print(f"GRAND TOTAL (ALL TRADES)")
    print(f"{'='*100}")
    print(f"All trades actual P&L:     ${grand_actual:>+,.0f}")
    print(f"All trades hold-to-expiry: ${grand_hold:>+,.0f}")
    print(f"Net difference:            ${grand_hold - grand_actual:>+,.0f}")
    print(f"{'='*100}\n")


if __name__ == '__main__':
    analyze_trades()
