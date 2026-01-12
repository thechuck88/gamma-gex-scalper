#!/usr/bin/env python3
"""Test different GEX pin strength values and compare results."""

import sys
sys.path.insert(0, '/root/gamma')

from backtest_realistic_intraday import *

def test_pin_strength(pin_strength_value):
    """Run backtest with specified pin strength."""
    print(f"\n{'='*80}")
    print(f"TESTING PIN STRENGTH: {pin_strength_value}")
    print(f"{'='*80}\n")

    # Monkey-patch the IntraDayMarketSimulator to use specified pin strength
    original_init = IntraDayMarketSimulator.__init__

    def patched_init(self, start_price, gex_pin, vix, trading_hours=6.5):
        original_init(self, start_price, gex_pin, vix, trading_hours)
        self.pin_strength = pin_strength_value

    IntraDayMarketSimulator.__init__ = patched_init

    # Run backtest
    results = run_backtest()

    # Restore original
    IntraDayMarketSimulator.__init__ = original_init

    return results

if __name__ == "__main__":
    # Test different pin strengths
    pin_strengths = [0.1, 0.2, 0.3, 0.5]

    results_by_pin = {}

    for pin_strength in pin_strengths:
        # Set same random seed for fair comparison
        random.seed(42)
        np.random.seed(42)

        results_by_pin[pin_strength] = test_pin_strength(pin_strength)

    # Print comparison table
    print("\n" + "="*80)
    print("PIN STRENGTH COMPARISON")
    print("="*80)
    print(f"\n{'Pin':>6} | {'Win%':>6} | {'PF':>6} | {'Net P/L':>12} | {'Final $':>12} | {'Holds':>6} | {'Hold P/L':>10}")
    print("-" * 80)

    for pin, results in results_by_pin.items():
        print(f"{pin:>6.1f} | {results['win_rate']*100:>5.1f}% | {results['profit_factor']:>6.2f} | "
              f"${results['net_pl']:>11,.0f} | ${results['final_balance']:>11,.0f} | "
              f"{results['hold_count']:>6} | ${results['hold_pl']:>9,.0f}")

    print("="*80)
    print("\nKEY INSIGHTS:")
    print("-" * 80)

    # Calculate changes from baseline (0.2)
    baseline = results_by_pin[0.2]

    for pin in [0.1, 0.3, 0.5]:
        r = results_by_pin[pin]
        win_rate_change = (r['win_rate'] - baseline['win_rate']) * 100
        pf_change = r['profit_factor'] - baseline['profit_factor']
        pl_change = r['net_pl'] - baseline['net_pl']

        print(f"\nPin {pin:.1f} vs 0.2 baseline:")
        print(f"  Win Rate:      {win_rate_change:+.1f}% ({r['win_rate']*100:.1f}% vs {baseline['win_rate']*100:.1f}%)")
        print(f"  Profit Factor: {pf_change:+.2f} ({r['profit_factor']:.2f} vs {baseline['profit_factor']:.2f})")
        print(f"  Net P/L:       ${pl_change:+,.0f} (${r['net_pl']:,.0f} vs ${baseline['net_pl']:,.0f})")

    print("\n" + "="*80)
