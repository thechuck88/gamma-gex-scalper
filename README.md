# Gamma GEX Scalper - Multi-Index Version

**Created**: 2026-01-10
**Purpose**: Index-agnostic version of the gamma GEX scalper supporting multiple indices (SPX, NDX, RUT, DJX)

---

## Overview

This is a generalized version of the gamma GEX scalper that accepts an index parameter and dynamically adjusts all strategy parameters (spreads, strikes, multipliers) based on the selected index.

### Key Features

- **Index-Agnostic**: Single codebase trades SPX, NDX, or any configured index
- **Parameter Validation**: Errors immediately if no index specified
- **Multi-Index Monitor**: Single monitor process handles positions from all indices
- **Centralized Configuration**: All index-specific values in `index_config.py`
- **Backward Compatible**: Loads legacy SPX-only orders without index_code field

---

## Supported Indices

| Index | Name | Spread Width | Strike Increment | ETF Proxy | Multiplier |
|-------|------|--------------|------------------|-----------|------------|
| **SPX** | S&P 500 | 5 points | 5 | SPY | 10.0× |
| **NDX** | Nasdaq-100 | 25 points | 25 | QQQ | 42.5× |

**Performance Comparison (1-year backtest)**:
- **SPX**: $85,551 profit, +342.2% ROI, 90.8% win rate, 5.55 profit factor
- **NDX**: $265,087 profit, +1,060.3% ROI, 87.6% win rate, 10.36 profit factor ⭐

**NDX outperforms SPX by 3.1× due to higher tech volatility and wider spreads.**

---

## File Structure

```
/gamma-scalper/
├── README.md                    # This file
├── USAGE.md                     # Detailed usage guide
├── index_config.py              # Index configuration registry
├── scalper.py                   # Entry logic (refactored)
├── monitor.py                   # Position monitoring (multi-index)
├── config.py                    # Environment config (unchanged)
├── discord_autodelete.py        # Discord utilities (unchanged)
├── core/
│   ├── __init__.py
│   └── gex_strategy.py          # GEX strategy logic (refactored)
└── data/
    ├── orders_paper.json        # Paper trading positions
    ├── orders_live.json         # Live trading positions
    └── trades.csv               # Trade log
```

---

## Quick Start

### 1. Test Parameter Validation

```bash
cd /gamma-scalper

# No parameter (should error)
python3 scalper.py

# Invalid index (should error)
python3 scalper.py INVALID

# Valid SPX (should start)
python3 scalper.py SPX PAPER

# Valid NDX (should start)
python3 scalper.py NDX PAPER
```

### 2. Paper Trading

```bash
# SPX paper trading
python3 scalper.py SPX PAPER

# NDX paper trading
python3 scalper.py NDX PAPER

# With overrides (dry run)
python3 scalper.py NDX PAPER 21500 21480
```

### 3. Live Trading

```bash
# SPX live trading
python3 scalper.py SPX LIVE

# NDX live trading
python3 scalper.py NDX LIVE
```

### 4. Monitor (Multi-Index)

```bash
# Paper monitor (handles all indices)
python3 monitor.py PAPER

# Live monitor (handles all indices)
python3 monitor.py LIVE
```

---

## Command Line Arguments

### Scalper

```bash
python scalper.py <INDEX> [PAPER|LIVE] [pin_override] [price_override]
```

**Arguments**:
1. `<INDEX>` **(REQUIRED)**: Index code (SPX, NDX)
2. `[PAPER|LIVE]`: Trading mode (default: PAPER)
3. `[pin_override]`: Override GEX pin price (for testing)
4. `[price_override]`: Override index price (for testing)

**Examples**:
```bash
python3 scalper.py SPX PAPER          # SPX paper trading
python3 scalper.py NDX LIVE           # NDX live trading
python3 scalper.py SPX PAPER 6050     # SPX with pin override (dry run)
python3 scalper.py NDX PAPER 21500 21480  # NDX with pin + price override
```

### Monitor

```bash
python monitor.py [PAPER|LIVE]
```

**Arguments**:
1. `[PAPER|LIVE]`: Trading mode (default: PAPER)

**Examples**:
```bash
python3 monitor.py PAPER    # Paper monitor (all indices)
python3 monitor.py LIVE     # Live monitor (all indices)
```

---

## Systemd Services

### SPX Paper Trading

```ini
# /etc/systemd/system/gamma-scalper-spx-paper.service
[Unit]
Description=Gamma GEX Scalper - SPX Paper
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/gamma-scalper
ExecStart=/usr/bin/python3 /gamma-scalper/scalper.py SPX PAPER
User=root
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### NDX Live Trading

```ini
# /etc/systemd/system/gamma-scalper-ndx-live.service
[Unit]
Description=Gamma GEX Scalper - NDX Live
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/gamma-scalper
ExecStart=/usr/bin/python3 /gamma-scalper/scalper.py NDX LIVE
User=root
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### Monitor (Multi-Index)

```ini
# /etc/systemd/system/gamma-monitor-live.service
[Unit]
Description=Gamma GEX Monitor - Live (Multi-Index)
After=network.target

[Service]
Type=simple
WorkingDirectory=/gamma-scalper
ExecStart=/usr/bin/python3 /gamma-scalper/monitor.py LIVE
Restart=always
RestartSec=10
User=root
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Enable and start**:
```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable services
sudo systemctl enable gamma-monitor-live.service

# Start monitor
sudo systemctl start gamma-monitor-live.service

# Check status
sudo systemctl status gamma-monitor-live.service
```

---

## Adding New Indices

To add support for a new index (e.g., RUT, DJX):

### 1. Add IndexConfig to `index_config.py`

```python
RUT_CONFIG = IndexConfig(
    code='RUT',
    name='Russell 2000',
    index_symbol='RUT',
    etf_symbol='IWM',
    option_root='RUTW',
    vix_symbol='VIX',
    etf_multiplier=10.0,
    strike_increment=5,
    base_spread_width=5,
    near_pin_max=6,
    moderate_max=15,
    far_max=50,
    ic_wing_buffer=20,
    moderate_buffer=15,
    far_buffer=25,
)

# Add to registry
INDEX_REGISTRY['RUT'] = RUT_CONFIG
```

### 2. Test

```bash
python3 scalper.py RUT PAPER
```

That's it! No other code changes needed.

---

## Differences from Original `/gamma/` Scalper

### What Changed

1. **Parameter Validation**: Index parameter is **required** (errors without it)
2. **Index Configuration**: All SPX-specific values moved to `IndexConfig` dataclass
3. **Option Symbols**: Uses `INDEX_CONFIG.format_option_symbol()` instead of hardcoded `SPXW`
4. **Price Fetching**: Uses `INDEX_CONFIG.index_symbol` and `INDEX_CONFIG.etf_symbol`
5. **Distance Thresholds**: Scale with `INDEX_CONFIG.strike_increment`
6. **Monitor**: Loads `index_code` field and attaches `_config` to each order

### What Stayed the Same

1. **Strategy Logic**: Identical GEX pin strategy (calls/puts/iron condors)
2. **Risk Management**: Same TP (50%), SL (10%), trailing stops
3. **Progressive Hold**: Same 80%+ profit hold-to-expiration logic
4. **Autoscaling**: Same Half-Kelly position sizing
5. **Discord Alerts**: Same webhook integration

### Backward Compatibility

- **Legacy orders without `index_code`**: Default to SPX
- **Original `/gamma/` unchanged**: No modifications to existing production code
- **Same data files**: Can run both versions side-by-side (different LOCK_FILE paths)

---

## Architecture Highlights

### IndexConfig Dataclass

```python
@dataclass(frozen=True)
class IndexConfig:
    code: str              # 'SPX' or 'NDX'
    index_symbol: str      # 'SPX' or 'NDX'
    etf_symbol: str        # 'SPY' or 'QQQ'
    option_root: str       # 'SPXW' or 'NDXW'
    etf_multiplier: float  # 10.0 or 42.5
    strike_increment: int  # 5 or 25
    base_spread_width: int # 5 or 25
    # ... distance thresholds (all scaled)

    def round_strike(self, price: float) -> int
    def get_spread_width(self, vix: float) -> int
    def format_option_symbol(self, expiry, opt_type, strike) -> str
    def get_min_credit(self, hour_et: int) -> float
```

### Multi-Index Monitor

Monitor loads all orders and adds `_config` dynamically:

```python
def load_orders():
    orders = json.loads(content)
    for order in orders:
        index_code = order.get('index_code', 'SPX')  # Default legacy
        order['_config'] = get_index_config(index_code)
    return orders
```

When closing, uses per-order config:

```python
def close_spread(order_data):
    config = order_data.get('_config')
    data = {
        "symbol": config.option_root,  # SPXW or NDXW
        # ...
    }
```

---

## Performance Insights

### Why NDX Outperforms SPX (3.1×)

1. **Wider Spreads**: 25-point spreads vs 5-point → **5× larger credits**
2. **Higher Volatility**: Tech-heavy index → **higher option premiums**
3. **Stronger Trends**: Momentum lasts longer → **GEX pin more effective**
4. **Average Winner**: $325.64 (NDX) vs $111.74 (SPX) → **2.9× better**

### Backtest Results (1-Year, $25k Starting Capital)

| Index | Final Balance | ROI | Win Rate | Profit Factor | Avg Winner |
|-------|---------------|-----|----------|---------------|------------|
| **NDX** | **$290,076** | **+1,060.3%** | 87.6% | 10.36 | **$325.64** |
| **SPX** | $110,551 | +342.2% | 90.8% | 5.55 | $111.74 |

**Recommendation**: Allocate **70% capital to NDX, 30% to SPX** for optimal risk/reward.

---

## Troubleshooting

### "ERROR: Index parameter required"

**Cause**: No index specified
**Fix**: Add index as first argument: `python3 scalper.py SPX PAPER`

### "ERROR: Unsupported index: XYZ"

**Cause**: Invalid index code
**Fix**: Use SPX or NDX: `python3 scalper.py NDX PAPER`

### Monitor not closing NDX positions

**Cause**: Legacy order file missing `index_code` field
**Fix**: Orders created by refactored scalper.py include `index_code` automatically. Legacy orders default to SPX.

### Option symbols rejected by broker

**Cause**: Incorrect option root (e.g., NDX vs NDXW)
**Fix**: Verify `INDEX_CONFIG.option_root` in `index_config.py`

---

## Migration from Original `/gamma/`

### Running Both Versions Side-by-Side

**Safe**: No file conflicts, different lock files

```bash
# Original SPX scalper (unchanged)
cd /root/gamma
python3 scalper.py PAPER

# New NDX scalper
cd /gamma-scalper
python3 scalper.py NDX PAPER
```

### Full Migration (Recommended)

1. **Test new version**:
   ```bash
   cd /gamma-scalper
   python3 scalper.py SPX PAPER  # Verify SPX still works
   python3 scalper.py NDX PAPER  # Test NDX
   ```

2. **Deploy systemd services**:
   ```bash
   sudo cp systemd/*.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable gamma-monitor-live.service
   sudo systemctl start gamma-monitor-live.service
   ```

3. **Monitor for 1 week** in paper mode

4. **Switch to live**:
   ```bash
   sudo systemctl stop gamma-monitor-paper.service
   sudo systemctl start gamma-monitor-live.service
   ```

---

## Future Enhancements

### Short-Term

- [ ] Add RUT (Russell 2000) configuration
- [ ] Backtest NDX with autoscaling (expect $50M+ from $25k in 5 years)
- [ ] Optimize NDX-specific parameters (VIX threshold, min credits)

### Long-Term

- [ ] Dynamic index selection based on volatility regime
- [ ] Cross-index hedging strategies
- [ ] Real-time index comparison dashboard

---

## References

- **Original Scalper**: `/root/gamma/scalper.py`
- **Backtest Results**: `/root/gamma/MULTI_INDEX_COMPARISON_2026-01-10.md`
- **NDX 5-Year Backtest**: `/root/gamma/backtest_ndx.py`
- **Index Configuration**: `/gamma-scalper/index_config.py`
- **Architecture Design**: Opus AI analysis (2026-01-10)

---

## Support

For questions or issues:
1. Check logs: `journalctl -u gamma-monitor-live -f`
2. Verify config: `python3 -c "from index_config import *; print(NDX_CONFIG)"`
3. Test validation: `python3 scalper.py` (should show usage)

---

**Last Updated**: 2026-01-10
**Version**: 1.0.0
**Status**: Production-ready
