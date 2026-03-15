import argparse
import logging

from telegram.ext import Application, MessageHandler, filters
from telegram.request import HTTPXRequest

from bot.handlers import handle_video_message
from config import config

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Telegram → YouTube Bot")
    parser.add_argument(
        "--auth",
        action="store_true",
        help="Run the YouTube OAuth2 authorization flow and exit",
    )
    args = parser.parse_args()

    if args.auth:
        from youtube.auth import run_oauth_flow
        run_oauth_flow()
        print("YouTube authorization successful. Token saved to", config.google_token_file)
        return

    # Build the video message filter
    video_filter = (
        filters.VIDEO
        | filters.VIDEO_NOTE
        | filters.Document.MimeType("video/mp4")
        | filters.Document.MimeType("video/quicktime")
        | filters.Document.MimeType("video/x-matroska")
        | filters.Document.MimeType("video/webm")
        | filters.Document.MimeType("video/avi")
        | filters.Document.MimeType("video/mpeg")
        | filters.Document.MimeType("video/x-msvideo")
    )

    # Use longer timeouts for all Telegram API requests to handle large file downloads
    request = HTTPXRequest(read_timeout=600, write_timeout=600, connect_timeout=30)
    builder = Application.builder().token(config.telegram_token).request(request)

    if config.use_local_server:
        # Local Bot API Server mode: required for files > 20 MB
        base = config.local_api_server_url.rstrip("/")
        builder = (
            builder
            .local_mode(True)
            .base_url(f"{base}/bot")
            .base_file_url(f"{base}/file/bot")
        )
        logger.info("Using Local Bot API Server: %s", base)

    app = builder.build()
    app.add_handler(MessageHandler(video_filter, handle_video_message))

    logger.info("Bot started, polling for messages...")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
