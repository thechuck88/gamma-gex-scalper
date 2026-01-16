#!/usr/bin/env python3
"""
autoscaling.py - Half-Kelly Position Sizing for GEX Trading

Calculates optimal position size based on:
- Account balance
- Trade history (rolling 50-trade statistics)
- Max risk per contract

Usage:
    from autoscaling import calculate_position_size

    position_size = calculate_position_size(
        account_balance=25000,
        max_risk_per_contract=250,
        mode='PAPER'
    )
"""

import os
import json
import csv
from datetime import datetime, timedelta
import numpy as np

# Configurable base directory
GAMMA_HOME = os.environ.get('GAMMA_HOME', '/root/gamma')

# Configuration
STARTING_CAPITAL = 20000        # Reference starting capital
MAX_CONTRACTS = 3               # Conservative max for $20k account
BOOTSTRAP_TRADES = 10           # Use 1 contract until we have this many trades
ROLLING_WINDOW = 50             # Use last N trades for statistics
SAFETY_HALT_PCT = 0.50          # Stop trading if balance < 50% of starting capital

# File paths
BALANCE_FILE = f"{GAMMA_HOME}/data/account_balance.json"
TRADES_FILE = f"{GAMMA_HOME}/data/trades.csv"


def load_account_balance(mode='PAPER'):
    """
    Load current account balance from account_balance.json.

    Returns:
        float: Current account balance
    """
    if not os.path.exists(BALANCE_FILE):
        # Initialize if doesn't exist
        return STARTING_CAPITAL

    try:
        with open(BALANCE_FILE, 'r') as f:
            data = json.load(f)
            balance = data.get('balance', STARTING_CAPITAL)
            return float(balance)
    except Exception as e:
        print(f"[AUTOSCALING] Warning: Could not load balance from {BALANCE_FILE}: {e}")
        return STARTING_CAPITAL


def load_trade_history(mode='PAPER', max_trades=ROLLING_WINDOW):
    """
    Load recent trade history from trades.csv.

    Args:
        mode: 'PAPER' or 'REAL' (filters by account ID)
        max_trades: Maximum number of recent trades to load

    Returns:
        list: List of P/L values (per contract) from recent trades
    """
    if not os.path.exists(TRADES_FILE):
        return []

    try:
        # Determine account ID based on mode
        from config import PAPER_ACCOUNT_ID, LIVE_ACCOUNT_ID
        account_id = LIVE_ACCOUNT_ID if mode == 'REAL' else PAPER_ACCOUNT_ID

        # Read trades CSV
        trades = []
        with open(TRADES_FILE, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Filter by account ID and mode
                if row.get('Account_ID') != account_id:
                    continue

                # Skip incomplete trades (no P/L yet)
                if not row.get('P/L_$') or row.get('P/L_$').strip() == '':
                    continue

                # Extract P/L per contract
                try:
                    # Column name is "P/L_$" not "P/L_Dollar"
                    pl_dollar = float(row.get('P/L_$', 0))

                    # Position_Size column may not exist (old data), default to 1
                    position_size = int(row.get('Position_Size', 1))

                    # Calculate per-contract P/L
                    pl_per_contract = pl_dollar / position_size if position_size > 0 else pl_dollar
                    trades.append(pl_per_contract)
                except (ValueError, TypeError):
                    continue

        # Return most recent trades (up to max_trades)
        return trades[-max_trades:] if trades else []

    except Exception as e:
        print(f"[AUTOSCALING] Warning: Could not load trades from {TRADES_FILE}: {e}")
        return []


def calculate_position_size(account_balance=None, max_risk_per_contract=800, mode='PAPER', verbose=True):
    """
    Calculate position size using Half-Kelly formula.

    Half-Kelly Formula:
        Kelly% = (Win_Rate * Avg_Win - Loss_Rate * Avg_Loss) / Avg_Win
        Half_Kelly% = Kelly% / 2
        Position_Size = (Account_Balance * Half_Kelly%) / Max_Risk_Per_Contract

    Args:
        account_balance: Current account balance (if None, loads from file)
        max_risk_per_contract: Maximum loss per contract
            - GEX PIN spreads: $250 ($5 wide - $2.50 credit)
            - OTM Single-Sided: $900 ($10 wide - $1.00 credit)
        mode: 'PAPER' or 'REAL'
        verbose: Print logging messages

    Returns:
        int: Number of contracts to trade (0 = safety halt, 1-MAX_CONTRACTS)
    """
    # Load account balance if not provided
    if account_balance is None:
        account_balance = load_account_balance(mode)

    # Safety halt: Stop trading if account drops below 50%
    if account_balance < STARTING_CAPITAL * SAFETY_HALT_PCT:
        if verbose:
            print(f"[AUTOSCALING] ⚠️ SAFETY HALT: Balance ${account_balance:,.0f} < ${STARTING_CAPITAL * SAFETY_HALT_PCT:,.0f}")
            print(f"[AUTOSCALING] Position size = 0 (trading halted)")
        return 0

    # Load trade history
    trade_history = load_trade_history(mode, max_trades=ROLLING_WINDOW)

    # Bootstrap phase: Use 1 contract until we have enough trades
    if len(trade_history) < BOOTSTRAP_TRADES:
        if verbose:
            print(f"[AUTOSCALING] Bootstrap phase: {len(trade_history)}/{BOOTSTRAP_TRADES} trades")
            print(f"[AUTOSCALING] Position size = 1 (building statistics)")
        return 1

    # Separate winners and losers
    winners = [t for t in trade_history if t > 0]
    losers = [t for t in trade_history if t <= 0]

    # Safety check: Need both winners and losers for Kelly calculation
    if not winners or not losers:
        if verbose:
            print(f"[AUTOSCALING] Insufficient data: {len(winners)} winners, {len(losers)} losers")
            print(f"[AUTOSCALING] Position size = 1 (need both wins and losses)")
        return 1

    # Calculate statistics
    total_trades = len(trade_history)
    win_rate = len(winners) / total_trades
    loss_rate = len(losers) / total_trades
    avg_win = np.mean(winners)
    avg_loss = abs(np.mean(losers))

    # Kelly% = (p * W - q * L) / W
    # where p = win rate, W = avg win, q = loss rate, L = avg loss
    kelly_pct = (win_rate * avg_win - loss_rate * avg_loss) / avg_win

    # Half-Kelly for conservative sizing
    half_kelly_pct = kelly_pct / 2

    # Calculate position size based on max risk
    # Position Size = (Account * Half_Kelly%) / Max_Risk_Per_Contract
    if half_kelly_pct > 0:
        contracts = (account_balance * half_kelly_pct) / max_risk_per_contract
        contracts = int(contracts)
        contracts = max(1, contracts)  # Always trade at least 1 contract
        contracts = min(contracts, MAX_CONTRACTS)  # Cap at maximum
    else:
        # Negative Kelly means expected loss (shouldn't happen with good strategy)
        contracts = 1

    if verbose:
        print(f"[AUTOSCALING] Account Balance: ${account_balance:,.0f}")
        print(f"[AUTOSCALING] Trade History: {total_trades} trades ({len(winners)} wins, {len(losers)} losses)")
        print(f"[AUTOSCALING] Win Rate: {win_rate*100:.1f}% | Avg Win: ${avg_win:.2f} | Avg Loss: ${avg_loss:.2f}")
        print(f"[AUTOSCALING] Kelly%: {kelly_pct*100:.2f}% | Half-Kelly%: {half_kelly_pct*100:.2f}%")
        print(f"[AUTOSCALING] Max Risk: ${max_risk_per_contract} | Position Size: {contracts} contract(s)")

    return contracts


def get_max_risk_for_strategy(strategy, entry_credit):
    """
    Calculate max risk per contract based on strategy type.

    Args:
        strategy: Strategy name from scalper
            - 'CALL' or 'PUT': Directional GEX spreads ($5 wide)
            - 'IC': Iron Condor ($5 wide each side)
            - 'OTM_SINGLE_SIDED': Single-sided OTM spread ($10 wide)
            - 'OTM_IRON_CONDOR': OTM IC ($10 wide each side)
        entry_credit: Entry credit received (used for calculation)

    Returns:
        float: Max risk per contract in dollars
    """
    if strategy in ['CALL', 'PUT', 'IC']:
        # GEX strategies: $5 wide spreads, ~$2.50 credit
        # Max risk = ($5 - $2.50) * 100 = $250
        # IC has 2 spreads but we size based on total credit
        return 250

    elif strategy in ['OTM_SINGLE_SIDED', 'OTM_IRON_CONDOR']:
        # OTM spreads: $10 wide, variable credit
        # Max risk = ($10 - credit) * 100
        spread_width = 10.0
        max_risk = (spread_width - entry_credit) * 100
        # Conservative minimum: assume at least $1.00 credit
        max_risk = min(max_risk, 900)  # Cap at $900 for safety
        return max_risk

    else:
        # Default: Conservative estimate for unknown strategies
        return 800


if __name__ == '__main__':
    """Test autoscaling with current account data."""
    print("=" * 80)
    print("AUTOSCALING TEST")
    print("=" * 80)
    print()

    # Test for PAPER mode
    print("PAPER MODE:")
    print("-" * 80)
    position_size = calculate_position_size(mode='PAPER', max_risk_per_contract=250)
    print()

    # Show max risk for different strategies
    print("MAX RISK CALCULATION:")
    print("-" * 80)
    print(f"CALL spread (credit $2.50): ${get_max_risk_for_strategy('CALL', 2.50):.0f}")
    print(f"PUT spread (credit $2.50): ${get_max_risk_for_strategy('PUT', 2.50):.0f}")
    print(f"Iron Condor (credit $2.70): ${get_max_risk_for_strategy('IC', 2.70):.0f}")
    print(f"OTM Single-Sided (credit $1.00): ${get_max_risk_for_strategy('OTM_SINGLE_SIDED', 1.00):.0f}")
    print(f"OTM Single-Sided (credit $0.50): ${get_max_risk_for_strategy('OTM_SINGLE_SIDED', 0.50):.0f}")
    print()
