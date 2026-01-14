#!/usr/bin/env python3
"""
replay_state.py - State management and trade tracking

Manages:
- Open positions
- Trade history
- P&L calculation
- Statistics generation
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum


class ExitReason(Enum):
    """Reasons for exiting a trade."""
    PROFIT_TARGET = "PROFIT_TARGET"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    EXPIRATION = "EXPIRATION"
    MANUAL = "MANUAL"


@dataclass
class ReplayTrade:
    """Represents a single trade during replay."""

    trade_id: int
    entry_time: datetime
    entry_credit: float
    short_strike: float
    long_strike: float
    spread_type: str  # 'CALL' or 'PUT'
    index_symbol: str
    vix_at_entry: float

    exit_time: Optional[datetime] = None
    exit_spread_value: Optional[float] = None
    exit_reason: Optional[ExitReason] = None
    pnl_dollars: Optional[float] = None
    pnl_percent: Optional[float] = None

    # Strategy info
    is_ic: bool = False
    peak_rank: int = 1
    description: str = ""

    # Tracking state
    peak_spread_value: float = field(default_factory=float)
    valley_spread_value: Optional[float] = None
    trailing_stop_activated: bool = False
    last_update_time: Optional[datetime] = None

    def mark_closed(self, exit_time: datetime, exit_spread_value: float,
                   exit_reason: ExitReason):
        """Mark trade as closed."""
        self.exit_time = exit_time
        self.exit_spread_value = exit_spread_value
        self.exit_reason = exit_reason

        # Calculate P&L
        # P&L = (entry_credit - exit_spread_value) * 100
        self.pnl_dollars = (self.entry_credit - exit_spread_value) * 100

        if self.entry_credit > 0:
            self.pnl_percent = (self.entry_credit - exit_spread_value) / self.entry_credit
        else:
            self.pnl_percent = 0.0

        self.last_update_time = exit_time

    def is_open(self) -> bool:
        """Check if trade is still open."""
        return self.exit_time is None

    def duration_seconds(self) -> float:
        """Get duration of trade in seconds."""
        if self.is_open():
            return 0.0

        delta = self.exit_time - self.entry_time
        return delta.total_seconds()

    def __str__(self) -> str:
        """String representation."""
        status = "OPEN" if self.is_open() else f"CLOSED ({self.exit_reason.value})"
        entry_str = self.entry_time.strftime("%H:%M:%S") if self.entry_time else "N/A"
        pnl_str = f"${self.pnl_dollars:+.0f}" if self.pnl_dollars is not None else "N/A"

        return (f"Trade {self.trade_id}: {self.index_symbol} {self.spread_type} "
                f"@ {entry_str} - Entry: ${self.entry_credit:.2f}, P&L: {pnl_str} [{status}]")


@dataclass
class ReplayStateManager:
    """Manages all state during replay simulation."""

    starting_balance: float = 100000.0

    # State
    current_balance: float = field(default_factory=float)
    open_trades: Dict[int, ReplayTrade] = field(default_factory=dict)
    closed_trades: List[ReplayTrade] = field(default_factory=list)
    next_trade_id: int = 1

    # Statistics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    break_even_trades: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    peak_balance: float = field(default_factory=float)

    def __post_init__(self):
        """Initialize balance."""
        self.current_balance = self.starting_balance
        self.peak_balance = self.starting_balance

    def open_trade(self, entry_time: datetime, entry_credit: float,
                  short_strike: float, long_strike: float,
                  spread_type: str, index_symbol: str, vix: float,
                  is_ic: bool = False, peak_rank: int = 1,
                  description: str = "") -> ReplayTrade:
        """
        Open a new trade.

        Returns:
            ReplayTrade object
        """
        trade_id = self.next_trade_id
        self.next_trade_id += 1

        trade = ReplayTrade(
            trade_id=trade_id,
            entry_time=entry_time,
            entry_credit=entry_credit,
            short_strike=short_strike,
            long_strike=long_strike,
            spread_type=spread_type,
            index_symbol=index_symbol,
            vix_at_entry=vix,
            is_ic=is_ic,
            peak_rank=peak_rank,
            description=description,
            peak_spread_value=entry_credit
        )

        self.open_trades[trade_id] = trade
        return trade

    def close_trade(self, trade_id: int, exit_time: datetime,
                   exit_spread_value: float, exit_reason: ExitReason):
        """
        Close a trade.

        Returns:
            ReplayTrade object
        """
        if trade_id not in self.open_trades:
            raise ValueError(f"Trade {trade_id} not found in open trades")

        trade = self.open_trades.pop(trade_id)
        trade.mark_closed(exit_time, exit_spread_value, exit_reason)
        self.closed_trades.append(trade)

        # Update statistics
        self.total_trades += 1
        self.total_pnl += trade.pnl_dollars
        self.current_balance += trade.pnl_dollars

        if trade.pnl_dollars > 0:
            self.winning_trades += 1
        elif trade.pnl_dollars < 0:
            self.losing_trades += 1
        else:
            self.break_even_trades += 1

        # Update peak and drawdown
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance

        drawdown = self.peak_balance - self.current_balance
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

        return trade

    def update_trade_peak(self, trade_id: int, current_spread_value: float):
        """Update peak spread value for trailing stop logic."""
        if trade_id in self.open_trades:
            trade = self.open_trades[trade_id]
            if current_spread_value < trade.peak_spread_value:
                trade.peak_spread_value = current_spread_value

    def get_trade(self, trade_id: int) -> Optional[ReplayTrade]:
        """Get trade by ID."""
        if trade_id in self.open_trades:
            return self.open_trades[trade_id]

        # Search closed trades
        for trade in self.closed_trades:
            if trade.trade_id == trade_id:
                return trade

        return None

    def get_open_trades(self) -> List[ReplayTrade]:
        """Get all open trades."""
        return list(self.open_trades.values())

    def get_closed_trades(self) -> List[ReplayTrade]:
        """Get all closed trades."""
        return self.closed_trades.copy()

    def get_all_trades(self) -> List[ReplayTrade]:
        """Get all trades (open and closed)."""
        return self.get_open_trades() + self.get_closed_trades()

    def get_statistics(self) -> Dict:
        """Get comprehensive statistics."""
        avg_win = 0.0
        max_win = 0.0
        if self.winning_trades > 0:
            winning_pnl = sum(t.pnl_dollars for t in self.closed_trades if t.pnl_dollars > 0)
            avg_win = winning_pnl / self.winning_trades
            max_win = max(t.pnl_dollars for t in self.closed_trades if t.pnl_dollars > 0)

        avg_loss = 0.0
        max_loss = 0.0
        if self.losing_trades > 0:
            losing_pnl = sum(t.pnl_dollars for t in self.closed_trades if t.pnl_dollars < 0)
            avg_loss = losing_pnl / self.losing_trades
            max_loss = min(t.pnl_dollars for t in self.closed_trades if t.pnl_dollars < 0)

        win_rate = 0.0
        if self.total_trades > 0:
            win_rate = self.winning_trades / self.total_trades

        profit_factor = 0.0
        if self.losing_trades > 0:
            winning_total = sum(t.pnl_dollars for t in self.closed_trades if t.pnl_dollars > 0)
            losing_total = abs(sum(t.pnl_dollars for t in self.closed_trades if t.pnl_dollars < 0))
            if losing_total > 0:
                profit_factor = winning_total / losing_total

        return {
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'break_even_trades': self.break_even_trades,
            'win_rate': win_rate,
            'total_pnl': self.total_pnl,
            'avg_win': avg_win,
            'max_win': max_win,
            'avg_loss': avg_loss,
            'max_loss': max_loss,
            'profit_factor': profit_factor,
            'current_balance': self.current_balance,
            'peak_balance': self.peak_balance,
            'max_drawdown': self.max_drawdown,
            'return_percent': ((self.current_balance - self.starting_balance) / self.starting_balance) * 100
        }

    def __str__(self) -> str:
        """String representation."""
        return (f"StateManager: {self.total_trades} trades, "
                f"W:{self.winning_trades} L:{self.losing_trades} BE:{self.break_even_trades}, "
                f"P&L: ${self.total_pnl:+.0f}, Balance: ${self.current_balance:,.0f}")
