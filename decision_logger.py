#!/usr/bin/env python3
"""
Decision logger for gamma scalper entry/rejection decisions.

Logs all entry placement and rejection decisions with detailed reasoning
for each attempt, allowing users to understand why trades were made or skipped.

Usage:
    from decision_logger import DecisionLogger

    logger = DecisionLogger()
    logger.log_placed("HIGH", 2.45, "SPX near GEX pin, favorable setup")
    logger.log_rejected("VIX spike 15% in 5min (18.45→21.28)")

    decisions = logger.get_recent(limit=20)
    for d in decisions:
        print(f"{d['timestamp_et']}: {d['decision']} - {d['reason']}")
"""

import json
import os
from datetime import datetime, timedelta
import pytz
import fcntl

DECISIONS_FILE = '/root/gamma/data/entry_decisions.json'
ET = pytz.timezone('US/Eastern')


def ensure_data_dir():
    """Ensure data directory exists."""
    data_dir = os.path.dirname(DECISIONS_FILE)
    os.makedirs(data_dir, exist_ok=True)


class DecisionLogger:
    """Logs gamma scalper entry placement and rejection decisions."""

    def __init__(self):
        ensure_data_dir()
        self.file = DECISIONS_FILE

    def _read_decisions(self):
        """Read existing decisions from file (thread-safe)."""
        if not os.path.exists(self.file):
            return []

        try:
            with open(self.file, 'r') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    return json.load(f)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception as e:
            print(f"[ERROR] Failed to read decisions: {e}")
            return []

    def _write_decisions(self, decisions):
        """Write decisions to file (thread-safe)."""
        try:
            # Use temp file + rename for atomic writes
            temp_file = self.file + '.tmp'
            with open(temp_file, 'w') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(decisions, f, indent=2)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            os.rename(temp_file, self.file)
        except Exception as e:
            print(f"[ERROR] Failed to write decisions: {e}")

    def log_placed(self, confidence, credit, reason):
        """Log a successful trade placement.

        Args:
            confidence: str - "HIGH", "MEDIUM", or "LOW"
            credit: float - expected credit amount
            reason: str - brief explanation
        """
        now_utc = datetime.now(tz=pytz.UTC)
        now_et = now_utc.astimezone(ET)

        decision = {
            'timestamp_utc': now_utc.isoformat(),
            'timestamp_et': now_et.strftime('%H:%M:%S'),
            'timestamp_et_full': now_et.strftime('%m/%d %H:%M:%S ET'),
            'decision': 'PLACED',
            'confidence': confidence,
            'credit': round(credit, 2),
            'reason': reason
        }

        decisions = self._read_decisions()
        decisions.append(decision)
        self._write_decisions(decisions)

    def log_rejected(self, reason):
        """Log a rejected entry.

        Args:
            reason: str - explanation for rejection
        """
        now_utc = datetime.now(tz=pytz.UTC)
        now_et = now_utc.astimezone(ET)

        decision = {
            'timestamp_utc': now_utc.isoformat(),
            'timestamp_et': now_et.strftime('%H:%M:%S'),
            'timestamp_et_full': now_et.strftime('%m/%d %H:%M:%S ET'),
            'decision': 'REJECTED',
            'reason': reason
        }

        decisions = self._read_decisions()
        decisions.append(decision)
        self._write_decisions(decisions)

    def get_recent(self, limit=20, hours=8):
        """Get recent decisions.

        Args:
            limit: int - max number of decisions to return
            hours: int - only return decisions from last N hours (0 = unlimited)

        Returns:
            list - recent decisions, newest first
        """
        decisions = self._read_decisions()

        if hours > 0:
            cutoff = datetime.now(tz=pytz.UTC) - timedelta(hours=hours)
            decisions = [
                d for d in decisions
                if datetime.fromisoformat(d['timestamp_utc']) > cutoff
            ]

        # Return newest first
        return sorted(decisions, key=lambda d: d['timestamp_utc'], reverse=True)[:limit]

    def get_today_summary(self):
        """Get summary of today's decisions.

        Returns:
            dict - {placed: count, rejected: count, last_placed: time or None}
        """
        today_start = datetime.now(tz=pytz.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        decisions = self._read_decisions()

        today_decisions = [
            d for d in decisions
            if datetime.fromisoformat(d['timestamp_utc']) >= today_start
        ]

        placed = [d for d in today_decisions if d['decision'] == 'PLACED']
        rejected = [d for d in today_decisions if d['decision'] == 'REJECTED']

        return {
            'placed_count': len(placed),
            'rejected_count': len(rejected),
            'last_placed_time': placed[-1]['timestamp_et_full'] if placed else None,
            'last_placed_confidence': placed[-1].get('confidence') if placed else None,
            'last_rejected_reason': rejected[-1]['reason'] if rejected else None
        }

    def clear(self):
        """Clear all decisions."""
        ensure_data_dir()
        with open(self.file, 'w') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump([], f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


if __name__ == '__main__':
    # Display recent decisions (production use only - do not add test data)
    logger = DecisionLogger()

    print("\n=== RECENT DECISIONS (Last 8 hours) ===\n")
    recent = logger.get_recent(limit=10)
    if recent:
        for d in recent:
            if d['decision'] == 'PLACED':
                print(f"{d['timestamp_et']} | ✅ {d['decision']:8s} | {d['confidence']:6s} | ${d.get('credit', 0):>6.2f} | {d['reason']}")
            else:
                print(f"{d['timestamp_et']} | ❌ {d['decision']:8s} |          | ❌ SKIPPED | {d['reason']}")
    else:
        print("  (No decisions logged yet)")

    # Display today's summary
    print("\n=== TODAY'S SUMMARY ===\n")
    summary = logger.get_today_summary()
    print(f"Placements:  {summary['placed_count']}")
    print(f"Rejections:  {summary['rejected_count']}")
    if summary['last_placed_time']:
        print(f"Last Trade:  {summary['last_placed_time']} ({summary['last_placed_confidence']})")
    if summary['last_rejected_reason']:
        print(f"Last Reject: {summary['last_rejected_reason']}")
