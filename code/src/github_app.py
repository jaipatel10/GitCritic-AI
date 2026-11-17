from optparse import Option
import os
import hmac
import hashlib
import json
from ssl import VERIFY_ALLOW_PROXY_CERTS
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, Header
import uvicorn
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

from github_client import fetch_pr_diff

app = FastAPI(title='GitCriticAI Github App')

WEBHOOK_SECRET = os.environ["GITHUB_WEBHOOK_SECRET"]
APP_ID   = os.environ["GITHUB_APP_ID"]

def verify_webhook_signature(payload_body: bytes, signature_header: str) -> bool:
    """Verify that webhook came from Github using the shared secret."""
    if not signature_header:
        return False
    if not signature_header.startswith('sha256='):
        return False
    
    expected_signature = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(),
        payload_body,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature_header)

@app.get('/')
def health():
    """Simple health check."""
    return {'status': 'ok', 'app': 'GitCriticAI'}


@app.post('/webhook')
async def webhook(
    request: Request,
    x_github_event: Optional[str] = Header(None),
    x_github_signature_256: Optional[str] = Header(
        None,
        alias="X-Hub-Signature-256"
    ),
    x_github_delivery: Optional[str] = Header(None)
):
    """Receive Github webhooks"""
    body = await request.body()

    if not verify_webhook_signature(body, x_github_signature_256):
        print(f'[{x_github_delivery}] Invalid signature - rejecting')
        raise HTTPException(status_code=401, detail='Invalid signature')

    # Parse payload
    payload = json.loads(body)
    event = x_github_event
    delivery_id = x_github_delivery

    print(f'[{delivery_id}] Received {event} event')

    Path("logs").mkdir(exist_ok=True)

    # Handle PR events only
    if event == "pull_request":
        action = payload.get("action")
        pr_number = payload["pull_request"]["number"]
        repo_full_name = payload["repository"]["full_name"]
        owner = payload["repository"]["owner"]["login"]
        repo = payload["repository"]["name"]
        installation_id = payload["installation"]["id"]
        
        print(f"[{delivery_id}] PR #{pr_number} on {repo_full_name}: {action}")
        
        if action in ("opened", "synchronize"):
            print(f"[{delivery_id}] Fetching diff from GitHub API...")
            try:
                diff_text = fetch_pr_diff(owner, repo, pr_number, installation_id)
                print(f"[{delivery_id}] Got diff: {len(diff_text)} chars, {diff_text.count(chr(10))} lines")
                
                # Save to disk for debugging
                diff_file = Path(f"logs/{delivery_id}.diff")
                diff_file.write_text(diff_text)
                print(f"[{delivery_id}] Saved to {diff_file}")
            except requests.HTTPError as e:
                print(f"[{delivery_id}] GitHub API error: {e.response.status_code} - {e.response.text}")
            except Exception as e:
                print(f"[{delivery_id}] Error fetching diff: {e}")
    elif event == 'ping':
        # Github sends this when the webhook is first installed
        print(f'[{delivery_id}] webhook ping - connection OK')

    return {'status': 'received', 'event': event}


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000)




        