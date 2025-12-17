# gex_config.py — Environment-based configuration (Dec 11, 2025)
# All secrets loaded from environment variables

import os

# Tradier Account IDs (no fallback - fail fast if not set)
PAPER_ACCOUNT_ID = os.getenv("TRADIER_PAPER_ACCOUNT_ID")
LIVE_ACCOUNT_ID  = os.getenv("TRADIER_LIVE_ACCOUNT_ID")

# Tradier API Keys
TRADIER_SANDBOX_KEY = os.getenv("TRADIER_SANDBOX_KEY")
TRADIER_LIVE_KEY    = os.getenv("TRADIER_LIVE_KEY")

# Validate required credentials (fail fast on startup)
if not TRADIER_SANDBOX_KEY:
    raise EnvironmentError("TRADIER_SANDBOX_KEY not set in environment")
if not TRADIER_LIVE_KEY:
    raise EnvironmentError("TRADIER_LIVE_KEY not set in environment")
if not PAPER_ACCOUNT_ID:
    raise EnvironmentError("TRADIER_PAPER_ACCOUNT_ID not set in environment")
if not LIVE_ACCOUNT_ID:
    raise EnvironmentError("TRADIER_LIVE_ACCOUNT_ID not set in environment")

# These are just defaults — scalper will override
DEFAULT_ACCOUNT_ID = PAPER_ACCOUNT_ID
DEFAULT_KEY        = TRADIER_SANDBOX_KEY

# Discord Webhook Settings
DISCORD_ENABLED = True
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Validate Discord webhook URL format (prevent typos/misconfigurations)
if DISCORD_WEBHOOK_URL and not DISCORD_WEBHOOK_URL.startswith("https://discord.com/api/webhooks/"):
    raise ValueError(
        f"Invalid DISCORD_WEBHOOK_URL format: must start with 'https://discord.com/api/webhooks/'\n"
        f"Got: {DISCORD_WEBHOOK_URL[:50]}..."
    )

# Delayed webhook (7 min delay) - for free tier
DISCORD_DELAYED_ENABLED = True
DISCORD_DELAYED_WEBHOOK_URL = os.getenv("DISCORD_DELAYED_WEBHOOK_URL", "")

# Validate delayed webhook URL format
if DISCORD_DELAYED_WEBHOOK_URL and not DISCORD_DELAYED_WEBHOOK_URL.startswith("https://discord.com/api/webhooks/"):
    raise ValueError(
        f"Invalid DISCORD_DELAYED_WEBHOOK_URL format: must start with 'https://discord.com/api/webhooks/'\n"
        f"Got: {DISCORD_DELAYED_WEBHOOK_URL[:50]}..."
    )

DISCORD_DELAY_SECONDS = 420  # 7 minutes

# Healthcheck.io heartbeat - alerts if monitor stops running
HEALTHCHECK_URL = os.getenv("HEALTHCHECK_URL", "")
HEALTHCHECK_ENABLED = bool(HEALTHCHECK_URL)
