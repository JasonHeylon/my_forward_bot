from pathlib import Path

from telegram import Message, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from bot.downloader import download_video
from bot.progress import ProgressReporter
from config import config
from youtube.uploader import upload_to_youtube

# 支持的视频文档 MIME 类型
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

    # ── 1. 提取视频信息 ────────────────────────────────────────────────────────
    video_info = _extract_video_info(message)
    if video_info is None:
        await message.reply_text("无法识别消息中的可下载视频，请直接发送视频文件。")
        return

    file_id, file_size, caption, mime_type = video_info

    # ── 2. 文件大小校验 ────────────────────────────────────────────────────────
    if file_size and file_size > config.max_file_size:
        size_gb = file_size / 1_073_741_824
        max_gb = config.max_file_size / 1_073_741_824
        await message.reply_text(
            f"视频文件过大（{size_gb:.1f} GB），最大支持 {max_gb:.1f} GB。"
        )
        return

    # ── 3. 生成 YouTube 元数据（直接使用 Telegram 消息内容）─────────────────
    description = caption or ""
    title = (caption[:20] if caption else "上传的视频")

    # ── 4. 发送初始状态消息 ────────────────────────────────────────────────────
    progress = ProgressReporter(message)
    await progress.send("开始处理：正在从 Telegram 下载视频...")

    local_path: Path | None = None
    try:
        # ── 5. 下载视频 ────────────────────────────────────────────────────────
        await context.bot.send_chat_action(message.chat_id, ChatAction.UPLOAD_VIDEO)
        local_path = await download_video(
            bot=context.bot,
            file_id=file_id,
            file_size=file_size,
            progress=progress,
        )

        # ── 6. 上传到 YouTube ──────────────────────────────────────────────────
        await progress.update(
            f"正在上传到 YouTube（私密）...\n标题：{title}",
            force=True,
        )
        video_id = await upload_to_youtube(
            file_path=local_path,
            title=title,
            description=description,
            mime_type=mime_type or "video/mp4",
            progress=progress,
        )

        # ── 7. 完成 ────────────────────────────────────────────────────────────
        youtube_url = f"https://youtu.be/{video_id}"
        await progress.update(
            f"上传完成！视频已保存为私密草稿。\n\n"
            f"标题：{title}\n"
            f"链接：{youtube_url}",
            force=True,
        )

    except Exception as exc:
        await progress.update(f"处理失败：{exc}\n\n请重试。", force=True)
        raise

    finally:
        if local_path and local_path.exists():
            local_path.unlink()


def _extract_video_info(message: Message):
    """
    从消息中提取视频信息。
    返回 (file_id, file_size, caption, mime_type) 或 None。
    支持：message.video、message.document（视频 MIME）、message.video_note
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
