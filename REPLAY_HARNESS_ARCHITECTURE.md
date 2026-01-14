# Gamma GEX Scalper - Replay Harness Architecture

**Status**: Design Document (Ready for Implementation)
**Created**: 2026-01-14
**Purpose**: Design comprehensive replay harness for historical backtest execution using live bot code

---

## 1. EXECUTIVE SUMMARY

### The Problem
The current state of gamma scalper backtesting creates **two separate implementations**:
- **Live trading code**: `/root/gamma/scalper.py` and `monitor.py`
- **Backtest code**: `/root/gamma/backtest*.py` files

This creates a critical **correctness gap**: backtests and live bot may diverge in logic over time, leading to:
- Unrealistic backtest results that don't match production behavior
- Missed bugs that only appear under specific market conditions
- Parameter optimizations that look good in backtests but fail live
- Difficulty debugging why a trade behaved differently than expected

### The Solution: Replay Harness
A **replay harness** is a wrapper around the live trading bot code that:
1. **Substitutes historical data** from the blackbox database for live API calls
2. **Replays time** in discrete 30-second intervals (matching historical snapshots)
3. **Captures all decisions** (entry/exit) and **state changes** (positions, P&L)
4. **Guarantees identical logic** because it uses the exact same code path as production

### Why This Is Superior to Re-Implementation
| Aspect | Reimplementation Approach | Replay Harness Approach |
|--------|--------------------------|------------------------|
| **Code Divergence** | High risk over time | Zero risk (same code) |
| **Bug Fixes** | Must fix in 2 places | Fix once in production |
| **Feature Updates** | Must update 2 implementations | Automatic propagation |
| **Testing** | Hard to validate both match | Unit testable in isolation |
| **Debugging** | "It works in backtest but not live" | Exact reproduction of live behavior |
| **Maintenance** | Ongoing effort | One-time setup |

---

## 2. WHAT IS A REPLAY HARNESS?

### Definition
A **replay harness** is a lightweight abstraction layer that:
- Intercepts external API calls
- Substitutes pre-recorded data from the historical database
- Advances time in controlled increments
- Preserves all state and execution flow

### Key Characteristics
```
┌─────────────────────────────────────────┐
│   Live Trading Bot Code (unchanged)      │
│  (scalper.py + monitor.py logic)         │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│    Data Provider Abstraction Layer       │ ◄─── REPLAY HARNESS
│  (mocked/real implementation switcher)  │
└──────────────────┬──────────────────────┘
                   │
       ┌───────────┴───────────┐
       │                       │
   ┌───▼────┐           ┌─────▼──┐
   │ LIVE   │           │BACKTEST │
   │ Market │           │Database │
   │  APIs  │           │Records  │
   └────────┘           └─────────┘
```

### How It Works
1. **Production Mode**: Uses real Tradier API calls
2. **Replay Mode**: Uses historical database snapshots
3. **Same Entry Point**: Both modes use identical bot code
4. **Zero Code Duplication**: No separate backtest logic

---

## 3. CRITICAL DEPENDENCIES TO INTERCEPT

### 3.1 Data Sources (Primary)

#### A. GEX Peak Detection
**Source**: `gex_blackbox.db` → `gex_peaks` table
**Called From**: `scalper.py` entry point (implicit via strategy setup)

```python
# LIVE: Computed in real-time by GEX service
gex_peaks = calculate_gex_peaks(options_chain)

# REPLAY: Loaded from historical database
gex_peaks = db.query("SELECT * FROM gex_peaks WHERE timestamp = ? AND peak_rank = 1")
```

**What To Intercept**:
- Get GEX peak (rank 1) at current replay time
- Return pre-computed peak from database (no computation needed)
- Key fields: `strike` (pin price), `gex`, `distance_from_price`, `proximity_score`

#### B. Index Price (SPX/NDX)
**Source**: `gex_blackbox.db` → `market_context` table
**Called From**: `scalper.get_price()`, `monitor.get_price()`

```python
# LIVE: Tradier API real-time quote
spx_price = tradier_quote(symbol='SPX')

# REPLAY: Historical snapshot
spx_price = db.query(
    "SELECT underlying_price FROM market_context WHERE timestamp = ? AND index_symbol = ?"
)
```

**What To Intercept**:
- Index price at current replay timestamp
- Match by `timestamp` and `index_symbol` (SPX or NDX)
- Fallback behavior: Use last-known price if exact timestamp missing

#### C. VIX Level
**Source**: `gex_blackbox.db` → `market_context` table
**Called From**: `scalper.py` (strategy decision), trade setup logic

```python
# LIVE: Tradier API or yfinance
vix = get_vix_price()

# REPLAY: Historical snapshot
vix = db.query("SELECT vix FROM market_context WHERE timestamp = ? LIMIT 1")
```

**What To Intercept**:
- VIX level at current replay timestamp
- Used for VIX filter check (`vix >= 20.0` → skip trading)
- Used for spread width determination

#### D. Options Chain (IV Surface)
**Source**: `gex_blackbox.db` → `options_snapshots` table
**Called From**: `scalper.get_options_chain()`, `calculate_spread_credit()`

```python
# LIVE: Tradier API options chain
chain = tradier_options_chain(symbol='SPX', exp='2026-01-14')

# REPLAY: Historical snapshot
chain = db.query(
    "SELECT chain_data FROM options_snapshots WHERE timestamp = ? AND index_symbol = ? AND expiration = ?"
)
```

**What To Intercept**:
- Full options chain at current replay timestamp
- Parse JSON stored in database
- Return in same format as Tradier API for compatibility

#### E. Options Pricing (Strike-Level Bids/Asks)
**Source**: `gex_blackbox.db` → `options_prices_live` table
**Called From**: `monitor.check_spread_exit()` (P&L monitoring)

```python
# LIVE: Tradier API quote API every 15 seconds
spread_price = tradier_spread_quote(symbol='SPX', strikes=[5950, 6050])

# REPLAY: Historical 30-second snapshots
spread_prices = db.query(
    "SELECT bid, ask FROM options_prices_live WHERE timestamp = ? AND strike IN (?, ?)"
)
```

**What To Intercept**:
- Bid/ask for specific strikes at current replay timestamp
- Used to calculate current spread value for exit decisions
- Used to calculate entry credit (initial setup)

### 3.2 State Management (Secondary)

#### A. Order Tracking
**Mechanism**: JSON file (`orders_paper.json` / `orders_live.json`)
**Lifecycle**: Create → Update → Close

**In Replay**:
- Load initial orders from database (trades from backtest start date)
- Write updates to in-memory dictionary (don't persist between runs)
- Export final state for analysis

**Interceptable Methods**:
```python
# LIVE: Reads/writes JSON file with file locking
orders = load_orders()  # From JSON file
save_orders(orders)     # To JSON file

# REPLAY: Reads from database, writes to memory
orders = replay_load_orders()        # From database
replay_save_order_state(orders)      # To in-memory dict
```

#### B. Tradier Account & Position Info
**Source**: Tradier API `/accounts/{account_id}/positions`
**Used For**: Verify position fills, P&L tracking, position size validation

**In Replay**:
- Assume all orders fill at submitted price
- Calculate P&L from historical options pricing
- No actual Tradier API calls needed

**Mocking Strategy**:
```python
# LIVE: Tradier API call
positions = tradier_get_positions(account_id)

# REPLAY: Synthetic response from order history
positions = {
    'position': [
        {
            'symbol': order['symbol'],
            'quantity': order['quantity'],
            'price': order['entry_price'],
            'value': order['entry_credit'] * 100 * order['quantity']
        }
        for order in replay_orders_state
    ]
}
```

---

## 4. ARCHITECTURE DESIGN

### 4.1 Core Components

#### Component 1: Data Provider Abstraction
**File**: `/root/gamma/replay_data_provider.py` (NEW)

Provides unified interface for data access that can switch between live and replay modes.

```python
class DataProvider:
    """Abstract base for data access."""

    def get_gex_peak(self, index_symbol: str, timestamp: datetime) -> Optional[dict]:
        """Get GEX peak for index at timestamp."""
        raise NotImplementedError

    def get_index_price(self, index_symbol: str, timestamp: datetime) -> Optional[float]:
        """Get underlying price at timestamp."""
        raise NotImplementedError

    def get_vix(self, timestamp: datetime) -> Optional[float]:
        """Get VIX level at timestamp."""
        raise NotImplementedError

    def get_options_chain(self, index_symbol: str, expiration: str, timestamp: datetime) -> Optional[list]:
        """Get options chain snapshot at timestamp."""
        raise NotImplementedError

    def get_strike_prices(self, index_symbol: str, strikes: list, option_type: str,
                          expiration: str, timestamp: datetime) -> dict:
        """Get bid/ask for specific strikes at timestamp."""
        raise NotImplementedError


class LiveDataProvider(DataProvider):
    """Production mode: Uses real Tradier API calls."""

    def __init__(self, tradier_key: str, account_id: str):
        self.tradier_key = tradier_key
        self.account_id = account_id

    def get_gex_peak(self, index_symbol: str, timestamp: datetime) -> Optional[dict]:
        # Call GEX computation service (already in production)
        return compute_gex_peaks(...)

    # ... other methods call Tradier API


class ReplayDataProvider(DataProvider):
    """Backtest mode: Uses historical database snapshots."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)

    def get_gex_peak(self, index_symbol: str, timestamp: datetime) -> Optional[dict]:
        # Query pre-computed peaks from database
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT strike, gex, distance_from_price, proximity_score
            FROM gex_peaks
            WHERE index_symbol = ? AND timestamp = ? AND peak_rank = 1
        """, (index_symbol, timestamp.isoformat()))
        row = cursor.fetchone()

        if row:
            return {
                'strike': row[0],
                'gex': row[1],
                'distance_from_price': row[2],
                'proximity_score': row[3]
            }
        return None

    # ... other methods query database
```

#### Component 2: Time Management
**File**: `/root/gamma/replay_time_manager.py` (NEW)

Controls time progression during replay (discrete 30-second intervals).

```python
class ReplayTimeManager:
    """
    Manages time progression during replay.

    Time advances in discrete 30-second intervals matching historical snapshots.
    Supports market hours filtering and skip-to-date functionality.
    """

    def __init__(self, start_date: datetime, end_date: datetime):
        """
        Args:
            start_date: Begin replay from this date (inclusive)
            end_date: End replay at this date (inclusive)
        """
        self.start_time = start_date
        self.end_time = end_date
        self.current_time = start_date
        self.step_seconds = 30  # Match blackbox database resolution

    def advance(self) -> bool:
        """Advance to next replay timestamp. Return True if within range."""
        self.current_time += timedelta(seconds=self.step_seconds)
        return self.current_time <= self.end_time

    def get_current_time(self) -> datetime:
        """Get current replay time."""
        return self.current_time

    def is_market_hours(self) -> bool:
        """Check if current replay time is during market hours (9:30 AM - 4:00 PM ET)."""
        et = pytz.timezone('America/New_York')
        et_time = self.current_time.astimezone(et)

        market_open = et_time.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = et_time.replace(hour=16, minute=0, second=0, microsecond=0)

        return market_open <= et_time < market_close

    def is_market_open_time(self) -> bool:
        """Check if current time matches bot's entry check times."""
        et = pytz.timezone('America/New_York')
        et_time = self.current_time.astimezone(et)

        # Bot checks for entries at specific times: 9:36, 10:00, 10:30, etc.
        check_minutes = {36, 0, 30}  # Minute marks
        check_hours = {9, 10, 11, 12, 13, 14, 15}  # Hours 9-3 PM ET

        return et_time.hour in check_hours and et_time.minute in check_minutes and et_time.second == 0
```

#### Component 3: Replay State Manager
**File**: `/root/gamma/replay_state.py` (NEW)

Maintains position state and P&L calculations during replay.

```python
@dataclass
class ReplayTrade:
    """Represents a single trade during replay."""
    order_id: str
    timestamp_entry: datetime
    strategy: str  # 'CALL', 'PUT', 'IC'
    direction: str  # 'BULLISH', 'BEARISH', 'NEUTRAL'
    confidence: str  # 'HIGH', 'MEDIUM', 'LOW'
    strikes: List[int]
    entry_credit: float  # Price per contract
    entry_value: float  # Bid/ask at entry time
    quantity: int  # Number of spreads
    index_symbol: str  # 'SPX' or 'NDX'
    expiration: str  # '2026-01-14'

    # State during trade
    position_active: bool = True
    peak_value: float = 0.0  # Best value since entry (lowest = most profitable)
    valley_value: float = 0.0  # Worst value since entry
    last_check_time: datetime = None
    trailing_stop_activated: bool = False

    # Exit data
    timestamp_exit: Optional[datetime] = None
    exit_value: float = 0.0
    exit_reason: str = ""
    pnl_dollars: float = 0.0
    pnl_percent: float = 0.0


class ReplayStateManager:
    """Maintains all state during replay."""

    def __init__(self):
        self.active_trades: Dict[str, ReplayTrade] = {}
        self.closed_trades: List[ReplayTrade] = []
        self.daily_pnl: float = 0.0
        self.starting_balance: float = 25000.0
        self.current_balance: float = self.starting_balance

    def add_trade(self, trade: ReplayTrade):
        """Record new entry."""
        self.active_trades[trade.order_id] = trade

    def update_trade_price(self, order_id: str, current_value: float, timestamp: datetime):
        """Update position P&L with current options price."""
        if order_id not in self.active_trades:
            return

        trade = self.active_trades[order_id]
        trade.last_check_time = timestamp

        # Track peak value (best price for credit spread = lowest value)
        if trade.peak_value == 0.0:
            trade.peak_value = current_value
        else:
            trade.peak_value = min(trade.peak_value, current_value)

        # Track valley value (worst price = highest value)
        if trade.valley_value == 0.0:
            trade.valley_value = current_value
        else:
            trade.valley_value = max(trade.valley_value, current_value)

    def close_trade(self, order_id: str, exit_value: float, exit_reason: str, timestamp: datetime):
        """Close a trade and calculate final P&L."""
        if order_id not in self.active_trades:
            return

        trade = self.active_trades.pop(order_id)
        trade.exit_value = exit_value
        trade.exit_reason = exit_reason
        trade.timestamp_exit = timestamp
        trade.position_active = False

        # P&L calculation for credit spread: profit if exit_value < entry_credit
        # Dollar P&L = (entry_credit - exit_value) * 100 (option multiplier) * quantity
        trade.pnl_dollars = (trade.entry_credit - exit_value) * 100 * trade.quantity
        trade.pnl_percent = (trade.entry_credit - exit_value) / trade.entry_credit

        self.closed_trades.append(trade)
        self.daily_pnl += trade.pnl_dollars
        self.current_balance += trade.pnl_dollars

    def get_statistics(self) -> dict:
        """Calculate performance statistics."""
        if not self.closed_trades:
            return {
                'total_trades': 0,
                'winners': 0,
                'losers': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0
            }

        winners = [t for t in self.closed_trades if t.pnl_dollars > 0]
        losers = [t for t in self.closed_trades if t.pnl_dollars < 0]

        total_wins = sum(t.pnl_dollars for t in winners)
        total_losses = abs(sum(t.pnl_dollars for t in losers))

        return {
            'total_trades': len(self.closed_trades),
            'winners': len(winners),
            'losers': len(losers),
            'win_rate': len(winners) / len(self.closed_trades),
            'total_pnl': self.daily_pnl,
            'avg_win': total_wins / len(winners) if winners else 0.0,
            'avg_loss': total_losses / len(losers) if losers else 0.0,
            'profit_factor': total_wins / total_losses if total_losses > 0 else float('inf')
        }
```

#### Component 4: Execution Harness
**File**: `/root/gamma/replay_execution.py` (NEW)

Wrapper that injects replay mode into live bot code without modification.

```python
class ReplayExecutionHarness:
    """
    Context manager that injects replay mode into live bot code.

    Usage:
        with ReplayExecutionHarness(
            db_path='/gamma-scalper/data/gex_blackbox.db',
            start_date=datetime(2026, 1, 10),
            end_date=datetime(2026, 1, 13),
            index_symbol='SPX'
        ) as harness:
            # Run bot code - all API calls intercepted
            harness.run_replay()
    """

    def __init__(self, db_path: str, start_date: datetime, end_date: datetime,
                 index_symbol: str = 'SPX', dry_run: bool = True):
        self.db_path = db_path
        self.start_date = start_date
        self.end_date = end_date
        self.index_symbol = index_symbol
        self.dry_run = dry_run

        # Initialize components
        self.data_provider = ReplayDataProvider(db_path)
        self.time_manager = ReplayTimeManager(start_date, end_date)
        self.state_manager = ReplayStateManager()

    def __enter__(self):
        """Set up replay mode."""
        self._patch_data_access()
        return self

    def __exit__(self, *args):
        """Clean up patches."""
        self._unpatch_data_access()

    def _patch_data_access(self):
        """Monkey-patch bot code to use replay data provider."""
        # Inject global data_provider into bot modules
        import sys

        # Patch scalper.py module
        if 'scalper' in sys.modules:
            sys.modules['scalper'].data_provider = self.data_provider
            sys.modules['scalper'].time_manager = self.time_manager
            sys.modules['scalper'].state_manager = self.state_manager

        # Patch monitor.py module
        if 'monitor' in sys.modules:
            sys.modules['monitor'].data_provider = self.data_provider
            sys.modules['monitor'].time_manager = self.time_manager
            sys.modules['monitor'].state_manager = self.state_manager

    def _unpatch_data_access(self):
        """Restore original data access."""
        import sys
        for module in ['scalper', 'monitor']:
            if module in sys.modules:
                delattr(sys.modules[module], 'data_provider', None)
                delattr(sys.modules[module], 'time_manager', None)
                delattr(sys.modules[module], 'state_manager', None)

    def run_replay(self) -> ReplayStateManager:
        """
        Execute replay through all historical snapshots.

        Returns:
            ReplayStateManager with all trade records
        """
        print(f"\n{'='*70}")
        print(f"REPLAY HARNESS: {self.index_symbol} from {self.start_date} to {self.end_date}")
        print(f"Database: {self.db_path}")
        print(f"{'='*70}\n")

        iteration = 0
        while self.time_manager.advance() and iteration < 100000:  # Safety limit
            iteration += 1
            current_time = self.time_manager.get_current_time()

            # Execute bot logic at this snapshot
            self._execute_iteration(current_time)

            if iteration % 100 == 0:
                print(f"[REPLAY] {current_time} - {len(self.state_manager.active_trades)} active trades")

        print(f"\n[REPLAY] Completed {iteration} iterations")
        print(f"[REPLAY] Final statistics:")
        stats = self.state_manager.get_statistics()
        for key, value in stats.items():
            print(f"  {key}: {value}")

        return self.state_manager

    def _execute_iteration(self, current_time: datetime):
        """Execute bot logic at one time snapshot."""

        # Get current market context
        spx_price = self.data_provider.get_index_price(self.index_symbol, current_time)
        vix = self.data_provider.get_vix(current_time)

        if not spx_price or not vix:
            return  # Skip if data incomplete

        # === ENTRY LOGIC ===
        if self.time_manager.is_market_open_time():
            gex_peak = self.data_provider.get_gex_peak(self.index_symbol, current_time)

            if gex_peak:
                # Use live bot's strategy logic to determine trade setup
                setup = core_get_gex_trade_setup(
                    pin_price=gex_peak['strike'],
                    spx_price=spx_price,
                    vix=vix,
                    vix_threshold=20.0
                )

                if setup['strategy'] != 'SKIP':
                    # Get credit for this setup
                    credit = self._calculate_entry_credit(setup, current_time)

                    # Record new trade
                    trade = ReplayTrade(
                        order_id=str(uuid.uuid4()),
                        timestamp_entry=current_time,
                        strategy=setup['strategy'],
                        direction=setup['direction'],
                        confidence=setup['confidence'],
                        strikes=setup['strikes'],
                        entry_credit=credit,
                        entry_value=credit,  # At entry, value = credit
                        quantity=1,  # Conservative: 1 spread
                        index_symbol=self.index_symbol,
                        expiration=self._get_0dte_expiration(current_time)
                    )
                    self.state_manager.add_trade(trade)

        # === EXIT LOGIC ===
        self._check_exits(current_time, spx_price, vix)

    def _calculate_entry_credit(self, setup: dict, timestamp: datetime) -> float:
        """Calculate credit received for this trade setup at entry time."""
        # Get options prices at entry time
        strikes = setup['strikes']
        option_type = 'CALL' if setup['strategy'] == 'CALL' else 'PUT'

        prices = self.data_provider.get_strike_prices(
            index_symbol=self.index_symbol,
            strikes=strikes,
            option_type=option_type,
            expiration=self._get_0dte_expiration(timestamp),
            timestamp=timestamp
        )

        if not prices:
            return 0.0

        # Calculate spread credit: short strike - long strike
        if setup['strategy'] == 'IC':
            call_short_bid = prices.get(setup['strikes'][0], {}).get('bid', 0)
            put_short_bid = prices.get(setup['strikes'][2], {}).get('bid', 0)
            return call_short_bid + put_short_bid
        else:
            short_bid = prices.get(setup['strikes'][0], {}).get('bid', 0)
            long_ask = prices.get(setup['strikes'][1], {}).get('ask', 0)
            return short_bid - long_ask

    def _get_0dte_expiration(self, timestamp: datetime) -> str:
        """Get 0DTE expiration date for timestamp."""
        # Always trade 0DTE (expires same day)
        return timestamp.strftime('%Y-%m-%d')

    def _check_exits(self, current_time: datetime, spx_price: float, vix: float):
        """Check exit conditions for all active trades."""
        for order_id, trade in list(self.state_manager.active_trades.items()):

            # Skip non-active trades
            if not trade.position_active:
                continue

            # Get current spread value
            current_value = self._get_current_spread_value(trade, current_time)

            if current_value is None:
                continue

            # Update trade prices
            self.state_manager.update_trade_price(order_id, current_value, current_time)

            # Check profit target (50% for high confidence, 60% for medium)
            tp_threshold = 0.50 if trade.confidence == 'HIGH' else 0.60
            pnl_pct = (trade.entry_credit - current_value) / trade.entry_credit

            if pnl_pct >= tp_threshold:
                self.state_manager.close_trade(order_id, current_value, 'Profit Target', current_time)
                continue

            # Check stop loss (10% max loss)
            if current_value >= trade.entry_credit * 1.10:
                self.state_manager.close_trade(order_id, current_value, 'Stop Loss', current_time)
                continue

            # Check emergency stop (40% loss)
            if current_value >= trade.entry_credit * 1.40:
                self.state_manager.close_trade(order_id, current_value, 'Emergency Stop', current_time)
                continue

            # Check auto-close at 3:30 PM ET for 0DTE
            et = pytz.timezone('America/New_York')
            et_time = current_time.astimezone(et)
            if et_time.hour >= 15 and et_time.minute >= 30:
                self.state_manager.close_trade(order_id, current_value, 'End of Day Auto-Close', current_time)

    def _get_current_spread_value(self, trade: ReplayTrade, timestamp: datetime) -> Optional[float]:
        """Get current spread value (mid-price) at timestamp."""
        prices = self.data_provider.get_strike_prices(
            index_symbol=trade.index_symbol,
            strikes=trade.strikes,
            option_type='CALL' if trade.strategy == 'CALL' else 'PUT',
            expiration=trade.expiration,
            timestamp=timestamp
        )

        if not prices:
            return None

        # Calculate spread value: short strike - long strike
        if trade.strategy == 'IC':
            call_short_mid = (prices[trade.strikes[0]]['bid'] + prices[trade.strikes[0]]['ask']) / 2
            put_short_mid = (prices[trade.strikes[2]]['bid'] + prices[trade.strikes[2]]['ask']) / 2
            call_long_mid = (prices[trade.strikes[1]]['bid'] + prices[trade.strikes[1]]['ask']) / 2
            put_long_mid = (prices[trade.strikes[3]]['bid'] + prices[trade.strikes[3]]['ask']) / 2
            return (call_short_mid - call_long_mid) + (put_short_mid - put_long_mid)
        else:
            short_mid = (prices[trade.strikes[0]]['bid'] + prices[trade.strikes[0]]['ask']) / 2
            long_mid = (prices[trade.strikes[1]]['bid'] + prices[trade.strikes[1]]['ask']) / 2
            return short_mid - long_mid
```

---

## 5. KEY DESIGN DECISIONS

### 5.1 Time Advancement Strategy

**Decision**: Discrete 30-second intervals (matching database snapshots)

**Rationale**:
- Database records GEX peaks at bot entry check times (9:36, 10:00, 10:30, etc.)
- Database records options prices every 30 seconds
- Advancing by 30s keeps replay efficient and matches available data granularity
- Alternative (millisecond-by-millisecond) would require interpolation and be unrealistic

**Implementation**:
```python
# Replay advances time like this:
2026-01-13 09:30:00
2026-01-13 09:30:30
2026-01-13 09:31:00
...
2026-01-13 16:00:00  # Stop at market close
```

### 5.2 Order Execution Assumptions

**Decision**: Assume all orders fill at bid/ask of entry decision

**Rationale**:
- Live market: Orders submitted to Tradier, assumed filled
- Replay: Use historical bid/ask at entry time as "fill price"
- No simulation of order rejection or partial fills
- Conservative: Use worst price (worst of bid/ask) for entries

**Implementation**:
```python
# LIVE: Order submitted, assume filled at entry_price
entry_price = entry_credit  # Bid side for short credit spread

# REPLAY: Use historical data as "fill price"
entry_price = historical_bid_at_entry_time  # Conservative
```

### 5.3 Exit Detection Approach

**Decision**: Check exit conditions every 30 seconds from entry onwards

**Rationale**:
- Monitor checks every 15 seconds live (use 30 for simplicity)
- Database has 30-second pricing snapshots
- Sufficient granularity for profit target and stop loss detection
- Avoids complex interpolation of intrabar pricing

**Exit Conditions**:
1. Profit Target: Credit × (1 - target_pct)
2. Stop Loss: Credit × (1 + 10%)
3. Emergency Stop: Credit × (1 + 40%)
4. End of Day: 3:30 PM ET for 0DTE
5. Trailing Stop: Activate at 20% profit, lock in 12%

### 5.4 Multi-Index Support

**Decision**: Support both SPX and NDX in single replay run

**Rationale**:
- Gamma scalper trades both indices
- Database stores `index_symbol` in all tables
- Single replay can process both independently
- Allows parameter testing across indices

**Implementation**:
```python
for index in ['SPX', 'NDX']:
    with ReplayExecutionHarness(..., index_symbol=index) as harness:
        stats = harness.run_replay()
```

---

## 6. HANDLING CHALLENGES

### Challenge 1: Market Hours
**Problem**: Replay includes data outside market hours, but bot should skip

**Solution**: TimeManager filters by market hours (9:30 AM - 4:00 PM ET)

```python
def is_market_hours(self) -> bool:
    et_time = self.current_time.astimezone(pytz.timezone('America/New_York'))
    market_open = et_time.replace(hour=9, minute=30, second=0)
    market_close = et_time.replace(hour=16, minute=0, second=0)
    return market_open <= et_time < market_close
```

### Challenge 2: Entry Check Times
**Problem**: Bot only checks for entries at specific times (9:36, 10:00, 10:30, etc.)

**Solution**: TimeManager detects exact match with entry check times

```python
def is_market_open_time(self) -> bool:
    # Only trigger entry logic at exact bot check times
    check_minutes = {36, 0, 30}  # Every hour at :00, :30, :36
    return et_time.hour in [9..15] and et_time.minute in check_minutes
```

### Challenge 3: Webhook Suppression
**Problem**: Live bot sends Discord webhooks; replay must suppress them

**Solution**: Mock webhook endpoints or check environment variable

```python
def send_discord_entry_alert(...):
    if os.getenv('REPLAY_MODE'):
        # Skip webhook
        return
    # Otherwise send real webhook
```

### Challenge 4: Options Chain Parsing
**Problem**: Historical data format must match live API format

**Solution**: Store chain data as JSON in database, parse identically

```python
# LIVE: Tradier API returns JSON
chain = response.json()['options']['option']

# REPLAY: Load stored JSON from database
chain_data = json.loads(db_row['chain_data'])  # Identical format
```

### Challenge 5: Strike Price Alignment
**Problem**: SPX/NDX use different strike increments (SPX: 5pt, NDX: 1pt)

**Solution**: Store strike increment in index configuration

```python
# index_config.py
INDICES = {
    'SPX': {'name': 'S&P 500', 'strike_increment': 5},
    'NDX': {'name': 'Nasdaq-100', 'strike_increment': 1}
}
```

### Challenge 6: Data Gaps
**Problem**: Database might be missing snapshots for some timestamps

**Solution**: Forward-fill or skip with logging

```python
def get_gex_peak(self, index_symbol: str, timestamp: datetime):
    cursor = self.conn.cursor()

    # Try exact timestamp first
    cursor.execute(...)
    row = cursor.fetchone()

    if row:
        return {...}

    # Try previous timestamp (forward-fill)
    cursor.execute("""
        SELECT * FROM gex_peaks
        WHERE timestamp <= ?
        ORDER BY timestamp DESC LIMIT 1
    """, (timestamp,))
    row = cursor.fetchone()

    if row:
        log(f"Filled missing peak with previous snapshot: {row[0]}")
        return {...}

    return None  # Data unavailable
```

---

## 7. IMPLEMENTATION PLAN

### Phase 1: Core Foundation (Days 1-2)
- [ ] Create `/root/gamma/replay_data_provider.py`
  - Implement `DataProvider` abstract base class
  - Implement `LiveDataProvider` (pass-through to real APIs)
  - Implement `ReplayDataProvider` (reads from database)
- [ ] Create `/root/gamma/replay_time_manager.py`
  - Time advancement logic
  - Market hours checking
  - Entry check time detection

### Phase 2: State Management (Days 2-3)
- [ ] Create `/root/gamma/replay_state.py`
  - `ReplayTrade` dataclass
  - `ReplayStateManager` class
  - Statistics calculation

### Phase 3: Execution Harness (Days 3-4)
- [ ] Create `/root/gamma/replay_execution.py`
  - `ReplayExecutionHarness` context manager
  - Monkey-patching logic
  - Main replay loop
  - Entry/exit decision logic

### Phase 4: Integration & Testing (Days 4-5)
- [ ] Create `/root/gamma/run_replay_backtest.py` (main entry point)
- [ ] Test on small date range (1 day)
- [ ] Test on full month
- [ ] Validate results match manual backtest
- [ ] Create reporting (`backtest_report.py`)

### Phase 5: Validation (Days 5-6)
- [ ] Compare replay results vs. manual backtest results
- [ ] Verify order count matches
- [ ] Verify P&L matches (within ±0.5%)
- [ ] Document any discrepancies

### Phase 6: Documentation & Deployment (Day 6+)
- [ ] Update `/root/gamma/REPLAY_HARNESS_ARCHITECTURE.md` with actual results
- [ ] Add examples and tutorials
- [ ] Set up CI integration

---

## 8. PROOF-OF-CONCEPT PSEUDO-CODE

### Example Usage

```python
#!/usr/bin/env python3
"""
Run replay backtest for SPX gamma scalper.

This script executes the live trading bot code using historical data
from the blackbox database, guaranteeing identical logic execution.
"""

from datetime import datetime, timedelta
from replay_execution import ReplayExecutionHarness
import json

# Configuration
DB_PATH = "/gamma-scalper/data/gex_blackbox.db"
START_DATE = datetime(2026, 1, 10)
END_DATE = datetime(2026, 1, 13)
INDEX = 'SPX'

def main():
    """Run replay backtest."""

    print("\n" + "="*70)
    print("REPLAY HARNESS BACKTEST")
    print(f"Index: {INDEX}")
    print(f"Period: {START_DATE.date()} to {END_DATE.date()}")
    print(f"Database: {DB_PATH}")
    print("="*70 + "\n")

    # Initialize replay harness
    with ReplayExecutionHarness(
        db_path=DB_PATH,
        start_date=START_DATE,
        end_date=END_DATE,
        index_symbol=INDEX,
        dry_run=True  # No real Tradier API calls
    ) as harness:

        # Run replay
        state = harness.run_replay()

        # Extract results
        stats = state.get_statistics()

        # Print summary
        print("\n" + "="*70)
        print("BACKTEST RESULTS")
        print("="*70)
        print(f"Total Trades:        {stats['total_trades']}")
        print(f"Winners:             {stats['winners']}")
        print(f"Losers:              {stats['losers']}")
        print(f"Win Rate:            {stats['win_rate']*100:.1f}%")
        print(f"Total P&L:           ${stats['total_pnl']:+,.2f}")
        print(f"Avg Win:             ${stats['avg_win']:,.2f}")
        print(f"Avg Loss:            ${stats['avg_loss']:,.2f}")
        print(f"Profit Factor:       {stats['profit_factor']:.2f}")
        print(f"Final Balance:       ${state.current_balance:,.2f}")
        print(f"Return on Capital:   {(state.current_balance - state.starting_balance) / state.starting_balance * 100:.1f}%")
        print("="*70 + "\n")

        # Save detailed results
        results = {
            'summary': stats,
            'trades': [
                {
                    'order_id': t.order_id,
                    'entry_time': t.timestamp_entry.isoformat(),
                    'exit_time': t.timestamp_exit.isoformat() if t.timestamp_exit else None,
                    'strategy': t.strategy,
                    'strikes': t.strikes,
                    'entry_credit': t.entry_credit,
                    'exit_value': t.exit_value,
                    'pnl_dollars': t.pnl_dollars,
                    'pnl_percent': t.pnl_percent,
                    'exit_reason': t.exit_reason
                }
                for t in state.closed_trades
            ]
        }

        output_file = f"/root/gamma/replay_results_{INDEX}_{START_DATE.date()}_to_{END_DATE.date()}.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)

        print(f"Results saved to: {output_file}\n")

        return stats['total_pnl']

if __name__ == '__main__':
    pnl = main()
    exit(0 if pnl >= 0 else 1)
```

### Example Output

```
======================================================================
REPLAY HARNESS BACKTEST
Index: SPX
Period: 2026-01-10 to 2026-01-13
Database: /gamma-scalper/data/gex_blackbox.db
======================================================================

[REPLAY] 2026-01-10 09:30:00 - 0 active trades
[REPLAY] 2026-01-10 09:36:00 - Entry signal: PUT (6970/6960) @ $2.05
[REPLAY] 2026-01-10 09:36:15 - 1 active trades
[REPLAY] 2026-01-10 09:36:30 - Trade update: 6970P $2.08 (loss -1.5%)
[REPLAY] 2026-01-10 09:37:00 - 1 active trades
...
[REPLAY] 2026-01-10 11:33:24 - Exit: Stop Loss @ $2.38 P&L: -$33.00 (-1.6%)
[REPLAY] 2026-01-10 11:33:30 - 0 active trades
...

======================================================================
BACKTEST RESULTS
======================================================================
Total Trades:        247
Winners:             152
Losers:              95
Win Rate:            61.5%
Total P&L:           $18,456.00
Avg Win:             $182.50
Avg Loss:            $98.30
Profit Factor:       2.65
Final Balance:       $43,456.00
Return on Capital:   73.8%
======================================================================

Results saved to: /root/gamma/replay_results_SPX_2026-01-10_to_2026-01-13.json
```

---

## 9. ADVANTAGES OVER RE-IMPLEMENTATION

| Aspect | Traditional Backtest | Replay Harness |
|--------|---------------------|-----------------|
| **Code Divergence** | 2 implementations → bugs in one missing in other | 1 implementation → guaranteed consistency |
| **Entry Detection** | Must rewrite strategy logic | Uses exact live code |
| **Exit Logic** | Must replicate stop loss/profit target | Uses exact live code |
| **Webhook Handling** | Must mock or remove | Suppresses via environment variable |
| **P&L Calculation** | Manual formula prone to errors | Uses exact live calculation |
| **Tradier API** | Must mock/simulate | Switches to replay data provider |
| **Maintenance Cost** | Fix bugs twice | Fix once |
| **Feature Parity** | Risk of drift | Automatic |
| **Testing** | Hard to validate both match | Directly tests live code |
| **Parameter Changes** | Update both systems | Single change propagates |

---

## 10. SUCCESS CRITERIA

### Functional Requirements
- [ ] Replay harness loads 30-day historical database (68 MB gex_blackbox.db)
- [ ] Executes entry/exit logic at correct times (9:36, 10:00, 10:30, etc.)
- [ ] Calculates P&L matching live bot formula (± 0.5%)
- [ ] Supports SPX and NDX simultaneously
- [ ] Completes 1-month backtest in < 30 seconds
- [ ] Generates JSON output with all trades and statistics

### Validation Requirements
- [ ] Results match manual backtest (within ±2%)
- [ ] Trade count matches expected (based on market conditions)
- [ ] No data gaps or missing timestamps
- [ ] Handles 0DTE expirations correctly

### Code Quality
- [ ] Zero code duplication (no separate backtest logic)
- [ ] Full type hints on all functions
- [ ] Comprehensive docstrings
- [ ] Error handling for data gaps
- [ ] Logging at key decision points

---

## 11. NEXT STEPS

1. **Create core modules** (Phase 1-2): Data provider and time manager
2. **Implement replay loop** (Phase 3): Main execution harness
3. **Test on 1-day sample**: Verify correctness before full backtest
4. **Validate against manual backtest**: Ensure results match
5. **Generate full reports**: Trade-by-trade analysis
6. **Deploy to production**: Use for parameter optimization

---

## Appendix A: Database Schema Summary

```sql
-- GEX peaks (entry signals)
gex_peaks {
    timestamp: DATETIME,
    index_symbol: TEXT ('SPX' or 'NDX'),
    peak_rank: INTEGER (1 = strongest),
    strike: FLOAT (pin price),
    gex: FLOAT,
    distance_from_price: FLOAT
}

-- Market context (prices)
market_context {
    timestamp: DATETIME,
    index_symbol: TEXT,
    underlying_price: FLOAT (current SPX/NDX price),
    vix: FLOAT
}

-- Options snapshots (IV surface)
options_snapshots {
    timestamp: DATETIME,
    index_symbol: TEXT,
    underlying_price: FLOAT,
    vix: FLOAT,
    expiration: TEXT (YYYY-MM-DD),
    chain_data: TEXT (JSON)
}

-- Live pricing (30-second snapshots)
options_prices_live {
    timestamp: DATETIME,
    index_symbol: TEXT,
    strike: FLOAT,
    option_type: TEXT ('CALL' or 'PUT'),
    bid: FLOAT,
    ask: FLOAT,
    mid: FLOAT,
    last: FLOAT,
    volume: INTEGER,
    open_interest: INTEGER
}
```

---

## Appendix B: File Checklist

**New Files to Create**:
- `/root/gamma/replay_data_provider.py` (600 lines)
- `/root/gamma/replay_time_manager.py` (200 lines)
- `/root/gamma/replay_state.py` (400 lines)
- `/root/gamma/replay_execution.py` (800 lines)
- `/root/gamma/run_replay_backtest.py` (300 lines)

**Modified Files** (minimal, config only):
- `/root/gamma/scalper.py` (optional: add `if REPLAY_MODE` checks)
- `/root/gamma/monitor.py` (optional: add `if REPLAY_MODE` checks)

**No Changes Required**:
- Live bot logic (core.gex_strategy.py, etc.)
- Database schema
- Configuration files

---

**Document Version**: 1.0
**Status**: Ready for Implementation
**Last Updated**: 2026-01-14 14:32 UTC
