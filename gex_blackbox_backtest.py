#!/usr/bin/env python3
"""
GEX Black Box Backtest - Replay recorded market data

Uses black box recorder database to backtest GEX strategy with REAL historical data.

This solves the fundamental problem: Previous backtests used FAKE GEX (random pins),
now we can backtest with ACTUAL historical GEX peaks!

Usage:
    # Backtest SPX for specific date range
    python3 gex_blackbox_backtest.py SPX 2026-01-13 2026-02-13

    # Backtest NDX for specific date range
    python3 gex_blackbox_backtest.py NDX 2026-01-13 2026-02-13

    # Backtest all available data
    python3 gex_blackbox_backtest.py SPX --all
"""

import sys
import sqlite3
import json
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, '/root/gamma')

DB_PATH = "/root/gamma/data/gex_blackbox.db"


def get_snapshots(index_symbol, start_date=None, end_date=None):
    """
    Retrieve recorded snapshots from database.

    Returns: List of dicts with snapshot data
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if start_date and end_date:
        query = """
            SELECT
                s.timestamp,
                s.underlying_price,
                s.vix,
                s.chain_data,
                c.is_competing,
                c.peak1_strike,
                c.peak2_strike,
                c.adjusted_pin
            FROM options_snapshots s
            LEFT JOIN competing_peaks c ON s.timestamp = c.timestamp
                AND s.index_symbol = c.index_symbol
            WHERE s.index_symbol = ?
                AND s.timestamp >= ?
                AND s.timestamp <= ?
            ORDER BY s.timestamp ASC
        """
        cursor.execute(query, (index_symbol, start_date, end_date))
    else:
        query = """
            SELECT
                s.timestamp,
                s.underlying_price,
                s.vix,
                s.chain_data,
                c.is_competing,
                c.peak1_strike,
                c.peak2_strike,
                c.adjusted_pin
            FROM options_snapshots s
            LEFT JOIN competing_peaks c ON s.timestamp = c.timestamp
                AND s.index_symbol = c.index_symbol
            WHERE s.index_symbol = ?
            ORDER BY s.timestamp ASC
        """
        cursor.execute(query, (index_symbol,))

    snapshots = []
    for row in cursor.fetchall():
        timestamp, price, vix, chain_json, is_competing, p1, p2, adj_pin = row
        snapshots.append({
            'timestamp': datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S'),
            'underlying_price': price,
            'vix': vix,
            'chain': json.loads(chain_json),
            'is_competing': bool(is_competing),
            'peak1_strike': p1,
            'peak2_strike': p2,
            'adjusted_pin': adj_pin
        })

    conn.close()
    return snapshots


def get_peaks_for_snapshot(index_symbol, timestamp):
    """Get top 3 peaks for a snapshot."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT peak_rank, strike, gex, distance_from_price, proximity_score
        FROM gex_peaks
        WHERE index_symbol = ?
            AND timestamp = ?
        ORDER BY peak_rank ASC
    """, (index_symbol, timestamp.strftime('%Y-%m-%d %H:%M:%S')))

    peaks = []
    for row in cursor.fetchall():
        rank, strike, gex, distance, score = row
        peaks.append({
            'rank': rank,
            'strike': strike,
            'gex': gex,
            'distance': distance,
            'score': score
        })

    conn.close()
    return peaks


def simulate_trade(entry_snapshot, exit_snapshot, strategy_type):
    """
    Simulate a single trade using recorded data.

    Args:
        entry_snapshot: Snapshot at entry time
        exit_snapshot: Snapshot at exit time (or EOD)
        strategy_type: 'IC', 'CALL', 'PUT'

    Returns:
        dict with trade results
    """
    # Simplified simulation - real backtest would need:
    # 1. Strike selection logic
    # 2. Credit calculation from bid/ask
    # 3. Exit monitoring (TP/SL checks at each snapshot)
    # 4. Precise P&L calculation

    entry_price = entry_snapshot['underlying_price']
    exit_price = exit_snapshot['underlying_price']
    price_move = exit_price - entry_price

    # Placeholder logic (would be much more detailed in production)
    if strategy_type == 'IC':
        # IC profits from low movement
        if abs(price_move) < 20:  # Stayed in cage
            pnl = 100  # Won
        else:
            pnl = -50  # Stop loss
    elif strategy_type == 'CALL':
        # Call spread (bearish) profits from down move
        if price_move < -5:
            pnl = 100
        else:
            pnl = -50
    elif strategy_type == 'PUT':
        # Put spread (bullish) profits from up move
        if price_move > 5:
            pnl = 100
        else:
            pnl = -50
    else:
        pnl = 0

    return {
        'entry_time': entry_snapshot['timestamp'],
        'exit_time': exit_snapshot['timestamp'],
        'entry_price': entry_price,
        'exit_price': exit_price,
        'price_move': price_move,
        'strategy': strategy_type,
        'pnl': pnl
    }


def run_backtest(index_symbol, start_date=None, end_date=None):
    """
    Run backtest on recorded data.

    This is a FRAMEWORK - actual implementation would need:
    1. Precise entry logic (time windows, filters)
    2. Strike selection from recorded chain
    3. Credit calculation from bid/ask
    4. Minute-by-minute exit monitoring
    5. Real P&L calculation
    """
    print(f"\n{'='*60}")
    print(f"GEX BLACK BOX BACKTEST")
    print(f"{'='*60}")
    print(f"Index: {index_symbol}")
    if start_date:
        print(f"Period: {start_date} to {end_date}")
    else:
        print(f"Period: All available data")

    # Load snapshots
    snapshots = get_snapshots(index_symbol, start_date, end_date)

    if not snapshots:
        print("\n❌ No data found for this period")
        print("\nTo collect data, run:")
        print(f"  python3 gex_blackbox_recorder.py {index_symbol}")
        return

    print(f"\n✓ Loaded {len(snapshots)} snapshots")

    first_date = snapshots[0]['timestamp'].date()
    last_date = snapshots[-1]['timestamp'].date()
    days = (last_date - first_date).days + 1

    print(f"Date range: {first_date} to {last_date} ({days} days)")

    # Group by date for daily analysis
    by_date = defaultdict(list)
    for snap in snapshots:
        by_date[snap['timestamp'].date()].append(snap)

    print(f"Trading days: {len(by_date)}")

    # Count competing peaks days
    competing_days = sum(1 for snaps in by_date.values()
                        if any(s['is_competing'] for s in snaps))
    print(f"Competing peaks days: {competing_days} ({competing_days/len(by_date)*100:.1f}%)")

    # Example: Simulate one trade per day at 9:36 AM
    print(f"\n{'='*60}")
    print("SIMULATED TRADES (Simplified)")
    print(f"{'='*60}")
    print("NOTE: This is a framework demonstration.")
    print("Real backtest would need full trade simulation logic.")
    print("")

    trades = []
    for trade_date, day_snapshots in sorted(by_date.items()):
        if not day_snapshots:
            continue

        # Entry: First snapshot of day (would be 9:36 AM in real data)
        entry_snap = day_snapshots[0]

        # Exit: Last snapshot of day (would be 3:30 PM in real data)
        exit_snap = day_snapshots[-1]

        # Determine strategy based on competing peaks
        if entry_snap['is_competing']:
            strategy = 'IC'
        else:
            # Would use actual bot logic here
            strategy = 'CALL' if entry_snap['underlying_price'] > entry_snap['peak1_strike'] else 'PUT'

        # Simulate trade
        trade = simulate_trade(entry_snap, exit_snap, strategy)
        trades.append(trade)

        print(f"{trade_date}: {strategy:4} entry={trade['entry_price']:.0f} "
              f"exit={trade['exit_price']:.0f} move={trade['price_move']:+.0f}pts "
              f"P&L=${trade['pnl']:+.0f}")

    # Summary stats
    if trades:
        total_pnl = sum(t['pnl'] for t in trades)
        winners = [t for t in trades if t['pnl'] > 0]
        losers = [t for t in trades if t['pnl'] <= 0]
        win_rate = len(winners) / len(trades) * 100 if trades else 0

        print(f"\n{'='*60}")
        print("BACKTEST RESULTS (Simplified)")
        print(f"{'='*60}")
        print(f"Total Trades: {len(trades)}")
        print(f"Winners: {len(winners)} ({win_rate:.1f}%)")
        print(f"Losers: {len(losers)}")
        print(f"Total P&L: ${total_pnl:+,.0f}")
        print(f"\n⚠️  NOTE: These are PLACEHOLDER results!")
        print(f"Real backtest needs full implementation:")
        print(f"  - Precise strike selection from recorded chains")
        print(f"  - Credit calculation from bid/ask spreads")
        print(f"  - Minute-by-minute TP/SL monitoring")
        print(f"  - Accurate P&L using real option prices")


def analyze_data_coverage(index_symbol):
    """Analyze what data is available."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            MIN(timestamp) as first_snapshot,
            MAX(timestamp) as last_snapshot,
            COUNT(*) as total_snapshots,
            COUNT(DISTINCT DATE(timestamp)) as trading_days
        FROM options_snapshots
        WHERE index_symbol = ?
    """, (index_symbol,))

    row = cursor.fetchone()
    if row[0]:
        first, last, total, days = row
        print(f"\n{'='*60}")
        print(f"DATA COVERAGE: {index_symbol}")
        print(f"{'='*60}")
        print(f"First snapshot: {first}")
        print(f"Last snapshot:  {last}")
        print(f"Total snapshots: {total:,}")
        print(f"Trading days: {days}")
        print(f"Avg snapshots/day: {total/days:.1f}")

        # Check for competing peaks
        cursor.execute("""
            SELECT COUNT(DISTINCT DATE(timestamp))
            FROM competing_peaks
            WHERE index_symbol = ? AND is_competing = 1
        """, (index_symbol,))
        competing_days = cursor.fetchone()[0]
        print(f"Days with competing peaks: {competing_days} ({competing_days/days*100:.1f}%)")

    else:
        print(f"\n❌ No data found for {index_symbol}")
        print(f"\nTo collect data, run:")
        print(f"  python3 gex_blackbox_recorder.py {index_symbol}")

    conn.close()


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 gex_blackbox_backtest.py <SPX|NDX> [start_date] [end_date]")
        print("  python3 gex_blackbox_backtest.py <SPX|NDX> --all")
        print("  python3 gex_blackbox_backtest.py <SPX|NDX> --coverage")
        print("")
        print("Examples:")
        print("  python3 gex_blackbox_backtest.py SPX 2026-01-13 2026-02-13")
        print("  python3 gex_blackbox_backtest.py NDX --all")
        print("  python3 gex_blackbox_backtest.py SPX --coverage")
        sys.exit(1)

    index_symbol = sys.argv[1].upper()

    if index_symbol not in ['SPX', 'NDX']:
        print(f"ERROR: Invalid index '{index_symbol}'. Use SPX or NDX.")
        sys.exit(1)

    # Check if database exists
    import os
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found: {DB_PATH}")
        print(f"\nFirst, collect data:")
        print(f"  python3 gex_blackbox_recorder.py {index_symbol}")
        sys.exit(1)

    # Coverage check
    if len(sys.argv) > 2 and sys.argv[2] == '--coverage':
        analyze_data_coverage(index_symbol)
        return

    # Date range
    if len(sys.argv) > 2 and sys.argv[2] == '--all':
        start_date = None
        end_date = None
    elif len(sys.argv) >= 4:
        start_date = sys.argv[2] + ' 00:00:00'
        end_date = sys.argv[3] + ' 23:59:59'
    else:
        # Default: Last 30 days
        end_date = datetime.now().strftime('%Y-%m-%d 23:59:59')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d 00:00:00')

    # Run backtest
    run_backtest(index_symbol, start_date, end_date)


if __name__ == '__main__':
    main()
