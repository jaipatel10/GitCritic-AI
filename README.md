# GitCriticAI

> Multi-agent AI code reviewer for GitHub. Four specialized agents (security, 
> performance, logic, style) review your PRs in parallel. A synthesizer 
> produces a single ranked comment.

**Status:** Architecture design (Nov 2026). Build starts Week 12 of my 
Applied AI Engineer learning journey.

## Why

Code review eats 20-40% of senior engineering time. Existing AI tools 
(CodeRabbit, Copilot) give generic feedback. CriticAI uses multi-agent 
debate with specialized perspectives, plus codebase-aware retrieval.

## Architecture

See [docs/architecture.md](docs/architecture.md) and [docs/diagram.png](docs/diagram.png).

## Evals

See [docs/evals.md](docs/evals.md). 50 test PRs, precision/recall per agent, 
cost per review.

## Roadmap

- [x] Architecture design 
- [ ] Single-agent prototype
- [ ] Multi-agent orchestration 
- [ ] Eval dataset + metrics 
- [ ] GitHub app integration 
- [ ] Public launch + blog post

## Tech stack

- Backend: FastAPI (Python)
- LLM: Claude (Anthropic) for reasoning, embeddings for retrieval
- Vector DB: pgvector
- GitHub: App via Octokit
- Hosting: Railway

Built as part of transitioning from Android engineering to Applied AI.

## Privacy & Security

GitCriticAI clones your repository only for the duration of a single PR review, 
then permanently deletes it. Nothing is persisted on GitCriticAI's servers between 
reviews — not source code, not embeddings, nothing.

**Implementation:**
- Shallow clone (latest commit only) into a per-review temp directory
- Vector embeddings generated in-memory (ChromaDB ephemeral mode)
- Clone + embeddings deleted immediately after review posts
- Only logs retained: webhook delivery IDs (for dedup) and commit SHAs (for 
  dedup) — no source code

**Scope of access:** GitCriticAI requires read access to your code (to review it) 
and write access to pull requests (to post comments). It has no access to 
repository secrets, actions, or deployment settings.

### Verification

The ephemeral cleanup is verified at each PR review:
1. The app logs "Temporary clone cleaned up" after each review
2. Post-review filesystem inspection shows no artifacts:
   - No GitCriticAI_clone_* directories in system temp folders
   - No persistent repos/ or chroma_db/ directories in the app folder

## Update on the development :

What’s now built (single-agent + RAG retrieval)
Current limitations (“RAG shows marginal value on simple diffs — harder evals coming next”)# Testing Day 2
Current limitations (“RAG shows marginal value on simple diffs — harder evals coming next”)# Test

# Test Tue Nov 17 15:51:01 +04 2026
# Test Tue Nov 17 15:56:57 +04 2026
# Change 16:03
