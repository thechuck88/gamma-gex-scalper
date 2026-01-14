#!/usr/bin/env python3
"""
replay_time_manager.py - Time advancement and market hours management

Handles:
- Advancing time in 30-second intervals
- Detecting market hours (9:30 AM - 4:00 PM ET)
- Identifying entry check times (9:36 AM, 10:00 AM, 10:30 AM, etc)
- Converting between UTC and ET
"""

from datetime import datetime, timedelta
import pytz


class TimeManager:
    """Manages time advancement during replay."""

    # Market hours: 9:30 AM - 4:00 PM ET
    MARKET_OPEN_HOUR = 9
    MARKET_OPEN_MINUTE = 30
    MARKET_CLOSE_HOUR = 16
    MARKET_CLOSE_MINUTE = 0

    # Entry check times (ET): 9:36 AM, 10:00 AM, 10:30 AM, 11:00 AM, 11:30 AM, 12:00 PM, 12:30 PM, 1:00 PM
    ENTRY_CHECK_TIMES = [
        (9, 36),   # 9:36 AM
        (10, 0),   # 10:00 AM
        (10, 30),  # 10:30 AM
        (11, 0),   # 11:00 AM
        (11, 30),  # 11:30 AM
        (12, 0),   # 12:00 PM
        (12, 30),  # 12:30 PM
        (13, 0),   # 1:00 PM (13:00 in 24-hour)
    ]

    def __init__(self, start_timestamp: datetime, end_timestamp: datetime):
        """
        Initialize time manager.

        Args:
            start_timestamp: Starting time (can be any timezone, will be treated as UTC)
            end_timestamp: Ending time (can be any timezone, will be treated as UTC)
        """
        self.start_timestamp = start_timestamp
        self.end_timestamp = end_timestamp
        self.current_timestamp = start_timestamp
        self.et_tz = pytz.timezone('US/Eastern')
        self.utc_tz = pytz.UTC
        print(f"[TIME] TimeManager initialized: {start_timestamp} to {end_timestamp}")

    def is_market_hours(self, timestamp: datetime) -> bool:
        """
        Check if timestamp is within market hours (9:30 AM - 4:00 PM ET).

        Args:
            timestamp: UTC timestamp (or naive timestamp treated as UTC)

        Returns:
            True if within market hours, False otherwise
        """
        # Make timezone-aware if naive
        if timestamp.tzinfo is None:
            timestamp = self.utc_tz.localize(timestamp)
        elif timestamp.tzinfo != self.utc_tz:
            timestamp = timestamp.astimezone(self.utc_tz)

        # Convert to ET
        et_time = timestamp.astimezone(self.et_tz)

        # Check if weekday (0=Monday, 4=Friday)
        if et_time.weekday() > 4:  # Saturday or Sunday
            return False

        # Check hour and minute
        hour = et_time.hour
        minute = et_time.minute

        # Open: 9:30 AM, Close: 4:00 PM
        open_time = (self.MARKET_OPEN_HOUR, self.MARKET_OPEN_MINUTE)
        close_time = (self.MARKET_CLOSE_HOUR, self.MARKET_CLOSE_MINUTE)

        current_time = (hour, minute)

        return open_time <= current_time < close_time

    def is_entry_check_time(self, timestamp: datetime) -> bool:
        """
        Check if timestamp matches one of the entry check times.

        Entry check times: 9:36 AM, 10:00 AM, 10:30 AM, 11:00 AM, 11:30 AM, 12:00 PM, 12:30 PM, 1:00 PM ET

        Args:
            timestamp: UTC timestamp (or naive timestamp treated as UTC)

        Returns:
            True if matches entry check time, False otherwise
        """
        # Make timezone-aware if naive
        if timestamp.tzinfo is None:
            timestamp = self.utc_tz.localize(timestamp)
        elif timestamp.tzinfo != self.utc_tz:
            timestamp = timestamp.astimezone(self.utc_tz)

        # Convert to ET
        et_time = timestamp.astimezone(self.et_tz)

        hour = et_time.hour
        minute = et_time.minute

        return (hour, minute) in self.ENTRY_CHECK_TIMES

    def advance_time(self, seconds: int = 30) -> datetime:
        """
        Advance current time by specified seconds.

        Args:
            seconds: Number of seconds to advance (default: 30)

        Returns:
            New current timestamp
        """
        self.current_timestamp = self.current_timestamp + timedelta(seconds=seconds)
        return self.current_timestamp

    def has_more_data(self) -> bool:
        """Check if current timestamp is before end timestamp."""
        return self.current_timestamp < self.end_timestamp

    def reset(self):
        """Reset to start timestamp."""
        self.current_timestamp = self.start_timestamp

    def get_time_range_seconds(self) -> float:
        """Get total time range in seconds."""
        delta = self.end_timestamp - self.start_timestamp
        return delta.total_seconds()

    def get_progress_percent(self) -> float:
        """Get progress through time range as percentage."""
        total_seconds = self.get_time_range_seconds()
        elapsed_seconds = (self.current_timestamp - self.start_timestamp).total_seconds()

        if total_seconds == 0:
            return 0.0

        return (elapsed_seconds / total_seconds) * 100

    def get_elapsed_seconds(self) -> float:
        """Get elapsed seconds since start."""
        delta = self.current_timestamp - self.start_timestamp
        return delta.total_seconds()

    def get_remaining_seconds(self) -> float:
        """Get remaining seconds until end."""
        delta = self.end_timestamp - self.current_timestamp
        return max(0, delta.total_seconds())

    def get_current_timestamp(self) -> datetime:
        """Get current timestamp."""
        return self.current_timestamp

    def get_current_et_time(self) -> str:
        """Get current time in ET as formatted string."""
        if self.current_timestamp.tzinfo is None:
            ts = self.utc_tz.localize(self.current_timestamp)
        else:
            ts = self.current_timestamp

        et_time = ts.astimezone(self.et_tz)
        return et_time.strftime("%Y-%m-%d %H:%M:%S %Z")

    def __str__(self) -> str:
        """String representation."""
        progress = self.get_progress_percent()
        et_time = self.get_current_et_time()
        return f"TimeManager: {et_time} ({progress:.1f}%)"
