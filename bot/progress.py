import asyncio
import time
from telegram import Message

MIN_INTERVAL = 3.0  # Minimum seconds between edits to avoid Telegram rate limits


class ProgressReporter:
    def __init__(self, original_message: Message):
        self._original = original_message
        self._status_msg: Message | None = None
        self._last_update = 0.0
        self._lock = asyncio.Lock()

    async def send(self, text: str) -> Message:
        """Send the initial status message. Must be called first."""
        async with self._lock:
            self._status_msg = await self._original.reply_text(text)
            self._last_update = time.monotonic()
            return self._status_msg

    async def update(self, text: str, force: bool = False):
        """Edit the status message in-place. Throttled to MIN_INTERVAL unless force=True."""
        async with self._lock:
            now = time.monotonic()
            if not force and (now - self._last_update) < MIN_INTERVAL:
                return
            if self._status_msg:
                try:
                    await self._status_msg.edit_text(text)
                    self._last_update = now
                except Exception:
                    pass  # Silently ignore if message is too old or already deleted
