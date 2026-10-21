---
name: data-and-evaluation
description: "Use when the task needs Data and evaluation engineering. Current practice as of 2026-10-21, with sources."
metadata:
  updated: 2026-10-21
  source: Agent HQ (github.com/PRIBINKBENNY/agent-hq), office/skills/data-and-evaluation.md
---

# Data and evaluation engineering

- A dataset is a product: a README (what, where from, licence, consent, known gaps), a schema, a version (DVC or a
  tagged parquet), a held-out split nobody trains on, and a datasheet-style card. Without these it is a folder.
- Labelling: write the guideline before the first label; measure agreement on 50 items with two labellers (or two
  model passes plus a human check); fix the guideline, then scale. Label Studio and CVAT are free.
- Evaluation harness shape: tasks in a file, a runner that is deterministic given seeds, scoring by code (regex,
  exact match, metric) before any LLM-as-judge; judge prompts versioned and spot-checked against humans on 30 items.
- Report: mean and standard deviation over 3 or more seeds, sample sizes, the exact model id and date, failure
  examples. One number without its spread is not a result.
- LLM agents: score the trajectory (right tools, no forbidden tools, no unbacked claims), not only the final text;
  Inspect AI (MIT, UK AISI) and lm-evaluation-harness are the open standards; Promptfoo for prompt regression.
- Robot learning data: LeRobot format (episodes, frames, actions, timestamps), sim and real kept apart and labelled,
  camera calibration stored with the data.
- Drift: re-run the same eval weekly; a drop beyond one standard deviation is an incident with a task, not a shrug.
- Privacy: minimise, pseudonymise, record the lawful basis; raw personal data never leaves the machine it was
  collected on without consent.

Studio and CVAT guides; the office's eval harness.

## Sources

Datasheets for Datasets (Gebru et al.); Inspect AI and lm-eval-harness docs; LeRobot dataset docs; Label
