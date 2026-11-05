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

- [x] Architecture design (Nov 2026)
- [ ] Single-agent prototype (Week 12)
- [ ] Multi-agent orchestration (Week 13)
- [ ] Eval dataset + metrics (Week 14)
- [ ] GitHub app integration (Week 15)
- [ ] Public launch + blog post (Week 16)

## Tech stack

- Backend: FastAPI (Python)
- LLM: Claude (Anthropic) for reasoning, embeddings for retrieval
- Vector DB: pgvector
- GitHub: App via Octokit
- Hosting: Railway

Built as part of transitioning from Android engineering to Applied AI.