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

STANDING_FILE = ROOT / "office" / "standing-work.yaml"
TUNING_FILE = ROOT / "office" / "tuning.json"


def _knob(name: str, default):
    try:
        return type(default)(json.loads(TUNING_FILE.read_text()).get(name, default))
    except Exception:
        return default


MAX_PARALLEL = int(os.environ.get("OFFICE_MAX_PARALLEL") or _knob("max_parallel", 2))
TASK_WALL_SECONDS = int(os.environ.get("OFFICE_TASK_WALL_SECONDS") or _knob("task_wall_seconds", 1500))
STANDING_BUDGET_FRACTION = float(os.environ.get("OFFICE_STANDING_BUDGET") or _knob("standing_budget_fraction", 0.25))

_running: dict[int, dict] = {}       # task_id -> {"proc", "task", "engine"}
_last_approval_id: int | None = None
_rr = 0


class _Adopted:
    """A run started by a previous scheduler process: tracked by pid only."""
    def __init__(self, pid: int):
        self.pid = pid; self.returncode = None
    def poll(self):
        try:
            os.kill(self.pid, 0)
            return None
        except OSError:
            self.returncode = 0
            return 0


_reconciled = False


def reconcile(brain: BrainStore) -> dict:
    """On startup: tasks marked running must belong to a live process. Adopt the live ones, requeue the rest."""
    global _reconciled
    _reconciled = True
    info = {"adopted": [], "requeued": []}
    for t in brain.task_list(limit=200, status="running"):
        if t["id"] in _running:
            continue
        try:
            out = subprocess.run(["pgrep", "-f", f"run.py .*--task-id {t['id']}( |$)"], capture_output=True, text=True, timeout=5).stdout.split()
        except Exception:
            out = []
        pids = [int(x) for x in out if x.isdigit()]
        if pids:
            _running[t["id"]] = {"proc": _Adopted(pids[0]), "task": t, "engine": "adopted"}; info["adopted"].append(t["id"])
        else:
            brain.task_update(t["id"], agent="scheduler", status="queued", result=None); info["requeued"].append(t["id"])
    return info


def running_ids() -> list[int]:
    return [tid for tid, r in _running.items() if r["proc"].poll() is None]


def busy() -> bool:
    return bool(running_ids())


def budget() -> dict:
    """Per provider: fraction of the daily/minute budget left, from the latest rate-limit headers."""
    try:
        sys.path.insert(0, str(ROOT / "office"))
        from runtime import read_usage, active_providers
    except Exception:
        return {}
    out = {}
    for prov in active_providers():
        u = read_usage().get(prov, {})
        def frac(rem_key, lim_key):
            try:
                return float(u[rem_key]) / float(u[lim_key]) if u.get(lim_key) else None
            except (ValueError, ZeroDivisionError):
                return None
        day = frac("x-ratelimit-remaining-tokens-day", "x-ratelimit-limit-tokens-day")
        if day is None:
            day = frac("x-ratelimit-remaining-requests", "x-ratelimit-limit-requests")   # groq exposes daily requests
        minute = frac("x-ratelimit-remaining-tokens-minute", "x-ratelimit-limit-tokens-minute")
        if minute is None:
            minute = frac("x-ratelimit-remaining-tokens", "x-ratelimit-limit-tokens")
        out[prov] = {"day": day, "minute": minute, "ok": (day is None or day > STANDING_BUDGET_FRACTION) and (minute is None or minute > 0.15)}
    return out


def pick_engine() -> str:
    """Spread parallel runs across providers that still have budget; round-robin among the healthy ones."""
    global _rr
    b = budget()
    healthy = [p for p, v in b.items() if v["ok"]] or list(b.keys())
    if not healthy:
        return "auto"
    _rr += 1
    return healthy[_rr % len(healthy)]


def standing_allowed() -> bool:
    b = budget()
    return not b or any(v["ok"] for v in b.values())


def enqueue_standing_work(brain: BrainStore) -> list[str]:
    """Keep every office busy: when the queue is short, add the standing item that has waited longest."""
    if not STANDING_FILE.exists() or not standing_allowed():
        return []
    queued = [t for t in brain.task_list(limit=100, status="queued")]
    if len(queued) >= MAX_PARALLEL:
        return []
    items = yaml.safe_load(STANDING_FILE.read_text()) or []
    st = _load_state(); now = datetime.now(); ts = now.timestamp(); cands = []
    for it in items:
        if not it.get("enabled", True):
            continue
        if it.get("weekdays") and now.weekday() >= 5:
            continue
        if it.get("hours"):
            lo, hi = [int(x) for x in str(it["hours"]).split("-")]
            if not (lo <= now.hour <= hi):
                continue
        last = st.get("standing:" + it["name"], 0)
        overdue = (ts - last) / 3600 - float(it.get("every_hours", 6))
        if overdue >= 0 and not any(t.get("source") == "standing:" + it["name"] for t in queued):
            cands.append((overdue, it))
    if not cands:
        return []
    cands.sort(key=lambda c: -c[0])
    out = []
    for _, it in cands[:MAX_PARALLEL - len(queued)]:
        brain.task_create(it.get("title", it["name"]), it["task"], owner=it["agent"], created_by="scheduler",
                          priority=int(it.get("priority", 2)), source="standing:" + it["name"])
        st["standing:" + it["name"]] = ts; out.append(it["name"])
    _save_state(st)
    return out


def _notify(title: str, message: str):
    t = title.replace('"', "'")[:60]; m = message.replace('"', "'")[:200]
    try:
        subprocess.run(["osascript", "-e", f'display notification "{m}" with title "Agent HQ" subtitle "{t}"'],
                       capture_output=True, timeout=10)
    except Exception:
        pass
    try:
        sys.path.insert(0, str(ROOT / "office"))
        import push
        push.send(t, m, "/m", "hq")
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
        if job.get("hours"):                      # e.g. "08-16": only within these London hours, weekdays
            lo, hi = [int(x) for x in str(job["hours"]).split("-")]
            if now.weekday() >= 5 or not (lo <= now.hour <= hi):
                return False
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
    """One scheduler step: reap finished runs, enqueue due + standing work, start tasks up to MAX_PARALLEL."""
    global MAX_PARALLEL, TASK_WALL_SECONDS, STANDING_BUDGET_FRACTION
    if not os.environ.get("OFFICE_MAX_PARALLEL"):
        MAX_PARALLEL = _knob("max_parallel", 2); TASK_WALL_SECONDS = _knob("task_wall_seconds", 1500); STANDING_BUDGET_FRACTION = _knob("standing_budget_fraction", 0.25)
    info = {"started": [], "finished": [], "enqueued": []}
    if not _reconciled:
        info["reconciled"] = reconcile(brain)
    for tid, r in list(_running.items()):
        started = r.setdefault("started", time.time())
        if r["proc"].poll() is None and time.time() - started > TASK_WALL_SECONDS:
            try:
                r["proc"].terminate() if hasattr(r["proc"], "terminate") else os.kill(r["proc"].pid, 15)
            except Exception:
                pass
            t = brain.task_get(tid)
            retried = "retried-after-timeout" in (t.get("result") or "")
            brain.task_update(tid, agent="scheduler", status="failed" if retried else "queued",
                              result=f"stopped after {TASK_WALL_SECONDS}s wall-clock; retried-after-timeout" if not retried else "stopped twice after the wall-clock limit")
            _notify("Task timed out", f"{t['owner']}: {t['title'][:90]}")
            info["finished"].append(tid); _running.pop(tid, None)
            continue
        if r["proc"].poll() is not None:
            t = brain.task_get(tid)
            if t["status"] == "running":   # run.py marks done/failed itself; safety net if it died hard
                brain.task_update(tid, agent="scheduler", status="failed", result=f"process exited {r['proc'].returncode} without reporting")
                t = brain.task_get(tid)
            _notify(f"Task {t['status']}: {t['owner']}", t["title"][:120])
            info["finished"].append(tid); _running.pop(tid, None)
    info["enqueued"] = enqueue_due_jobs(brain) + enqueue_standing_work(brain)
    check_approvals(brain)
    housekeeping()
    while len(running_ids()) < MAX_PARALLEL:
        nxt = brain.task_claim_next()
        if not nxt:
            break
        eng = engine if engine != "auto" else pick_engine()
        _running[nxt["id"]] = {"proc": _spawn(nxt, eng), "task": nxt, "engine": eng}
        info["started"].append(nxt["id"])
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




if __name__ == "__main__":
    brain = BrainStore()
    print("scheduler running: task board + schedule.yaml (Ctrl-C to stop)")
    while True:
        info = tick(brain)
        for tid in info["started"]:
            print(time.strftime("%H:%M:%S"), "started task", tid, "on", _running.get(tid, {}).get("engine"))
        for tid in info["finished"]:
            print(time.strftime("%H:%M:%S"), "finished task", tid)
        for n in info["enqueued"]:
            print(time.strftime("%H:%M:%S"), "scheduled job enqueued:", n)
        time.sleep(5)
