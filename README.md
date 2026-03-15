# my-forward-bot

Telegram 转发视频 → 自动上传 YouTube 私密草稿的 Bot。

转发任意含视频的 Telegram 消息给 Bot，它会自动下载视频，以消息内容前 20 字为标题、完整内容为描述，上传至 YouTube 并保存为**私密（未发布）**状态，最后回复 YouTube 链接。

## 功能特性

- 支持转发的视频消息（video、document 类视频文件、video_note）
- 自动以 Telegram 消息内容生成 YouTube 标题和描述
- 支持大文件（200MB ～ 1.5GB），流式下载不占内存
- YouTube 断点续传上传，网络中断后自动恢复
- 上传全程在 Telegram 中实时显示进度
- 上传完成后自动删除服务器临时文件
- 支持 Docker 部署

## 项目架构

```
my-forward-bot/
├── main.py                  # 入口，注册消息处理器，支持 --auth 参数
├── config.py                # 配置管理，启动时校验所有必填环境变量
├── requirements.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
│
├── bot/
│   ├── handlers.py          # 核心流程：提取视频 → 下载 → 上传 → 回复
│   ├── downloader.py        # 视频下载（≤20MB 走 API；>20MB 流式 CDN）
│   └── progress.py          # 限速进度消息（原地编辑，3s 最小间隔）
│
├── youtube/
│   ├── auth.py              # OAuth2 授权、Token 持久化与自动刷新
│   └── uploader.py          # 16MB 分块断点续传上传，指数退避重试
│
├── downloads/               # 临时视频文件（上传后自动删除）
└── tokens/                  # YouTube OAuth Token（持久化）
```

### 处理流程

```
用户转发视频消息
       │
       ▼
handlers.py 提取视频信息（file_id / file_size / caption）
       │
       ├─ 文件大小校验（>1.5GB 拒绝）
       │
       ├─ downloader.py 下载视频
       │    ≤ 20MB → Telegram Bot API 直接下载
       │    > 20MB → httpx 流式下载 Telegram CDN，每 10MB 更新进度
       │
       ├─ 生成元数据
       │    标题 = caption 前 20 字（无 caption 则"上传的视频"）
       │    描述 = caption 完整内容
       │
       ├─ uploader.py 上传至 YouTube（私密）
       │    POST 发起断点续传会话
       │    PUT 16MB 分块上传，308 继续 / 200·201 完成 / 5xx 重试
       │    网络中断 → 查询断点 → 续传
       │
       ├─ 回复 YouTube 链接
       │
       └─ finally: 删除本地临时文件
```

## 部署前准备

### 1. Telegram Bot Token

在 Telegram 中找 [@BotFather](https://t.me/BotFather)，创建 Bot 并获取 Token。

### 2. Google Cloud 配置（一次性）

1. 进入 [Google Cloud Console](https://console.cloud.google.com)，创建新项目
2. **APIs & Services → Library** → 搜索并启用 **YouTube Data API v3**
3. **APIs & Services → OAuth consent screen**
   - User Type：External
   - 添加 Scope：`https://www.googleapis.com/auth/youtube.upload`
   - 将自己的 Google 账号加入「测试用户」
4. **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
   - Application type：**Desktop app**
   - 下载 JSON 文件，重命名为 `client_secrets.json`，放到项目根目录

### 3. YouTube OAuth 授权（一次性，需要浏览器）

由于服务器通常没有浏览器，**在本地机器**执行授权：

```bash
# 本地执行
pip install -r requirements.txt
cp .env.example .env       # 填写 TELEGRAM_BOT_TOKEN 等配置
python main.py --auth      # 浏览器授权，生成 tokens/youtube_token.json
```

## 本地测试

### 完整步骤

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 TELEGRAM_BOT_TOKEN（其他项保持默认即可）

# 3. 放置 Google OAuth 配置
# 将从 Google Cloud Console 下载的文件放到项目根目录，命名为 client_secrets.json

# 4. YouTube 授权（浏览器会自动打开）
python main.py --auth
# 授权完成后生成 tokens/youtube_token.json

# 5. 启动 Bot
python main.py
```

### 测试验证

Bot 启动后，在 Telegram 中给 Bot 发一个视频（或转发含视频的消息）：

- 终端会输出处理日志
- Telegram 中会看到进度消息实时更新
- 完成后进入 YouTube Studio → 内容，确认视频以**私密**状态上传成功

> **建议先用小文件测试**：本地上行带宽有限，1GB 视频上传会很慢。建议先用几十 MB 的小视频验证整个流程，确认无误后再测试大文件。

### Token 失效时重新授权

```bash
rm tokens/youtube_token.json
python main.py --auth
```

## Docker 部署

```bash
# 1. 将本地生成的 token 上传到服务器
scp tokens/youtube_token.json user@server:/path/to/my-forward-bot/tokens/
scp client_secrets.json    user@server:/path/to/my-forward-bot/

# 2. 在服务器上创建 .env
cp .env.example .env
# 编辑 .env，至少填写 TELEGRAM_BOT_TOKEN

# 3. 构建并启动
docker compose up -d --build

# 4. 查看日志
docker compose logs -f bot
```

## 环境变量说明

复制 `.env.example` 为 `.env` 并填写：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token（必填） | — |
| `GOOGLE_CLIENT_SECRETS_FILE` | OAuth 客户端配置文件路径 | `client_secrets.json` |
| `GOOGLE_TOKEN_FILE` | OAuth Token 保存路径 | `tokens/youtube_token.json` |
| `DOWNLOAD_DIR` | 临时视频下载目录 | `downloads` |
| `MAX_FILE_SIZE` | 最大文件大小（字节） | `1717986918`（1.6GB） |
| `DOWNLOAD_PROGRESS_CHUNK` | 下载进度更新间隔（字节） | `10485760`（10MB） |
| `TELEGRAM_DIRECT_DOWNLOAD_THRESHOLD` | 超过此大小改用 CDN 下载（字节） | `20971520`（20MB） |

## 使用方式

Bot 启动后，在 Telegram 中：

1. 直接发送视频文件给 Bot，或转发含视频的消息
2. 消息的文字内容会作为 YouTube 描述，前 20 字作为标题
3. Bot 会实时更新处理进度
4. 完成后回复 YouTube 链接（视频为私密状态，需在 YouTube Studio 手动发布）

**示例：**

转发消息内容：`2024年春节家庭聚会，今年人到得特别齐...`

YouTube 标题：`2024年春节家庭聚会，今年人`
YouTube 描述：`2024年春节家庭聚会，今年人到得特别齐...`（完整内容）
