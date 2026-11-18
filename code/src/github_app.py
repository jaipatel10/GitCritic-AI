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
from review_pr import Review

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

def format_review_as_markdown(review: Review) -> str:
    """Convert a review object to github flavored markdown"""
    severity_emoji = {
        "critical": "🚨",
        "high": "⚠️",
        "medium": "💡",
        "low": "ℹ️",
    }
    body = ['## GitCriticAI Review', '', f'> {review.summary}', '']

    if not review.findings:
        body.append('No issues found. LGTM ✅')
        return '\n'.join(body)

    # Group by severity
    severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    sorted_findings = sorted(review.findings, key=lambda f: severity_order[f.severity])

    body.append(f'**Found {len(sorted_findings)} issue(s):**\n')

    for f in sorted_findings:
        emoji = severity_emoji.get(f.severity, "•")
        body.append(f'### {emoji} {f.severity.upper()} - {f.category}')
        body.append(f'**{f.file}:{f.line}** - {f.message}')
        body.append(f'\n{f.rationale}\n')

    body.append('---')
    body.append("_Reviewed by [CriticAI](https://github.com/jaipatel10/GitCritic-AI). React with 👍/👎 to help improve._")

    return '\n'.join(body)


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
    if event == 'pull_request':
        action = payload.get("action")
        pr_number = payload["pull_request"]["number"]
        repo_full_name = payload["repository"]["full_name"]
        owner = payload["repository"]["owner"]["login"]
        repo = payload["repository"]["name"]
        installation_id = payload["installation"]["id"]
        
        print(f"[{delivery_id}] PR #{pr_number} on {repo_full_name}: {action}")

        # Only react to opened/synchronize (new commits pushed)
        if action in ('opened', 'synchronize'):
            print(f'[{delivery_id}] Fetching diff...')
            try:
                diff_text = fetch_pr_diff(owner, repo, pr_number, installation_id)
                print(f"[{delivery_id}] Got diff: {len(diff_text)} chars")

                # Run CriticAI review
                print(f"[{delivery_id}] Running review...")
                review = review_diff_with_context(diff_text, codebase_path=None)
                print(f"[{delivery_id}] Review complete: {len(review.findings)} findings")

                # Format as markdown
                comment_body = format_review_as_markdown(review)

                # Post to PR
                print(f"[{delivery_id}] Posting comment to PR #{pr_number}...")
                post_pr_comment(owner, repo, pr_number, installation_id, comment_body)
                print(f"[{delivery_id}] ✓ Comment posted")
            except Exception as e:
                print(f'[{delivery_id}] Error: {e}')
                import traceback
                traceback.print_exc()

    elif event == 'ping':
        # Github sends this when the webhook is first installed
        print(f'[{delivery_id}] webhook ping - connection OK')

    return {'status': 'received', 'event': event}


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000)




        