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

# Chunk size must be a multiple of 256KB; 16MB balances efficiency and retry cost
CHUNK_SIZE = 16 * 1024 * 1024  # 16MB


async def upload_to_youtube(
    file_path: Path,
    title: str,
    description: str,
    mime_type: str,
    progress: ProgressReporter,
) -> str:
    """
    Upload a video file to YouTube as private. Returns the YouTube video ID.
    Uses the resumable upload protocol to support large files and network interruptions.
    """
    creds = get_credentials()

    # Refresh credentials in a thread pool executor (google-auth is a sync library)
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
    Initiate a resumable upload session with YouTube.
    Returns the upload session URL from the Location response header.
    Video is set to private (privacyStatus: private) and will never be auto-published.
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
    Upload the video in 16MB chunks using the resumable upload protocol.

    Protocol responses:
    - 308 Resume Incomplete: chunk accepted, continue with next chunk
    - 200/201: upload complete, parse and return video_id
    - 5xx: exponential backoff retry (up to 5 attempts)
    - Network interruption: query resume offset, then continue from that byte
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
                    retry_count = 0  # Reset retry counter on successful chunk
                    pct = uploaded / file_size * 100
                    await progress.update(
                        f"Uploading to YouTube: {uploaded / 1_048_576:.0f} MB"
                        f" / {file_size / 1_048_576:.0f} MB ({pct:.0f}%)"
                    )
                    await f.seek(uploaded)
                    continue

                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"Server error {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )

                resp.raise_for_status()

            except (httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                retry_count += 1
                if retry_count > max_retries:
                    raise RuntimeError(
                        f"Upload failed after {max_retries} retries: {exc}"
                    ) from exc

                wait = 2 ** retry_count
                await progress.update(
                    f"Upload interrupted, retrying in {wait}s... ({retry_count}/{max_retries})",
                    force=True,
                )
                await asyncio.sleep(wait)

                # Query how many bytes YouTube has received, then resume from there
                uploaded = await _query_upload_offset(upload_url, file_size)
                await f.seek(uploaded)

    raise RuntimeError("Upload loop ended without receiving a YouTube video ID.")


async def _query_upload_offset(upload_url: str, file_size: int) -> int:
    """
    Query YouTube for the number of bytes successfully received so far.
    Used to resume an interrupted upload. Returns the byte offset to resume from.
    """
    headers = {
        "Content-Range": f"bytes */{file_size}",
        "Content-Length": "0",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.put(upload_url, headers=headers)

    if resp.status_code == 308:
        # Range header format: bytes=0-N
        range_header = resp.headers.get("Range", "bytes=0--1")
        end_byte = int(range_header.split("-")[1])
        return end_byte + 1

    if resp.status_code in (200, 201):
        return file_size  # Already complete

    raise RuntimeError(f"Could not query upload offset: HTTP {resp.status_code}")
