from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    telegram_token: str
    google_client_secrets_file: Path
    google_token_file: Path
    download_dir: Path
    max_file_size: int
    download_progress_chunk: int
    # Optional: URL of a self-hosted Telegram Local Bot API Server.
    # Required for files larger than 20 MB. Leave empty to use the standard API.
    local_api_server_url: str | None
    # Optional: Telegram channel to repost videos to (bot must be an admin)
    target_channel_id: str | None

    @property
    def use_local_server(self) -> bool:
        return bool(self.local_api_server_url)

    @classmethod
    def from_env(cls) -> "Config":
        missing = []

        def require(key: str) -> str:
            val = os.getenv(key)
            if not val:
                missing.append(key)
            return val or ""

        telegram_token = require("TELEGRAM_BOT_TOKEN")
        google_client_secrets_file = require("GOOGLE_CLIENT_SECRETS_FILE")
        google_token_file = require("GOOGLE_TOKEN_FILE")

        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                "Please copy .env.example to .env and fill in the values."
            )

        return cls(
            telegram_token=telegram_token,
            google_client_secrets_file=Path(google_client_secrets_file),
            google_token_file=Path(google_token_file),
            download_dir=Path(os.getenv("DOWNLOAD_DIR", "downloads")),
            max_file_size=int(os.getenv("MAX_FILE_SIZE", str(1717986918))),
            download_progress_chunk=int(os.getenv("DOWNLOAD_PROGRESS_CHUNK", str(10485760))),
            local_api_server_url=os.getenv("LOCAL_API_SERVER_URL") or None,
            target_channel_id=os.getenv("TELEGRAM_CHANNEL_ID") or None,
        )


config = Config.from_env()
