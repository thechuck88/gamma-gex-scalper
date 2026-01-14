#!/usr/bin/env python3
"""
Realistic P&L Backtest using Real Option Pricing Data

Uses actual bid/ask spreads from options_prices_live table instead of estimates.
Tracks spread value bar-by-bar to calculate realistic P&L with proper exit conditions.

Date: 2026-01-14
"""

import sqlite3
import pandas as pd
from datetime import datetime
from collections import defaultdict
import sys
sys.path.insert(0, '/root/gamma')
from core.gex_strategy import get_gex_trade_setup
from core.broken_wing_ic_calculator import BrokenWingICCalculator

DB_PATH = "/root/gamma/data/gex_blackbox.db"

def get_optimized_connection():
    """Get database connection with optimizations."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def determine_spread_type(underlying_price, pin_strike):
    """
    Determine spread type based on SPX position relative to PIN.
    - If SPX > PIN: Trade CALL spreads (sell OTM calls)
    - If SPX < PIN: Trade PUT spreads (sell OTM puts)
    - If very close: Could trade Iron Condor (but simplify to directional for now)
    """
    distance_pct = abs(underlying_price - pin_strike) / underlying_price

    if underlying_price > pin_strike:
        return 'call'
    elif underlying_price < pin_strike:
        return 'put'
    else:
        # At the PIN - use call for now (could do IC)
        return 'call'


def get_entry_credit(conn, timestamp, index_symbol, short_strike, long_strike, option_type):
    """
    Get REAL entry credit from database using actual bid/ask prices.
    Uses closest timestamp >= entry time to handle timestamp misalignment.

    Short: Sell at BID
    Long: Buy at ASK
    Net: BID - ASK

    Args:
        option_type: 'call' or 'put'
    """
    cursor = conn.cursor()

    # Find closest future timestamp with price data
    cursor.execute("""
    SELECT DISTINCT timestamp FROM options_prices_live
    WHERE timestamp >= ? AND index_symbol = ?
    ORDER BY timestamp ASC LIMIT 1
    """, (timestamp, index_symbol))

    closest_ts_row = cursor.fetchone()
    if not closest_ts_row:
        return None

    closest_ts = closest_ts_row[0]

    # Get short leg (at PIN) - we receive BID
    cursor.execute("""
    SELECT bid FROM options_prices_live
    WHERE timestamp = ? AND index_symbol = ? AND strike = ? AND option_type = ?
    """, (closest_ts, index_symbol, short_strike, option_type))

    short_bid_row = cursor.fetchone()
    short_bid = short_bid_row[0] if short_bid_row else None

    # Get long leg (+5 OTM) - we pay ASK
    cursor.execute("""
    SELECT ask FROM options_prices_live
    WHERE timestamp = ? AND index_symbol = ? AND strike = ? AND option_type = ?
    """, (closest_ts, index_symbol, long_strike, option_type))

    long_ask_row = cursor.fetchone()
    long_ask = long_ask_row[0] if long_ask_row else None

    if short_bid is None or long_ask is None:
        return None

    return short_bid - long_ask


def get_ic_entry_credit(conn, timestamp, index_symbol, call_short, call_long, put_short, put_long):
    """
    Get REAL entry credit for a full Iron Condor (both legs).

    Total IC Credit = (Call side) + (Put side)
    = (short_call_bid - long_call_ask) + (short_put_bid - long_put_ask)
    """
    cursor = conn.cursor()

    # Find closest future timestamp with price data
    cursor.execute("""
    SELECT DISTINCT timestamp FROM options_prices_live
    WHERE timestamp >= ? AND index_symbol = ?
    ORDER BY timestamp ASC LIMIT 1
    """, (timestamp, index_symbol))

    closest_ts_row = cursor.fetchone()
    if not closest_ts_row:
        return None

    closest_ts = closest_ts_row[0]

    # Get all 4 legs
    cursor.execute("""
    SELECT bid FROM options_prices_live
    WHERE timestamp = ? AND index_symbol = ? AND strike = ? AND option_type = 'call'
    """, (closest_ts, index_symbol, call_short))
    call_short_bid = cursor.fetchone()
    call_short_bid = call_short_bid[0] if call_short_bid else None

    cursor.execute("""
    SELECT ask FROM options_prices_live
    WHERE timestamp = ? AND index_symbol = ? AND strike = ? AND option_type = 'call'
    """, (closest_ts, index_symbol, call_long))
    call_long_ask = cursor.fetchone()
    call_long_ask = call_long_ask[0] if call_long_ask else None

    cursor.execute("""
    SELECT bid FROM options_prices_live
    WHERE timestamp = ? AND index_symbol = ? AND strike = ? AND option_type = 'put'
    """, (closest_ts, index_symbol, put_short))
    put_short_bid = cursor.fetchone()
    put_short_bid = put_short_bid[0] if put_short_bid else None

    cursor.execute("""
    SELECT ask FROM options_prices_live
    WHERE timestamp = ? AND index_symbol = ? AND strike = ? AND option_type = 'put'
    """, (closest_ts, index_symbol, put_long))
    put_long_ask = cursor.fetchone()
    put_long_ask = put_long_ask[0] if put_long_ask else None

    if any(x is None for x in [call_short_bid, call_long_ask, put_short_bid, put_long_ask]):
        return None

    # Total credit from both sides
    return (call_short_bid - call_long_ask) + (put_short_bid - put_long_ask)


def get_spread_value_at_time(conn, timestamp, index_symbol, short_strike, long_strike, option_type):
    """
    Get current spread value at a specific timestamp.
    This is what we'd pay to close the spread now.

    Args:
        option_type: 'call' or 'put'
    """
    cursor = conn.cursor()

    # Current short price (to close, we buy at ASK)
    cursor.execute("""
    SELECT ask FROM options_prices_live
    WHERE timestamp = ? AND index_symbol = ? AND strike = ? AND option_type = ?
    """, (timestamp, index_symbol, short_strike, option_type))

    short_ask_row = cursor.fetchone()
    short_ask = short_ask_row[0] if short_ask_row else None

    # Current long price (to close, we sell at BID)
    cursor.execute("""
    SELECT bid FROM options_prices_live
    WHERE timestamp = ? AND index_symbol = ? AND strike = ? AND option_type = ?
    """, (timestamp, index_symbol, long_strike, option_type))

    long_bid_row = cursor.fetchone()
    long_bid = long_bid_row[0] if long_bid_row else None

    if short_ask is None or long_bid is None:
        return None

    # Cost to close: Pay ASK for short, receive BID for long
    return short_ask - long_bid


def get_future_timestamps(conn, entry_timestamp, index_symbol, max_bars=100):
    """Get future timestamps starting from entry for tracking the position."""
    cursor = conn.cursor()

    cursor.execute("""
    SELECT DISTINCT timestamp FROM options_prices_live
    WHERE timestamp > ? AND index_symbol = ?
    ORDER BY timestamp ASC
    LIMIT ?
    """, (entry_timestamp, index_symbol, max_bars))

    return [row[0] for row in cursor.fetchall()]


def calculate_gex_polarity(conn, timestamp, index_symbol):
    """
    Calculate GEX polarity for competing peaks (for BWIC logic).
    Returns: (gpi, gex_magnitude) tuple

    GPI (GEX Polarity Index) ranges from -1 (bearish) to +1 (bullish)
    """
    cursor = conn.cursor()

    # Get competing peaks info
    cursor.execute("""
    SELECT peak1_strike, peak2_strike, peak1_gex, peak2_gex, is_competing
    FROM competing_peaks
    WHERE timestamp = ? AND index_symbol = ?
    """, (timestamp, index_symbol))

    row = cursor.fetchone()
    if not row:
        return 0.0, 0  # No competing peaks, neutral

    peak1_strike, peak2_strike, peak1_gex, peak2_gex, is_competing = row

    # Only use polarity if actually competing
    if not is_competing:
        return 0.0, 0

    if peak1_strike is None or peak2_strike is None:
        return 0.0, 0

    if peak1_gex is None or peak2_gex is None:
        return 0.0, 0

    # Calculate polarity: positive if peak1 > peak2, negative if peak2 > peak1
    total_gex = abs(peak1_gex) + abs(peak2_gex)
    if total_gex == 0:
        return 0.0, 0

    gpi = (peak1_gex - peak2_gex) / total_gex  # Ranges from -1 to +1
    gex_magnitude = total_gex

    return gpi, gex_magnitude


def apply_bwic_to_ic(setup, timestamp, index_symbol, vix, conn):
    """
    Apply Broken Wing Iron Condor (BWIC) logic to IC setups.

    Returns: Modified setup dict with BWIC strikes if applicable
    """
    # Only apply BWIC to Iron Condor setups
    if setup.strategy != 'IC':
        return setup

    # Get GEX polarity from competing peaks
    gpi, gex_magnitude = calculate_gex_polarity(conn, timestamp, index_symbol)

    # Decide if we should use BWIC
    should_use, reason = BrokenWingICCalculator.should_use_bwic(
        gex_magnitude=int(gex_magnitude) if gex_magnitude else 0,
        gpi=gpi,
        has_competing_peaks=(gpi != 0.0),
        vix=vix
    )

    if not should_use:
        return setup  # Use symmetric wings (default from get_gex_trade_setup)

    # Calculate BWIC wing widths
    widths = BrokenWingICCalculator.get_bwic_wing_widths(
        gpi=gpi,
        vix=vix,
        gex_magnitude=int(gex_magnitude) if gex_magnitude else 0,
        use_bwic=True
    )

    # Extract current strikes [call_short, call_long, put_short, put_long]
    call_short, call_long, put_short, put_long = setup.strikes

    # Apply BWIC wing widths
    call_long_new = call_short + widths.call_width
    put_long_new = put_short - widths.put_width

    # Update setup with BWIC strikes
    setup.strikes = [call_short, call_long_new, put_short, put_long_new]
    setup.description = (
        f"IC-BWIC: {call_short}/{call_long_new}C ({widths.call_width}pt) + "
        f"{put_short}/{put_long_new}P ({widths.put_width}pt) [GPI={gpi:.2f}]"
    )

    return setup


def simulate_trade(conn, entry_time, entry_credit, index_symbol, short_strike, long_strike, option_type,
                   sl_pct=0.10, tp_pct=0.50, trailing_enabled=True):
    """
    Simulate a single trade from entry to exit.
    Returns: (exit_time, exit_spread_value, exit_reason, pnl)

    Args:
        option_type: 'call' or 'put'
    """

    if entry_credit is None or entry_credit <= 0:
        return None, None, "INVALID_ENTRY", 0

    # Calculate exit thresholds
    sl_threshold = entry_credit * (1 + sl_pct)  # When we lose 10%
    tp_threshold = entry_credit * (1 - tp_pct)  # When we gain 50%

    # Trailing stop state
    trailing_activated = False
    peak_spread_value = entry_credit

    # Track position through time
    future_timestamps = get_future_timestamps(conn, entry_time, index_symbol, max_bars=200)

    for timestamp in future_timestamps:
        spread_value = get_spread_value_at_time(conn, timestamp, index_symbol, short_strike, long_strike, option_type)

        if spread_value is None:
            continue

        # Update peak for trailing stop
        if spread_value < peak_spread_value:
            peak_spread_value = spread_value

        # Check stop loss (spread value gets worse)
        if spread_value > sl_threshold:
            pnl = (entry_credit - spread_value) * 100
            return timestamp, spread_value, "STOP_LOSS", pnl

        # Check profit target (spread value improves significantly)
        if spread_value < tp_threshold:
            pnl = (entry_credit - spread_value) * 100
            return timestamp, spread_value, "PROFIT_TARGET", pnl

        # Check trailing stop (activates when in profit)
        if trailing_enabled and spread_value < (entry_credit * 0.80):  # 20% profit
            trailing_activated = True

        if trailing_activated:
            # Trail is 12% profit minimum
            trailing_threshold = entry_credit * 0.88
            if spread_value > trailing_threshold:
                pnl = (entry_credit - spread_value) * 100
                return timestamp, spread_value, "TRAILING_STOP", pnl

    # If we exit the loop, hold to expiration (end of data)
    if future_timestamps:
        final_timestamp = future_timestamps[-1]
        final_spread = get_spread_value_at_time(conn, final_timestamp, index_symbol,
                                                short_strike, long_strike)
        if final_spread is not None:
            pnl = (entry_credit - final_spread) * 100
            return final_timestamp, final_spread, "EXPIRATION", pnl

    return None, None, "NO_EXIT", 0


def run_backtest():
    """Run realistic backtest using all trades from database."""

    conn = get_optimized_connection()
    cursor = conn.cursor()

    # Get all GEX peaks (entry opportunities) - ALL peaks, not just rank 1
    # Live bot trades multiple peaks per timestamp, not just the primary one
    # Also trades both SPX and NDX, not just SPX
    query = """
    SELECT
        g.timestamp,
        g.index_symbol,
        s.underlying_price,
        s.vix,
        g.strike as pin_strike,
        g.gex,
        g.peak_rank,
        c.is_competing
    FROM gex_peaks g
    LEFT JOIN options_snapshots s ON g.timestamp = s.timestamp
        AND g.index_symbol = s.index_symbol
    LEFT JOIN competing_peaks c ON g.timestamp = c.timestamp
        AND g.index_symbol = c.index_symbol
    ORDER BY g.timestamp ASC, g.index_symbol ASC, g.peak_rank ASC
    """

    cursor.execute(query)
    snapshots = cursor.fetchall()

    trades = []
    trade_num = 0

    for snapshot in snapshots:
        timestamp, index_symbol, underlying, vix, pin_strike, gex, peak_rank, competing = snapshot

        # Filter: Only trade valid GEX peaks
        if pin_strike is None or gex is None or gex == 0:
            continue

        # Filter: Underlying must be valid
        if underlying is None:
            continue

        # Filter: VIX range
        if vix is None or vix < 12.0 or vix >= 20.0:
            continue

        # Filter: Only trade best peak ranks (1 and 2, not all 3)
        # This reduces over-trading - live bot doesn't trade every rank
        if peak_rank is not None and peak_rank > 2:
            continue

        # Use distance-based logic from get_gex_trade_setup (SINGLE SOURCE OF TRUTH)
        # This replaces the hardcoded PIN±5 logic that was causing 63% too-high entry credits
        setup = get_gex_trade_setup(pin_strike, underlying, vix, vix_threshold=20.0)

        # Skip if VIX too high or too far from PIN
        if setup.strategy == 'SKIP':
            continue

        # Apply BWIC (Broken Wing Iron Condor) logic if applicable
        # This uses GEX polarity from competing peaks to adjust wing widths asymmetrically
        if setup.strategy == 'IC':
            setup = apply_bwic_to_ic(setup, timestamp, index_symbol, vix, conn)

        # Extract strikes and spread type from setup
        if setup.strategy == 'IC':
            # Iron Condor: Calculate full IC credit (both call and put sides)
            # strikes = [call_short, call_long, put_short, put_long]
            call_short, call_long, put_short, put_long = setup.strikes
            short_strike = call_short
            long_strike = call_long
            spread_type = 'call'
            is_ic = True
            # For IC, get full credit from both legs
            entry_credit = get_ic_entry_credit(conn, timestamp, index_symbol,
                                               call_short, call_long, put_short, put_long)
        elif setup.strategy == 'CALL':
            short_strike = setup.strikes[0]
            long_strike = setup.strikes[1]
            spread_type = 'call'
            is_ic = False
            # For directional spreads, get single-leg credit
            entry_credit = get_entry_credit(conn, timestamp, index_symbol, short_strike, long_strike, spread_type)
        elif setup.strategy == 'PUT':
            short_strike = setup.strikes[0]
            long_strike = setup.strikes[1]
            spread_type = 'put'
            is_ic = False
            # For directional spreads, get single-leg credit
            entry_credit = get_entry_credit(conn, timestamp, index_symbol, short_strike, long_strike, spread_type)
        else:
            continue

        if entry_credit is None:
            continue

        # Filter: Minimum entry credit (live bot trades higher-credit spreads)
        # SPX: minimum $1.50, NDX: minimum $4.00 (these have good risk/reward)
        min_credit = 4.00 if index_symbol == 'NDX' else 1.50
        if entry_credit < min_credit:
            continue

        trade_num += 1

        # Simulate the trade with optimized parameters
        # Stop loss 15% (adjusted for 30-second data granularity)
        # Profit target 50%, Trailing stop enabled
        exit_time, exit_spread, exit_reason, pnl = simulate_trade(
            conn, timestamp, entry_credit, index_symbol, short_strike, long_strike, spread_type,
            sl_pct=0.15, tp_pct=0.50, trailing_enabled=True
        )

        if exit_time is None:
            continue

        # Extract times
        entry_hour = timestamp.split()[1] if ' ' in str(timestamp) else timestamp
        exit_hour = exit_time.split()[1] if ' ' in str(exit_time) else exit_time

        trades.append({
            'num': trade_num,
            'entry_time': entry_hour,
            'exit_time': exit_hour,
            'short_strike': short_strike,
            'long_strike': long_strike,
            'spread_type': spread_type.upper(),
            'entry_credit': entry_credit,
            'exit_spread': exit_spread,
            'exit_reason': exit_reason,
            'pnl': pnl,
            'vix': vix,
            'underlying': underlying,
            'peak_rank': peak_rank,
            'strategy': setup.description if hasattr(setup, 'description') else 'N/A',
            'is_ic': is_ic,
        })

    conn.close()

    return trades


def print_report(trades):
    """Print comprehensive backtest report."""

    print("\n" + "="*80)
    print("REALISTIC P&L BACKTEST - Using Real Option Pricing Data")
    print("="*80)
    print(f"\nDatabase: {DB_PATH}")
    print(f"Period: 2026-01-12 to 2026-01-13 (2 trading days)")
    print(f"Indices: SPX + NDX (all peaks, all ranks)")
    print(f"Data source: options_prices_live table (real bid/ask spreads)")

    if not trades:
        print("\nNo valid trades found.")
        return

    # Statistics
    winners = [t for t in trades if t['pnl'] > 0]
    losers = [t for t in trades if t['pnl'] < 0]
    total_pnl = sum(t['pnl'] for t in trades)

    print(f"\n" + "="*80)
    print("SUMMARY STATISTICS")
    print("="*80)
    print(f"Total Trades: {len(trades)}")
    print(f"Winners: {len(winners)} ({len(winners)/len(trades)*100:.1f}%)")
    print(f"Losers: {len(losers)} ({len(losers)/len(trades)*100:.1f}%)")
    print(f"\nTotal P&L: ${total_pnl:,.0f}")
    print(f"Avg P&L/Trade: ${total_pnl/len(trades):,.0f}")

    if winners:
        avg_win = sum(t['pnl'] for t in winners) / len(winners)
        max_win = max(t['pnl'] for t in winners)
        print(f"Avg Winner: ${avg_win:,.0f}")
        print(f"Max Winner: ${max_win:,.0f}")

    if losers:
        avg_loss = sum(t['pnl'] for t in losers) / len(losers)
        min_loss = min(t['pnl'] for t in losers)
        print(f"Avg Loser: ${avg_loss:,.0f}")
        print(f"Max Loser: ${min_loss:,.0f}")

    if losers:
        profit_factor = sum(t['pnl'] for t in winners) / abs(sum(t['pnl'] for t in losers))
        print(f"Profit Factor: {profit_factor:.2f}")

    # By exit reason
    print(f"\n" + "="*80)
    print("BY EXIT REASON")
    print("="*80)

    by_exit = defaultdict(lambda: {'count': 0, 'pnl': 0})
    for t in trades:
        by_exit[t['exit_reason']]['count'] += 1
        by_exit[t['exit_reason']]['pnl'] += t['pnl']

    print(f"{'Exit Reason':<20} {'Count':<8} {'Total P&L':<15} {'Avg':<12}")
    print("-"*80)
    for reason in sorted(by_exit.keys()):
        data = by_exit[reason]
        avg = data['pnl'] / data['count'] if data['count'] > 0 else 0
        print(f"{reason:<20} {data['count']:<8} ${data['pnl']:<14,.0f} ${avg:<11,.0f}")

    # Trade list
    print(f"\n" + "="*80)
    print("TRADE DETAILS")
    print("="*80)
    print(f"{'#':<4} {'Time':<10} {'T':<4} {'Rk':<3} {'Strikes':<15} {'Entry$':<8} {'Exit$':<8} {'Exit Reason':<15} {'P&L':<8}")
    print("-"*80)

    for t in trades:
        strikes = f"{t['short_strike']:.0f}/{t['long_strike']:.0f}"
        print(f"{t['num']:<4} {t['entry_time']:<10} {t['spread_type']:<4} {t['peak_rank']:<3} {strikes:<15} "
              f"${t['entry_credit']:<7.2f} ${t['exit_spread']:<7.2f} {t['exit_reason']:<15} ${t['pnl']:<7.0f}")

    print("\n" + "="*80)


if __name__ == '__main__':
    print("Running realistic P&L backtest with real option pricing data...")
    trades = run_backtest()
    print_report(trades)

    # Save report
    if trades:
        with open('/root/gamma/BACKTEST_REALISTIC_PNL.txt', 'w') as f:
            # Redirect print to file
            import sys
            from io import StringIO
            old_stdout = sys.stdout
            sys.stdout = f
            print_report(trades)
            sys.stdout = old_stdout

        print("\n✓ Report saved to: /root/gamma/BACKTEST_REALISTIC_PNL.txt")
