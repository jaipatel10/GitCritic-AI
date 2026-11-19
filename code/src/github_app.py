import os
import hmac
import hashlib
import json
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, Header, BackgroundTasks
import uvicorn
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

from github_client import fetch_pr_diff, post_pr_comment, clone_repo_shallow, ephemeral_clone
from review_pr import Review, review_diff_with_context

app = FastAPI(title='GitCriticAI Github App')

WEBHOOK_SECRET = os.environ["GITHUB_WEBHOOK_SECRET"]
APP_ID   = os.environ["GITHUB_APP_ID"]
LOG_DIR = PROJECT_ROOT / "logs"
PROCESSED_DELIEVERIES_FILE = LOG_DIR / "processed_deliveries.json"
LAST_SHA_FILE = LOG_DIR / "last_reviewed_sha.json"

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

def load_processed() -> set:
    if PROCESSED_DELIEVERIES_FILE.exists():
        return set(json.loads(PROCESSED_DELIEVERIES_FILE.read_text()))
    return set()

def mark_processed(delivery_id: str):
    processed = load_processed()
    processed.add(delivery_id)
    PROCESSED_DELIEVERIES_FILE.parent.mkdir(exist_ok=True)
    PROCESSED_DELIEVERIES_FILE.write_text(json.dumps(list(processed)))

def already_reviewed_sha(repo: str, pr_number: int, sha: str) -> bool:
    data = json.loads(LAST_SHA_FILE.read_text()) if LAST_SHA_FILE.exists() else {}
    key = f'{repo}#{pr_number}'
    return data.get(key) == sha

def mark_sha_reviewed(repo: str, pr_number: int, sha: str):
    data = json.loads(LAST_SHA_FILE.read_text()) if LAST_SHA_FILE.exists() else {}
    data[f'{repo}#{pr_number}'] = sha
    LAST_SHA_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_SHA_FILE.write_text(json.dumps(data))


@app.get('/')
def health():
    """Simple health check."""
    return {'status': 'ok', 'app': 'GitCriticAI'}



def process_pr_review(
    delivery_id: str,
    owner: str,
    repo: str,
    pr_number: int,
    installation_id: int,
    repo_full_name: str,
    head_sha: str,
):
    """Clone, review and comment in a background thread."""
    # Step 1: Fetch PR diff
    try:
        diff_text = fetch_pr_diff(
            owner, repo, pr_number, installation_id
        )
        print(f"[{delivery_id}] Got diff: {len(diff_text)} chars")
    except Exception as e:
        print(f"[{delivery_id}] Failed to fetch diff: {e}")
        return

    # Step 2: Try reviewing with RAG
    clone_succeeded = False
    try:
        with ephemeral_clone(
            owner, repo, installation_id
        ) as codebase_path:
            clone_succeeded = True
            print(f"[{delivery_id}] Clone: {codebase_path}")
            review = review_diff_with_context(
                diff_text,
                codebase_path=codebase_path
            )
            print(
                f"[{delivery_id}] Review complete: "
                f"{len(review.findings)} findings"
            )
        print(f"[{delivery_id}] Temporary clone cleaned up")
    except Exception as e:
        print(f"[{delivery_id}] Clone/RAG review failed: {e}")
        if clone_succeeded:
            # Clone was successful, so don't blindly retry Claude.
            try:
                post_pr_comment(
                    owner, repo, pr_number, installation_id,
                    "⚠️ CriticAI encountered a review error."
                )
            except Exception as comment_error:
                print(f"Error comment failed: {comment_error}")
            return
        # Step 3: Fall back if cloning failed
        print(f"[{delivery_id}] Retrying without RAG...")
        try:
            review = review_diff_with_context(
                diff_text,
                codebase_path=None
            )
        except Exception as review_error:
            print(f"[{delivery_id}] Fallback failed: {review_error}")
            try:
                post_pr_comment(
                    owner, repo, pr_number, installation_id,
                    "⚠️ CriticAI encountered a review error."
                )
            except Exception as comment_error:
                print(f"Error comment failed: {comment_error}")
            return

    # Step 4: Format and post the review
    comment_body = format_review_as_markdown(review)
    try:
        post_pr_comment(
            owner, repo, pr_number,
            installation_id, comment_body
        )
        print(f"[{delivery_id}] Comment posted")

    except Exception as e:
        print(f"[{delivery_id}] Failed to post comment: {e}")
        return

    # Step 5: Save processed state
    try:
        mark_sha_reviewed(repo_full_name, pr_number, head_sha)
        mark_processed(delivery_id)
        print(f"[{delivery_id}] Review state saved")
    except Exception as e:
        print(f"[{delivery_id}] State save failed: {e}")


@app.post('/webhook')
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: Optional[str] = Header(None),
    x_github_signature_256: Optional[str] = Header(
        None,
        alias="X-Hub-Signature-256"
    ),
    x_github_delivery: Optional[str] = Header(None)
):
    """Receive Github webhooks"""
    body = await request.body()

     # Fast path: signature + dedup + enqueue
    if not verify_webhook_signature(body, x_github_signature_256):
        print(f'[{x_github_delivery}] Invalid signature - rejecting')
        raise HTTPException(status_code=401, detail='Invalid signature')

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Parse payload
    payload = json.loads(body)
    event = x_github_event
    delivery_id = x_github_delivery

    # Check if already processed
    processed = load_processed()
    if delivery_id in processed:
        print(f'[{delivery_id}] Already processed, skipping')
        return {'status': 'duplicate'}

    print(f'[{delivery_id}] Received {event} event')

    # Handle PR events only
    if event == 'pull_request':
        action = payload.get("action")
        if action not in ('opened', 'synchronize'):
            return {'status': 'ignored', 'action': action}

        pr_number = payload["pull_request"]["number"]
        repo_full_name = payload["repository"]["full_name"]
        owner = payload["repository"]["owner"]["login"]
        repo = payload["repository"]["name"]
        installation_id = payload["installation"]["id"]
        head_sha = payload['pull_request']['head']['sha']

        # Check if SHA is already processed
        if already_reviewed_sha(repo_full_name, pr_number, head_sha):
            print(f'[{delivery_id}] Already reviewed SHA {head_sha[:8]}, skipping')
            return {'status': 'duplicate_sha'}

        print(f"[{delivery_id}] PR #{pr_number} on {repo_full_name}: {action}")

        # Enqueue the heavy work — returns immediately
        background_tasks.add_task(
            process_pr_review,
            delivery_id, owner, repo, pr_number, installation_id,
            repo_full_name, head_sha,
        )
        print(f"[{delivery_id}] Queued review for PR #{pr_number}")

    elif event == 'ping':
        # Github sends this when the webhook is first installed
        print(f'[{delivery_id}] webhook ping - connection OK')

    return {'status': 'accepted'}  # ← returns in <200ms


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000)




        