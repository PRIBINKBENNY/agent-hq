---
name: testing-and-quality
description: "Use when the task needs Testing and quality. Current practice as of 2026-10-18, with sources."
metadata:
  updated: 2026-10-18
  source: Agent HQ (github.com/PRIBINKBENNY/agent-hq), office/skills/testing-and-quality.md
---

# Testing and quality

- Test behaviour, not implementation: one failing test first for every bug, then the fix (debugger), proving it.
- Unit tests deterministic and offline (mock network, time, randomness); a few integration tests for real paths.
- For LLM features: an eval set of real cases with expected outcomes; check tool choice and final result
  (trajectory), track pass rate across changes, never "it looked fine once".
- Coverage is a hint, not a goal; review edge cases (empty input, huge input, unicode, timeouts, rate limits).
- Security checks in review: secrets, injection (SQL, shell, prompt), unsafe deserialisation, missing auth on endpoints.
- A reviewer's verdict names the exact file and line and what would change the decision.

## Sources

industry practice; LLM-specific eval guidance from the AI agent sources in ai-agent-engineering.md.
