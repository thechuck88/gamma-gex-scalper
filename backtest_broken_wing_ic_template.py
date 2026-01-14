#!/usr/bin/env python3
"""
Broken Wing IC Backtest Template

This is a TEMPLATE showing how to backtest BWIC vs normal IC strategy.

To use:
1. Load historical trades from CSV (scalper.py output)
2. For each trade, recalculate with BWIC logic
3. Compare outcomes: Normal IC vs BWIC
4. Generate statistics and comparison report

NOTE: This requires actual trade data with GEX polarity values.
Current trades may not have GEX polarity logged, so this is a reference
for how to structure the backtest once data is available.

Author: Claude (2026-01-14)
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

# Import BWIC calculator
import sys
sys.path.insert(0, str(Path(__file__).parent))
from core.broken_wing_ic_calculator import BrokenWingICCalculator


class BWICBacktester:
    """
    Compare BWIC vs Normal IC strategy on historical trades.
    """

    def __init__(self, trades_csv: str):
        """
        Initialize backtest engine.

        Args:
            trades_csv: Path to trades CSV from scalper.py
        """
        self.trades_csv = trades_csv
        self.trades = self._load_trades()
        self.results = {
            'normal_ic': [],
            'bwic': [],
            'comparison': {}
        }

    def _load_trades(self) -> pd.DataFrame:
        """Load trades from CSV."""
        try:
            df = pd.read_csv(self.trades_csv)
            print(f"Loaded {len(df)} trades from {self.trades_csv}")
            return df
        except FileNotFoundError:
            print(f"ERROR: Could not find {self.trades_csv}")
            return pd.DataFrame()

    def analyze_single_trade(self, trade: pd.Series) -> Dict:
        """
        Analyze one trade with both Normal IC and BWIC logic.

        Args:
            trade: One row from trades DataFrame

        Returns:
            Dictionary with both outcomes
        """

        # Extract trade data
        entry_credit = float(trade.get('Entry_Credit', 0))
        strikes_str = trade.get('Strikes', '')
        pl_dollars = float(trade.get('P/L_$', 0))
        pl_pct = float(trade.get('P/L_%', 0))
        strategy = trade.get('Strategy', '')

        # Only analyze IC trades
        if strategy != 'IC':
            return None

        # For backtest, assume:
        # - Normal IC: 20-point equal wings (baseline)
        # - BWIC: Asymmetric wings based on simulated GEX

        results = {
            'strategy': strategy,
            'entry_credit': entry_credit,
            'actual_pnl': pl_dollars,
            'actual_pnl_pct': pl_pct,
            'actual_won': 1 if pl_dollars > 0 else 0
        }

        # Simulate BWIC calculation (example)
        # In reality, would use actual GEX data from trade logs
        gpi_simulated = np.random.uniform(-0.5, +0.5)  # Simulate GEX polarity
        magnitude_simulated = np.random.uniform(5e9, 20e9)  # Simulate GEX magnitude

        should_use_bwic, reason = BrokenWingICCalculator.should_use_bwic(
            gex_magnitude=magnitude_simulated,
            gpi=gpi_simulated,
            has_competing_peaks=False,
            vix=18  # Assume normal VIX
        )

        results['gpi_simulated'] = gpi_simulated
        results['magnitude_simulated'] = magnitude_simulated
        results['should_use_bwic'] = should_use_bwic

        if should_use_bwic:
            # Simulate BWIC outcome
            # Assumption: BWIC reduces loss by 30% when wrong, keeps profit when right
            if results['actual_won']:
                # Correct directional bias - slight less profit (narrower wing)
                results['bwic_pnl'] = results['actual_pnl'] * 0.95
                results['bwic_won'] = 1
            else:
                # Incorrect directional bias - much smaller loss (narrow wing protection)
                results['bwic_pnl'] = results['actual_pnl'] * 0.4  # Lose 40% instead of 100%
                results['bwic_won'] = 0
        else:
            # Not using BWIC, same as normal IC
            results['bwic_pnl'] = results['actual_pnl']
            results['bwic_won'] = results['actual_won']

        return results

    def run_backtest(self) -> Dict:
        """
        Run full backtest comparing Normal IC vs BWIC.

        Returns:
            Dictionary with comparative statistics
        """

        print("\n" + "=" * 70)
        print("BWIC vs Normal IC Backtest")
        print("=" * 70)

        # Filter to IC trades only
        ic_trades = self.trades[self.trades['Strategy'] == 'IC']
        print(f"\nTesting {len(ic_trades)} Iron Condor trades")

        # Analyze each trade
        results = []
        for idx, trade in ic_trades.iterrows():
            result = self.analyze_single_trade(trade)
            if result:
                results.append(result)

        if not results:
            print("ERROR: No IC trades found in data")
            return {}

        # Convert to DataFrame for analysis
        df_results = pd.DataFrame(results)

        # Calculate statistics
        stats = {
            'normal_ic': self._calculate_stats(df_results, 'actual'),
            'bwic': self._calculate_stats(df_results, 'bwic'),
        }

        # Print comparison
        self._print_comparison(stats)

        return {
            'trades': df_results,
            'stats': stats
        }

    def _calculate_stats(self, df: pd.DataFrame, prefix: str) -> Dict:
        """Calculate statistics for one strategy."""

        if prefix == 'actual':
            pnl_col = 'actual_pnl'
            win_col = 'actual_won'
        else:
            pnl_col = 'bwic_pnl'
            win_col = 'bwic_won'

        pnl = df[pnl_col]
        wins = df[win_col]

        total_trades = len(df)
        total_wins = wins.sum()
        total_losses = total_trades - total_wins

        net_pnl = pnl.sum()
        avg_win = pnl[pnl > 0].mean() if (pnl > 0).any() else 0
        avg_loss = pnl[pnl <= 0].mean() if (pnl <= 0).any() else 0
        max_loss = pnl.min()
        max_win = pnl.max()

        win_rate = total_wins / total_trades if total_trades > 0 else 0
        profit_factor = (-avg_win / avg_loss) if avg_loss != 0 else float('inf')

        # Sharpe ratio (simplified - no risk-free rate)
        returns = pnl / df['entry_credit']
        daily_returns = returns
        sharpe = daily_returns.mean() / daily_returns.std() if daily_returns.std() != 0 else 0

        # Drawdown
        cumulative_pnl = pnl.cumsum()
        running_max = cumulative_pnl.expanding().max()
        drawdown = cumulative_pnl - running_max
        max_drawdown = drawdown.min()

        return {
            'total_trades': total_trades,
            'total_wins': total_wins,
            'total_losses': total_losses,
            'net_pnl': net_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'max_win': max_win,
            'max_loss': max_loss,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown
        }

    def _print_comparison(self, stats: Dict):
        """Print formatted comparison table."""

        normal = stats['normal_ic']
        bwic = stats['bwic']

        print("\n" + "=" * 70)
        print(f"{'Metric':<30} {'Normal IC':>15} {'BWIC':>15} {'Improvement':>15}")
        print("=" * 70)

        metrics = [
            ('Total P&L', normal['net_pnl'], bwic['net_pnl']),
            ('Total Trades', normal['total_trades'], bwic['total_trades']),
            ('Wins', normal['total_wins'], bwic['total_wins']),
            ('Win Rate', normal['win_rate'], bwic['win_rate']),
            ('Avg Winner', normal['avg_win'], bwic['avg_win']),
            ('Avg Loser', normal['avg_loss'], bwic['avg_loss']),
            ('Profit Factor', normal['profit_factor'], bwic['profit_factor']),
            ('Max Win', normal['max_win'], bwic['max_win']),
            ('Max Loss', normal['max_loss'], bwic['max_loss']),
            ('Max Drawdown', normal['max_drawdown'], bwic['max_drawdown']),
            ('Sharpe Ratio', normal['sharpe_ratio'], bwic['sharpe_ratio']),
        ]

        for metric_name, normal_val, bwic_val in metrics:
            if isinstance(normal_val, int):
                normal_str = f"{normal_val}"
                bwic_str = f"{bwic_val}"
                improvement_str = f"{bwic_val - normal_val:+.0f}"
            elif metric_name == 'Win Rate':
                normal_str = f"{normal_val*100:.1f}%"
                bwic_str = f"{bwic_val*100:.1f}%"
                improvement_str = f"{(bwic_val - normal_val)*100:+.1f}%"
            elif metric_name in ['Profit Factor', 'Sharpe Ratio']:
                normal_str = f"{normal_val:.2f}"
                bwic_str = f"{bwic_val:.2f}"
                improvement_str = f"{(bwic_val - normal_val):+.2f}"
            else:
                normal_str = f"${normal_val:,.0f}"
                bwic_str = f"${bwic_val:,.0f}"
                improvement_str = f"${bwic_val - normal_val:+,.0f}"

            print(f"{metric_name:<30} {normal_str:>15} {bwic_str:>15} {improvement_str:>15}")

        print("=" * 70)

        # Decision logic
        print("\nDecision Logic:")

        improvement_sharpe = (bwic['sharpe_ratio'] - normal['sharpe_ratio']) / normal['sharpe_ratio'] if normal['sharpe_ratio'] > 0 else 0
        improvement_dd = (normal['max_drawdown'] - bwic['max_drawdown']) / abs(normal['max_drawdown']) if normal['max_drawdown'] != 0 else 0
        improvement_max_loss = (normal['max_loss'] - bwic['max_loss']) / abs(normal['max_loss']) if normal['max_loss'] != 0 else 0

        print(f"  Sharpe improvement: {improvement_sharpe*100:+.1f}%")
        print(f"  Max drawdown improvement: {improvement_dd*100:+.1f}%")
        print(f"  Max loss improvement: {improvement_max_loss*100:+.1f}%")

        if improvement_sharpe >= 0.10 and improvement_dd >= 0.15:
            print(f"\n  ✓ BWIC RECOMMENDED (Sharpe +{improvement_sharpe*100:.1f}%, DD -{improvement_dd*100:.1f}%)")
        elif improvement_sharpe >= 0.05 or improvement_dd >= 0.10:
            print(f"\n  ~ BWIC NEUTRAL (marginal improvements, needs more data)")
        else:
            print(f"\n  ✗ BWIC NOT RECOMMENDED (no significant improvement)")


# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    # Path to trades CSV (from scalper output)
    trades_csv = "/root/gamma/data/trades.csv"

    # Check if file exists
    if not Path(trades_csv).exists():
        print(f"Note: {trades_csv} not found")
        print("\nTo run backtest:")
        print(f"  1. Generate trades with scalper.py")
        print(f"  2. Trades will be logged to {trades_csv}")
        print(f"  3. Run this script: python backtest_broken_wing_ic_template.py")
        print("\nFor now, showing test with simulated data...")

        # Create dummy data for demonstration
        dummy_trades = pd.DataFrame({
            'Strategy': ['IC'] * 50 + ['CALL'] * 30 + ['PUT'] * 20,
            'Entry_Credit': np.random.uniform(0.5, 2.0, 100),
            'Strikes': ['6050/6070C + 6030/6010P'] * 100,
            'P/L_$': np.concatenate([
                np.random.normal(80, 150, 50),      # IC wins ~60% WR
                np.random.normal(50, 120, 30),      # Call wins
                np.random.normal(30, 100, 20)       # Put wins
            ]),
            'P/L_%': np.random.uniform(-0.5, 0.5, 100),
        })

        backtest = BWICBacktester.__new__(BWICBacktester)
        backtest.trades = dummy_trades
        backtest.trades_csv = "simulated"

    else:
        backtest = BWICBacktester(trades_csv)

    # Run backtest
    results = backtest.run_backtest()

    # Print sample trades
    if 'trades' in results:
        print("\n" + "=" * 70)
        print("Sample Trades (first 5):")
        print("=" * 70)
        print(results['trades'].head(5).to_string())
