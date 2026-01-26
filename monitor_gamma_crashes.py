#!/usr/bin/env python3
"""
Gamma Bot Crash Monitor - Sends alerts on crashes and errors

Monitors both live and paper gamma bots for crashes, errors, and restarts.
Sends Discord and email alerts immediately when issues are detected.

Run as systemd service for 24/7 monitoring.
"""
import time
import sys
import os
import re
import subprocess
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from pathlib import Path
import requests

# Configuration
LOG_FILE_LIVE = "/root/gamma/data/monitor_live.log"
LOG_FILE_PAPER = "/root/gamma/data/monitor_paper.log"
CHECK_INTERVAL = 60  # Check every 60 seconds
LOOKBACK_SECONDS = 120  # Look back 2 minutes for errors

# Email configuration from environment
SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER', 'nwflguy@gmail.com')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
EMAIL_TO = 'nwflguy@gmail.com'

# Discord webhook from gamma.env
DISCORD_WEBHOOK = os.getenv('DISCORD_WEBHOOK', '')

# State files
STATE_FILE = "/tmp/gamma_crash_monitor_state.txt"
CRASH_LOOP_STATE_LIVE = "/tmp/gamma_live_crash_loop_state.txt"
CRASH_LOOP_STATE_PAPER = "/tmp/gamma_paper_crash_loop_state.txt"

# Error patterns to detect
ERROR_PATTERNS = [
    (r'ERROR.*Error', 'Error detected'),
    (r'KeyError:', 'KeyError exception'),
    (r'Traceback \(most recent call last\):', 'Python exception'),
    (r'CRITICAL -', 'Critical error'),
    (r'Failed to.*order', 'Order failure'),
    (r'Failed to send.*Discord', 'Discord send failure'),
    (r'Bot crashed', 'Bot crash detected'),
    (r'Position.*failed', 'Position failure'),
]

def send_email_alert(subject, message):
    """Send email alert"""
    if not SMTP_PASSWORD:
        print("⚠️  SMTP password not configured, skipping email")
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"🚨 Gamma Bot: {subject}"
        msg['From'] = SMTP_USER
        msg['To'] = EMAIL_TO

        text_part = MIMEText(message, 'plain')
        msg.attach(text_part)

        html_message = f"""
        <html>
        <head></head>
        <body>
            <h2 style="color: #dc3545;">🚨 Gamma Bot Alert</h2>
            <h3>{subject}</h3>
            <pre style="background-color: #f5f5f5; padding: 15px; border-left: 4px solid #dc3545;">
{message}
            </pre>
            <p style="color: #6c757d; font-size: 12px;">
                Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}<br>
                Gamma Bot Crash Monitor
            </p>
        </body>
        </html>
        """
        html_part = MIMEText(html_message, 'html')
        msg.attach(html_part)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        print(f"✅ Email sent: {subject}")
        return True
    except Exception as e:
        print(f"❌ Email send failed: {e}")
        return False

def send_discord_alert(title, message, color=0xff0000):
    """Send Discord alert"""
    if not DISCORD_WEBHOOK:
        print("⚠️  Discord webhook not configured")
        return False

    try:
        payload = {
            "embeds": [{
                "title": f"🚨 {title}",
                "description": message,
                "color": color,
                "timestamp": datetime.utcnow().isoformat(),
                "footer": {"text": "Gamma Bot Monitor"}
            }]
        }
        response = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        if response.status_code in [200, 204]:
            print(f"✅ Discord alert sent: {title}")
            return True
        else:
            print(f"❌ Discord alert failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Discord alert exception: {e}")
        return False

def send_critical_alert(title, message):
    """Send both Discord and email for critical issues"""
    print(f"\n🚨 CRITICAL ALERT: {title}")
    send_discord_alert(title, message, color=0xff0000)
    send_email_alert(title, message)

def load_alerted_errors():
    """Load set of already-alerted error timestamps"""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_alerted_error(timestamp_str):
    """Save alerted error timestamp to state file"""
    with open(STATE_FILE, 'a') as f:
        f.write(f"{timestamp_str}\n")

def cleanup_old_state():
    """Remove state entries older than 24 hours"""
    if not os.path.exists(STATE_FILE):
        return

    cutoff = datetime.now() - timedelta(hours=24)
    valid_entries = []

    with open(STATE_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    ts = datetime.fromisoformat(line.split('|')[0])
                    if ts > cutoff:
                        valid_entries.append(line)
                except:
                    pass

    with open(STATE_FILE, 'w') as f:
        for entry in valid_entries:
            f.write(f"{entry}\n")

def parse_log_timestamp(line):
    """Extract timestamp from log line"""
    match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
        except:
            return None
    return None

def check_service_status(service_name, bot_type):
    """Check if service is running or stopped due to start limit"""
    try:
        result = subprocess.run(
            ['systemctl', 'show', service_name,
             '-p', 'ActiveState', '-p', 'SubState', '-p', 'Result'],
            capture_output=True,
            text=True,
            timeout=5
        )

        output = result.stdout.strip()
        lines = {line.split('=')[0]: line.split('=')[1]
                 for line in output.split('\n') if '=' in line}

        active_state = lines.get('ActiveState', 'unknown')
        sub_state = lines.get('SubState', 'unknown')
        result_state = lines.get('Result', 'unknown')

        if active_state == 'failed' or sub_state == 'failed':
            journal = subprocess.run(
                ['journalctl', '-u', service_name, '-n', '20', '--no-pager'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if 'start-limit' in journal.stdout.lower() or 'too many' in journal.stdout.lower():
                message = f"""SERVICE STOPPED DUE TO CRASH LOOP!

The Gamma {bot_type} bot has crashed 5+ times in 5 minutes and systemd has stopped trying to restart it.

Status: {active_state} / {sub_state}
Result: {result_state}

Recent journal entries:
{journal.stdout[-1000:]}

MANUAL INTERVENTION REQUIRED:
1. Check logs: tail -100 /root/gamma/data/monitor_{bot_type.lower()}.log
2. Identify root cause
3. Fix the issue
4. Reset: systemctl reset-failed {service_name}
5. Restart: systemctl start {service_name}
"""
                send_critical_alert(f"CRASH LOOP - Gamma {bot_type} Stopped", message)
                return False

        return True

    except Exception as e:
        print(f"❌ Service status check failed for {service_name}: {e}")
        return True

def detect_crash_loop(service_name, bot_type, crash_loop_state_file):
    """Detect if bot is crashing repeatedly"""
    try:
        result = subprocess.run(
            ['journalctl', '-u', service_name, '--since', '5 minutes ago',
             '--no-pager', '-o', 'cat'],
            capture_output=True,
            text=True,
            timeout=10
        )

        crash_count = result.stdout.count('Failed with result')
        restart_count = result.stdout.count(f'Started {service_name}')

        if crash_count >= 3:
            if os.path.exists(crash_loop_state_file):
                last_alert_time = datetime.fromtimestamp(os.path.getmtime(crash_loop_state_file))
                if (datetime.now() - last_alert_time).total_seconds() < 300:
                    return

            message = f"""WARNING: Multiple crashes detected!

Crashes in last 5 minutes: {crash_count}
Restarts in last 5 minutes: {restart_count}

The Gamma {bot_type} bot is crashing repeatedly. This may indicate:
- Tradier API issues
- Network connectivity problems
- Code bugs
- Configuration errors
- VIX data issues

Service will stop after 5 crashes in 5 minutes.

Recent activity:
{result.stdout[-1000:]}
"""
            send_critical_alert(f"Crash Loop Detected - Gamma {bot_type}", message)
            Path(crash_loop_state_file).touch()

    except Exception as e:
        print(f"❌ Crash loop detection failed for {service_name}: {e}")

def check_for_errors(log_file, bot_type):
    """Check log file for recent errors"""
    if not os.path.exists(log_file):
        send_critical_alert(
            f"Log File Missing - Gamma {bot_type}",
            f"Gamma {bot_type} log file not found: {log_file}\nBot may have crashed or been deleted."
        )
        return

    alerted = load_alerted_errors()
    cutoff_time = datetime.now() - timedelta(seconds=LOOKBACK_SECONDS)
    new_errors = []

    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()[-500:]

        for i, line in enumerate(lines):
            ts = parse_log_timestamp(line)
            if not ts or ts < cutoff_time:
                continue

            for pattern, error_type in ERROR_PATTERNS:
                if re.search(pattern, line):
                    error_id = f"{bot_type}|{ts.isoformat()}|{error_type}"

                    if error_id not in alerted:
                        start_idx = max(0, i - 5)
                        end_idx = min(len(lines), i + 6)
                        context = ''.join(lines[start_idx:end_idx])

                        new_errors.append({
                            'timestamp': ts,
                            'type': error_type,
                            'line': line.strip(),
                            'context': context,
                            'id': error_id,
                            'bot_type': bot_type
                        })
                        break

        for error in new_errors:
            message = f"**Bot:** Gamma {error['bot_type']}\n"
            message += f"**Time:** {error['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}\n"
            message += f"**Type:** {error['type']}\n\n"
            message += f"**Error Line:**\n```\n{error['line']}\n```\n\n"
            message += f"**Context:**\n```\n{error['context'][-1000:]}\n```"

            if send_discord_alert(f"Gamma {error['bot_type']} Error: {error['type']}", message):
                save_alerted_error(error['id'])

    except Exception as e:
        print(f"❌ Error checking log {log_file}: {e}")

def check_bot_heartbeat(log_file, bot_type):
    """Check if bot is still alive (recent log activity)"""
    if not os.path.exists(log_file):
        return False

    try:
        mtime = os.path.getmtime(log_file)
        last_write = datetime.fromtimestamp(mtime)
        age = (datetime.now() - last_write).total_seconds()

        if age > 600:
            message = f"""No log activity for {age/60:.1f} minutes.
Last log write: {last_write.strftime('%Y-%m-%d %H:%M:%S')}

Gamma {bot_type} bot may have crashed silently. Check systemd status:
  systemctl status gamma-scalper-monitor-{bot_type.lower()}
"""
            send_critical_alert(f"Gamma {bot_type} Bot Possibly Dead", message)
            return False

        return True
    except Exception as e:
        print(f"❌ Heartbeat check failed for {bot_type}: {e}")
        return False

def main():
    """Main monitoring loop"""
    print("="*80)
    print("GAMMA BOTS CRASH MONITOR (Live + Paper)")
    print("="*80)
    print(f"Live log: {LOG_FILE_LIVE}")
    print(f"Paper log: {LOG_FILE_PAPER}")
    print(f"Check interval: {CHECK_INTERVAL}s")
    print(f"Lookback window: {LOOKBACK_SECONDS}s")
    print(f"Email alerts: {EMAIL_TO}")
    print("="*80)
    print()

    send_discord_alert(
        "Gamma Bots Monitor Started",
        f"Now monitoring Gamma bots (Live + Paper) for crashes and errors.\n"
        f"Check interval: {CHECK_INTERVAL}s\n"
        f"Will alert on: errors, exceptions, crashes, restarts, crash loops\n"
        f"Critical alerts sent to: Discord + {EMAIL_TO}",
        color=0x00ff00
    )

    heartbeat_check_counter = 0
    service_check_counter = 0

    try:
        while True:
            # Check both live and paper bots
            check_for_errors(LOG_FILE_LIVE, "LIVE")
            check_for_errors(LOG_FILE_PAPER, "PAPER")

            detect_crash_loop('gamma-scalper-monitor-live.service', 'LIVE', CRASH_LOOP_STATE_LIVE)
            detect_crash_loop('gamma-scalper-monitor-paper.service', 'PAPER', CRASH_LOOP_STATE_PAPER)

            service_check_counter += 1
            if service_check_counter >= 5:
                check_service_status('gamma-scalper-monitor-live.service', 'LIVE')
                check_service_status('gamma-scalper-monitor-paper.service', 'PAPER')
                service_check_counter = 0

            heartbeat_check_counter += 1
            if heartbeat_check_counter >= 5:
                check_bot_heartbeat(LOG_FILE_LIVE, 'LIVE')
                check_bot_heartbeat(LOG_FILE_PAPER, 'PAPER')
                heartbeat_check_counter = 0

            if int(time.time()) % 3600 < CHECK_INTERVAL:
                cleanup_old_state()

            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Monitoring... (next check in {CHECK_INTERVAL}s)")

            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print("\n⚠️  Shutdown requested")
        send_discord_alert(
            "Gamma Bots Monitor Stopped",
            "Gamma bots crash monitoring has been stopped manually.",
            color=0xffaa00
        )

    except Exception as e:
        print(f"\n❌ Monitor crashed: {e}")
        import traceback
        send_critical_alert(
            "Gamma Bots Monitor Failed",
            f"The crash monitor itself has crashed!\n\n```\n{traceback.format_exc()}\n```"
        )
        raise

if __name__ == "__main__":
    main()
