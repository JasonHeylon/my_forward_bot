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
    Interactive OAuth2 authorization flow. Opens a browser for user consent.
    Saves credentials to config.google_token_file on completion.
    Run once with: python main.py --auth
    """
    flow = InstalledAppFlow.from_client_secrets_file(
        str(config.google_client_secrets_file),
        scopes=SCOPES,
    )
    # run_local_server starts a local HTTP server to catch the OAuth redirect
    creds = flow.run_local_server(port=0)
    _save_credentials(creds)
    return creds


def get_credentials() -> Credentials:
    """
    Load saved credentials, refresh if expired, and persist the refreshed token.
    Raises FileNotFoundError if the token file does not exist (run --auth first).
    """
    token_path = config.google_token_file
    if not token_path.exists():
        raise FileNotFoundError(
            f"YouTube token not found: {token_path}\n"
            "Please run: python main.py --auth"
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
