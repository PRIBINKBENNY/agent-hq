---
name: ai-agent-engineering
description: "Use when the task needs Building AI agents in production. Current practice as of 2026-10-18, with sources."
metadata:
  updated: 2026-10-18
  source: Agent HQ (github.com/PRIBINKBENNY/agent-hq), office/skills/ai-agent-engineering.md
---

# Building AI agents in production

- Guardrails belong at the tool layer: authorise every action where it executes, not only in the final text. Irreversible
  or outward actions (send, post, pay, trade, delete) need human approval. This office already works that way: keep it.
- Least privilege: each agent gets only the tools its job needs; read-only where read is enough (OWASP "excessive agency").
- MCP is a transport, not a security model: servers still need auth, input validation, rate limits, an owner and a version.
- Evaluate trajectories, not just final answers: did it choose the right tools in the right order and reach the outcome?
  Start from real traces, then build a small golden set from real tasks (dozens of cases) and re-run it on every change.
- Roll out gradually: read-only first, then actions behind approval once evals, logs and rollback are proven.
- Keep agents small: one job, a short brief, explicit stop conditions, a tool-call budget, structured handoffs.
- Observability: log every model call, tool call, cost and latency (this office: events.jsonl, ops_metrics, usage_report).
- Free stack for clients: OpenAI-compatible APIs (Groq, Gemini, Ollama local), MCP for tools, SQLite/pgvector for memory.

(agents 2026: tools, memory, evals, guardrails), c-sharpcorner.com (OpenAI Agents SDK approvals, tracing, evals).

## Sources

O'Reilly "The AI Agents Stack (2026 Edition)", foojay.io (agents, subagents, skills and MCP), andriifurmanets.com
