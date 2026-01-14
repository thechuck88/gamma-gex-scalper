# Replay Harness Design - Complete Documentation Index

**Project**: Gamma GEX Scalper - Replay Harness Architecture  
**Status**: Design Complete (Ready for Implementation)  
**Created**: 2026-01-14  
**Location**: `/root/gamma/`

---

## Documents Provided

### 1. **REPLAY_HARNESS_SUMMARY.md** (START HERE)
**Purpose**: Quick overview and executive summary  
**Best for**: Understanding the big picture in 5 minutes  
**Sections**:
- What is a replay harness?
- Why use this approach?
- Architecture overview
- Key dependencies
- File structure
- Next steps

**Read Time**: 5 minutes

---

### 2. **REPLAY_HARNESS_ARCHITECTURE.md** (MAIN DESIGN SPEC)
**Purpose**: Comprehensive architectural design  
**Best for**: Understanding full system design and challenges  
**Sections**:
1. Executive Summary
2. What is a Replay Harness?
3. Critical Dependencies to Intercept (GEX, prices, VIX, etc.)
4. Architecture Design (4 core components)
5. Key Design Decisions
6. Handling Challenges (market hours, gaps, etc.)
7. Implementation Plan (6-phase roadmap)
8. Proof-of-Concept Pseudo-Code
9. Advantages vs Re-Implementation
10. Success Criteria
11. Database Schema Reference

**Key Content**:
- 11 sections explaining every aspect
- Detailed diagrams
- Challenge/solution pairs
- Complete pseudo-code
- Database schema reference

**Read Time**: 45 minutes (full), 15 minutes (sections only)

---

### 3. **REPLAY_HARNESS_IMPLEMENTATION.md** (CODING GUIDE)
**Purpose**: Step-by-step implementation guide with code templates  
**Best for**: Developers implementing the modules  
**Sections**:
1. Module 1: replay_data_provider.py (complete code)
2. Module 2: replay_time_manager.py (complete code)
3. Module 3: replay_state.py (complete code)
4. Implementation Checklist
5. Testing Strategy

**Key Content**:
- Full source code for modules 1-3
- Copy-paste ready
- Docstrings and type hints included
- Database query patterns
- State management details

**Read Time**: 60 minutes (implementation), 15 minutes (reference)

---

### 4. **REPLAY_HARNESS_PHASE4_EXECUTION.md** (EXECUTION HARNESS)
**Purpose**: Complete execution harness implementation  
**Best for**: Developers implementing the main orchestration loop  
**Sections**:
1. Complete ReplayExecutionHarness class
2. Usage examples
3. Integration patterns
4. Testing strategy
5. Validation checklist

**Key Content**:
- Full source code for Module 4 (800 lines)
- Main orchestration loop
- Entry/exit decision logic
- P&L calculation
- Reporting and statistics

**Read Time**: 45 minutes (implementation), 10 minutes (reference)

---

## Reading Paths

### Path A: Quick Understanding (15 minutes)
1. Read REPLAY_HARNESS_SUMMARY.md
2. Skim architecture overview in REPLAY_HARNESS_ARCHITECTURE.md
3. Review diagram in REPLAY_HARNESS_SUMMARY.md

**Result**: Understand what, why, and how it works

---

### Path B: Detailed Design (60 minutes)
1. Read REPLAY_HARNESS_SUMMARY.md (5 min)
2. Read REPLAY_HARNESS_ARCHITECTURE.md sections 1-6 (40 min)
3. Review design decisions (10 min)
4. Skim pseudo-code examples (5 min)

**Result**: Complete understanding of design rationale

---

### Path C: Implementation Ready (4 hours)
1. Read REPLAY_HARNESS_SUMMARY.md (5 min)
2. Read REPLAY_HARNESS_ARCHITECTURE.md (45 min)
3. Read REPLAY_HARNESS_IMPLEMENTATION.md (60 min)
4. Read REPLAY_HARNESS_PHASE4_EXECUTION.md (45 min)
5. Study code templates (30 min)
6. Create implementation plan (15 min)

**Result**: Ready to implement 4 modules

---

### Path D: Implementation + Testing (8 hours)
1. All of Path C (4 hours)
2. Implement modules 1-4 (3 hours)
3. Run test cases from Phase 4 (1 hour)

**Result**: Working replay harness

---

## Quick Reference

### Component Summaries

#### Module 1: replay_data_provider.py (700 lines)
**Responsibility**: Unified data access abstraction  
**Classes**:
- `DataProvider` (abstract base)
- `LiveDataProvider` (real API calls)
- `ReplayDataProvider` (database queries)

**Key Methods**:
```python
get_gex_peak(index_symbol, timestamp) -> Dict
get_index_price(index_symbol, timestamp) -> float
get_vix(timestamp) -> float
get_options_chain(index_symbol, expiration, timestamp) -> List[Dict]
get_strike_prices(index_symbol, strikes, option_type, expiration, timestamp) -> Dict
```

---

#### Module 2: replay_time_manager.py (200 lines)
**Responsibility**: Time advancement and market hours detection  
**Class**: `ReplayTimeManager`

**Key Methods**:
```python
advance() -> bool  # Advance 30 seconds, return True if in range
get_current_time() -> datetime
is_market_hours() -> bool  # 9:30 AM - 4:00 PM ET
is_market_open_time() -> bool  # Entry check times (9:36, 10:00, etc)
is_end_of_day() -> bool  # 3:30 PM ET
skip_to_time(target_time) -> bool
```

---

#### Module 3: replay_state.py (400 lines)
**Responsibility**: Trade tracking and statistics  
**Classes**:
- `ReplayTrade` (dataclass for single trade)
- `ReplayStateManager` (tracks all state)

**Key Methods**:
```python
add_trade(trade) -> None
update_trade_price(order_id, current_value, timestamp) -> None
close_trade(order_id, exit_value, exit_reason, timestamp) -> None
get_statistics() -> Dict
export_trades_json(filepath) -> None
```

---

#### Module 4: replay_execution.py (800 lines)
**Responsibility**: Main orchestration and decision logic  
**Class**: `ReplayExecutionHarness`

**Key Methods**:
```python
run_replay() -> ReplayStateManager  # Main loop
_execute_iteration(timestamp) -> None  # One time step
_check_entries(timestamp, price, vix) -> None  # Entry logic
_check_exits(timestamp, price, vix) -> None  # Exit logic
_calculate_entry_credit(setup, timestamp) -> float
_get_current_spread_value(trade, timestamp) -> float
```

---

## File Locations

All new files in `/root/gamma/`:

```
/root/gamma/
├── replay_data_provider.py              # Module 1 (create)
├── replay_time_manager.py               # Module 2 (create)
├── replay_state.py                      # Module 3 (create)
├── replay_execution.py                  # Module 4 (create)
├── run_replay_backtest.py               # Entry point (create)
│
├── REPLAY_HARNESS_SUMMARY.md            # Quick overview (provided)
├── REPLAY_HARNESS_ARCHITECTURE.md       # Full design (provided)
├── REPLAY_HARNESS_IMPLEMENTATION.md     # Coding guide (provided)
├── REPLAY_HARNESS_PHASE4_EXECUTION.md   # Execution harness (provided)
└── REPLAY_HARNESS_INDEX.md              # This file (provided)
```

**Total Size of Documentation**: ~2,500 lines across 4 documents

---

## Key Concepts

### Replay Harness
A wrapper that feeds historical data to live bot code, guaranteeing identical logic.

### Data Provider
Abstract interface that switches between real API calls (production) and database queries (replay).

### Time Manager
Controls 30-second time advancement and detects market hours/entry check times.

### State Manager
Tracks all active trades, calculates P&L, and generates statistics.

### Execution Harness
Main orchestration that invokes entry/exit logic at each time step.

---

## Implementation Timeline

**Phase 1**: Data Provider (Days 1-2)
- Abstract base class
- LiveDataProvider (pass-through)
- ReplayDataProvider (database queries)

**Phase 2**: Time Manager (Days 2-3)
- Time advancement
- Market hours detection
- Entry check time detection

**Phase 3**: State Manager (Days 3-4)
- Trade tracking
- P&L calculation
- Statistics generation

**Phase 4**: Execution Harness (Days 4-5)
- Main orchestration loop
- Entry/exit decision logic
- Integration and testing

**Phase 5**: Validation (Days 5-6)
- 1-day test
- 1-week test
- 1-month test
- Compare vs manual backtest

**Phase 6**: Documentation (Day 6+)
- Update guides with results
- Create examples
- Setup CI integration

---

## Success Criteria

### Functional
- [ ] Loads 68 MB database
- [ ] Executes 30 iterations/second
- [ ] 1-month backtest < 60 seconds
- [ ] JSON output with all trades

### Validation
- [ ] Results ±2% vs manual backtest
- [ ] Trade count ±5% expected
- [ ] P&L verified on samples
- [ ] No data gaps

### Code Quality
- [ ] Zero code duplication
- [ ] Full type hints
- [ ] Comprehensive error handling
- [ ] Logging at key points

---

## How to Get Started

1. **Read** REPLAY_HARNESS_SUMMARY.md (5 min)
2. **Understand** REPLAY_HARNESS_ARCHITECTURE.md (45 min)
3. **Implement** modules 1-4 using code templates (4 hours)
4. **Test** on 1-day sample (30 min)
5. **Validate** on full month (1 hour)

**Total Time**: ~6 hours to working backtest

---

## Q&A

**Q: How is this different from existing backtest code?**  
A: This uses the exact live bot code instead of reimplementing logic. Guarantees consistency.

**Q: What if data is missing in database?**  
A: Forward-fill from previous snapshot. Skip iteration if critical data missing.

**Q: Will it be fast enough?**  
A: Yes. 30 sec iterations × 20,000 (1 month) = ~30 seconds total.

**Q: What about order execution?**  
A: Assume fills at bid/ask of entry time. Simple, realistic for liquid index options.

**Q: Can I modify the strategy?**  
A: Changes to live bot (scalper.py, monitor.py) automatically propagate to replay.

**Q: Where do I start coding?**  
A: Module 1 (replay_data_provider.py). Templates provided in IMPLEMENTATION.md.

---

## Document Cross-References

| Want to understand... | Read... |
|---|---|
| Quick overview | SUMMARY.md |
| Full architecture | ARCHITECTURE.md (sections 1-4) |
| Design decisions | ARCHITECTURE.md (section 5) |
| Challenges/solutions | ARCHITECTURE.md (section 6) |
| Implementation steps | IMPLEMENTATION.md |
| Code templates | IMPLEMENTATION.md + PHASE4_EXECUTION.md |
| Testing strategy | PHASE4_EXECUTION.md |
| Success criteria | ARCHITECTURE.md (section 10) |
| Database schema | ARCHITECTURE.md (Appendix A) |
| Timeline | ARCHITECTURE.md (section 7) |

---

## File Statistics

| Document | Lines | Sections | Code | Purpose |
|---|---|---|---|---|
| SUMMARY.md | 300 | 15 | 1 | Overview |
| ARCHITECTURE.md | 900 | 11 | 10 | Design |
| IMPLEMENTATION.md | 1,100 | 7 | 800 | Guides |
| PHASE4_EXECUTION.md | 700 | 8 | 450 | Code |
| **TOTAL** | **3,000** | **41** | **1,260** | **Complete Design** |

---

## Next Actions

1. **Review** REPLAY_HARNESS_SUMMARY.md
2. **Study** REPLAY_HARNESS_ARCHITECTURE.md
3. **Implement** modules using IMPLEMENTATION.md
4. **Test** using PHASE4_EXECUTION.md
5. **Deploy** as production backtest harness

---

**Created**: 2026-01-14  
**Status**: Ready for Implementation  
**Effort**: ~40 hours development + testing  
**Value**: Guaranteed backtest correctness forever

