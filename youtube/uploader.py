import asyncio
import json
from pathlib import Path

import aiofiles
import httpx

from bot.progress import ProgressReporter
from youtube.auth import get_credentials

YOUTUBE_UPLOAD_URL = (
    "https://www.googleapis.com/upload/youtube/v3/videos"
    "?uploadType=resumable&part=snippet,status"
)

# 分块大小必须是 256KB 的整数倍；16MB 是效率与重试代价的平衡点
CHUNK_SIZE = 16 * 1024 * 1024  # 16MB


async def upload_to_youtube(
    file_path: Path,
    title: str,
    description: str,
    mime_type: str,
    progress: ProgressReporter,
) -> str:
    """
    将视频文件上传至 YouTube（私密），返回 YouTube video ID。
    使用断点续传协议，支持大文件和网络中断恢复。
    """
    creds = get_credentials()

    # 过期时在线程池中刷新（google-auth 是同步库）
    if creds.expired and creds.refresh_token:
        loop = asyncio.get_event_loop()
        from google.auth.transport.requests import Request
        await loop.run_in_executor(None, creds.refresh, Request())

    file_size = file_path.stat().st_size

    upload_url = await _initiate_upload(creds.token, title, description, mime_type, file_size)
    return await _upload_chunks(upload_url, file_path, file_size, mime_type, progress)


async def _initiate_upload(
    access_token: str,
    title: str,
    description: str,
    mime_type: str,
    file_size: int,
) -> str:
    """
    向 YouTube 发起断点续传会话，返回 upload session URL（Location header）。
    视频设置为私密（privacyStatus: private），不会自动公开。
    """
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "categoryId": "22",  # People & Blogs
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
        },
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": mime_type,
        "X-Upload-Content-Length": str(file_size),
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            YOUTUBE_UPLOAD_URL,
            headers=headers,
            content=json.dumps(body).encode(),
        )
        resp.raise_for_status()
        return resp.headers["Location"]


async def _upload_chunks(
    upload_url: str,
    file_path: Path,
    file_size: int,
    mime_type: str,
    progress: ProgressReporter,
) -> str:
    """
    以 16MB 分块 PUT 上传视频。

    协议说明：
    - 308 Resume Incomplete：分块已接收，继续下一块
    - 200/201：上传完成，解析 video_id
    - 5xx：指数退避重试（最多 5 次）
    - 网络中断：查询断点后续传
    """
    uploaded = 0
    retry_count = 0
    max_retries = 5

    async with aiofiles.open(file_path, "rb") as f:
        while uploaded < file_size:
            chunk_start = uploaded
            chunk_data = await f.read(CHUNK_SIZE)
            if not chunk_data:
                break
            chunk_end = chunk_start + len(chunk_data) - 1

            headers = {
                "Content-Range": f"bytes {chunk_start}-{chunk_end}/{file_size}",
                "Content-Type": mime_type,
            }

            try:
                async with httpx.AsyncClient(timeout=300.0) as client:
                    resp = await client.put(upload_url, headers=headers, content=chunk_data)

                if resp.status_code in (200, 201):
                    data = resp.json()
                    return data["id"]

                if resp.status_code == 308:
                    uploaded = chunk_end + 1
                    retry_count = 0
                    pct = uploaded / file_size * 100
                    await progress.update(
                        f"正在上传到 YouTube：{uploaded / 1_048_576:.0f} MB"
                        f" / {file_size / 1_048_576:.0f} MB ({pct:.0f}%)"
                    )
                    await f.seek(uploaded)
                    continue

                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"服务器错误 {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )

                resp.raise_for_status()

            except (httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                retry_count += 1
                if retry_count > max_retries:
                    raise RuntimeError(
                        f"上传失败，已重试 {max_retries} 次：{exc}"
                    ) from exc

                wait = 2 ** retry_count
                await progress.update(
                    f"上传中断，{wait}s 后重试... (第 {retry_count}/{max_retries} 次)",
                    force=True,
                )
                await asyncio.sleep(wait)

                # 查询 YouTube 已接收的字节数，从断点处续传
                uploaded = await _query_upload_offset(upload_url, file_size)
                await f.seek(uploaded)

    raise RuntimeError("上传循环结束但未收到 YouTube video ID。")


async def _query_upload_offset(upload_url: str, file_size: int) -> int:
    """
    查询 YouTube 已成功接收的字节数，用于网络中断后续传。
    返回下次应从哪个字节开始发送。
    """
    headers = {
        "Content-Range": f"bytes */{file_size}",
        "Content-Length": "0",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.put(upload_url, headers=headers)

    if resp.status_code == 308:
        # Range: bytes=0-N
        range_header = resp.headers.get("Range", "bytes=0--1")
        end_byte = int(range_header.split("-")[1])
        return end_byte + 1

    if resp.status_code in (200, 201):
        return file_size  # 已上传完毕

    raise RuntimeError(f"无法查询上传断点：HTTP {resp.status_code}")
