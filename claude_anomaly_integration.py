"""
Claude Anomaly Integration - Universal trading blocker for all bots

INTEGRATION INSTRUCTIONS:
========================

1. Import this module in any trading bot:

   from claude_anomaly_integration import should_block_trading

2. Add check before entering any trade:

   blocked, reason = should_block_trading()
   if blocked:
       logger.warning(f"🚫 TRADE BLOCKED: {reason}")
       return  # Skip this signal

3. That's it! The anomaly detector runs separately via cron.

SUPPORTED PAUSE FLAGS:
- /tmp/mnq_trading_paused.json (MNQ futures)
- /tmp/stock_paused_MARKET_WIDE.json (Stock veto system)

"""
import json
import os
from datetime import datetime
from pathlib import Path

# Check multiple pause flag files (MNQ futures + Stock market-wide blocks)
PAUSE_FLAG_FILES = [
    "/tmp/mnq_trading_paused.json",           # MNQ futures anomaly detector
    "/tmp/stock_paused_MARKET_WIDE.json"      # Stock veto system (FOMC, CPI, NFP, VIX, circuit breakers)
]

def should_block_trading():
    """
    Check if trading is currently paused by any anomaly detector.

    Checks multiple pause flag sources:
    - MNQ futures anomaly detector
    - Stock veto system (market-wide blocks: FOMC, CPI/PPI, NFP, VIX spikes, circuit breakers)

    Returns:
        (bool, str): (is_blocked, reason)

    Examples:
        blocked, reason = should_block_trading()
        if blocked:
            logger.warning(f"Trade blocked: {reason}")
            return  # Skip signal
    """

    # Check each pause flag file
    for pause_file in PAUSE_FLAG_FILES:
        if not os.path.exists(pause_file):
            continue

        try:
            with open(pause_file, 'r') as f:
                pause_data = json.load(f)

            # Check if pause has expired
            # Support both 'expires' (MNQ) and 'expires_at' (stock) formats
            expires_str = pause_data.get('expires') or pause_data.get('expires_at')
            if not expires_str:
                continue

            expires = datetime.fromisoformat(expires_str)

            if datetime.now() > expires:
                # Pause expired, remove file
                try:
                    os.remove(pause_file)
                except:
                    pass  # Ignore errors
                continue

            # Still paused
            reason = pause_data.get('reason', 'Anomaly detected')
            category = pause_data.get('category', 'UNKNOWN')
            confidence = pause_data.get('confidence', 0)
            remaining_minutes = (expires - datetime.now()).total_seconds() / 60

            # Build detailed reason string
            details = f"{reason}"
            if category and category != 'UNKNOWN':
                details += f" [{category}]"
            if confidence > 0:
                details += f" (confidence: {confidence}%)"
            details += f" (expires in {remaining_minutes:.1f} min)"

            return True, details

        except Exception as e:
            # If there's any error reading pause file, allow trading (fail-safe)
            print(f"Warning: Could not read pause file {pause_file}: {e}")
            continue

    # No active pause flags
    return False, None

def get_pause_status():
    """
    Get detailed pause status (for logging/monitoring).

    Returns:
        dict or None
    """
    if not os.path.exists(PAUSE_FLAG_FILE):
        return None

    try:
        with open(PAUSE_FLAG_FILE, 'r') as f:
            pause_data = json.load(f)

        expires = datetime.fromisoformat(pause_data['expires'])
        remaining_seconds = (expires - datetime.now()).total_seconds()

        return {
            'paused': True,
            'reason': pause_data.get('reason', 'Unknown'),
            'since': pause_data.get('timestamp'),
            'expires': pause_data.get('expires'),
            'remaining_minutes': remaining_seconds / 60,
            'expired': remaining_seconds <= 0
        }
    except:
        return None

# Example usage in your strategy
if __name__ == "__main__":
    print("Testing anomaly integration...")
    print()

    blocked, reason = should_block_trading()

    if blocked:
        print(f"❌ Trading is currently BLOCKED")
        print(f"   Reason: {reason}")
    else:
        print("✅ Trading is ALLOWED")

    print()

    status = get_pause_status()
    if status:
        print("Pause details:")
        for key, value in status.items():
            print(f"  {key}: {value}")
    else:
        print("No active pause")
