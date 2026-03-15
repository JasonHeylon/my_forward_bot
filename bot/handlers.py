from pathlib import Path

from telegram import Message, Update
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

    # ── 1. Extract video info ──────────────────────────────────────────────────
    video_info = _extract_video_info(message)
    if video_info is None:
        await message.reply_text("Could not find a downloadable video in this message. Please send a video file directly.")
        return

    file_id, file_size, caption, mime_type = video_info

    # ── 2. File size check ─────────────────────────────────────────────────────
    if file_size and file_size > config.max_file_size:
        size_gb = file_size / 1_073_741_824
        max_gb = config.max_file_size / 1_073_741_824
        await message.reply_text(
            f"Video is too large ({size_gb:.1f} GB). Maximum supported size is {max_gb:.1f} GB."
        )
        return

    # ── 3. Generate YouTube metadata from Telegram message content ─────────────
    description = caption or ""
    title = (caption[:20] if caption else "Uploaded Video")

    # ── 4. Send initial status message ────────────────────────────────────────
    progress = ProgressReporter(message)
    await progress.send("Starting: downloading video from Telegram...")

    local_path: Path | None = None
    try:
        # ── 5. Download video ──────────────────────────────────────────────────
        await context.bot.send_chat_action(message.chat_id, ChatAction.UPLOAD_VIDEO)
        local_path = await download_video(
            bot=context.bot,
            file_id=file_id,
            file_size=file_size,
            progress=progress,
        )

        # ── 6. Upload to YouTube ───────────────────────────────────────────────
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

        # ── 7. Done ────────────────────────────────────────────────────────────
        youtube_url = f"https://youtu.be/{video_id}"
        await progress.update(
            f"Done! Video saved as private draft.\n\n"
            f"Title: {title}\n"
            f"Link: {youtube_url}",
            force=True,
        )

    except Exception as exc:
        await progress.update(f"Failed: {exc}\n\nPlease try again.", force=True)
        raise

    finally:
        # Always delete the local temp file after success or failure
        if local_path and local_path.exists():
            local_path.unlink()


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
