# Implementation Guide: Realistic P&L Calculation

This guide provides ready-to-use SQL queries and Python code templates for integrating real option pricing into the backtest.

---

## Part 1: SQL Queries

All queries use the `gex_blackbox.db` SQLite database.

### Query 1: Get Unique Snapshots for a Day

```sql
-- Find all 30-second price snapshots for a specific trading day
SELECT DISTINCT timestamp
FROM options_prices_live
WHERE DATE(timestamp) = '2026-01-12'
AND index_symbol = 'SPX'
ORDER BY timestamp ASC;

-- Result: 2,300 distinct timestamps across the entire 30-hour period
```

### Query 2: Get Real Option Prices at Specific Strike

```sql
-- Get pricing for one strike across all times
SELECT
    timestamp,
    strike,
    option_type,
    bid,
    ask,
    mid,
    volume,
    open_interest
FROM options_prices_live
WHERE index_symbol = 'SPX'
AND strike = 6975.0
AND option_type = 'call'
ORDER BY timestamp ASC
LIMIT 50;

-- Shows price evolution: [1.70, 1.95, 2.25, 2.20, ...]
```

### Query 3: Calculate Spread Value Over Time

```sql
-- Get spread value (short bid - long ask) at each timestamp
SELECT
    opl.timestamp,
    -- Short leg (we sell, get BID)
    (SELECT bid FROM options_prices_live
     WHERE timestamp = opl.timestamp
     AND index_symbol = 'SPX'
     AND strike = 6975.0
     AND option_type = 'call') as short_bid,
    -- Long leg (we buy, pay ASK)
    (SELECT ask FROM options_prices_live
     WHERE timestamp = opl.timestamp
     AND index_symbol = 'SPX'
     AND strike = 6980.0
     AND option_type = 'call') as long_ask,
    -- Spread value
    ((SELECT bid FROM options_prices_live
      WHERE timestamp = opl.timestamp
      AND index_symbol = 'SPX'
      AND strike = 6975.0
      AND option_type = 'call')
     -
     (SELECT ask FROM options_prices_live
      WHERE timestamp = opl.timestamp
      AND index_symbol = 'SPX'
      AND strike = 6980.0
      AND option_type = 'call')) as spread_value
FROM options_prices_live opl
WHERE timestamp >= '2026-01-12 14:35:39'
AND timestamp <= '2026-01-12 16:00:00'
AND index_symbol = 'SPX'
GROUP BY opl.timestamp
ORDER BY opl.timestamp ASC;
```

### Query 4: Find GEX Peak with Pricing

```sql
-- Get GEX peak information with actual option pricing at that peak
SELECT
    gp.timestamp,
    gp.index_symbol,
    gp.strike as gex_peak_strike,
    gp.gex,
    gp.distance_from_price,
    gp.proximity_score,
    -- Get the call price at this peak
    opl.bid as peak_call_bid,
    opl.ask as peak_call_ask,
    -- Get 5-point OTM call price
    opl2.bid as long_call_bid,
    opl2.ask as long_call_ask
FROM gex_peaks gp
LEFT JOIN options_prices_live opl
    ON gp.timestamp = opl.timestamp
    AND gp.index_symbol = opl.index_symbol
    AND gp.strike = opl.strike
    AND opl.option_type = 'call'
LEFT JOIN options_prices_live opl2
    ON gp.timestamp = opl2.timestamp
    AND gp.index_symbol = opl2.index_symbol
    AND opl2.strike = (gp.strike + 5)
    AND opl2.option_type = 'call'
WHERE gp.index_symbol = 'SPX'
AND gp.peak_rank = 1
ORDER BY gp.timestamp ASC;
```

### Query 5: Detect Competing Peaks and Adjusted PIN

```sql
-- Show when competing peaks occur and what adjusted PIN to use
SELECT
    cp.timestamp,
    cp.index_symbol,
    cp.is_competing,
    cp.peak1_strike,
    cp.peak1_gex,
    cp.peak2_strike,
    cp.peak2_gex,
    cp.adjusted_pin,
    ROUND(cp.score_ratio * 100, 1) as peak2_pct_of_peak1,
    CASE
        WHEN cp.is_competing = 1 THEN 'USE adjusted_pin'
        ELSE 'USE peak1_strike'
    END as setup_guidance
FROM competing_peaks cp
WHERE cp.index_symbol = 'SPX'
ORDER BY cp.timestamp ASC;
```

### Query 6: Get All Option Prices for a Timestamp

```sql
-- Complete option chain at one moment in time
SELECT
    strike,
    option_type,
    bid,
    ask,
    ROUND((bid + ask) / 2, 2) as mid,
    volume,
    open_interest,
    ROUND(ask - bid, 3) as bid_ask_spread
FROM options_prices_live
WHERE timestamp = '2026-01-12 14:35:39'
AND index_symbol = 'SPX'
ORDER BY strike, option_type;

-- Shows full market at entry time
-- Used to determine spreads to trade
```

### Query 7: Track Position P&L for Specific Trade

```sql
-- Given entry timestamp and strikes, show P&L evolution
WITH entry_data AS (
    SELECT
        '2026-01-12 14:35:39'::timestamp as entry_time,
        6975.0 as short_strike,
        6980.0 as long_strike,
        'SPX' as idx_symbol,
        -- Entry credit from first timestamp
        (SELECT (bid - ask) FROM options_prices_live
         WHERE timestamp = '2026-01-12 14:35:39'
         AND index_symbol = 'SPX'
         AND strike = 6975.0
         AND option_type = 'call') -
        (SELECT ask FROM options_prices_live
         WHERE timestamp = '2026-01-12 14:35:39'
         AND index_symbol = 'SPX'
         AND strike = 6980.0
         AND option_type = 'call') as entry_credit
)
SELECT
    opl.timestamp,
    ROUND((JULIANDAY(opl.timestamp) - JULIANDAY(ed.entry_time)) * 1440, 0) as minutes_since_entry,
    (SELECT bid FROM options_prices_live
     WHERE timestamp = opl.timestamp
     AND index_symbol = 'SPX'
     AND strike = ed.short_strike
     AND option_type = 'call') as short_bid,
    (SELECT ask FROM options_prices_live
     WHERE timestamp = opl.timestamp
     AND index_symbol = 'SPX'
     AND strike = ed.long_strike
     AND option_type = 'call') as long_ask,
    ROUND(
        (SELECT bid FROM options_prices_live
         WHERE timestamp = opl.timestamp
         AND index_symbol = 'SPX'
         AND strike = ed.short_strike
         AND option_type = 'call') -
        (SELECT ask FROM options_prices_live
         WHERE timestamp = opl.timestamp
         AND index_symbol = 'SPX'
         AND strike = ed.long_strike
         AND option_type = 'call'),
        2
    ) as current_spread_value,
    ROUND(
        ed.entry_credit -
        ((SELECT bid FROM options_prices_live
          WHERE timestamp = opl.timestamp
          AND index_symbol = 'SPX'
          AND strike = ed.short_strike
          AND option_type = 'call') -
         (SELECT ask FROM options_prices_live
          WHERE timestamp = opl.timestamp
          AND index_symbol = 'SPX'
          AND strike = ed.long_strike
          AND option_type = 'call')),
        2
    ) as profit_dollars,
    ROUND(
        100.0 *
        (ed.entry_credit -
         ((SELECT bid FROM options_prices_live
           WHERE timestamp = opl.timestamp
           AND index_symbol = 'SPX'
           AND strike = ed.short_strike
           AND option_type = 'call') -
          (SELECT ask FROM options_prices_live
           WHERE timestamp = opl.timestamp
           AND index_symbol = 'SPX'
           AND strike = ed.long_strike
           AND option_type = 'call'))) / NULLIF(ed.entry_credit, 0),
        1
    ) as profit_pct
FROM options_prices_live opl, entry_data ed
WHERE opl.timestamp >= ed.entry_time
AND opl.timestamp <= DATETIME(ed.entry_time, '+2 hours')
AND opl.index_symbol = ed.idx_symbol
GROUP BY opl.timestamp
ORDER BY opl.timestamp ASC;
```

---

## Part 2: Python Implementation

### DatabaseConnection Class

```python
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

class BlackboxDB:
    """Interface to gex_blackbox.db for backtest data access."""

    def __init__(self, db_path='/gamma-scalper/data/gex_blackbox.db'):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row

    def __del__(self):
        if self.conn:
            self.conn.close()

    def get_option_price(self, timestamp, index_symbol, strike, option_type, use='bid'):
        """
        Get option price at specific timestamp.

        Args:
            timestamp: datetime or string '2026-01-12 14:35:39'
            index_symbol: 'SPX' or 'NDX'
            strike: Strike price (float)
            option_type: 'call' or 'put'
            use: 'bid', 'ask', or 'mid'

        Returns: Price (float) or None
        """
        query = f"""
        SELECT {use}
        FROM options_prices_live
        WHERE timestamp = ?
        AND index_symbol = ?
        AND strike = ?
        AND option_type = ?
        """

        cursor = self.conn.cursor()
        cursor.execute(query, (str(timestamp), index_symbol, strike, option_type))
        result = cursor.fetchone()

        return result[0] if result else None

    def get_spread_value(self, timestamp, index_symbol, short_strike, long_strike, option_type='call'):
        """
        Get current value of a spread (short bid - long ask).

        For selling spreads, we care about:
        - Short leg: What we can sell for (BID)
        - Long leg: What we pay to buy back (ASK)
        - Spread value: Short BID - Long ASK
        """
        short_bid = self.get_option_price(timestamp, index_symbol, short_strike, option_type, 'bid')
        long_ask = self.get_option_price(timestamp, index_symbol, long_strike, option_type, 'ask')

        if short_bid is None or long_ask is None:
            return None

        return short_bid - long_ask

    def get_gex_peak(self, timestamp, index_symbol, peak_rank=1):
        """Get GEX peak information at specific timestamp."""
        query = """
        SELECT * FROM gex_peaks
        WHERE timestamp = ?
        AND index_symbol = ?
        AND peak_rank = ?
        """

        cursor = self.conn.cursor()
        cursor.execute(query, (str(timestamp), index_symbol, peak_rank))
        result = cursor.fetchone()

        return dict(result) if result else None

    def get_competing_peaks(self, timestamp, index_symbol):
        """Check if peaks are competing at timestamp."""
        query = """
        SELECT * FROM competing_peaks
        WHERE timestamp = ?
        AND index_symbol = ?
        """

        cursor = self.conn.cursor()
        cursor.execute(query, (str(timestamp), index_symbol))
        result = cursor.fetchone()

        return dict(result) if result else None

    def get_timestamps(self, date_str, index_symbol='SPX'):
        """Get all 30-second snapshots for a date."""
        query = """
        SELECT DISTINCT timestamp
        FROM options_prices_live
        WHERE DATE(timestamp) = ?
        AND index_symbol = ?
        ORDER BY timestamp ASC
        """

        df = pd.read_sql_query(query, self.conn, params=(date_str, index_symbol))
        return df['timestamp'].tolist()

    def get_option_chain(self, timestamp, index_symbol):
        """Get all options at a specific timestamp."""
        query = """
        SELECT strike, option_type, bid, ask, mid, volume, open_interest
        FROM options_prices_live
        WHERE timestamp = ?
        AND index_symbol = ?
        ORDER BY strike, option_type
        """

        df = pd.read_sql_query(query, self.conn, params=(str(timestamp), index_symbol))
        return df
```

### Entry Credit Calculation

```python
class EntryCalculator:
    """Calculate realistic entry credits using real option prices."""

    def __init__(self, db):
        self.db = db

    def calculate_call_spread_credit(self, timestamp, index_symbol, short_strike, long_strike):
        """
        Calculate credit for SHORT call spread.

        We SHORT short_strike call (get paid BID)
        We LONG long_strike call (pay ASK)

        Net credit = short_bid - long_ask
        """
        short_bid = self.db.get_option_price(timestamp, index_symbol, short_strike, 'call', 'bid')
        long_ask = self.db.get_option_price(timestamp, index_symbol, long_strike, 'call', 'ask')

        if short_bid is None or long_ask is None:
            return None

        return short_bid - long_ask

    def calculate_put_spread_credit(self, timestamp, index_symbol, short_strike, long_strike):
        """
        Calculate credit for SHORT put spread.

        We SHORT short_strike put (get paid BID)
        We LONG long_strike put (pay ASK)
        """
        short_bid = self.db.get_option_price(timestamp, index_symbol, short_strike, 'put', 'bid')
        long_ask = self.db.get_option_price(timestamp, index_symbol, long_strike, 'put', 'ask')

        if short_bid is None or long_ask is None:
            return None

        return short_bid - long_ask

    def calculate_iron_condor_credit(self, timestamp, index_symbol,
                                      call_short, call_long, put_short, put_long):
        """
        Calculate credit for iron condor.

        Total credit = call spread credit + put spread credit
        """
        call_credit = self.calculate_call_spread_credit(timestamp, index_symbol, call_short, call_long)
        put_credit = self.calculate_put_spread_credit(timestamp, index_symbol, put_short, put_long)

        if call_credit is None or put_credit is None:
            return None

        return call_credit + put_credit

    def find_entry_credit_for_gex_peak(self, timestamp, index_symbol, peak_rank=1):
        """
        For a GEX peak, determine the best entry credit.

        Assumes: SHORT at peak, LONG 5 (SPX) or 25 (NDX) points OTM.
        """
        peak_data = self.db.get_gex_peak(timestamp, index_symbol, peak_rank)

        if not peak_data:
            return None

        short_strike = peak_data['strike']
        spread_width = 5 if index_symbol == 'SPX' else 25
        long_strike = short_strike + spread_width

        return self.calculate_call_spread_credit(timestamp, index_symbol, short_strike, long_strike)
```

### Position Tracking Class

```python
class PositionTracker:
    """Track position value and P&L over time."""

    def __init__(self, db, entry_timestamp, index_symbol, short_strike, long_strike,
                 option_type='call', entry_credit=None):
        self.db = db
        self.entry_timestamp = entry_timestamp
        self.index_symbol = index_symbol
        self.short_strike = short_strike
        self.long_strike = long_strike
        self.option_type = option_type

        # Calculate entry credit if not provided
        if entry_credit is None:
            self.entry_credit = self.db.get_spread_value(
                entry_timestamp, index_symbol, short_strike, long_strike, option_type
            )
        else:
            self.entry_credit = entry_credit

        # Tracking state
        self.best_spread_value = self.entry_credit
        self.peak_profit_pct = 0
        self.trailing_activated = False

    def get_profit_pct(self, spread_value):
        """Calculate profit % at current spread value."""
        if self.entry_credit is None or self.entry_credit == 0:
            return 0
        return (self.entry_credit - spread_value) / self.entry_credit

    def check_exit_conditions(self, timestamp, spread_value=None,
                             stop_loss_pct=0.10, profit_target_pct=0.50):
        """
        Check if position should be exited at this timestamp.

        Returns: (should_exit, reason, pnl_dollars)
        """
        # Get current spread value if not provided
        if spread_value is None:
            spread_value = self.db.get_spread_value(
                timestamp, self.index_symbol, self.short_strike, self.long_strike, self.option_type
            )

        if spread_value is None:
            return (False, None, None)

        # Track best spread value
        if spread_value < self.best_spread_value:
            self.best_spread_value = spread_value

        profit_pct = self.get_profit_pct(spread_value)
        peak_profit_pct = self.get_profit_pct(self.best_spread_value)

        # 1. STOP LOSS (highest priority)
        if spread_value > self.entry_credit * (1 + stop_loss_pct):
            pnl = (self.entry_credit - spread_value) * 100
            return (True, f"SL ({int(stop_loss_pct*100)}%)", pnl)

        # 2. TRAILING STOP (if reached 20%, exit below 8%)
        if peak_profit_pct >= 0.20 and not self.trailing_activated:
            self.trailing_activated = True

        if self.trailing_activated and profit_pct < 0.08:
            pnl = (self.entry_credit - spread_value) * 100
            return (True, "Trailing Stop", pnl)

        # 3. PROFIT TARGET
        if profit_pct >= profit_target_pct:
            pnl = (self.entry_credit - spread_value) * 100
            return (True, f"Profit Target ({int(profit_target_pct*100)}%)", pnl)

        # Still holding
        return (False, None, None)
```

### Main Backtest Loop

```python
class RealisticBacktest:
    """Run backtest using real option prices."""

    def __init__(self, db_path='/gamma-scalper/data/gex_blackbox.db'):
        self.db = BlackboxDB(db_path)
        self.entry_calc = EntryCalculator(self.db)
        self.trades = []

    def backtest_date(self, date_str, index_symbol='SPX', min_credit=0.50):
        """
        Run backtest for a single trading day.

        Args:
            date_str: '2026-01-12'
            index_symbol: 'SPX' or 'NDX'
            min_credit: Minimum credit to enter (filters low-credit trades)
        """
        timestamps = self.db.get_timestamps(date_str, index_symbol)

        if not timestamps:
            print(f"No data for {date_str} {index_symbol}")
            return

        entry_timestamp = timestamps[0]  # First opportunity of the day

        # For demo, let's trade the first viable setup
        peak_data = self.db.get_gex_peak(entry_timestamp, index_symbol, peak_rank=1)

        if not peak_data:
            return

        # Entry setup
        short_strike = peak_data['strike']
        long_strike = short_strike + (5 if index_symbol == 'SPX' else 25)

        # Calculate entry credit
        entry_credit = self.entry_calc.calculate_call_spread_credit(
            entry_timestamp, index_symbol, short_strike, long_strike
        )

        if entry_credit is None or entry_credit < min_credit:
            return

        # Simulate position
        tracker = PositionTracker(
            self.db, entry_timestamp, index_symbol, short_strike, long_strike, 'call', entry_credit
        )

        # Check each subsequent timestamp for exits
        for timestamp_idx, check_timestamp in enumerate(timestamps[1:], start=1):
            should_exit, reason, pnl = tracker.check_exit_conditions(check_timestamp)

            if should_exit:
                # Record trade
                self.trades.append({
                    'date': date_str,
                    'index': index_symbol,
                    'entry_time': entry_timestamp,
                    'exit_time': check_timestamp,
                    'short_strike': short_strike,
                    'long_strike': long_strike,
                    'entry_credit': entry_credit,
                    'exit_reason': reason,
                    'pnl': round(pnl, 2),
                    'pnl_pct': round((pnl / (entry_credit * 100)) * 100, 1)
                })
                return

        # Held to close
        final_spread = self.db.get_spread_value(
            timestamps[-1], index_symbol, short_strike, long_strike, 'call'
        )
        if final_spread:
            self.trades.append({
                'date': date_str,
                'index': index_symbol,
                'entry_time': entry_timestamp,
                'exit_time': timestamps[-1],
                'short_strike': short_strike,
                'long_strike': long_strike,
                'entry_credit': entry_credit,
                'exit_reason': 'Hold to Close',
                'pnl': round((entry_credit - final_spread) * 100, 2),
                'pnl_pct': round(((entry_credit - final_spread) / entry_credit) * 100, 1)
            })

    def print_results(self):
        """Print backtest summary."""
        if not self.trades:
            print("No trades executed")
            return

        df = pd.DataFrame(self.trades)

        total_pnl = df['pnl'].sum()
        winners = df[df['pnl'] > 0]
        losers = df[df['pnl'] <= 0]

        print(f"\n{'='*70}")
        print(f"REALISTIC BACKTEST RESULTS")
        print(f"{'='*70}\n")

        print(f"Total Trades: {len(df)}")
        print(f"Total P/L: ${total_pnl:,.0f}")
        print(f"Win Rate: {len(winners)/len(df)*100:.1f}%")
        print(f"Avg Winner: ${winners['pnl'].mean():,.0f}")
        print(f"Avg Loser: ${losers['pnl'].mean():,.0f}")

        print(f"\nTrade Log:")
        print(df.to_string(index=False))

# Usage
if __name__ == '__main__':
    backtest = RealisticBacktest()
    backtest.backtest_date('2026-01-12', 'SPX', min_credit=0.50)
    backtest.print_results()
```

---

## Part 3: Integration Checklist

- [ ] Create `BlackboxDB` class in `db_interface.py`
- [ ] Create `EntryCalculator` class in `entry_calculator.py`
- [ ] Create `PositionTracker` class in `position_tracker.py`
- [ ] Create `RealisticBacktest` class in `realistic_backtest_v2.py`
- [ ] Add SQL queries to `queries.sql`
- [ ] Test with single trade (known entry/exit)
- [ ] Run backtest for 2026-01-12 (full day)
- [ ] Compare results: before vs after
- [ ] Validate P&L distribution (should be diverse, not fixed)
- [ ] Document findings

---

## Part 4: Validation Tests

### Test 1: Entry Credit Accuracy

```python
# Verify entry credits are realistic
db = BlackboxDB()
entry_credit = db.get_spread_value('2026-01-12 14:35:39', 'SPX', 6975.0, 6980.0, 'call')
print(f"Entry credit: ${entry_credit:.2f}")
# Expected: $1.10 (not $2.50 estimated)
```

### Test 2: Price Path Tracking

```python
# Verify spread value changes realistically
timestamps = db.get_timestamps('2026-01-12', 'SPX')
for ts in timestamps[:10]:
    value = db.get_spread_value(ts, 'SPX', 6975.0, 6980.0, 'call')
    print(f"{ts}: Spread = ${value:.2f}")
# Expected: Values like [1.10, 1.55, 2.05, 2.00, 1.90, ...]
```

### Test 3: P&L Distribution

```python
# After running backtest, check P/L distribution
df = pd.DataFrame(trades)
winners = df[df['pnl'] > 0]
losers = df[df['pnl'] <= 0]

print(f"Winner range: ${winners['pnl'].min():.0f} to ${winners['pnl'].max():.0f}")
print(f"Loser range: ${losers['pnl'].min():.0f} to ${losers['pnl'].max():.0f}")
# Expected: Diverse ranges, NOT all $250 or -$250
```

---

## References

- Database schema: `/gamma-scalper/data/gex_blackbox.db`
- Option pricing data: `options_prices_live` table (418,170 records)
- GEX peaks: `gex_peaks` table
- Competing peaks: `competing_peaks` table
- Historical example: See `REALISTIC_PNL_EXAMPLE.md`
