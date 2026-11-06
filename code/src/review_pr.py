import sys
import json
from pathlib import Path
from typing import Literal
from anthropic import Anthropic
from pydantic import BaseModel

# Schema for the claude's response
class Finding(BaseModel):
    severity: Literal['low', 'medium', 'high', 'critical']
    file: str
    line: int
    category: Literal['security', 'performance', 'logic', 'style']
    message: str
    rationale: str

class Review(BaseModel):
    findings: list[Finding]
    summary: str

client = Anthropic()

SYSTEM_PROMPT = """You are a senior software engineer reviewing a pull request.
    Analyze the diff and return findings in strict JSON format.

    Focus on real issues, not nitpicks:
    - Security: injection, auth bypasses, exposed secrets, unsafe deserialization
    - Performance: inefficient algorithms, N+1 queries, memory issues
    - Logic: edge cases, null handling, correctness, missing tests
    - Style: naming, conventions, dead code, missing types

    For each finding, assign a severity (low/medium/high/critical) and category.
    Only report issues you are confident about. False positives waste engineer time.

    Return ONLY valid JSON matching this structure (no markdown fences):
    {
    "findings": [
        {
        "severity": "high",
        "file": "path/to/file.py",
        "line": 42,
        "category": "security",
        "message": "Short actionable message",
        "rationale": "Why this is a problem"
        }
    ],
    "summary": "Overall 2-3 sentence assessment of this PR"
    }

    If the PR has no issues worth flagging, return an empty findings array."""

def review_diff(diff_text: str) -> Review:
    response = client.messages.create(
        model='claude-sonnet-4-5',
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{'role':'user', 'content':f'Review this PR diff:\n\n{diff_text}'}]
    )
    text = response.content[0].text.strip()
    # Strip markdown fences if Claude wraps the JSON
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])

    data = json.loads(text)
    return Review(**data)

def format_review(review: Review) -> str:
    """Format review as human readable format"""
    output = [f'=====Summary======\n{review.summary}\n']

    if not review.findings:
        output.append('No issues found. LGTM')
        return '\n'.join(output)

    # Sort findings by severity
    severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    sorted_findings = sorted(review.findings, key=lambda f: severity_order[f.severity])

    output.append(f'===== Findings ({len(sorted_findings)}) ======')
    for f in sorted_findings:
        output.append(f'\n[{f.severity.upper():<8}] {f.category:<12} {f.file}:{f.line}')
        output.append(f' {f.message}')
        output.append(f' Why: {f.rationale}')

    return '\n'.join(output)

def main():
    if len(sys.argv) < 2:
        print(f'Usage: python review_pr.py <path-to-diff-file>')
        sys.exit(1)
    
    diff_path = Path(sys.argv[1])
    if not diff_path.exists():
        print(f'File not found: {diff_path}')
        sys.exit(1)

    diff_text = diff_path.read_text()
    print(f'Reviewing {diff_path.name} ({len(diff_text)} chars)...', file=sys.stderr)

    review = review_diff(diff_text)
    print(format_review(review))

    # Print Cost
    # (cost estimation — adjust based on current pricing)
    print(f'\n [Debug] Findings: {len(review.findings)}', file=sys.stderr)

if __name__ == "__main__":
    main()

    




