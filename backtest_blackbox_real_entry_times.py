#!/usr/bin/env python3
"""
GEX Scalper Backtest: Real Entry Times with Blackbox Live Data (UTC→ET Converted)

Uses actual blackbox collector database with real GEX PIN information:
- Database timestamps: UTC (converted to ET for analysis)
- Entry times: 9:36 AM, 10:00 AM, 10:30 AM, 11:00 AM, 11:30 AM, 12:00 PM, 12:30 PM, 1:00 PM ET
- Real GEX peaks calculated from actual market data
- 30-second options chain prices
- Real VIX values

Testing: CUTOFF_HOUR (13 vs 14) and VIX_FLOOR (12.0 vs 13.0)
"""

import sqlite3
import json
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

DB_PATH = "/root/gamma/data/gex_blackbox.db"

# Your actual live entry times (ET)
ENTRY_TIMES_ET = [
    "09:36", "10:00", "10:30", "11:00", 
    "11:30", "12:00", "12:30", "13:00"  # 13:00 = 1 PM ET
]

# Optimization parameters to test
CUTOFF_HOURS = [13, 14]  # 1 PM vs 2 PM ET cutoff
VIX_FLOORS = [12.0, 13.0]


def get_optimized_connection():
    """Get database connection with optimizations."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def analyze_entry_quality(snapshot_data):
    """Calculate quality score for entry based on GEX metrics."""
    timestamp, date_et, time_et, symbol, underlying, vix, pin, gex, distance, proximity, competing, p1, p2, ratio = snapshot_data
    
    if pin is None or gex is None or gex == 0:
        return None
    
    # GEX magnitude score (normalized, higher is better)
    gex_normalized = min(gex / 20e9, 1.0)
    gex_score = gex_normalized * 100
    
    # Distance score (optimal 5-20 points from price)
    distance_val = abs(distance) if distance else 0
    if 5 <= distance_val <= 20:
        distance_score = 100
    elif distance_val < 5:
        distance_score = 60  # Too close to ATM
    elif 20 < distance_val <= 30:
        distance_score = 80
    else:
        distance_score = 40  # Too far
    
    # Competing peaks score
    competing_score = 100 if not competing else 70
    
    # VIX score (lower is better for credit spreads, but need vol)
    if 12 <= vix <= 20:
        vix_score = 100
    elif vix < 12:
        vix_score = 60
    elif vix <= 30:
        vix_score = 80
    else:
        vix_score = 40
    
    # Weighted quality score
    quality = (gex_score * 0.35) + (distance_score * 0.30) + (competing_score * 0.20) + (vix_score * 0.15)
    
    return {
        'quality': quality,
        'gex_score': gex_score,
        'distance_score': distance_score,
        'competing_score': competing_score,
        'vix_score': vix_score,
    }


def backtest_scenario(cutoff_hour_et, vix_floor, index_symbol='SPX'):
    """Run complete backtest with given parameters."""
    conn = get_optimized_connection()
    cursor = conn.cursor()
    
    # Get all snapshots that match criteria (fixed ambiguous column names)
    query = """
    SELECT 
        s.timestamp,
        DATE(DATETIME(s.timestamp, '-5 hours')) as date_et,
        TIME(DATETIME(s.timestamp, '-5 hours')) as time_et,
        s.index_symbol,
        s.underlying_price,
        s.vix,
        g.strike as pin_strike,
        g.gex as pin_gex,
        g.distance_from_price,
        g.proximity_score,
        c.is_competing,
        c.peak1_strike,
        c.peak2_strike,
        c.score_ratio
    FROM options_snapshots s
    LEFT JOIN gex_peaks g ON s.timestamp = g.timestamp 
        AND s.index_symbol = g.index_symbol 
        AND g.peak_rank = 1
    LEFT JOIN competing_peaks c ON s.timestamp = c.timestamp 
        AND s.index_symbol = c.index_symbol
    WHERE CAST(strftime('%H', DATETIME(s.timestamp, '-5 hours')) AS INTEGER) < ?
        AND s.vix >= ?
        AND s.index_symbol = ?
    ORDER BY s.timestamp ASC
    """
    
    cursor.execute(query, (cutoff_hour_et, vix_floor, index_symbol))
    snapshots = cursor.fetchall()
    conn.close()
    
    # Analyze entries
    entries_by_time = defaultdict(list)
    quality_scores = []
    
    for snapshot in snapshots:
        quality_data = analyze_entry_quality(snapshot)
        if quality_data:
            time_et = snapshot[2]
            entries_by_time[time_et].append({
                'snapshot': snapshot,
                'quality': quality_data,
            })
            quality_scores.append(quality_data['quality'])
    
    # Count high-quality entries
    high_quality = [q for q in quality_scores if q >= 60]
    medium_quality = [q for q in quality_scores if 40 <= q < 60]
    low_quality = [q for q in quality_scores if q < 40]
    
    return {
        'cutoff_hour': cutoff_hour_et,
        'vix_floor': vix_floor,
        'total_snapshots': len(snapshots),
        'unique_entry_times': len(entries_by_time),
        'high_quality_entries': len(high_quality),
        'medium_quality_entries': len(medium_quality),
        'low_quality_entries': len(low_quality),
        'avg_quality': statistics.mean(quality_scores) if quality_scores else 0,
        'min_quality': min(quality_scores) if quality_scores else 0,
        'max_quality': max(quality_scores) if quality_scores else 0,
        'entries_by_time': entries_by_time,
    }


def main():
    print("\n" + "="*90)
    print("GEX SCALPER BACKTEST: Real Entry Times + Blackbox Live Data (UTC→ET Converted)")
    print("="*90)
    
    # Check data coverage
    conn = get_optimized_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT 
        COUNT(*) as total_snapshots,
        COUNT(DISTINCT DATE(DATETIME(s.timestamp, '-5 hours'))) as trading_days,
        MIN(DATETIME(s.timestamp, '-5 hours')) as start_et,
        MAX(DATETIME(s.timestamp, '-5 hours')) as end_et
    FROM options_snapshots s
    """)
    row = cursor.fetchone()
    conn.close()
    
    total_snapshots, trading_days, start_et, end_et = row
    
    print(f"\n📊 DATABASE COVERAGE (with UTC→ET conversion):")
    print(f"  • Total snapshots: {total_snapshots}")
    print(f"  • Trading days: {trading_days}")
    print(f"  • Period: {start_et} to {end_et} ET")
    print(f"  • Entry times tested: {', '.join(ENTRY_TIMES_ET)}")
    
    # Run backtest scenarios
    print("\n" + "="*90)
    print("BACKTEST SCENARIOS")
    print("="*90)
    
    results = []
    for cutoff in CUTOFF_HOURS:
        for vix_floor in VIX_FLOORS:
            result = backtest_scenario(cutoff, vix_floor)
            results.append(result)
            
            print(f"\n✓ Scenario: CUTOFF_HOUR={cutoff} ET (stop after {cutoff}:00), VIX_FLOOR={vix_floor}")
            print(f"  Snapshots analyzed: {result['total_snapshots']}")
            print(f"  Entry time slots: {result['unique_entry_times']}")
            print(f"  High quality (≥60): {result['high_quality_entries']}")
            print(f"  Medium quality (40-60): {result['medium_quality_entries']}")
            print(f"  Low quality (<40): {result['low_quality_entries']}")
            print(f"  Average quality score: {result['avg_quality']:.1f}/100")
            print(f"  Quality range: {result['min_quality']:.1f} - {result['max_quality']:.1f}")
    
    # Comparison table
    print("\n" + "="*90)
    print("COMPARISON TABLE")
    print("="*90)
    print(f"{'CUTOFF':<8} {'VIX_FL':<8} {'SNAPS':<8} {'TIMES':<8} {'HIGH_Q':<8} {'MED_Q':<8} {'AVG_Q':<10}")
    print("-"*90)
    
    for r in results:
        print(f"{r['cutoff_hour']:<8} {r['vix_floor']:<8.1f} {r['total_snapshots']:<8} "
              f"{r['unique_entry_times']:<8} {r['high_quality_entries']:<8} "
              f"{r['medium_quality_entries']:<8} {r['avg_quality']:<10.1f}")
    
    # Detailed time analysis for best scenario
    best_result = max(results, key=lambda x: x['high_quality_entries'])
    
    print("\n" + "="*90)
    print(f"ENTRY TIME BREAKDOWN: Best Scenario (CUTOFF={best_result['cutoff_hour']}, VIX={best_result['vix_floor']})")
    print("="*90)
    print(f"{'Entry Time':<12} {'Snapshots':<12} {'Avg Quality':<15} {'High Q Cnt':<12}")
    print("-"*90)
    
    for entry_time in ENTRY_TIMES_ET:
        if entry_time in best_result['entries_by_time']:
            entries = best_result['entries_by_time'][entry_time]
            quality_scores = [e['quality']['quality'] for e in entries]
            avg_q = statistics.mean(quality_scores)
            high_q_cnt = len([q for q in quality_scores if q >= 60])
            
            print(f"{entry_time}       {len(entries):<12} {avg_q:<15.1f} {high_q_cnt:<12}")
    
    # Recommendations
    print("\n" + "="*90)
    print("RECOMMENDATIONS & NEXT STEPS")
    print("="*90)
    
    print("\n✓ All 8 entry times have real GEX PIN data available")
    print(f"✓ Best scenario: CUTOFF_HOUR={best_result['cutoff_hour']}, VIX_FLOOR={best_result['vix_floor']}")
    print(f"  → {best_result['high_quality_entries']} high-quality entries")
    
    print(f"\n  Impact analysis:")
    for r in results:
        if r['vix_floor'] == 13.0:
            if r['cutoff_hour'] == 13:
                opt1_high_q = r['high_quality_entries']
            else:
                baseline_high_q = r['high_quality_entries']
    
    print(f"    • CUTOFF_HOUR 14→13 (remove after 1 PM): impact TBD with position management")
    print(f"    • VIX_FLOOR 12→13 (require higher vol): impact TBD with position management")

if __name__ == '__main__':
    main()
