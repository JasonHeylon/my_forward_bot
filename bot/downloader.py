import hashlib
from pathlib import Path

import aiofiles
import httpx
from telegram import Bot

from bot.progress import ProgressReporter
from config import config

# Standard Bot API limit for getFile
_STANDARD_API_MAX = 20 * 1024 * 1024  # 20 MB


async def download_video(
    bot: Bot,
    file_id: str,
    file_size: int | None,
    progress: ProgressReporter,
) -> Path:
    """
    Download a video from Telegram to the local temp directory.
    Returns the local file path.

    In local server mode, the telegram-bot-api volume is mounted read-only at
    /var/lib/telegram-bot-api, so download_to_drive() copies the file directly
    without going through HTTP — this works for files of any size.
    """
    config.download_dir.mkdir(parents=True, exist_ok=True)

    safe_name = hashlib.sha256(file_id.encode()).hexdigest()[:16]
    local_path = config.download_dir / f"{safe_name}.video"

    is_large = file_size and file_size > _STANDARD_API_MAX

    if is_large and not config.use_local_server:
        size_mb = file_size / 1_048_576
        raise ValueError(
            f"File is {size_mb:.0f} MB. The standard Telegram Bot API only supports "
            f"files up to 20 MB.\n\n"
            f"To handle large files, set up a Telegram Local Bot API Server and set "
            f"LOCAL_API_SERVER_URL in your .env file. See README for details."
        )

    size_mb = f"{file_size / 1_048_576:.0f} MB" if file_size else "unknown size"
    await progress.update(f"Downloading video ({size_mb})...")

    tg_file = await bot.get_file(file_id)
    await tg_file.download_to_drive(local_path)

    await progress.update(f"Download complete ({size_mb}).", force=True)
    return local_path
