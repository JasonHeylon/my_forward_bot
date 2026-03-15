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
    telegram_direct_download_threshold: int

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
            telegram_direct_download_threshold=int(
                os.getenv("TELEGRAM_DIRECT_DOWNLOAD_THRESHOLD", str(20971520))
            ),
        )


config = Config.from_env()
