from cmd import PROMPT
import sys
import json
from pathlib import Path
from typing import Literal
from anthropic import Anthropic
from pydantic import BaseModel
from retriever import CodebaseRetriever

# Schema for the claude's response
class Finding(BaseModel):
    severity: str
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

    **You MUST use exactly one of these 4 categories for every finding — no other values are allowed:**
    - "security" — injection, auth bypasses, exposed secrets, unsafe operations
    - "performance" — inefficient algorithms, N+1 queries, memory issues, blocking calls
    - "logic" — edge cases, correctness, error handling, null handling, race conditions
    - "style" — naming, conventions, dead code, missing types, readability

    If a finding feels like "correctness" or "reliability" — use "logic".
    If it feels like "vulnerability" — use "security".
    Never invent new category names.

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


def extract_diff_for_search(diff_text: str, max_chars:int = 500) -> str:
    """Extract just added/modified lines (without +/-) to use as a search query"""
    changed_lines = []
    for line in diff_text.split('\n'):
        if line.startswith('+') and not line.startswith('+++'):
            changed_lines.append(line[1:])
    return '\n'.join(changed_lines)[:max_chars]

def review_diff_with_context(diff_text: str, codebase_path: Path = None) -> Review:
    context_section = ""

    if codebase_path:
        retriever = CodebaseRetriever(codebase_path)
        search_query = extract_diff_for_search(diff_text)
        relevant = retriever.retrieve(search_query, k=3)

        if relevant:
            context_section = "### Relevant codebase context (existing code for reference):\n\n"
            for chunk in relevant:
                file_short = chunk['file'].split('/')[-1]
                context_section += f"### {file_short}:{chunk['start_line']} — {chunk['name']}\n```python\n{chunk['code'][:500]}\n```\n\n"
    
    PROMPT = f'{context_section}## PR Diff to review:\n\n{diff_text}'
    print(f'Context prompt : {PROMPT}')
    response = client.messages.create(
        model='claude-sonnet-4-5',
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{'role':'user', 'content':PROMPT}]
    )
    text = response.content[0].text.strip()
    # Strip markdown fences if Claude wraps the JSON
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])

    data = json.loads(text)
    review = Review(**data)
    # Normalize categories for consistent scoring
    for finding in review.findings:
        finding.category = normalize_category(finding.category)
    return review


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

def normalize_category(cat: str) -> str:
    """Map any Claude-produced category to one of our 4 standard ones."""
    cat = cat.lower().strip()
    mapping = {
        'correctness': 'logic',
        'bug': 'logic',
        'error': 'logic',
        'reliability': 'logic',
        'maintainability': 'style',
        'readability': 'style',
        'convention': 'style',
        'vulnerability': 'security',
        'injection': 'security',
        'efficiency': 'performance',
        'scalability': 'performance',
    }
    return mapping.get(cat, cat if cat in ['security', 'performance', 'logic', 'style'] else 'logic')

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
    print(f'codebase context: {Path(sys.argv[2])}')

    review = review_diff_with_context(diff_text, codebase_path=Path(sys.argv[2])) 
    print(format_review(review))

    # Print Cost
    # (cost estimation — adjust based on current pricing)
    print(f'\n [Debug] Findings: {len(review.findings)}', file=sys.stderr)

if __name__ == "__main__":
    main()

    




