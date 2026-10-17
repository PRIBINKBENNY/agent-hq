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


def paused() -> dict:
    """Global pause: {'paused': bool, 'reason': str, 'until': ts|None}. Expired timed pauses count as resumed."""
    try:
        d = json.loads(TUNING_FILE.read_text())
    except Exception:
        return {"paused": False}
    if not d.get("paused"):
        return {"paused": False}
    until = d.get("paused_until")
    if until and time.time() > float(until):
        d["paused"] = False; TUNING_FILE.write_text(json.dumps(d, indent=1))
        return {"paused": False}
    return {"paused": True, "reason": d.get("paused_reason", ""), "until": until, "since": d.get("paused_at")}


def set_paused(flag: bool, reason: str = "", hours: float | None = None) -> dict:
    try:
        d = json.loads(TUNING_FILE.read_text())
    except Exception:
        d = {}
    d["paused"] = bool(flag); d["paused_reason"] = reason if flag else ""
    d["paused_at"] = time.time() if flag else None; d["paused_until"] = (time.time() + hours * 3600) if (flag and hours) else None
    TUNING_FILE.write_text(json.dumps(d, indent=1))
    return paused()


def running_ids() -> list[int]:
    return [tid for tid, r in _running.items() if r["proc"].poll() is None]


def busy() -> bool:
    return bool(running_ids())


def _provider_down() -> dict:
    try:
        sys.path.insert(0, str(ROOT / "office"))
        from runtime import provider_down
        return provider_down()
    except Exception:
        return {}


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
        down = prov in _provider_down()
        out[prov] = {"day": day, "minute": minute, "down": down, "ok": not down and (day is None or day > STANDING_BUDGET_FRACTION) and (minute is None or minute > 0.15)}
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


def standing_rate_ok(st: dict, now_ts: float) -> bool:
    """Round-the-clock pacing: at most `standing_per_hour` standing items are started per rolling hour, so the day's
    free-tier allowance is spread across 24 hours instead of being burnt in a 3 a.m. burst (then nothing by noon)."""
    cap = int(_knob("standing_per_hour", 3))
    recent = [t for t in st.get("standing_starts", []) if now_ts - t < 3600]
    st["standing_starts"] = recent
    return len(recent) < cap


def enqueue_standing_work(brain: BrainStore) -> list[str]:
    """Keep every office busy, round the clock: when the queue is short, add the standing item that has waited longest.
    If nothing is due and nobody is working, start the item closest to due anyway (idle filler), within the hourly pace."""
    if not STANDING_FILE.exists() or not standing_allowed():
        return []
    queued = [t for t in brain.task_list(limit=100, status="queued")]
    now_ts = time.time()
    def waiting(t: dict) -> bool:                       # parked until a provider's cooldown ends: not startable work
        stamps = re.findall(r"retry_after:(\d+)", t.get("result") or "")
        return bool(stamps) and float(stamps[-1]) > now_ts
    startable = [t for t in queued if not waiting(t)]
    if len(startable) >= MAX_PARALLEL:
        return []
    items = yaml.safe_load(STANDING_FILE.read_text()) or []
    st = _load_state(); now = datetime.now(); ts = now.timestamp(); cands = []
    if not standing_rate_ok(st, ts):
        _save_state(st); return []
    idle = not startable and not running_ids()
    for it in items:
        if not it.get("enabled", True):
            continue
        if it.get("weekdays") and now.weekday() >= 5:
            continue
        if it.get("requires_env") and not (os.environ.get(str(it["requires_env"])) or "").strip():
            continue                                   # e.g. mail triage only when Gmail is configured
        if it.get("hours"):
            lo, hi = [int(x) for x in str(it["hours"]).split("-")]
            if not (lo <= now.hour <= hi):
                continue
        last = st.get("standing:" + it["name"], 0)
        every = float(it.get("every_hours", 6)); elapsed_h = (ts - last) / 3600
        overdue = elapsed_h - every
        # idle filler: nothing queued or running -> the item nearest to due may start early, once a third of its interval
        # (and at least an hour) has passed; never for weekly items
        early_ok = idle and every <= 48 and elapsed_h >= max(1.0, every / 3)
        if (overdue >= 0 or early_ok) and not any(t.get("source") == "standing:" + it["name"] for t in queued):
            cands.append((elapsed_h / every, it))
    if not cands:
        _save_state(st); return []
    cands.sort(key=lambda c: -c[0])
    out = []
    for _, it in cands[:MAX_PARALLEL - len(startable)]:
        if not standing_rate_ok(st, ts):
            break
        brain.task_create(it.get("title", it["name"]), it["task"], owner=it["agent"], created_by="scheduler",
                          priority=int(it.get("priority", 2)), source="standing:" + it["name"])
        st["standing:" + it["name"]] = ts; st.setdefault("standing_starts", []).append(ts); out.append(it["name"])
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
            if t["status"] == "failed" and "no capable model" in (t.get("result") or ""):
                # every cloud provider was cooling down: capacity, not the task, failed. Retry in 15 minutes, then hourly;
                # sweep_stale retires what has genuinely gone stale, so nothing is abandoned for lack of quota
                tries = (t.get("result") or "").count("retry_after")
                delay = 900 if tries < 3 else 3600
                brain.task_update(tid, agent="scheduler", status="queued", result=(t.get("result") or "")[:300] + f" | retry_after:{int(time.time()) + delay}")
                info["finished"].append(tid); _running.pop(tid, None); continue
            if t["status"] == "running":   # run.py marks done/failed itself; safety net if it died hard
                brain.task_update(tid, agent="scheduler", status="failed", result=f"process exited {r['proc'].returncode} without reporting")
                t = brain.task_get(tid)
            _notify(f"Task {t['status']}: {t['owner']}", t["title"][:120])
            info["finished"].append(tid); _running.pop(tid, None)
    if paused()["paused"]:
        info["paused"] = True
        check_approvals(brain); housekeeping(); tunnel_watch()
        return info                     # finished runs are reaped above; nothing new is enqueued or started
    info["swept"] = sweep_stale(brain)           # work that waited too long (e.g. through a pause) is replaced, not run late
    info["enqueued"] = enqueue_due_jobs(brain) + enqueue_standing_work(brain)
    check_approvals(brain)
    housekeeping(); tunnel_watch()
    healthy = [p for p, v in budget().items() if v["ok"] and not v.get("down")]
    effective = max(1, min(MAX_PARALLEL, len(healthy))) if budget() else MAX_PARALLEL
    try:
        from runtime import cloud_available
        ok_cloud, soonest = cloud_available()
    except Exception:
        ok_cloud, soonest = True, 0
    if not ok_cloud:
        info["waiting_for_cloud_until"] = soonest; effective = 0        # queue, do not burn runs that will fail
    now = time.time(); skip: list[int] = []
    while len(running_ids()) < effective:
        nxt = brain.task_claim_next(exclude=skip)
        if not nxt:
            break
        stamps = re.findall(r"retry_after:(\d+)", nxt.get("result") or "")   # the result accumulates one per retry: honour the latest
        if stamps and float(stamps[-1]) > now:
            brain.task_update(nxt["id"], agent="scheduler", status="queued")   # not yet: leave it queued, try the next one
            skip.append(nxt["id"]); continue
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


# ---------------------------------------------------------------- stale work + phone tunnel watch
_last_sweep = 0.0


def sweep_stale(brain: BrainStore, now: float | None = None) -> list[int]:
    """Cancel queued scheduler work that has waited past its usefulness (typically after a long pause):
    hourly jobs older than 3h, anything the scheduler created more than 36h ago. The next due run replaces it."""
    global _last_sweep
    now = now or time.time()
    if now - _last_sweep < 60:
        return []
    _last_sweep = now
    hourly: set[str] = set()
    try:
        hourly = {j["name"] for j in (yaml.safe_load(SCHEDULE_FILE.read_text()) or []) if j.get("every") == "hourly"}
    except Exception:
        pass
    out = []
    for t in brain.task_list(limit=200, status="queued"):
        if t.get("created_by") != "scheduler":
            continue
        age = now - float(t.get("created_at") or now)
        src = t.get("source") or ""
        limit = 3 * 3600 if src.startswith("schedule:") and src[len("schedule:"):] in hourly else 36 * 3600
        if age > limit:
            brain.task_update(t["id"], agent="scheduler", status="cancelled",
                              result=f"stale: queued {age / 3600:.0f}h ago; the next scheduled run replaces it")
            out.append(t["id"])
    return out


TUNNEL_LOG = LOG_DIR / "tunnel.log"
TUNNEL_LABEL = "com.pribin.agenthq.tunnel"
_last_tunnel_check = 0.0


def tunnel_status() -> dict:
    """{'running', 'url', 'dead'} for the free Cloudflare quick tunnel behind the phone app.
    A quick tunnel dies for good when the Mac sleeps: cloudflared then logs 'Tunnel not found' forever
    and only a restart (which hands out a new URL) brings the phone app back."""
    if not TUNNEL_LOG.exists():
        return {"running": False, "url": None, "dead": False}
    try:
        size = TUNNEL_LOG.stat().st_size
        with open(TUNNEL_LOG, "rb") as f:
            head = f.read(8000).decode("utf-8", "ignore")
            f.seek(max(0, size - 6000)); tail = f.read().decode("utf-8", "ignore")
        running = subprocess.run(["pgrep", "-f", "cloudflared tunnel"], capture_output=True, timeout=5).returncode == 0
        last_lines = tail.splitlines()[-12:]
        not_found = sum("Tunnel not found" in ln for ln in last_lines)
        recovered = ("Registered tunnel connection" in tail[tail.rfind("Tunnel not found"):]) if not_found else True
        urls = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", head + tail)
        return {"running": running, "url": (urls[-1] if urls else None), "dead": bool(running and not_found >= 3 and not recovered)}
    except Exception:
        return {"running": False, "url": None, "dead": False}


def tunnel_watch(force: bool = False) -> dict:
    """Once a minute: restart a dead quick tunnel (launchd starts it again with a fresh URL) and, when the
    address changes, tell Pribin on the Mac and on the phone (web push still reaches the old install)."""
    global _last_tunnel_check
    if not force and time.time() - _last_tunnel_check < 60:
        return {}
    _last_tunnel_check = time.time()
    st = tunnel_status(); state = _load_state(); info: dict = {}
    if st["dead"]:
        if time.time() - float(state.get("tunnel_kick_ts", 0)) < 600:
            return {"dead": True}
        try:
            TUNNEL_LOG.write_text("")          # thousands of retry lines; start clean so the new URL is easy to find
            subprocess.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{TUNNEL_LABEL}"], capture_output=True, timeout=20)
            state["tunnel_kick_ts"] = time.time(); _save_state(state); info["kicked"] = True
        except Exception as e:
            info["error"] = str(e)[:120]
        return info
    if st["url"] and st["url"] != state.get("tunnel_url"):
        prev = state.get("tunnel_url"); state["tunnel_url"] = st["url"]; _save_state(state); info["url"] = st["url"]
        if prev:                                # moved, not first start
            _notify("Phone app moved", st["url"] + "/m")
            try:
                import push
                info["push"] = push.send("Agent HQ phone app moved", "Open the new address and add it to your home screen again.",
                                         url=st["url"] + "/m", tag="tunnel")
            except Exception as e:
                info["push_error"] = str(e)[:120]
    return info



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
