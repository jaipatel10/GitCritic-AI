import sys
import json
from pathlib import Path
from typing import Literal

from anthropic import Anthropic
from pydantic import BaseModel
from retriever import CodebaseRetriever


# ----------------------------------------
# 1. Claude response schemas
# ----------------------------------------

class Finding(BaseModel):
    severity: Literal["low", "medium", "high", "critical"]
    file: str
    line: int
    category: Literal["security", "performance", "logic", "style"]
    message: str
    rationale: str


class Review(BaseModel):
    findings: list[Finding]
    summary: str


client = Anthropic()


# ----------------------------------------
# 2. System prompt
# ----------------------------------------

SYSTEM_PROMPT = """
You are a senior software engineer reviewing a pull request.
Analyze the diff and return findings in strict JSON format.

You MUST use exactly one of these four categories:
- "security": injection, auth bypasses, exposed secrets, unsafe operations
- "performance": inefficient algorithms, N+1 queries, memory issues, blocking calls
- "logic": edge cases, correctness, error handling, null handling, race conditions
- "style": naming, conventions, dead code, missing types, readability

If a finding is about correctness or reliability, use "logic".
If it is about a vulnerability, use "security".
Never invent new categories.

Allowed severity values:
- low
- medium
- high
- critical

Only report issues you are confident about.
False positives waste engineer time.

Return ONLY valid JSON matching this structure:

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

If the PR has no issues worth flagging,
return an empty findings array.
"""


# ----------------------------------------
# 3. Normalize Claude's categories
# ----------------------------------------

def normalize_category(cat: str) -> str:
    """Convert known category aliases to our four standard categories."""

    cat = cat.lower().strip()

    mapping = {
        "correctness": "logic",
        "bug": "logic",
        "error": "logic",
        "reliability": "logic",

        "maintainability": "style",
        "readability": "style",
        "convention": "style",

        "vulnerability": "security",
        "injection": "security",

        "efficiency": "performance",
        "scalability": "performance",
    }

    return mapping.get(cat, cat)


# ----------------------------------------
# 4. Parse and validate Claude's response
# ----------------------------------------

def parse_review_response(response) -> Review:
    """Extract text, normalize categories, and validate with Pydantic."""

    if response.stop_reason == "max_tokens":
        raise ValueError(
            "Claude response was truncated. Increase max_tokens."
        )

    text_blocks = [
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ]

    if not text_blocks:
        raise ValueError("Claude returned no text response.")

    text = "\n".join(text_blocks).strip()

    # Remove optional markdown code fences
    if text.startswith("```"):
        lines = text.splitlines()

        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()

    data = json.loads(text)

    # IMPORTANT:
    # Normalize BEFORE Pydantic validation.
    for finding in data["findings"]:
        finding["category"] = normalize_category(
            finding["category"]
        )

    return Review.model_validate(data)


# ----------------------------------------
# 5. Call Claude
# ----------------------------------------

def ask_claude(prompt: str) -> Review:
    """Send a review prompt to Claude and return a validated Review."""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    return parse_review_response(response)


# ----------------------------------------
# 6. Extract search query from PR diff
# ----------------------------------------

def extract_diff_for_search(
    diff_text: str,
    max_chars: int = 500
) -> str:
    """Extract added lines for semantic and BM25 search."""

    changed_lines = []

    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            changed_lines.append(line[1:])

    return "\n".join(changed_lines)[:max_chars]


# ----------------------------------------
# 7. Review PR with optional RAG context
# ----------------------------------------

def review_diff_with_context(
    diff_text: str,
    codebase_path: Path | None = None
) -> Review:

    # No repository available — review diff directly.
    if codebase_path is None:
        return review_diff(diff_text)

    search_query = extract_diff_for_search(diff_text)

    # Build ephemeral index, retrieve, and clean up.
    with CodebaseRetriever(codebase_path) as retriever:
        relevant_chunks = retriever.retrieve(
            query=search_query,
            k=3,
            alpha=0.5,
            max_distance=0.7
        )

    # The Chroma collection has been deleted.
    # Relevant chunks remain available as Python dictionaries.
    context_section = ""

    if relevant_chunks:
        context_section = (
            "## Relevant codebase context "
            "(existing code for reference):\n\n"
        )

        for chunk in relevant_chunks:
            context_section += (
                f"### {chunk['file']}:{chunk['start_line']} "
                f"— {chunk['name']}\n"
                f"```python\n"
                f"{chunk['code'][:500]}\n"
                f"```\n\n"
            )

    print(
        f"[Review] Retrieved {len(relevant_chunks)} "
        f"relevant code chunks"
    )

    prompt = (
        f"{context_section}"
        f"## PR Diff to review:\n\n"
        f"{diff_text}"
    )

    return ask_claude(prompt)


# ----------------------------------------
# 8. Review PR without RAG
# ----------------------------------------

def review_diff(diff_text: str) -> Review:
    """Review PR changes without additional codebase context."""

    prompt = f"Review this PR diff:\n\n{diff_text}"

    return ask_claude(prompt)


# ----------------------------------------
# 9. Format review for terminal
# ----------------------------------------

def format_review(review: Review) -> str:
    """Format review as human-readable text."""

    output = [
        f"===== Summary =====\n{review.summary}\n"
    ]

    if not review.findings:
        output.append("No issues found. LGTM")
        return "\n".join(output)

    severity_order = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3
    }

    sorted_findings = sorted(
        review.findings,
        key=lambda f: severity_order[f.severity]
    )

    output.append(
        f"===== Findings ({len(sorted_findings)}) ====="
    )

    for finding in sorted_findings:
        output.append(
            f"\n[{finding.severity.upper():<8}] "
            f"{finding.category:<12} "
            f"{finding.file}:{finding.line}"
        )

        output.append(f" {finding.message}")
        output.append(f" Why: {finding.rationale}")

    return "\n".join(output)


# ----------------------------------------
# 10. CLI entry point
# ----------------------------------------

def main():
    if len(sys.argv) not in (2, 3):
        print(
            "Usage: python review_pr.py "
            "<path-to-diff-file> [codebase-path]"
        )
        sys.exit(1)

    diff_path = Path(sys.argv[1])

    if not diff_path.is_file():
        print(f"File not found: {diff_path}")
        sys.exit(1)

    diff_text = diff_path.read_text(encoding="utf-8")

    print(
        f"Reviewing {diff_path.name} "
        f"({len(diff_text)} chars)..."
    )

    if len(sys.argv) == 3:
        codebase_path = Path(sys.argv[2])

        review = review_diff_with_context(
            diff_text,
            codebase_path=codebase_path
        )
    else:
        review = review_diff(diff_text)

    print(format_review(review))

    print(
        f"\n[Debug] Findings: {len(review.findings)}",
        file=sys.stderr
    )


if __name__ == "__main__":
    main()
