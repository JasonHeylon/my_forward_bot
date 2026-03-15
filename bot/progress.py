import asyncio
import time
from telegram import Message

MIN_INTERVAL = 3.0  # 两次编辑最小间隔（秒），避免触发 Telegram 频率限制


class ProgressReporter:
    def __init__(self, original_message: Message):
        self._original = original_message
        self._status_msg: Message | None = None
        self._last_update = 0.0
        self._lock = asyncio.Lock()

    async def send(self, text: str) -> Message:
        """发送初始状态消息，必须最先调用。"""
        async with self._lock:
            self._status_msg = await self._original.reply_text(text)
            self._last_update = time.monotonic()
            return self._status_msg

    async def update(self, text: str, force: bool = False):
        """原地编辑状态消息。除非 force=True，否则限速 MIN_INTERVAL 秒。"""
        async with self._lock:
            now = time.monotonic()
            if not force and (now - self._last_update) < MIN_INTERVAL:
                return
            if self._status_msg:
                try:
                    await self._status_msg.edit_text(text)
                    self._last_update = now
                except Exception:
                    pass  # 消息过旧或已被删除时静默忽略
