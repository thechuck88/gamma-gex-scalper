#!/usr/bin/env python3
"""
GEX Scalper Backtest: Using Blackbox Live Data with Actual Entry Times

Uses real market data collected by gex_blackbox_service_v2.py:
- Real 30-second options chain pricing
- Real GEX peaks calculated from actual market data
- Actual competing peak detection
- Entry times: 9:36 AM, 10:00 AM, 10:30 AM, 11:00 AM, 11:30 AM, 12:00 PM, 12:30 PM, 1:00 PM

Database: /root/gamma/data/gex_blackbox.db
Period: 2026-01-12 to 2026-01-13 (live trading window)
"""

import sqlite3
import json
import sys
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

DB_PATH = "/root/gamma/data/gex_blackbox.db"

# Actual entry times used in live trading (ET)
ENTRY_TIMES = [
    "09:36", "10:00", "10:30", "11:00", 
    "11:30", "12:00", "12:30", "13:00"  # 13:00 = 1 PM
]

# Optimization parameters being tested
CUTOFF_HOUR_TEST = [13, 14]  # 1 PM vs 2 PM
VIX_FLOOR_TEST = [12.0, 13.0]
RSI_ENFORCEMENT = [True, False]


def get_optimized_connection():
    """Get database connection with optimizations."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA mmap_size=30000000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def get_snapshots_by_entry_time(index_symbol, entry_time_str, cutoff_hour=13):
    """
    Get snapshots at specific entry times.
    
    Args:
        index_symbol: 'SPX' or 'NDX'
        entry_time_str: '09:36', '10:00', etc.
        cutoff_hour: Skip entries at or after this hour (13 = 1 PM)
    
    Returns:
        List of (timestamp, pin_strike, vix, competing) tuples
    """
    hour, minute = map(int, entry_time_str.split(':'))
    
    # Skip if after cutoff
    if hour >= cutoff_hour:
        return []
    
    conn = get_optimized_connection()
    cursor = conn.cursor()
    
    # Find snapshots near this time (within 2 minutes)
    query = """
    SELECT 
        s.timestamp,
        s.underlying_price,
        s.vix,
        g.strike as pin_strike,
        g.gex as pin_gex,
        c.is_competing,
        c.peak1_strike,
        c.peak2_strike,
        c.adjusted_pin
    FROM options_snapshots s
    LEFT JOIN gex_peaks g ON s.timestamp = g.timestamp 
        AND s.index_symbol = g.index_symbol 
        AND g.peak_rank = 1
    LEFT JOIN competing_peaks c ON s.timestamp = c.timestamp 
        AND s.index_symbol = c.index_symbol
    WHERE s.index_symbol = ?
        AND strftime('%H:%M', s.timestamp) BETWEEN ? AND ?
    ORDER BY s.timestamp ASC
    """
    
    # Time window: +/- 2 minutes from requested time
    time_min = f"{hour:02d}:{minute-2:02d}".replace(':', '').lstrip('0') or '0'
    time_max = f"{hour:02d}:{minute+2:02d}".replace(':', '').lstrip('0') or '0'
    
    cursor.execute(query, (index_symbol, f"{hour:02d}:{minute-2:02d}", f"{hour:02d}:{minute+2:02d}"))
    results = cursor.fetchall()
    conn.close()
    
    return results


def calculate_entry_credit(strike_price, option_type, timestamp):
    """
    Calculate entry credit from actual market prices at entry time.
    Uses bid/ask data from options_prices_live.
    """
    conn = get_optimized_connection()
    cursor = conn.cursor()
    
    # Find options prices closest to the strike
    query = """
    SELECT bid, ask, mid FROM options_prices_live
    WHERE timestamp <= ? AND strike = ? AND option_type = ?
    ORDER BY timestamp DESC LIMIT 1
    """
    
    cursor.execute(query, (timestamp, strike_price, option_type))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return 0.0
    
    bid, ask, mid = result
    return mid if mid else (bid + ask) / 2 if bid and ask else 0.0


def simulate_entry(timestamp, pin_strike, vix, is_competing, index_symbol):
    """
    Simulate trade entry at specific time with actual PIN strike.
    Returns trade setup with entry credit, spreads, etc.
    """
    if pin_strike is None or vix is None:
        return None
    
    # Determine strategy based on distance from PIN
    price_change_over_day_est = abs(pin_strike * 0.005)  # 0.5% estimate
    
    # Simple strategy: Call spread or Put spread based on GEX bias
    if not is_competing:
        # Single peak = strong bias
        strategy = 'CALL' if vix < 15 else 'PUT'
        wing_width = 5
    else:
        # Competing peaks = neutral
        strategy = 'IC'
        wing_width = 5
    
    # Calculate spreads
    short_strike = pin_strike
    long_strike = pin_strike + (wing_width if strategy == 'CALL' else -wing_width)
    
    # Get entry credit
    if strategy == 'CALL':
        short_credit = calculate_entry_credit(short_strike, 'CALL', timestamp)
        long_credit = calculate_entry_credit(long_strike, 'CALL', timestamp)
        entry_credit = max(0.01, short_credit - long_credit)
    elif strategy == 'PUT':
        short_credit = calculate_entry_credit(short_strike, 'PUT', timestamp)
        long_credit = calculate_entry_credit(long_strike, 'PUT', timestamp)
        entry_credit = max(0.01, short_credit - long_credit)
    else:  # IC
        call_short = calculate_entry_credit(short_strike + wing_width, 'CALL', timestamp)
        call_long = calculate_entry_credit(short_strike + 2*wing_width, 'CALL', timestamp)
        put_short = calculate_entry_credit(short_strike - wing_width, 'PUT', timestamp)
        put_long = calculate_entry_credit(short_strike - 2*wing_width, 'PUT', timestamp)
        entry_credit = max(0.01, (call_short - call_long) + (put_short - put_long))
    
    if entry_credit < 1.0:  # Minimum credit filter
        return None
    
    return {
        'timestamp': timestamp,
        'strategy': strategy,
        'pin_strike': short_strike,
        'entry_credit': entry_credit,
        'wing_width': wing_width,
        'vix': vix,
    }


def backtest_scenario(cutoff_hour, vix_floor, rsi_enforce):
    """
    Run complete backtest with specific scenario parameters.
    """
    conn = get_optimized_connection()
    cursor = conn.cursor()
    
    # Get all unique dates in database
    cursor.execute("""
        SELECT DISTINCT DATE(timestamp) as trading_date 
        FROM options_snapshots 
        ORDER BY trading_date ASC
    """)
    dates = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    trades = []
    total_pl = 0
    winners = 0
    losers = 0
    
    for date in dates:
        for entry_time in ENTRY_TIMES:
            hour, minute = map(int, entry_time.split(':'))
            
            # Skip if after cutoff
            if hour >= cutoff_hour:
                continue
            
            # Get snapshot at this time
            conn = get_optimized_connection()
            cursor = conn.cursor()
            
            query = """
            SELECT 
                s.timestamp,
                s.underlying_price,
                s.vix,
                g.strike as pin_strike,
                g.gex as pin_gex,
                c.is_competing
            FROM options_snapshots s
            LEFT JOIN gex_peaks g ON s.timestamp = g.timestamp 
                AND s.index_symbol = g.index_symbol 
                AND g.peak_rank = 1
            LEFT JOIN competing_peaks c ON s.timestamp = c.timestamp 
                AND s.index_symbol = c.index_symbol
            WHERE DATE(s.timestamp) = ?
                AND strftime('%H:%M', s.timestamp) BETWEEN ? AND ?
                AND s.index_symbol = 'SPX'
            ORDER BY ABS(CAST(strftime('%s', s.timestamp) AS INTEGER) - 
                        CAST(strftime('%s', ? || ' ' || ?) AS INTEGER)) ASC
            LIMIT 1
            """
            
            time_min = f"{hour:02d}:{minute-2:02d}"
            time_max = f"{hour:02d}:{minute+2:02d}"
            
            cursor.execute(query, (date, time_min, time_max, date, entry_time))
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                continue
            
            timestamp, underlying, vix, pin_strike, pin_gex, is_competing = result
            
            # Apply VIX filter
            if vix < vix_floor:
                continue
            
            # Simulate entry
            entry = simulate_entry(timestamp, pin_strike, vix, is_competing, 'SPX')
            if not entry:
                continue
            
            # Simulate exit (simplified: 50% of max profit on expiration)
            max_profit = entry['wing_width'] - entry['entry_credit']
            simulated_exit = entry['entry_credit'] - (max_profit * 0.5)  # 50% profit target
            
            # Calculate P&L
            pl = (entry['entry_credit'] - simulated_exit) * 100
            
            trades.append({
                'date': date,
                'time': entry_time,
                'pin': entry['pin_strike'],
                'credit': entry['entry_credit'],
                'pl': pl,
                'vix': vix,
            })
            
            total_pl += pl
            if pl > 0:
                winners += 1
            else:
                losers += 1
    
    total_trades = winners + losers
    win_rate = (winners / total_trades * 100) if total_trades > 0 else 0
    
    return {
        'cutoff_hour': cutoff_hour,
        'vix_floor': vix_floor,
        'rsi_enforce': rsi_enforce,
        'total_trades': total_trades,
        'winners': winners,
        'losers': losers,
        'win_rate': win_rate,
        'total_pl': total_pl,
        'avg_pl': total_pl / total_trades if total_trades > 0 else 0,
        'trades': trades,
    }


def main():
    print("\n" + "="*80)
    print("GEX SCALPER BACKTEST: Live Entry Times with Blackbox Data")
    print("="*80)
    print(f"\nDatabase: {DB_PATH}")
    print(f"Entry Times: {', '.join(ENTRY_TIMES)}")
    print(f"Testing combinations:")
    print(f"  CUTOFF_HOUR: {CUTOFF_HOUR_TEST}")
    print(f"  VIX_FLOOR: {VIX_FLOOR_TEST}")
    print()
    
    results = []
    
    for cutoff in CUTOFF_HOUR_TEST:
        for vix_floor in VIX_FLOOR_TEST:
            print(f"Testing: CUTOFF_HOUR={cutoff}, VIX_FLOOR={vix_floor}...")
            result = backtest_scenario(cutoff, vix_floor, True)
            results.append(result)
            
            print(f"  ✓ {result['total_trades']} trades")
            print(f"    WR: {result['win_rate']:.1f}%")
            print(f"    P/L: ${result['total_pl']:.2f}")
            print()
    
    # Print comparison
    print("="*80)
    print("COMPARISON TABLE")
    print("="*80)
    print(f"{'CUTOFF':<8} {'VIX_FL':<8} {'TRADES':<8} {'WR %':<8} {'P/L':<12} {'AVG/TRD':<12}")
    print("-"*80)
    
    for r in results:
        print(f"{r['cutoff_hour']:<8} {r['vix_floor']:<8.1f} {r['total_trades']:<8} "
              f"{r['win_rate']:<8.1f} ${r['total_pl']:<11.2f} ${r['avg_pl']:<11.2f}")
    
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total scenarios tested: {len(results)}")
    print(f"Best by P/L: Scenario {results.index(max(results, key=lambda x: x['total_pl']))+1}")
    print(f"  {max(results, key=lambda x: x['total_pl'])}")
    print()

if __name__ == '__main__':
    main()
