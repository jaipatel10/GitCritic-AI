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

## Update on the development :

What’s now built (single-agent + RAG retrieval)
Current limitations (“RAG shows marginal value on simple diffs — harder evals coming next”)# Testing Day 2
Current limitations (“RAG shows marginal value on simple diffs — harder evals coming next”)# Test

# Test Tue Nov 17 15:51:01 +04 2026
# Test Tue Nov 17 15:56:57 +04 2026
