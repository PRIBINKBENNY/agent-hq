"""
Obsidian connection: the office's knowledge as plain Markdown notes in Pribin's vault, and his vault notes back into
the brain.

Vault: OBSIDIAN_VAULT in .env (default: /Users/pribinkbenny/Movies/ai employee). Everything the office writes lives
under one folder, "Agent HQ/", so his own notes are never touched:
  Agent HQ/Brain/<kind>/<id> <title>.md   one note per memory (frontmatter: id, kind, agent, tags, created), [[links]]
  Agent HQ/Agents/<name>.md               who each agent is, its department, tools and skills
  Agent HQ/Departments/<name>.md          mission, head, KPIs, members
  Agent HQ/Daily/<date>.md                the day's digest, approvals and board pack
  Agent HQ/Research/<slug>/...            proposal, literature, paper, review (copied)
  Agent HQ/Pipeline/...                   jobs and clients pipeline, roadmap, offer, trading plan (copied)
  Agent HQ/Inbox/                         HIS notes to the office: any .md dropped here is stored in the brain
                                          (kind from frontmatter or 'note', tags from frontmatter and #tags), then
                                          moved to Inbox/Done/
Runs hourly from the schedule (python office/obsidian.py); incremental, so it is cheap.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office")); sys.path.insert(0, str(ROOT / "brain"))

DEFAULT_VAULT = "/Users/pribinkbenny/Movies/ai employee"
STATE = ROOT / "office" / "logs" / "obsidian_state.json"
KIND_FOLDER = {"job": "Jobs", "lead": "Leads", "contact": "Contacts", "deal": "Deals", "decision": "Decisions", "lesson": "Lessons",
               "event": "Events", "approval": "Approvals", "note": "Notes", "fact": "Facts", "profile": "Profile", "company": "Companies"}


def vault() -> Path:
    return Path(os.environ.get("OBSIDIAN_VAULT") or DEFAULT_VAULT)


def hq() -> Path:
    return vault() / "Agent HQ"


def _state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save_state(st: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True); STATE.write_text(json.dumps(st))


def _slug(text: str, n: int = 60) -> str:
    t = re.sub(r"[\\/:*?\"<>|#^\[\]]", " ", text or ""); t = re.sub(r"\s+", " ", t).strip()
    return (t[:n].rstrip(" .") or "untitled")


def _title(m) -> str:
    c = re.sub(r"^(QA: \w+ - )?(PENDING APPROVAL|APPROVED|SENT|REJECTED) from [\w-]+: ", "", m.content or "")
    return _slug(c.split("\n", 1)[0], 70)


def _links(m) -> list[str]:
    out = [f"[[Agents/{m.agent}]]"] if m.agent and m.agent not in ("pribin", "scheduler", "runtime") else []
    for t in m.tags or []:
        if t.startswith("company:") or t.startswith("contact:") or t.startswith("project:"):
            out.append(f"[[{t.split(':', 1)[1]}]]")
    return out


def export_memories(brain, since: float) -> int:
    n = 0
    for m in brain.recent(limit=5000, namespace="*"):
        if (m.updated_at or m.created_at) <= since:
            continue
        kind = (m.kind or "note").lower(); folder = hq() / "Brain" / KIND_FOLDER.get(kind, kind.replace("_", "-").replace("-", " ").title())
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob(f"{m.id} *.md"):
            old.unlink()
        tags = [t.replace(":", "/") for t in (m.tags or []) if re.match(r"^[\w:./-]+$", t)]
        fm = {"id": m.id, "kind": m.kind, "agent": m.agent, "namespace": m.namespace, "created": time.strftime("%Y-%m-%d %H:%M", time.localtime(m.created_at)),
              "importance": m.importance, "source": m.source or "", "tags": tags}
        body = ["---", *(f"{k}: {json.dumps(v) if isinstance(v, (list, dict)) else v}" for k, v in fm.items()), "---", "",
                m.content.strip(), "", " ".join(_links(m)), ""]
        (folder / f"{m.id} {_title(m)}.md").write_text("\n".join(body)); n += 1
    return n


def export_agents_and_departments():
    import yaml
    from runtime import list_agents
    org = yaml.safe_load((ROOT / "office" / "org.yaml").read_text()) or {}
    (hq() / "Agents").mkdir(parents=True, exist_ok=True); (hq() / "Departments").mkdir(parents=True, exist_ok=True)
    depts = {d["key"]: d for d in org.get("departments", [])}; members: dict[str, list[str]] = {}
    for b in list_agents():
        members.setdefault(b.office, []).append(b.name)
        head = depts.get(b.office, {}).get("head") == b.name
        (hq() / "Agents" / f"{b.name}.md").write_text("\n".join([
            "---", f"office: {b.office}", f"tier: {b.tier}", f"head: {str(head).lower()}", "---", f"# {b.name}", "",
            b.description or "", "", f"Department: [[Departments/{depts.get(b.office, {}).get('name', b.office)}]]", "",
            "## Tools", ", ".join(f"`{t}`" for t in b.tools), "", "## Skill guides", ", ".join(b.skills) or "none", "",
            "## Instructions", "", b.system.strip(), ""]))
    for key, d in depts.items():
        (hq() / "Departments" / f"{d['name']}.md").write_text("\n".join([
            f"# {d['name']}", "", d.get("mission", ""), "", f"Head: [[Agents/{d.get('head')}]]", "",
            "## Judged on", *(f"- {k}" for k in d.get("kpis", [])), "", "## Members", *(f"- [[Agents/{m}]]" for m in sorted(members.get(key, []))), ""]))


def export_files():
    """Copies of the office's living documents (read-only mirrors; edits belong in the workspace or via the Inbox)."""
    ws = ROOT / "workspace"; pairs = {
        "Pipeline/Jobs.md": ws / "pipeline" / "jobs.md", "Pipeline/Clients.md": ws / "pipeline" / "clients.md", "Pipeline/Roadmap.md": ws / "roadmap.md",
        "Pipeline/Offer.md": ws / "offer.md", "Pipeline/90-day plan.md": ws / "plan-90-days.md", "Pipeline/Trading plan.md": ws / "trading" / "plan.md",
        "Pipeline/Lab sweep.md": ws / "trading" / "lab-sweep.md", "Daily/Approval digest.md": ws / "ops" / "approval-digest.md",
        "Research/STATUS.md": ws / "research" / "STATUS.md", "Research/BACKLOG.md": ws / "research" / "BACKLOG.md", "Research/Weekly.md": ws / "ops" / "research-weekly.md"}
    for rel, src in pairs.items():
        if src.exists():
            dst = hq() / rel; dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(f"> Mirror of `workspace/{src.relative_to(ws)}` (edit there, or write to Agent HQ/Inbox).\n\n" + src.read_text())
    for d in sorted((ws / "research").glob("*/")) if (ws / "research").exists() else []:
        for name in ("proposal.md", "literature.md", "paper.md", "review.md", "status.md"):
            if (d / name).exists():
                dst = hq() / "Research" / d.name / name; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy(d / name, dst)
    for f in sorted((ws / "ops" / "board").glob("*.md")) if (ws / "ops" / "board").exists() else []:
        dst = hq() / "Daily" / f"Board pack {f.stem}.md"; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy(f, dst)


def daily_note(brain):
    """Today's note: approvals waiting, what finished, what the office is working on."""
    import ceo
    day = time.strftime("%Y-%m-%d"); since = time.mktime(time.strptime(day, "%Y-%m-%d"))
    done = [t for t in brain.task_list(limit=300) if t["status"] == "done" and (t.get("finished_at") or 0) >= since]
    pend = ceo.pending_ranked()
    waiting = [f"- #{p['id']} {p['why']}: {p['text'][:100]}" for p in pend] or ["- none"]
    finished = [f"- {t['owner']}: {t['title'][:80]}" for t in done[:60]] or ["- nothing yet"]
    lines = [f"# {day}", "", "## Approvals waiting", *waiting, "", "## Finished today", *finished, "",
             "## Links", "[[Daily/Approval digest]] · [[Pipeline/Jobs]] · [[Pipeline/Clients]] · [[Research/STATUS]]", ""]
    (hq() / "Daily").mkdir(parents=True, exist_ok=True); (hq() / "Daily" / f"{day}.md").write_text("\n".join(lines))


def ingest_inbox(brain) -> list[str]:
    """Pribin's notes to the office: Inbox/*.md -> brain memories -> Inbox/Done/."""
    inbox = hq() / "Inbox"; inbox.mkdir(parents=True, exist_ok=True); (inbox / "Done").mkdir(exist_ok=True); stored = []
    for f in sorted(inbox.glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        text = f.read_text(); meta = {}
        fm = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
        if fm:
            try:
                import yaml; meta = yaml.safe_load(fm.group(1)) or {}; text = fm.group(2)
            except Exception:
                pass
        body = text.strip()
        if not body:
            continue
        tags = ["obsidian", "from-pribin"] + [str(t) for t in (meta.get("tags") or []) if isinstance(meta.get("tags"), list)] + [t for t in re.findall(r"(?<!\w)#([\w/-]+)", body)]
        kind = str(meta.get("kind") or "note"); ns = str(meta.get("namespace") or "global")
        m = brain.remember(f"{f.stem}: {body[:1800]}", agent="pribin", kind=kind if kind in ("note", "fact", "decision", "lead", "job", "lesson") else "note",
                           importance=int(meta.get("importance") or 4), tags=tags, source=f"obsidian:{f.name}", namespace=ns)
        shutil.move(str(f), str(inbox / "Done" / f"{time.strftime('%Y%m%d-%H%M')} {f.name}")); stored.append(f"{f.name} -> memory #{m.id}")
    if not (inbox / "README.md").exists():
        (inbox / "README.md").write_text("# Inbox\n\nDrop any note here (optional frontmatter: kind, tags, importance, namespace). Within the hour it is stored in the office's brain, every agent can recall it, and the file moves to Done/.\n")
    return stored


def home_note():
    (hq()).mkdir(parents=True, exist_ok=True)
    (hq() / "Home.md").write_text("\n".join([
        "# Agent HQ", "", "Everything the office knows, as notes. Synced hourly (and `python office/obsidian.py` any time).", "",
        "- [[Daily/" + time.strftime("%Y-%m-%d") + "|Today]] · [[Daily/Approval digest]]", "- [[Departments/Front Desk]] and the other departments in `Departments/`",
        "- `Agents/`: who everyone is · `Brain/`: every memory by kind · `Research/`: the lab's projects · `Pipeline/`: jobs, clients, roadmap, offer, trading plan",
        "- **Inbox/**: write a note here and the office remembers it.", "",
        "Search works across all of it; tags from the brain are Obsidian tags (e.g. #company/trainline, #status/applied).", ""]))


def sync(full: bool = False) -> dict:
    from store import BrainStore
    brain = BrainStore(); st = _state(); since = 0 if full else float(st.get("since", 0)); t0 = time.time()
    if not vault().exists():
        return {"error": f"vault not found: {vault()} (set OBSIDIAN_VAULT in .env)"}
    n = export_memories(brain, since); export_agents_and_departments(); export_files(); daily_note(brain); home_note(); stored = ingest_inbox(brain)
    st["since"] = t0; st["last"] = time.strftime("%Y-%m-%d %H:%M"); _save_state(st)
    return {"vault": str(hq()), "memories_written": n, "inbox_stored": stored, "seconds": round(time.time() - t0, 1)}


if __name__ == "__main__":
    import runtime  # noqa: F401  (.env)
    print(json.dumps(sync(full="--full" in sys.argv), indent=1))
