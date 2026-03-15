# my-forward-bot

A Telegram bot that automatically uploads forwarded videos to YouTube as private drafts.

Forward any message containing a video to the bot. It will download the video, use the first 20 characters of the message text as the YouTube title and the full text as the description, upload the video to YouTube as **private (unpublished)**, and reply with the YouTube link.

## Features

- Handles forwarded video messages (video, document-type video files, video_note)
- Generates YouTube title and description directly from Telegram message content
- Supports large files (200 MB – 1.5 GB) with streaming download (no full-file memory load)
- YouTube resumable upload with automatic recovery from network interruptions
- Real-time progress updates in Telegram throughout the process
- Temporary files are deleted from the server automatically after upload
- Docker deployment ready

## Architecture

```
my-forward-bot/
├── main.py                  # Entry point; registers handlers; supports --auth flag
├── config.py                # Configuration management; validates required env vars on startup
├── requirements.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
│
├── bot/
│   ├── handlers.py          # Core pipeline: extract → download → upload → reply
│   ├── downloader.py        # Video download (≤20 MB via API; >20 MB via CDN streaming)
│   └── progress.py          # Throttled in-place Telegram message editor (3s min interval)
│
├── youtube/
│   ├── auth.py              # OAuth2 flow, token persistence, and auto-refresh
│   └── uploader.py          # 16 MB chunked resumable upload with exponential backoff retry
│
├── downloads/               # Temporary video files (deleted automatically after upload)
└── tokens/                  # YouTube OAuth token (persisted across restarts)
```

### Processing Flow

```
User forwards a video message
         │
         ▼
handlers.py extracts video info (file_id / file_size / caption)
         │
         ├─ File size check (>1.5 GB → rejected)
         │
         ├─ downloader.py downloads the video
         │    ≤ 20 MB → Telegram Bot API download
         │    > 20 MB → httpx streaming from Telegram CDN, progress every 10 MB
         │
         ├─ Generate metadata from message content
         │    title       = first 20 chars of caption (fallback: "Uploaded Video")
         │    description = full caption text
         │
         ├─ uploader.py uploads to YouTube (private)
         │    POST to initiate resumable upload session
         │    PUT 16 MB chunks: 308 → continue / 200·201 → done / 5xx → retry
         │    Network interruption → query offset → resume
         │
         ├─ Reply with YouTube link
         │
         └─ finally: delete local temp file
```

## Prerequisites

### 1. Telegram Bot Token

Talk to [@BotFather](https://t.me/BotFather) on Telegram, create a bot, and copy the token.

### 2. Google Cloud Setup (one-time)

1. Go to [Google Cloud Console](https://console.cloud.google.com) and create a new project
2. **APIs & Services → Library** → search for and enable **YouTube Data API v3**
3. **APIs & Services → OAuth consent screen**
   - User Type: External
   - Add scope: `https://www.googleapis.com/auth/youtube.upload`
   - Add your Google account as a test user
4. **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
   - Application type: **Desktop app**
   - Download the JSON file, rename it to `client_secrets.json`, and place it in the project root

### 3. YouTube OAuth Authorization (one-time, requires a browser)

Since servers typically have no browser, run the authorization **on your local machine**:

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in TELEGRAM_BOT_TOKEN and other values
python main.py --auth       # opens browser, saves tokens/youtube_token.json
```

## Local Testing

### Step-by-step

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment variables
cp .env.example .env
# Edit .env and fill in TELEGRAM_BOT_TOKEN (other values can stay as defaults)

# 3. Place the Google OAuth config
# Put client_secrets.json (downloaded from Google Cloud Console) in the project root

# 4. YouTube authorization (browser will open automatically)
python main.py --auth
# Generates tokens/youtube_token.json

# 5. Start the bot
python main.py
```

### Verification

Once the bot is running, send or forward a video message to it in Telegram:

- The terminal will show processing logs
- Telegram will show real-time progress updates in a single message
- When done, go to **YouTube Studio → Content** and confirm the video is saved as a **private** draft

> **Tip:** Test with a small file first. Local upload speed is limited by your home internet upload bandwidth. A small video (tens of MB) is enough to verify the full pipeline before trying large files.

### Re-authorize if token expires

```bash
rm tokens/youtube_token.json
python main.py --auth
```

## Docker Deployment

```bash
# 1. Upload the locally generated token to the server
scp tokens/youtube_token.json user@server:/path/to/my-forward-bot/tokens/
scp client_secrets.json       user@server:/path/to/my-forward-bot/

# 2. Create .env on the server
cp .env.example .env
# Edit .env and fill in at least TELEGRAM_BOT_TOKEN

# 3. Build and start
docker compose up -d --build

# 4. View logs
docker compose logs -f bot
```

## Environment Variables

Copy `.env.example` to `.env` and fill in the values:

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token (required) | — |
| `GOOGLE_CLIENT_SECRETS_FILE` | Path to OAuth client secrets file | `client_secrets.json` |
| `GOOGLE_TOKEN_FILE` | Path where OAuth token is saved | `tokens/youtube_token.json` |
| `DOWNLOAD_DIR` | Temporary video download directory | `downloads` |
| `MAX_FILE_SIZE` | Maximum file size in bytes | `1717986918` (1.6 GB) |
| `DOWNLOAD_PROGRESS_CHUNK` | Download progress update interval in bytes | `10485760` (10 MB) |
| `TELEGRAM_DIRECT_DOWNLOAD_THRESHOLD` | Files above this size stream from CDN (bytes) | `20971520` (20 MB) |

## Usage

Once the bot is running, in Telegram:

1. Send a video file directly to the bot, or forward a message containing a video
2. The message text becomes the YouTube description; the first 20 characters become the title
3. The bot updates its status message in real time
4. When complete, it replies with the YouTube link (video is private — publish manually in YouTube Studio)

**Example:**

Message text: `Family reunion 2024, everyone made it this year...`

YouTube title: `Family reunion 2024, e`
YouTube description: `Family reunion 2024, everyone made it this year...` (full text)
