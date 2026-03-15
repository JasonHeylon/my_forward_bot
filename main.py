import argparse
import logging

from telegram.ext import Application, MessageHandler, filters

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
        help="执行 YouTube OAuth2 首次授权流程后退出",
    )
    args = parser.parse_args()

    if args.auth:
        from youtube.auth import run_oauth_flow
        run_oauth_flow()
        print("YouTube 授权成功！Token 已保存至", config.google_token_file)
        return

    # 构建支持的视频消息过滤器
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

    app = Application.builder().token(config.telegram_token).build()
    app.add_handler(MessageHandler(video_filter, handle_video_message))

    logger.info("Bot 启动，开始监听消息...")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
