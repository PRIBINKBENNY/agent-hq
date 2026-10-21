---
name: safety-engineering
description: "Use when the task needs Safety engineering for agents and robots. Current practice as of 2026-10-21, with sources."
metadata:
  updated: 2026-10-21
  source: Agent HQ (github.com/PRIBINKBENNY/agent-hq), office/skills/safety-engineering.md
---

# Safety engineering for agents and robots

- Hazard analysis first: list what the system can do in the world (send, pay, move, cut power), who can be harmed,
  how, how likely, how bad; one row per hazard with its control. Review it when a capability is added.
- Controls live below the model: allowlists, approval gates, rate and spend caps, joint and velocity limits, e-stops
  in firmware. A prompt is not a control.
- Red-team the office and every product before release: prompt injection via email, web and files; tool misuse;
  data exfiltration; goal hijack; denial of wallet. garak and Inspect AI have ready-made attack sets; keep the
  office's own cases in a file and rerun them weekly.
- Incident register: date, what happened, impact, root cause, the control added, who verified it. Near misses count.
- Robots: ISO 10218 (industrial) and ISO 13482 (personal care robots) define the expectations; for a lab, the
  practical set is protective stops, speed and force limits, a workspace nobody enters while powered, lockout on
  the supply, and a documented test before every change to control code.
- Assurance case: a one-page argument that the system is acceptably safe for its use, with evidence links (tests,
  logs, limits). Certifiers and clients read this first.
- Defaults are safety decisions: sim-only on, sending off, demo account, private repo.
- Never trade a gate for speed; if a gate blocks the business, redesign the workflow, not the gate.

UK AISI guidance; the office's own security audit guide.

## Sources

OWASP Top 10 for Agentic Applications (2025); garak and Inspect AI docs; ISO 10218-1 and ISO 13482 overviews;
