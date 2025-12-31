# Gamma GEX Scalper - Trading Hours

## Market Hours
- **Regular Hours**: 9:30 AM - 4:00 PM ET (Monday - Friday)
- **Weekends**: Closed

## Entry Timing
- **Market Open**: 9:30 AM ET
- **First Entry Check**: 9:36 AM ET (6 minutes after open)
  - Allows opening volatility to settle
  - Ensures more stable pricing for spreads

## Exit Timing
- **Auto-Close**: 3:30 PM ET for 0DTE positions
  - Prevents gamma risk into close
  - Ensures liquidity for exit

## Monitoring
- **Check Interval**: 15 seconds
- **Purpose**: Tight stop loss monitoring (15% stop, 50% profit target)

## Implementation
```python
# monitor.py line 441
market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)

# monitor.py line 69
POLL_INTERVAL = 15  # Seconds between checks
```

## Notes
- Bot starts monitoring at 9:30 AM but waits 6 minutes for initial volatility to settle
- This prevents entering spreads during the chaotic first few minutes of trading
- 15-second polling ensures quick reaction to stop loss or profit target hits
