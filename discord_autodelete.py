"""
Discord Auto-Delete Module
Tracks webhook messages and auto-deletes them after a TTL period
"""

import requests
import json
import time
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class TrackedMessage:
    """Represents a Discord message to be auto-deleted"""
    message_id: str
    webhook_url: str
    posted_at: float  # Unix timestamp
    ttl_seconds: int
    message_type: str  # 'signal', 'crash', 'heartbeat', etc.


class DiscordAutoDelete:
    """
    Manages auto-deletion of Discord webhook messages

    Usage:
        # Initialize
        auto_delete = DiscordAutoDelete(
            storage_file="/path/to/messages.json",
            default_ttl=3600  # 1 hour default
        )

        # Send message with auto-delete
        auto_delete.send_message(
            webhook_url="https://discord.com/api/webhooks/...",
            message_data={"content": "Hello"},
            ttl_seconds=1800,  # Delete after 30 minutes
            message_type="crash"
        )

        # Start cleanup thread
        auto_delete.start_cleanup_thread()
    """

    def __init__(self, storage_file: str, default_ttl: int = 3600):
        """
        Args:
            storage_file: Path to JSON file for storing message IDs
            default_ttl: Default time-to-live in seconds (default: 1 hour)
        """
        self.storage_file = Path(storage_file)
        self.default_ttl = default_ttl
        self.messages: List[TrackedMessage] = []
        self.lock = threading.Lock()
        self.cleanup_thread: Optional[threading.Thread] = None
        self.running = False

        # Load existing messages from storage
        self._load_messages()

    def _load_messages(self):
        """Load tracked messages from storage file"""
        if not self.storage_file.exists():
            logger.debug(f"Storage file not found: {self.storage_file}")
            return

        try:
            with open(self.storage_file, 'r') as f:
                data = json.load(f)
                self.messages = [TrackedMessage(**msg) for msg in data]
            logger.info(f"Loaded {len(self.messages)} tracked messages from {self.storage_file}")
        except Exception as e:
            logger.error(f"Failed to load messages from {self.storage_file}: {e}")
            self.messages = []

    def _save_messages(self):
        """Save tracked messages to storage file"""
        try:
            with open(self.storage_file, 'w') as f:
                data = [asdict(msg) for msg in self.messages]
                json.dump(data, f, indent=2)
            logger.debug(f"Saved {len(self.messages)} tracked messages to {self.storage_file}")
        except Exception as e:
            logger.error(f"Failed to save messages to {self.storage_file}: {e}")

    def send_message(
        self,
        webhook_url: str,
        message_data: Dict,
        ttl_seconds: Optional[int] = None,
        message_type: str = "general"
    ) -> Optional[str]:
        """
        Send message to Discord and track it for auto-deletion

        Args:
            webhook_url: Discord webhook URL
            message_data: Message payload (dict with 'content' or 'embeds')
            ttl_seconds: Time-to-live in seconds (None = use default)
            message_type: Type of message ('signal', 'crash', 'heartbeat')

        Returns:
            Message ID if successful, None if failed
        """
        if ttl_seconds is None:
            ttl_seconds = self.default_ttl

        try:
            # Add "?wait=true" to get message ID in response
            url = webhook_url if '?wait=true' in webhook_url else f"{webhook_url}?wait=true"

            response = requests.post(url, json=message_data, timeout=10)
            response.raise_for_status()

            # Extract message ID from response
            message_id = response.json().get('id')
            if not message_id:
                logger.warning("No message ID in Discord response")
                return None

            # Track message for deletion
            tracked_msg = TrackedMessage(
                message_id=message_id,
                webhook_url=webhook_url,
                posted_at=time.time(),
                ttl_seconds=ttl_seconds,
                message_type=message_type
            )

            with self.lock:
                self.messages.append(tracked_msg)
                self._save_messages()

            logger.debug(
                f"Tracked Discord message {message_id[:8]} "
                f"(type={message_type}, ttl={ttl_seconds}s)"
            )

            return message_id

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Discord message: {e}")
            return None
        except Exception as e:
            logger.error(f"Error sending Discord message: {e}")
            return None

    def delete_message(self, message: TrackedMessage) -> bool:
        """
        Delete a Discord message

        Args:
            message: TrackedMessage to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            # Discord API endpoint for deleting webhook messages
            # Format: DELETE /webhooks/{webhook.id}/{webhook.token}/messages/{message.id}
            delete_url = f"{message.webhook_url}/messages/{message.message_id}"

            logger.info(f"[DELETE] Attempting to delete message {message.message_id[:12]}...")
            logger.debug(f"[DELETE] URL: {delete_url[:80]}...")

            response = requests.delete(delete_url, timeout=10)

            logger.debug(f"[DELETE] Response status: {response.status_code}")

            if response.status_code == 204:
                logger.info(
                    f"[DELETE] ✅ Deleted Discord message {message.message_id[:12]} "
                    f"(type={message.message_type}, age={int(time.time() - message.posted_at)}s)"
                )
                return True
            elif response.status_code == 404:
                logger.info(f"[DELETE] ⚠️  Message {message.message_id[:12]} already deleted (404)")
                return True  # Consider already-deleted as success
            else:
                logger.warning(
                    f"[DELETE] ❌ Failed to delete message {message.message_id[:12]}: "
                    f"HTTP {response.status_code} - {response.text[:100]}"
                )
                return False

        except requests.exceptions.RequestException as e:
            logger.error(f"[DELETE] ❌ Network error deleting message {message.message_id[:12]}: {e}")
            return False
        except Exception as e:
            logger.error(f"[DELETE] ❌ Unexpected error deleting message {message.message_id[:12]}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def cleanup_old_messages(self):
        """Delete messages that have exceeded their TTL"""
        now = time.time()
        deleted_count = 0
        failed_count = 0

        logger.info(f"[CLEANUP] Starting cleanup check (total messages: {len(self.messages)})")

        with self.lock:
            messages_to_delete = []
            messages_to_keep = []

            for msg in self.messages:
                age = now - msg.posted_at
                expires_at = msg.posted_at + msg.ttl_seconds
                time_until_expire = expires_at - now

                if age >= msg.ttl_seconds:
                    logger.info(
                        f"[CLEANUP] Message {msg.message_id[:12]} EXPIRED "
                        f"(age={int(age)}s, ttl={msg.ttl_seconds}s, over by {int(age - msg.ttl_seconds)}s)"
                    )
                    messages_to_delete.append(msg)
                else:
                    logger.info(
                        f"[CLEANUP] Message {msg.message_id[:12]} not expired yet "
                        f"(age={int(age)}s, ttl={msg.ttl_seconds}s, expires in {int(time_until_expire)}s)"
                    )
                    messages_to_keep.append(msg)

            logger.info(f"[CLEANUP] Found {len(messages_to_delete)} expired messages to delete")

            # Attempt to delete expired messages
            for msg in messages_to_delete:
                logger.info(f"[CLEANUP] Deleting expired message {msg.message_id[:12]}...")
                if self.delete_message(msg):
                    deleted_count += 1
                    logger.info(f"[CLEANUP] ✅ Successfully deleted {msg.message_id[:12]}")
                else:
                    # Keep messages that failed to delete for retry
                    messages_to_keep.append(msg)
                    failed_count += 1
                    logger.warning(f"[CLEANUP] ❌ Failed to delete {msg.message_id[:12]}, will retry")

            # Update tracked messages
            self.messages = messages_to_keep
            self._save_messages()

        if deleted_count > 0 or failed_count > 0:
            logger.info(
                f"[CLEANUP] Completed: deleted {deleted_count}, failed {failed_count}, remaining {len(self.messages)}"
            )
        else:
            logger.debug(f"[CLEANUP] No expired messages to delete")

    def _cleanup_loop(self):
        """Background thread loop for periodic cleanup"""
        logger.info("[THREAD] Discord auto-delete cleanup thread started")
        logger.info(f"[THREAD] Storage file: {self.storage_file}")
        logger.info(f"[THREAD] Will check for expired messages every 60 seconds")

        iteration = 0

        while self.running:
            try:
                iteration += 1
                logger.info(f"[THREAD] Cleanup iteration #{iteration} - checking for expired messages...")
                self.cleanup_old_messages()
                logger.debug(f"[THREAD] Iteration #{iteration} complete, sleeping 60s...")
            except Exception as e:
                logger.error(f"[THREAD] ❌ Error in cleanup loop iteration #{iteration}: {e}")
                import traceback
                traceback.print_exc()

            # Sleep for 60 seconds between cleanup runs
            for i in range(60):
                if not self.running:
                    logger.info(f"[THREAD] Stop signal received, exiting...")
                    break
                time.sleep(1)

        logger.info("[THREAD] Discord auto-delete cleanup thread stopped")

    def start_cleanup_thread(self):
        """Start background thread for automatic cleanup"""
        if self.cleanup_thread and self.cleanup_thread.is_alive():
            logger.warning("Cleanup thread already running")
            return

        self.running = True
        self.cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="DiscordAutoDelete"
        )
        self.cleanup_thread.start()
        logger.info("Started Discord auto-delete cleanup thread")

    def stop_cleanup_thread(self):
        """Stop the background cleanup thread"""
        if not self.running:
            return

        logger.info("Stopping Discord auto-delete cleanup thread...")
        self.running = False

        if self.cleanup_thread:
            self.cleanup_thread.join(timeout=5)

    def get_stats(self) -> Dict:
        """Get statistics about tracked messages"""
        with self.lock:
            total = len(self.messages)
            by_type = {}
            oldest = None

            for msg in self.messages:
                by_type[msg.message_type] = by_type.get(msg.message_type, 0) + 1
                age = time.time() - msg.posted_at
                if oldest is None or age > oldest:
                    oldest = age

            return {
                'total_tracked': total,
                'by_type': by_type,
                'oldest_message_age_seconds': oldest
            }


# Example usage
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Initialize auto-delete
    auto_delete = DiscordAutoDelete(
        storage_file="/tmp/discord_messages.json",
        default_ttl=300  # 5 minutes for testing
    )

    # Start cleanup thread
    auto_delete.start_cleanup_thread()

    # Send a test message (replace with your webhook)
    webhook_url = "YOUR_WEBHOOK_URL_HERE"

    message_id = auto_delete.send_message(
        webhook_url=webhook_url,
        message_data={"content": "Test message - will auto-delete in 5 minutes"},
        ttl_seconds=300,
        message_type="test"
    )

    if message_id:
        print(f"Sent message: {message_id}")
        print(f"Stats: {auto_delete.get_stats()}")

    # Keep running
    try:
        while True:
            time.sleep(60)
            print(f"Stats: {auto_delete.get_stats()}")
    except KeyboardInterrupt:
        print("Stopping...")
        auto_delete.stop_cleanup_thread()
