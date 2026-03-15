import hashlib
from pathlib import Path

import aiofiles
import httpx
from telegram import Bot

from bot.progress import ProgressReporter
from config import config


async def download_video(
    bot: Bot,
    file_id: str,
    file_size: int | None,
    progress: ProgressReporter,
) -> Path:
    """
    Download a video from Telegram to the local temp directory.
    Returns the local file path.
    """
    config.download_dir.mkdir(parents=True, exist_ok=True)

    # Use a hash of file_id as the filename to avoid concurrent download conflicts
    safe_name = hashlib.sha256(file_id.encode()).hexdigest()[:16]
    local_path = config.download_dir / f"{safe_name}.video"

    if file_size and file_size > config.telegram_direct_download_threshold:
        await _download_large(bot, file_id, file_size, local_path, progress)
    else:
        await _download_small(bot, file_id, local_path, progress)

    return local_path


async def _download_small(bot: Bot, file_id: str, dest: Path, progress: ProgressReporter):
    """<= 20MB: use python-telegram-bot's built-in download method."""
    tg_file = await bot.get_file(file_id)
    await tg_file.download_to_drive(dest)
    await progress.update("Download complete.", force=True)


async def _download_large(
    bot: Bot,
    file_id: str,
    file_size: int,
    dest: Path,
    progress: ProgressReporter,
):
    """
    > 20MB: stream directly from the Telegram CDN.
    1. Call bot.get_file() to get the file_path
    2. Construct CDN URL: https://api.telegram.org/file/bot<TOKEN>/<file_path>
    3. Stream via httpx in 1MB chunks, reporting progress every 10MB
    """
    tg_file = await bot.get_file(file_id)
    cdn_url = f"https://api.telegram.org/file/bot{bot.token}/{tg_file.file_path}"

    downloaded = 0
    last_report = 0

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", cdn_url) as response:
            response.raise_for_status()
            async with aiofiles.open(dest, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=1_048_576):  # 1MB chunks
                    await f.write(chunk)
                    downloaded += len(chunk)

                    if downloaded - last_report >= config.download_progress_chunk:
                        pct = (downloaded / file_size * 100) if file_size else 0
                        size_mb = file_size / 1_048_576
                        done_mb = downloaded / 1_048_576
                        await progress.update(
                            f"Downloading... {done_mb:.1f} MB / {size_mb:.1f} MB ({pct:.0f}%)"
                        )
                        last_report = downloaded

    done_mb = downloaded / 1_048_576
    await progress.update(f"Download complete: {done_mb:.1f} MB", force=True)
