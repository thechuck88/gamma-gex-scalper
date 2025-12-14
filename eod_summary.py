#!/usr/bin/env python3
"""
Gamma Scalper - End of Day Summary
Sends daily performance summary to Discord.
"""
import os
import csv
import requests
from datetime import datetime

# Load Discord webhook from env
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "")
TRADE_LOG = "/root/gamma/data/trades.csv"

# Load from gamma.env if not in environment
if not DISCORD_WEBHOOK:
    env_file = "/etc/gamma.env"
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                if line.startswith("DISCORD_WEBHOOK_URL="):
                    DISCORD_WEBHOOK = line.strip().split("=", 1)[1]
                    break

def get_todays_trades():
    """Get trades from today."""
    today = datetime.now().strftime('%Y-%m-%d')
    trades = []

    if not os.path.exists(TRADE_LOG):
        return trades

    with open(TRADE_LOG, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('Timestamp_ET', '').startswith(today):
                trades.append(row)

    return trades

def calculate_stats(trades):
    """Calculate daily stats."""
    total_pnl = 0
    winners = 0
    losers = 0
    total_credit = 0

    strategies = {}

    for t in trades:
        # Count by strategy
        strat = t.get('Strategy', 'Unknown')
        strategies[strat] = strategies.get(strat, 0) + 1

        # Sum credits
        try:
            credit = float(t.get('Entry_Credit', 0) or 0)
            total_credit += credit
        except:
            pass

        # Sum P&L
        try:
            pnl = float(t.get('P/L_$', 0) or 0)
            total_pnl += pnl
            if pnl > 0:
                winners += 1
            elif pnl < 0:
                losers += 1
        except:
            pass

    return {
        'total_trades': len(trades),
        'winners': winners,
        'losers': losers,
        'open': len(trades) - winners - losers,
        'pnl': total_pnl,
        'total_credit': total_credit,
        'strategies': strategies
    }

def send_summary():
    """Send EOD summary to Discord."""
    if not DISCORD_WEBHOOK:
        print("No Discord webhook configured")
        return

    trades = get_todays_trades()
    stats = calculate_stats(trades)

    today = datetime.now().strftime('%Y-%m-%d')

    # Determine color based on P&L
    if stats['pnl'] > 0:
        color = 0x17dfad  # Green
        emoji = "📈"
    elif stats['pnl'] < 0:
        color = 0xdd326b  # Red
        emoji = "📉"
    else:
        color = 0x808080  # Gray
        emoji = "📊"

    # Format strategies
    strat_str = ", ".join([f"{k}: {v}" for k, v in stats['strategies'].items()]) or "None"

    win_rate = 0
    if stats['winners'] + stats['losers'] > 0:
        win_rate = stats['winners'] / (stats['winners'] + stats['losers']) * 100

    fields = [
        {"name": "Date", "value": today, "inline": True},
        {"name": "Total Trades", "value": str(stats['total_trades']), "inline": True},
        {"name": "Open", "value": str(stats['open']), "inline": True},
        {"name": "Winners", "value": str(stats['winners']), "inline": True},
        {"name": "Losers", "value": str(stats['losers']), "inline": True},
        {"name": "Win Rate", "value": f"{win_rate:.0f}%", "inline": True},
        {"name": "Total Credit", "value": f"${stats['total_credit']:.2f}", "inline": True},
        {"name": "Daily P&L", "value": f"${stats['pnl']:+,.2f}", "inline": True},
        {"name": "Strategies", "value": strat_str, "inline": False},
    ]

    msg = {
        "embeds": [{
            "title": f"{emoji} GAMMA SCALPER — Daily Summary",
            "color": color,
            "fields": fields,
            "footer": {"text": "SPX 0DTE GEX Scalper"},
            "timestamp": datetime.now().isoformat()
        }]
    }

    try:
        resp = requests.post(DISCORD_WEBHOOK, json=msg, timeout=10)
        print(f"EOD summary sent: {resp.status_code}")
    except Exception as e:
        print(f"Error sending summary: {e}")

if __name__ == "__main__":
    send_summary()
