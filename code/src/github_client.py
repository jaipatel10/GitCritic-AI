import os
import time
import jwt
import requests
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

APP_ID = os.environ["GITHUB_APP_ID"]
PRIVATE_KEY_PATH = os.environ["GITHUB_PRIVATE_KEY_PATH"]

def load_private_key() -> str:
    """Load the GitHub App's private key from disk."""
    return Path(PRIVATE_KEY_PATH).read_text()

def generate_app_jwt() -> str:
    """Generate a short-lived JWT for GitHub App auth. Valid 10 minutes max."""
    now = int(time.time())
    payload = {
        "iat": now - 60,                   # backdate to allow clock skew
        "exp": now + 10 * 60,              # expires in 10 minutes
        "iss": APP_ID,                     # issuer = this GitHub App
    }
    return jwt.encode(payload, load_private_key(), algorithm="RS256")

def get_installation_token(installation_id: int) -> str:
    """Exchange the app JWT for a short-lived installation access token."""
    app_jwt = generate_app_jwt()
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["token"]

def fetch_pr_diff(owner: str, repo: str, pr_number: int, installation_id: int) -> str:
    """Fetch the raw unified diff of a pull request."""
    token = get_installation_token(installation_id)
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    response = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3.diff",  # raw diff MIME type
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.text