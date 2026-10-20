"""
Export the office's skill guides in the Agent Skills format (one folder per skill with a SKILL.md carrying name and
description frontmatter), so the same guides install into Claude Code, Codex or any agent that reads SKILL.md, and
so they stand as a public, versioned part of the portfolio repo.

  python office/skills_export.py          -> skills/<slug>/SKILL.md (+ skills/README.md)
Runs weekly before the Friday publish; the public repo (git archive) carries the folder.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "office" / "skills"
OUT = ROOT / "skills"


def export() -> list[str]:
    OUT.mkdir(exist_ok=True); names = []
    for f in sorted(SRC.glob("*.md")):
        text = f.read_text().strip(); slug = f.stem
        title = text.splitlines()[0].lstrip("# ").strip()
        updated = re.search(r"updated (20\d\d-\d\d-\d\d)", title); title_clean = re.sub(r"\s*\(updated 20\d\d-\d\d-\d\d\)", "", title)
        body = "\n".join(text.splitlines()[1:]).strip()
        sources = re.search(r"^Sources?:\s*(.+)$", body, re.M)
        body_wo = re.sub(r"^Sources?:.*$", "", body, flags=re.M).strip()
        desc = title_clean.rstrip(".")
        d = OUT / slug; d.mkdir(exist_ok=True)
        (d / "SKILL.md").write_text("\n".join([
            "---", f"name: {slug}", f'description: "Use when the task needs {desc}. Current practice as of {updated.group(1) if updated else "2026"}, with sources."',
            f"metadata:", f"  updated: {updated.group(1) if updated else ''}", f"  source: Agent HQ (github.com/PRIBINKBENNY/agent-hq), office/skills/{slug}.md",
            "---", "", f"# {title_clean}", "", body_wo, "", "## Sources", "", sources.group(1) if sources else "see the guide header", ""]))
        names.append(slug)
    (OUT / "README.md").write_text("\n".join([
        "# Agent HQ skills", "", f"{len(names)} skill guides in the Agent Skills format (a folder per skill, `SKILL.md` with `name` and `description` frontmatter).",
        "They are the same guides the office's 42 agents are briefed with; each is dated and lists its sources, and the office refreshes the oldest ones every two weeks.", "",
        "Install into Claude Code: copy a folder into `~/.claude/skills/` (or `.claude/skills/` in a project). Codex and other SKILL.md readers: point them at this folder.", "",
        *(f"- `{n}/`" for n in names), "", f"Generated {time.strftime('%Y-%m-%d')} by `office/skills_export.py`.", ""]))
    return names


if __name__ == "__main__":
    print(", ".join(export()))
