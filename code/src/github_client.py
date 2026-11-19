import os
import time
import jwt
import requests
from pathlib import Path
from dotenv import load_dotenv
import subprocess
import tempfile
import base64
from contextlib import contextmanager

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

APP_ID = os.environ["GITHUB_APP_ID"]
PRIVATE_KEY_PATH = os.getenv("GITHUB_PRIVATE_KEY_PATH")
PRIVATE_KEY_BASE64 = os.getenv("GITHUB_PRIVATE_KEY_BASE64")

def load_private_key() -> str:
    """Load the GitHub App private key from env or local file."""

    if PRIVATE_KEY_BASE64:
        return base64.b64decode(
            PRIVATE_KEY_BASE64,
            validate=True
        ).decode("utf-8")

    if PRIVATE_KEY_PATH:
        return Path(PRIVATE_KEY_PATH).read_text(
            encoding="utf-8"
        )

    raise RuntimeError(
        "GitHub private key not configured."
    )


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
            "Accept": "application/vnd.github.diff",  # raw diff MIME type
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.text

def post_pr_comment(owner: str, repo: str, pr_number: int, installation_id: int, body: str) -> dict:
    """Post a comment on a pull request"""
    token = get_installation_token(installation_id)
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={'body': body},
        timeout=30
    )
    response.raise_for_status()
    return response.json()

def clone_repo_shallow(owner: str, repo: str, installation_id: str, target_dir: Path):
    """Shallow-clone a repo for RAG context. Use installation token for private repos."""
    token = get_installation_token(installation_id)
    clone_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"

    if target_dir.exists():
        # Pull latest instead of recloning
        subprocess.run(["git", "-C", str(target_dir), "fetch", "--depth=1"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(target_dir), "reset", "--hard", "origin/HEAD"], check=True, capture_output=True)
    else:
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth=1", clone_url, str(target_dir)],
            check=True, capture_output=True,
        )
    return target_dir

@contextmanager
def ephemeral_clone(owner: str, repo: str, installation_id: int):
    """Clone temporarily, authenticate securely, and clean up."""

    with tempfile.TemporaryDirectory(
        prefix="GitCriticAI_clone_"
    ) as temp_dir:

        clone_path = Path(temp_dir) / "repo"

        token = get_installation_token(installation_id)

        # Prepare GitHub HTTP Basic authentication
        credentials = base64.b64encode(
            f"x-access-token:{token}".encode()
        ).decode()

        # Pass authentication through Git environment configuration
        # rather than embedding credentials in the clone URL.
        env = os.environ.copy()

        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = (
            "http.https://github.com/.extraheader"
        )
        env["GIT_CONFIG_VALUE_0"] = (
            f"Authorization: Basic {credentials}"
        )

        clone_url = f"https://github.com/{owner}/{repo}.git"

        subprocess.run(
            [
                "git", "clone",
                "--depth=1",
                clone_url,
                str(clone_path)
            ],
            check=True,
            capture_output=True,
            timeout=120,
            env=env
        )

        yield clone_path

    # TemporaryDirectory automatically cleans up here.







