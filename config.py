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
# Separate webhooks for LIVE and PAPER modes
DISCORD_ENABLED = True
DISCORD_WEBHOOK_LIVE_URL = os.getenv("GAMMA_DISCORD_WEBHOOK_LIVE_URL", "")
DISCORD_WEBHOOK_PAPER_URL = os.getenv("GAMMA_DISCORD_WEBHOOK_PAPER_URL", "")

# Validate Discord webhook URL format (prevent typos/misconfigurations)
if DISCORD_WEBHOOK_LIVE_URL and not DISCORD_WEBHOOK_LIVE_URL.startswith("https://discord.com/api/webhooks/"):
    raise ValueError(
        f"Invalid GAMMA_DISCORD_WEBHOOK_LIVE_URL format: must start with 'https://discord.com/api/webhooks/'\n"
        f"Got: {DISCORD_WEBHOOK_LIVE_URL[:50]}..."
    )
if DISCORD_WEBHOOK_PAPER_URL and not DISCORD_WEBHOOK_PAPER_URL.startswith("https://discord.com/api/webhooks/"):
    raise ValueError(
        f"Invalid GAMMA_DISCORD_WEBHOOK_PAPER_URL format: must start with 'https://discord.com/api/webhooks/'\n"
        f"Got: {DISCORD_WEBHOOK_PAPER_URL[:50]}..."
    )

# Delayed webhook (7 min delay) - for free tier
DISCORD_DELAYED_ENABLED = True
DISCORD_DELAYED_WEBHOOK_URL = os.getenv("GAMMA_DISCORD_DELAYED_WEBHOOK_URL", "")

# Validate delayed webhook URL format
if DISCORD_DELAYED_WEBHOOK_URL and not DISCORD_DELAYED_WEBHOOK_URL.startswith("https://discord.com/api/webhooks/"):
    raise ValueError(
        f"Invalid GAMMA_DISCORD_DELAYED_WEBHOOK_URL format: must start with 'https://discord.com/api/webhooks/'\n"
        f"Got: {DISCORD_DELAYED_WEBHOOK_URL[:50]}..."
    )

DISCORD_DELAY_SECONDS = 420  # 7 minutes

# Discord Auto-Delete Settings
# Messages will be automatically deleted after TTL expires
DISCORD_AUTODELETE_ENABLED = True
DISCORD_AUTODELETE_STORAGE = "/root/gamma/data/discord_messages.json"

# TTL (time-to-live) in seconds for different message types
DISCORD_TTL_SIGNALS = 24 * 3600      # 24 hours - trading signals
DISCORD_TTL_CRASHES = 1 * 3600       # 1 hour - crash/error alerts
DISCORD_TTL_HEARTBEAT = 30 * 60      # 30 minutes - status updates
DISCORD_TTL_DEFAULT = 2 * 3600       # 2 hours - default for other messages

# Healthcheck.io heartbeat - alerts if monitor stops running
# Separate URLs for LIVE and PAPER modes to track each independently
HEALTHCHECK_LIVE_URL = os.getenv("GAMMA_HEALTHCHECK_LIVE_URL", "")
HEALTHCHECK_PAPER_URL = os.getenv("GAMMA_HEALTHCHECK_PAPER_URL", "")
