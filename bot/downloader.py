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

    File size limits:
    - Standard Bot API: getFile only works for files up to 20 MB.
    - Local Bot API Server (LOCAL_API_SERVER_URL set): supports files up to 2 GB.
    """
    config.download_dir.mkdir(parents=True, exist_ok=True)

    # Use a hash of file_id as the filename to avoid concurrent download conflicts
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

    if is_large:
        # Local server mode: stream from the local API server in chunks for progress reporting
        await _download_with_progress(bot, file_id, file_size, local_path, progress)
    else:
        # Standard small file download
        await _download_small(bot, file_id, local_path, progress)

    return local_path


async def _download_small(bot: Bot, file_id: str, dest: Path, progress: ProgressReporter):
    """Use python-telegram-bot's built-in download (works for any size in local server mode)."""
    tg_file = await bot.get_file(file_id)
    await tg_file.download_to_drive(dest)
    await progress.update("Download complete.", force=True)


async def _download_with_progress(
    bot: Bot,
    file_id: str,
    file_size: int,
    dest: Path,
    progress: ProgressReporter,
):
    """
    Stream the file via the local API server with progress reporting.
    The local server exposes the file at: <LOCAL_API_SERVER_URL>/file/bot<TOKEN>/<file_path>
    """
    tg_file = await bot.get_file(file_id)
    base = config.local_api_server_url.rstrip("/")
    file_url = f"{base}/file/bot{bot.token}/{tg_file.file_path}"

    downloaded = 0
    last_report = 0

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", file_url) as response:
            response.raise_for_status()
            async with aiofiles.open(dest, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=1_048_576):  # 1 MB chunks
                    await f.write(chunk)
                    downloaded += len(chunk)

                    if downloaded - last_report >= config.download_progress_chunk:
                        pct = (downloaded / file_size * 100) if file_size else 0
                        done_mb = downloaded / 1_048_576
                        size_mb = file_size / 1_048_576
                        await progress.update(
                            f"Downloading... {done_mb:.1f} MB / {size_mb:.1f} MB ({pct:.0f}%)"
                        )
                        last_report = downloaded

    done_mb = downloaded / 1_048_576
    await progress.update(f"Download complete: {done_mb:.1f} MB", force=True)
