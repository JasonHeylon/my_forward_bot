import json
from datetime import datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config import config

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def run_oauth_flow() -> Credentials:
    """
    交互式 OAuth2 授权流程，打开浏览器让用户同意授权。
    授权完成后将凭证保存至 config.google_token_file。
    首次运行：python main.py --auth
    """
    flow = InstalledAppFlow.from_client_secrets_file(
        str(config.google_client_secrets_file),
        scopes=SCOPES,
    )
    # run_local_server 会启动本地 HTTP 服务器接收 OAuth 回调
    creds = flow.run_local_server(port=0)
    _save_credentials(creds)
    return creds


def get_credentials() -> Credentials:
    """
    加载已保存的凭证，过期时自动刷新并持久化。
    若 token 文件不存在，抛出 FileNotFoundError（提示用户先运行 --auth）。
    """
    token_path = config.google_token_file
    if not token_path.exists():
        raise FileNotFoundError(
            f"YouTube token 文件不存在：{token_path}\n"
            "请先运行：python main.py --auth"
        )

    creds = _load_credentials(token_path)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_credentials(creds)

    return creds


def _save_credentials(creds: Credentials):
    config.google_token_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }
    config.google_token_file.write_text(json.dumps(data, indent=2))


def _load_credentials(path: Path) -> Credentials:
    data = json.loads(path.read_text())
    expiry = datetime.fromisoformat(data["expiry"]) if data.get("expiry") else None
    return Credentials(
        token=data["token"],
        refresh_token=data["refresh_token"],
        token_uri=data["token_uri"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=data["scopes"],
        expiry=expiry,
    )
