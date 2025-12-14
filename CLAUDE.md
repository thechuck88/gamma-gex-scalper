# CLAUDE.md — Gamma Scalper System

## Overview
Automated SPX 0DTE options scalping system using GEX (Gamma Exposure) pin levels. Trades credit spreads (put spreads, call spreads, iron condors) based on SPX proximity to the GEX pin.

## Architecture

```
scalper.py      → Entry logic, places trades via Tradier API
monitor.py      → Monitors positions, handles TP/SL/trailing stops
show.py         → Display positions, P/L, market data
check_trading_day.py → Creates /etc/trading-day flag if valid trading day
config.py       → Loads credentials from environment variables
```

## Environment Variables

All secrets stored in `/etc/gamma.env` (systemd) and `~/.bashrc` (interactive):

```bash
TRADIER_SANDBOX_KEY     # Paper trading API key
TRADIER_LIVE_KEY        # Live trading API key
TRADIER_PAPER_ACCOUNT_ID
TRADIER_LIVE_ACCOUNT_ID
DISCORD_WEBHOOK_URL     # Trade alerts
DISCORD_DELAYED_WEBHOOK_URL
HEALTHCHECK_URL         # Monitor heartbeat
```

## Common Commands

```bash
# Run scalper manually (paper mode)
./scalper.py

# Run scalper in live mode
./scalper.py LIVE

# Show positions and P/L
./show.py           # Paper account
./show.py LIVE      # Live account
./show.py ALL       # Both accounts

# Check monitor status
systemctl status gamma-monitor-paper.service
systemctl status gamma-monitor-live.service

# View monitor logs
journalctl -u gamma-monitor-paper.service -f

# Restart monitors
systemctl restart gamma-monitor-paper.service gamma-monitor-live.service
```

## Cron Schedule (ET timezone)

| Time | Job |
|------|-----|
| 8:00 AM | `check_trading_day.py` — Creates `/etc/trading-day` if not FOMC/holiday |
| 8:07 AM | Restart monitor services |
| 9:36 AM | Scalper run |
| 10:00 AM | Scalper run |
| 11:00 AM | Scalper run |
| 12:00 PM | Scalper run |
| 1:00 PM | Scalper run |

Scalper only runs if `/etc/trading-day` exists.

## Key Files

| File | Purpose |
|------|---------|
| `/etc/gamma.env` | Environment variables (chmod 600) |
| `/etc/trading-day` | Flag file created on valid trading days |
| `/tmp/gexscalper.lock` | Prevents concurrent scalper runs (auto-cleans after 5 min) |
| `data/orders_paper.json` | Active positions being monitored |
| `data/trades.csv` | Trade history log |
| `data/scalper.log` | Scalper cron output |

## Monitor Settings (monitor.py)

```python
POLL_INTERVAL = 15          # Seconds between checks
PROFIT_TARGET_PCT = 0.50    # 50% profit target
STOP_LOSS_PCT = 0.15        # 15% stop loss
TRAILING_TRIGGER_PCT = 0.25 # Activate trailing at 25% profit
TRAILING_LOCK_IN_PCT = 0.10 # Lock in 10% when trailing starts
TRAILING_DISTANCE_MIN = 0.08 # Trail tightens to 8% behind peak
AUTO_CLOSE_HOUR = 15        # Auto-close at 3:50 PM ET
AUTO_CLOSE_MINUTE = 50
```

## Trade Strategies

- **PUT spread**: When SPX above GEX pin (bearish lean)
- **CALL spread**: When SPX below GEX pin (bullish lean)
- **Iron Condor (IC)**: When SPX near GEX pin (neutral, collect premium both sides)

## FOMC / Holiday Exclusions

`check_trading_day.py` skips trading on:
- FOMC announcement days (hardcoded 2025 dates)
- Early close days (Jul 3, Nov 28, Dec 24)
- Market holidays (detected via Tradier API)

## Troubleshooting

```bash
# Check if env vars loaded
echo $TRADIER_SANDBOX_KEY

# Reload env vars in current shell
source ~/.bashrc

# Check cron ran
grep scalper /var/log/syslog | tail -10

# Check for stale lock file
ls -la /tmp/gexscalper.lock

# Manual test with env
set -a; . /etc/gamma.env; set +a; ./scalper.py
```
