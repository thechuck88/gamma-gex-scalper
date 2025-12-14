# gex_config.py — Environment-based configuration (Dec 11, 2025)
# All secrets loaded from environment variables

import os

# Tradier Account IDs
PAPER_ACCOUNT_ID = os.getenv("TRADIER_PAPER_ACCOUNT_ID", "VA45627947")
LIVE_ACCOUNT_ID  = os.getenv("TRADIER_LIVE_ACCOUNT_ID", "6YA47852")

# Tradier API Keys
TRADIER_SANDBOX_KEY = os.getenv("TRADIER_SANDBOX_KEY")
TRADIER_LIVE_KEY    = os.getenv("TRADIER_LIVE_KEY")

# Validate required keys
if not TRADIER_SANDBOX_KEY:
    raise EnvironmentError("TRADIER_SANDBOX_KEY not set in environment")
if not TRADIER_LIVE_KEY:
    raise EnvironmentError("TRADIER_LIVE_KEY not set in environment")

# These are just defaults — scalper will override
DEFAULT_ACCOUNT_ID = PAPER_ACCOUNT_ID
DEFAULT_KEY        = TRADIER_SANDBOX_KEY

# Discord Webhook Settings
DISCORD_ENABLED = True
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Delayed webhook (7 min delay) - for free tier
DISCORD_DELAYED_ENABLED = True
DISCORD_DELAYED_WEBHOOK_URL = os.getenv("DISCORD_DELAYED_WEBHOOK_URL", "")
DISCORD_DELAY_SECONDS = 420  # 7 minutes

# Healthcheck.io heartbeat - alerts if monitor stops running
HEALTHCHECK_URL = os.getenv("HEALTHCHECK_URL", "")
HEALTHCHECK_ENABLED = bool(HEALTHCHECK_URL)
