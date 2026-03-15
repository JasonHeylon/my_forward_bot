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
    从 Telegram 下载视频到本地临时目录。
    返回本地文件路径。
    """
    config.download_dir.mkdir(parents=True, exist_ok=True)

    # 用 file_id 的哈希值命名，避免并发冲突
    safe_name = hashlib.sha256(file_id.encode()).hexdigest()[:16]
    local_path = config.download_dir / f"{safe_name}.video"

    if file_size and file_size > config.telegram_direct_download_threshold:
        await _download_large(bot, file_id, file_size, local_path, progress)
    else:
        await _download_small(bot, file_id, local_path, progress)

    return local_path


async def _download_small(bot: Bot, file_id: str, dest: Path, progress: ProgressReporter):
    """≤ 20MB：用 python-telegram-bot 内置方法下载。"""
    tg_file = await bot.get_file(file_id)
    await tg_file.download_to_drive(dest)
    await progress.update("下载完成。", force=True)


async def _download_large(
    bot: Bot,
    file_id: str,
    file_size: int,
    dest: Path,
    progress: ProgressReporter,
):
    """
    > 20MB：通过 Telegram CDN 流式下载。
    1. 调用 bot.get_file() 获取 file_path
    2. 拼接 CDN URL：https://api.telegram.org/file/bot<TOKEN>/<file_path>
    3. 用 httpx 以 1MB 块流式写入磁盘，每 10MB 更新一次进度
    """
    tg_file = await bot.get_file(file_id)
    cdn_url = f"https://api.telegram.org/file/bot{bot.token}/{tg_file.file_path}"

    downloaded = 0
    last_report = 0

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", cdn_url) as response:
            response.raise_for_status()
            async with aiofiles.open(dest, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=1_048_576):  # 1MB
                    await f.write(chunk)
                    downloaded += len(chunk)

                    if downloaded - last_report >= config.download_progress_chunk:
                        pct = (downloaded / file_size * 100) if file_size else 0
                        size_mb = file_size / 1_048_576
                        done_mb = downloaded / 1_048_576
                        await progress.update(
                            f"正在下载... {done_mb:.1f} MB / {size_mb:.1f} MB ({pct:.0f}%)"
                        )
                        last_report = downloaded

    done_mb = downloaded / 1_048_576
    await progress.update(f"下载完成：{done_mb:.1f} MB", force=True)
