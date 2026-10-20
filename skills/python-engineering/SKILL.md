---
name: python-engineering
description: "Use when the task needs Modern Python engineering. Current practice as of 2026-10-18, with sources."
metadata:
  updated: 2026-10-18
  source: Agent HQ (github.com/PRIBINKBENNY/agent-hq), office/skills/python-engineering.md
---

# Modern Python engineering

- One config file: pyproject.toml for metadata and tool settings. src/ layout for packages. Python 3.11+ (3.13 here).
- uv for environments, dependencies, lockfiles and running (uv add, uv add --dev, uv run pytest); commit uv.lock.
  In THIS office use the shared venv and requirements.txt as the briefs say; use uv in client/portfolio projects.
- Ruff for linting and formatting (replaces Black, isort, flake8, pyupgrade); run it locally and in CI.
- pytest for tests; add pytest-cov once the suite is meaningful; tests must be deterministic (no network in unit tests).
- Type hints on public functions; a type checker in CI (mypy, or newer ty/Pyrefly: sources disagree, pick one).
- Secrets in .env with a .env.example; never hard-coded. Pin direct dependencies.
- For ML code: seed randomness, separate data/feature/model/eval code, save metrics with the model, log experiments.

(modern Python tooling 2026). Community consensus, not a standard.

## Sources

pydevtools.com (Modern Python tooling checklist), Trail of Bits "modern-python" skill, levelup.gitconnected.com
