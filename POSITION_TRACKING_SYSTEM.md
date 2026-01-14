# Position Tracking & Reconciliation System

## Problem

The gamma scalper bot had a critical flaw: **positions could exist in the broker account but not be tracked by the monitor**, resulting in:

- ❌ No stop loss protection
- ❌ No profit target monitoring  
- ❌ No automatic exits
- ❌ "Zombie" positions flying unmonitored

### Root Cause

The `orders_paper.json` (tracking file) wasn't being populated when positions were opened, leaving the monitor with zero awareness of open positions.

## Solution Architecture

### 1. Position Reconciliation (`position_reconciliation.py`)

**Compares broker account to tracking file and detects discrepancies:**

```bash
python3 position_reconciliation.py PAPER
```

Output:
```
POSITION RECONCILIATION — PAPER MODE
================================================
Broker Account Positions: 8
Monitor Tracked Orders:  3
Orphaned Symbols:        5 ← NOT BEING MONITORED!
```

### 2. Orphaned Position Recovery (`recover_orphaned_positions.py`)

**Reconstructs tracking file from broker account positions:**

```bash
python3 recover_orphaned_positions.py PAPER
```

Calculates entry credits:
- **Short legs**: Cost basis is negative (credit received)
- **Long legs**: Cost basis is positive (debit paid)
- **Net credit**: `-sum(all cost_basis)` = total credit received per contract

### 3. Monitor Integration (`monitor_reconciliation_integration.py`)

**Automatically runs on monitor startup to:**
- Fetch all positions from broker
- Detect orphaned positions  
- Add them to tracking file
- Log discrepancies

**Integration code (to be added to monitor.py):**

```python
from monitor_reconciliation_integration import reconcile_positions_on_startup

# In monitor startup section:
reconcile_positions_on_startup(mode)  # Run before main monitoring loop
```

## Workflow

### On Monitor Startup

```
Monitor starts
    ↓
Reconciliation runs
    ├─ Fetch broker positions
    ├─ Load tracking file
    ├─ Detect orphans
    └─ Add to tracking
    ↓
Main monitoring loop
    ├─ Check each tracked order
    ├─ Apply stop losses
    ├─ Monitor profit targets
    └─ Execute exits
```

### During Operation

1. **Scalper opens position** → writes to `orders_paper.json`
2. **Monitor reads tracking file** → starts monitoring
3. **Monitor checks every 15s** → applies stops, monitors TP
4. **Position closes** → removed from tracking, added to trades.csv

### After Crash/Restart

1. **Monitor restarts** → runs reconciliation automatically
2. **Reconciliation detects orphans** → positions that exist in broker but not in tracking
3. **Recovery adds them back** → to tracking file
4. **Monitoring resumes** → with full stop loss protection

## Critical Files

| File | Purpose |
|------|---------|
| `position_reconciliation.py` | Detect orphaned positions |
| `recover_orphaned_positions.py` | Recover orphans to tracking |
| `monitor_reconciliation_integration.py` | Automatic startup reconciliation |
| `data/orders_paper.json` | Tracking file for PAPER account |
| `data/orders_live.json` | Tracking file for LIVE account |

## Usage

### Manual Reconciliation Check

```bash
python3 position_reconciliation.py PAPER
```

### Manual Orphan Recovery

```bash
python3 recover_orphaned_positions.py PAPER
```

### Dry Run (preview changes)

```bash
python3 recover_orphaned_positions.py PAPER --dry-run
```

## Entry Credit Calculation

For a **PUT spread** with orphaned positions:

```
Long $25560P:   Cost basis = +$1,320  (debit paid)
Short $25620P:  Cost basis = -$2,100  (credit received)

Entry credit = -(+1,320 + -2,100) = -(-780) = +$780 per contract
```

This represents the net credit received per contract.

## Monitoring Parameters

Once recovered, orphaned positions are monitored with:
- **Stop Loss**: 10% (after 180s grace)
- **Emergency Stop**: 40% (hard limit)
- **Profit Target**: 50% (on HIGH confidence), 60% (on MEDIUM)
- **Trailing Stops**: Activate at 20%, lock 12%, trail to 8%

## Testing Checklist

- [x] Reconciliation detects 8 orphaned positions
- [x] Recovery calculates correct entry credits
- [x] Monitor loads recovered positions
- [x] Monitor applies stop losses to recovered positions
- [ ] Full integration with monitor.py startup
- [ ] Test position closes correctly after stop loss
- [ ] Test show.py displays recovered positions

## Future Improvements

1. **Broker API as Source of Truth** - Query broker on every show.py update
2. **Persistent Position State** - Database tracking of all position history
3. **Automatic Crash Recovery** - Monitor detects and recovers on startup automatically
4. **Position Reconciliation Reports** - Daily reports of any discrepancies
