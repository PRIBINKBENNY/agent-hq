"""
"Nobody stops": the scheduler.

Two jobs:
  1. Run the task board. Takes the highest-priority queued task and runs its owner agent on it,
     one at a time (Groq free tier does not like parallel runs). Marks it done/failed with the result.
  2. Recurring jobs from office/schedule.yaml (daily job scan, morning digest, ...), which simply
     enqueue tasks at the right time.

Run standalone:  .venv/bin/python office/scheduler.py
The dashboard also calls tick() every few seconds, so leaving the dashboard open is enough.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
from store import BrainStore  # noqa: E402

SCHEDULE_FILE = ROOT / "office" / "schedule.yaml"
STATE_FILE = ROOT / "office" / "logs" / "schedule_state.json"
LOG_DIR = ROOT / "office" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_current: subprocess.Popen | None = None
_current_task: dict | None = None
_last_approval_id: int | None = None


def _notify(title: str, message: str):
    t = title.replace('"', "'")[:60]; m = message.replace('"', "'")[:200]
    try:
        subprocess.run(["osascript", "-e", f'display notification "{m}" with title "Agent HQ" subtitle "{t}"'],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def check_approvals(brain: BrainStore) -> int:
    """Notify Pribin once per new pending approval. Returns number of new ones."""
    global _last_approval_id
    pending = [m for m in brain.recent(limit=30, kind="approval") if "pending" in m.tags]
    top = max((m.id for m in pending), default=0)
    if _last_approval_id is None:
        _last_approval_id = top; return 0
    new = [m for m in pending if m.id > _last_approval_id]
    for m in new:
        _notify("Approval needed", m.content.replace("PENDING APPROVAL from ", ""))
        paths = re.findall(r"(?:workspace/)?((?:applications|posts|proposals|outbox|interviews)/[\w./-]+?\.md|(?:applications|posts|proposals|outbox)/[\w./-]+/)", m.content)
        if paths and "qa-queued" not in m.tags and m.agent != "fact-checker":
            brain.task_create(f"QA check approval #{m.id}",
                              f"Fact-check the text behind approval #{m.id} before Pribin sees it. Files/folders: {', '.join(sorted(set(paths)))}. "
                              f"Approval text: {m.content[:300]}", owner="fact-checker", created_by="scheduler", priority=5, source="qa")
            brain.update(m.id, agent="scheduler", add_tags=["qa-queued"])
    _last_approval_id = max(top, _last_approval_id)
    return len(new)


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(st: dict):
    STATE_FILE.write_text(json.dumps(st, indent=1))


DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _due(job: dict, last_run: float | None, now: datetime) -> bool:
    every = job.get("every", "daily")
    at = job.get("at", "08:00")
    hh, mm = [int(x) for x in at.split(":")]
    if every == "hourly":
        return last_run is None or now.timestamp() - last_run >= 3600
    if every == "weekdays" and now.weekday() >= 5:
        return False
    if every == "weekly":
        if now.weekday() != DAYS.index(job.get("day", "sunday").lower()):
            return False
        if last_run is not None and now.timestamp() - last_run < 6 * 86400:
            return False
    # daily / weekdays / weekly: due once per day, at or after HH:MM, but only within the firing window
    minutes_now = now.hour * 60 + now.minute
    minutes_at = hh * 60 + mm
    if minutes_now < minutes_at:
        return False
    if minutes_now - minutes_at > float(job.get("window_hours", 6)) * 60:
        return False   # too late today (e.g. the Mac was asleep); wait for tomorrow
    if last_run is None:
        return True
    return datetime.fromtimestamp(last_run).date() < now.date()


def enqueue_due_jobs(brain: BrainStore) -> list[str]:
    """Create tasks for any scheduled job whose time has come. Returns job names enqueued."""
    if not SCHEDULE_FILE.exists():
        return []
    jobs = yaml.safe_load(SCHEDULE_FILE.read_text()) or []
    st = _load_state(); now = datetime.now(); out = []
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def dep_done(dep: str) -> bool:
        """The dependency's task from today exists and is finished."""
        for t in brain.task_list(limit=200):
            if t.get("source") == f"schedule:{dep}" and t["created_at"] >= day_start:
                return t["status"] in ("done", "failed", "cancelled")
        return False

    for job in jobs:
        if not job.get("enabled", True):
            continue
        name = job["name"]
        if job.get("after") and _due(job, st.get(name), now) and not dep_done(job["after"]):
            continue  # wait for the job it depends on
        if _due(job, st.get(name), now):
            brain.task_create(job.get("title", name), job.get("task") or job.get("command", ""),
                              owner="command" if job.get("command") else job.get("agent", "chief-of-staff"),
                              created_by="scheduler", priority=int(job.get("priority", 3)), source=f"schedule:{name}")
            st[name] = time.time(); out.append(name)
    if out:
        _save_state(st)
    return out


def _spawn(task: dict, engine: str = "auto") -> subprocess.Popen:
    log = LOG_DIR / f"task-{task['id']}.log"
    if task["owner"] == "command":
        # a script job: detail is the shell command, run from the project root with the venv on PATH
        cmd = ["/bin/zsh", "-c", f"({task.get('detail') or 'true'}) && {sys.executable} -c \"import sys; sys.path.insert(0,'brain'); "
               f"from store import BrainStore; BrainStore().task_update({task['id']}, agent='scheduler', status='done', result='command finished')\" "
               f"|| {sys.executable} -c \"import sys; sys.path.insert(0,'brain'); from store import BrainStore; "
               f"BrainStore().task_update({task['id']}, agent='scheduler', status='failed', result='command failed, see office/logs/task-{task['id']}.log')\""]
        with open(log, "w") as lf:
            return subprocess.Popen(cmd, cwd=str(ROOT), stdout=lf, stderr=subprocess.STDOUT,
                                    env={**os.environ, "PATH": str(Path(sys.executable).parent) + ":" + os.environ.get("PATH", "")})
    cmd = [sys.executable, str(ROOT / "office" / "run.py"), "--agent", task["owner"], "--engine", engine,
           "--task-id", str(task["id"]), f"{task['title']}\n\n{task.get('detail') or ''}".strip()]
    with open(log, "w") as lf:
        return subprocess.Popen(cmd, cwd=str(ROOT), stdout=lf, stderr=subprocess.STDOUT)


def tick(brain: BrainStore, engine: str = "auto") -> dict:
    """One scheduler step: finish bookkeeping for a completed run, enqueue due jobs, start next task."""
    global _current, _current_task
    info = {"started": None, "finished": None, "enqueued": []}
    if _current is not None and _current.poll() is not None:
        # run.py marks the task done/failed itself; this is a safety net if it died hard
        t = brain.task_get(_current_task["id"])
        if t["status"] == "running":
            brain.task_update(t["id"], agent="scheduler", status="failed", result=f"process exited {_current.returncode} without reporting")
        info["finished"] = _current_task["id"]
        t = brain.task_get(_current_task["id"])
        _notify(f"Task {t['status']}: {t['owner']}", t["title"][:120])
        _current = None; _current_task = None
    info["enqueued"] = enqueue_due_jobs(brain)
    check_approvals(brain)
    housekeeping()
    if _current is None:
        nxt = brain.task_claim_next()
        if nxt:
            _current = _spawn(nxt, engine); _current_task = nxt; info["started"] = nxt["id"]
    return info


_last_housekeeping = 0.0


def housekeeping(days_logs: int = 14, days_handoff: int = 7) -> dict:
    """Delete task logs and handoff notes older than N days; trim the events file to the last 20k lines."""
    global _last_housekeeping
    if time.time() - _last_housekeeping < 6 * 3600:
        return {}
    _last_housekeeping = time.time()
    removed = {"task_logs": 0, "handoff": 0, "events_trimmed": False}
    now = time.time()
    for f in LOG_DIR.glob("task-*.log"):
        if now - f.stat().st_mtime > days_logs * 86400:
            f.unlink(missing_ok=True); removed["task_logs"] += 1
    for f in LOG_DIR.glob("run-*.log"):
        if now - f.stat().st_mtime > days_logs * 86400:
            f.unlink(missing_ok=True); removed["task_logs"] += 1
    hand = ROOT / "workspace" / ".handoff"
    if hand.exists():
        for f in hand.glob("*.md"):
            if now - f.stat().st_mtime > days_handoff * 86400:
                f.unlink(missing_ok=True); removed["handoff"] += 1
    # daily brain backup, keep 7
    try:
        import shutil
        src = ROOT / "brain" / "data" / "brain.db"
        bdir = ROOT / "brain" / "data" / "backups"; bdir.mkdir(parents=True, exist_ok=True)
        today = time.strftime("%Y-%m-%d")
        dest = bdir / f"brain-{today}.db"
        if src.exists() and not dest.exists():
            import sqlite3
            con = sqlite3.connect(str(src)); bck = sqlite3.connect(str(dest)); con.backup(bck); bck.close(); con.close()
            removed["backup"] = dest.name
        for old_b in sorted(bdir.glob("brain-*.db"))[:-7]:
            old_b.unlink(missing_ok=True)
    except Exception as e:
        removed["backup_error"] = str(e)[:120]
    ev = LOG_DIR / "events.jsonl"
    if ev.exists() and ev.stat().st_size > 20_000_000:
        lines = ev.read_text().splitlines()[-20000:]
        ev.write_text("\n".join(lines) + "\n"); removed["events_trimmed"] = True
    return removed


def busy() -> bool:
    return _current is not None and _current.poll() is None


if __name__ == "__main__":
    brain = BrainStore()
    print("scheduler running: task board + schedule.yaml (Ctrl-C to stop)")
    while True:
        info = tick(brain)
        if info["started"]:
            print(time.strftime("%H:%M:%S"), "started task", info["started"])
        if info["finished"]:
            print(time.strftime("%H:%M:%S"), "finished task", info["finished"])
        for n in info["enqueued"]:
            print(time.strftime("%H:%M:%S"), "scheduled job enqueued:", n)
        time.sleep(5)
