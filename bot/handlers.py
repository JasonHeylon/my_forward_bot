from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from bot.downloader import download_video
from bot.progress import ProgressReporter
from config import config
from youtube.uploader import upload_to_youtube

# Supported video MIME types for document messages
_VIDEO_MIME_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-matroska",
    "video/webm",
    "video/avi",
    "video/mpeg",
    "video/x-msvideo",
}


async def handle_video_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message

    # ── 1. Deduplicate media groups ────────────────────────────────────────────
    # When a user sends multiple files at once, Telegram delivers them as
    # separate messages sharing the same media_group_id. Only process the first.
    if message.media_group_id:
        seen: set = context.bot_data.setdefault("seen_media_groups", set())
        if message.media_group_id in seen:
            return
        seen.add(message.media_group_id)

    # ── 2. Extract video info ──────────────────────────────────────────────────
    video_info = _extract_video_info(message)
    if video_info is None:
        await message.reply_text("Could not find a downloadable video in this message. Please send a video file directly.")
        return

    file_id, file_size, caption, mime_type = video_info

    # Extract caption from either caption field or text field (for forwarded messages)
    caption = caption or message.text or message.caption_html or ""

    # ── 3. File size check ─────────────────────────────────────────────────────
    if file_size and file_size > config.max_file_size:
        size_gb = file_size / 1_073_741_824
        max_gb = config.max_file_size / 1_073_741_824
        await message.reply_text(
            f"Video is too large ({size_gb:.1f} GB). Maximum supported size is {max_gb:.1f} GB."
        )
        return

    # ── 4. Check if another video is currently being processed ────────────────
    if context.bot_data.get("processing_video"):
        await message.reply_text(
            "⏳ Another video is currently being processed. Please wait until it completes."
        )
        return

    # ── 5. Show confirmation buttons ──────────────────────────────────────────
    size_mb = (file_size / 1_048_576) if file_size else 0
    caption_preview = (caption[:50] + "..." if caption and len(caption) > 50 else caption) if caption else "(no caption)"

    keyboard = [
        [
            InlineKeyboardButton(
                "📤 Upload to YouTube + Forward",
                callback_data=f"action:upload_and_forward:{message.message_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "📺 Upload to YouTube Only",
                callback_data=f"action:upload_only:{message.message_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "➡️ Forward to Channel Only",
                callback_data=f"action:forward_only:{message.message_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data=f"action:cancel:{message.message_id}"
            )
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await message.reply_text(
        f"📹 Video received ({size_mb:.0f} MB)\n"
        f"📝 Caption: {caption_preview}\n\n"
        f"Choose an action:",
        reply_markup=reply_markup
    )

    # Store video info in context for the callback handler to use
    context.bot_data[f"video:{message.message_id}"] = {
        "file_id": file_id,
        "file_size": file_size,
        "caption": caption,
        "mime_type": mime_type,
    }


async def handle_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks from the confirmation message."""
    query = update.callback_query
    await query.answer()

    # Parse callback data: "action:upload_and_forward:123"
    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "action":
        await query.edit_message_text("Invalid action.")
        return

    action, msg_id = parts[1], int(parts[2])

    # Retrieve stored video info
    video_data = context.bot_data.get(f"video:{msg_id}")
    if not video_data:
        await query.edit_message_text("Video info expired. Please send the video again.")
        return

    file_id = video_data["file_id"]
    file_size = video_data["file_size"]
    caption = video_data["caption"]
    mime_type = video_data["mime_type"]

    # ── Handle Cancel ──────────────────────────────────────────────────────────
    if action == "cancel":
        await query.edit_message_text("❌ Cancelled.")
        del context.bot_data[f"video:{msg_id}"]
        return

    # ── Handle Upload Only ─────────────────────────────────────────────────────
    if action == "upload_only":
        context.bot_data["processing_video"] = msg_id

        description = caption or ""
        title = (caption[:20] if caption else "Uploaded Video")

        await query.edit_message_text("Starting: downloading video from Telegram...")

        # Create a ProgressReporter that edits the callback message
        class CallbackProgressReporter:
            def __init__(self, callback_query):
                self._query = callback_query
                self._last_update = 0.0

            async def send(self, text: str):
                await self._query.edit_message_text(text)
                return self._query.message

            async def update(self, text: str, force: bool = False):
                import time
                now = time.monotonic()
                if not force and (now - self._last_update) < 3.0:
                    return
                try:
                    await self._query.edit_message_text(text)
                    self._last_update = now
                except Exception:
                    pass

        progress = CallbackProgressReporter(query)
        local_path: Path | None = None

        try:
            # Download video
            await context.bot.send_chat_action(query.message.chat_id, ChatAction.UPLOAD_VIDEO)
            local_path = await download_video(
                bot=context.bot,
                file_id=file_id,
                file_size=file_size,
                progress=progress,
            )

            # Upload to YouTube
            await progress.update(
                f"Uploading to YouTube (private)...\nTitle: {title}",
                force=True,
            )
            video_id = await upload_to_youtube(
                file_path=local_path,
                title=title,
                description=description,
                mime_type=mime_type or "video/mp4",
                progress=progress,
            )

            # Done
            youtube_url = f"https://youtu.be/{video_id}"
            await progress.update(
                f"✅ Done!\n\n"
                f"Title: {title}\n"
                f"YouTube: {youtube_url}",
                force=True,
            )

        except Exception as exc:
            await progress.update(f"❌ Failed: {exc}\n\nPlease try again.", force=True)
            raise

        finally:
            if local_path and local_path.exists():
                local_path.unlink()
            context.bot_data.pop("processing_video", None)
            del context.bot_data[f"video:{msg_id}"]
        return

    # ── Handle Forward Only ────────────────────────────────────────────────────
    if action == "forward_only":
        if not config.target_channel_id:
            await query.edit_message_text("No target channel configured (TELEGRAM_CHANNEL_ID is not set).")
            del context.bot_data[f"video:{msg_id}"]
            return

        context.bot_data["processing_video"] = msg_id
        await query.edit_message_text("Forwarding to channel...")
        try:
            await context.bot.send_video(
                chat_id=config.target_channel_id,
                video=file_id,
                caption=caption,
            )
            await query.edit_message_text("✅ Forwarded to channel successfully.")
        except Exception as exc:
            await query.edit_message_text(f"❌ Failed to forward: {exc}")
        finally:
            context.bot_data.pop("processing_video", None)
            del context.bot_data[f"video:{msg_id}"]
        return

    # ── Handle Upload and Forward ──────────────────────────────────────────────
    if action == "upload_and_forward":
        context.bot_data["processing_video"] = msg_id

        description = caption or ""
        title = (caption[:20] if caption else "Uploaded Video")

        # Forward to channel first (if configured)
        if config.target_channel_id:
            try:
                await context.bot.send_video(
                    chat_id=config.target_channel_id,
                    video=file_id,
                    caption=caption,
                )
            except Exception as exc:
                await query.edit_message_text(f"❌ Failed to forward to channel: {exc}")
                context.bot_data.pop("processing_video", None)
                del context.bot_data[f"video:{msg_id}"]
                return

        # Set up progress reporter
        await query.edit_message_text("Starting: downloading video from Telegram...")

        # Create a ProgressReporter that edits the callback message
        class CallbackProgressReporter:
            def __init__(self, callback_query):
                self._query = callback_query
                self._last_update = 0.0

            async def send(self, text: str):
                await self._query.edit_message_text(text)
                return self._query.message

            async def update(self, text: str, force: bool = False):
                import time
                now = time.monotonic()
                if not force and (now - self._last_update) < 3.0:
                    return
                try:
                    await self._query.edit_message_text(text)
                    self._last_update = now
                except Exception:
                    pass

        progress = CallbackProgressReporter(query)
        local_path: Path | None = None

        try:
            # Download video
            await context.bot.send_chat_action(query.message.chat_id, ChatAction.UPLOAD_VIDEO)
            local_path = await download_video(
                bot=context.bot,
                file_id=file_id,
                file_size=file_size,
                progress=progress,
            )

            # Upload to YouTube
            await progress.update(
                f"Uploading to YouTube (private)...\nTitle: {title}",
                force=True,
            )
            video_id = await upload_to_youtube(
                file_path=local_path,
                title=title,
                description=description,
                mime_type=mime_type or "video/mp4",
                progress=progress,
            )

            # Done
            youtube_url = f"https://youtu.be/{video_id}"
            await progress.update(
                f"✅ Done!\n\n"
                f"Title: {title}\n"
                f"YouTube: {youtube_url}\n"
                f"Channel: {'✅ Forwarded' if config.target_channel_id else 'N/A'}",
                force=True,
            )

        except Exception as exc:
            await progress.update(f"❌ Failed: {exc}\n\nPlease try again.", force=True)
            raise

        finally:
            if local_path and local_path.exists():
                local_path.unlink()
            context.bot_data.pop("processing_video", None)
            del context.bot_data[f"video:{msg_id}"]


def _extract_video_info(message: Message):
    """
    Extract video info from a message.
    Returns (file_id, file_size, caption, mime_type) or None.
    Supports: message.video, message.document (video MIME), message.video_note
    """
    if message.video:
        v = message.video
        return v.file_id, v.file_size, message.caption, v.mime_type or "video/mp4"

    if message.document:
        d = message.document
        if d.mime_type in _VIDEO_MIME_TYPES:
            return d.file_id, d.file_size, message.caption, d.mime_type

    if message.video_note:
        vn = message.video_note
        return vn.file_id, vn.file_size, None, "video/mp4"

    return None
