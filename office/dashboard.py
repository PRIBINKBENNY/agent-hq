"""
Agent HQ live dashboard.

  .venv/bin/python office/dashboard.py          ->  http://localhost:8787

Shows every agent's desk lighting up as it thinks / calls tools / delegates,
a live activity feed, the brain's latest memories, pending approvals, and a
command box that starts runs. Everything is local; the page tails
office/logs/events.jsonl and reads brain/data/brain.db.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office"))
sys.path.insert(0, str(ROOT / "brain"))

import uvicorn  # noqa: E402
from sse_starlette.sse import EventSourceResponse  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import HTMLResponse, JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402

from events import EVENTS_FILE, read_tail  # noqa: E402
from runtime import list_agents, OLLAMA_MODEL, active_providers, provider_models, read_usage  # noqa: E402
from tools import WORKSPACE  # noqa: E402
from store import BrainStore  # noqa: E402
import scheduler  # noqa: E402

PORT = int(os.environ.get("DASHBOARD_PORT", "8787"))
HTML_PATH = ROOT / "office" / "static" / "dashboard.html"
brain = BrainStore()
_procs: dict[str, subprocess.Popen] = {}


def roster() -> list[dict]:
    return [{"name": b.name, "office": b.office, "tier": b.tier, "description": b.description,
             "tools": b.tools, "delegates": b.delegates} for b in list_agents()]


def state() -> dict:
    day_start = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
    events = read_tail(2000)
    runs_today = {e["run_id"] for e in events if e.get("type") == "start" and e.get("depth") == 0 and e["ts"] >= day_start}
    pending = [m.to_dict() for m in brain.recent(limit=50, kind="approval") if "pending" in m.tags]
    memories = [m.to_dict() for m in brain.recent(limit=12, namespace="*")]
    return {
        "roster": roster(),
        "brain": brain.stats(),
        "memories": memories,
        "approvals": pending,
        "runs_today": len(runs_today),
        "engine": {"providers": active_providers(), "groq": bool(active_providers()),
                   "lead_models": [f"{p}:{provider_models(p, 'lead')[0]}" for p in active_providers() if provider_models(p, 'lead')],
                   "ollama": OLLAMA_MODEL, "usage": read_usage()},
        "running": [rid for rid, p in _procs.items() if p.poll() is None],
        "tasks": brain.task_list(limit=40),
        "scheduler_busy": scheduler.busy(),
        "now": time.time(),
    }


async def index(_: Request):
    return HTMLResponse(HTML_PATH.read_text())


async def api_state(_: Request):
    return JSONResponse(await asyncio.to_thread(state))


async def api_events(request: Request):
    """SSE: replay recent events, then stream new ones."""
    async def gen():
        last = read_tail(400)
        yield {"event": "snapshot", "data": json.dumps(last)}
        pos = EVENTS_FILE.stat().st_size if EVENTS_FILE.exists() else 0
        while True:
            if await request.is_disconnected():
                return
            if EVENTS_FILE.exists():
                size = EVENTS_FILE.stat().st_size
                if size < pos:
                    pos = 0
                if size > pos:
                    with open(EVENTS_FILE, "r") as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    for ln in chunk.splitlines():
                        if ln.strip():
                            yield {"event": "ev", "data": ln}
            await asyncio.sleep(0.4)
    return EventSourceResponse(gen(), ping=15)


def _busy() -> bool:
    return scheduler.busy() or any(p.poll() is None for p in _procs.values())


async def api_run(request: Request):
    body = await request.json()
    task = (body.get("task") or "").strip()
    agent = body.get("agent") or "chief-of-staff"
    engine = body.get("engine") or "auto"
    if not task:
        return JSONResponse({"error": "task is empty"}, status_code=400)
    if _busy() or body.get("queue"):
        t = brain.task_create(task[:120], task, owner=agent, created_by="pribin", priority=4, source="ui")
        return JSONResponse({"queued": True, "task_id": t["id"]})
    rid = f"ui{int(time.time())}"
    log = ROOT / "office" / "logs" / f"run-{rid}.log"
    cmd = [sys.executable, str(ROOT / "office" / "run.py"), "--agent", agent, "--engine", engine, task]
    with open(log, "w") as lf:
        p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=lf, stderr=subprocess.STDOUT)
    _procs[rid] = p
    return JSONResponse({"started": True, "pid": p.pid, "log": str(log)})


async def api_approve(request: Request):
    body = await request.json()
    mid = int(body.get("id"))
    decision = body.get("decision", "approved")
    m = brain.get(mid)
    new = m.content.replace("PENDING APPROVAL", decision.upper(), 1)
    brain.update(mid, agent="pribin", content=new, tags=[t for t in m.tags if t != "pending"] + [decision])
    follow = None
    if decision == "approved":
        follow = brain.task_create(f"Approved #{mid}: next step", 
            f"Pribin APPROVED this item: {new}\n\nDo the natural next step and nothing external: e.g. for an application, "
            f"have tracker log it as 'applied' and mail-assistant prepare a follow-up draft dated 7 days out; for a proposal, "
            f"have tracker log it as 'proposed'; for a post, have tracker note the publish date. Report what you did.",
            owner="chief-of-staff", created_by="pribin", priority=4, source="approval")
    return JSONResponse({"ok": True, "follow_up_task": follow["id"] if follow else None})


async def api_applied(request: Request):
    """Pribin pressed 'I applied' on an approval: record status:applied so the tracker and scorecard see it."""
    body = await request.json()
    mid = int(body.get("id"))
    m = brain.get(mid)
    company = next((t.split(":", 1)[1] for t in m.tags if t.startswith("company:")), None) or \
              next((t for t in m.tags if t not in ("application", "pending", "approved", "rejected", "qa-pass", "qa-fail", "qa-queued", "email", "cv")), "unknown")
    ev = brain.remember(f"Pribin applied: {m.content[:160]}", agent="pribin", kind="event", importance=4,
                        tags=["status:applied", f"company:{company}", "application"])
    brain.update(mid, agent="pribin", content=m.content.replace("PENDING APPROVAL", "APPLIED", 1),
                 tags=[t for t in m.tags if t != "pending"] + ["approved", "applied"])
    t = brain.task_create(f"Applied to {company}: log + follow-up", f"Pribin applied to {company} today ({m.content[:200]}). "
                          "tracker: set stage applied in pipeline/jobs.md with a follow-up date 7 days out. mail-assistant: draft the follow-up email dated then.",
                          owner="chief-of-staff", created_by="pribin", priority=3, source="applied")
    return JSONResponse({"ok": True, "event": ev.id, "task": t["id"]})


async def api_tasks(request: Request):
    if request.method == "GET":
        return JSONResponse({"tasks": await asyncio.to_thread(brain.task_list, limit=60)})
    body = await request.json()
    if body.get("action") == "cancel":
        return JSONResponse({"task": brain.task_update(int(body["id"]), agent="pribin", status="cancelled")})
    if body.get("action") == "retry":
        return JSONResponse({"task": brain.task_update(int(body["id"]), agent="pribin", status="queued", result=None)})
    return JSONResponse({"error": "unknown action"}, status_code=400)


async def api_runs(_: Request):
    return JSONResponse(await asyncio.to_thread(_read_runs))


def _read_runs() -> dict:
    out = []
    for f in sorted((ROOT / "office" / "logs").glob("20*.jsonl"), reverse=True)[:3]:
        for ln in f.read_text().splitlines():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    out.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return {"runs": out[:40]}


import contextlib  # noqa: E402


@contextlib.asynccontextmanager
async def _lifespan(app):
    task = asyncio.create_task(_scheduler_loop())
    try:
        yield
    finally:
        task.cancel()


_stats_cache: dict = {"ts": 0, "data": None}


async def api_stats(_: Request):
    if _stats_cache["data"] is not None and time.time() - _stats_cache["ts"] < 120:
        return JSONResponse(_stats_cache["data"])
    data = await asyncio.to_thread(_compute_stats)
    _stats_cache.update(ts=time.time(), data=data)
    return JSONResponse(data)


def _compute_stats() -> dict:
    """Ops panel: per-agent success, time, tokens, provider share, over the last 7 days; plus the scorecard."""
    import glob
    from tools import registry as _reg
    since = time.time() - 7 * 86400
    runs = []
    for f in glob.glob(str(ROOT / "office" / "logs" / "20*.jsonl")):
        for ln in open(f):
            try:
                e = json.loads(ln)
                if time.mktime(time.strptime(e["ts"], "%Y-%m-%d %H:%M:%S")) >= since:
                    runs.append(e)
            except Exception:
                pass
    agents: dict[str, dict] = {}
    providers: dict[str, int] = {}
    for e in runs:
        a = agents.setdefault(e["agent"], {"runs": 0, "tokens": 0, "seconds": 0.0, "empty": 0})
        a["runs"] += 1; a["tokens"] += int(e.get("tokens_in", 0)) + int(e.get("tokens_out", 0)); a["seconds"] += float(e.get("seconds", 0))
        if not (e.get("answer") or "").strip() or "No final answer" in (e.get("answer") or ""):
            a["empty"] += 1
        providers[(e.get("model") or "?").split(":")[0]] = providers.get((e.get("model") or "?").split(":")[0], 0) + 1
    tasks = [t for t in brain.task_list(limit=500) if t["created_at"] >= since]
    by_owner: dict[str, dict] = {}
    for t in tasks:
        o = by_owner.setdefault(t["owner"], {"done": 0, "failed": 0, "open": 0})
        o["done" if t["status"] == "done" else "failed" if t["status"] == "failed" else "open"] += 1
    try:
        card = json.loads(_reg.call("scorecard", {"days": 7}))
    except Exception as e:
        card = {"error": str(e)}
    evals = sorted((ROOT / "office" / "eval" / "results").glob("*.json"))
    last_eval = json.loads(evals[-1].read_text())["summary"] if evals else None
    return {"agents": agents, "providers": providers, "tasks_by_owner": by_owner, "scorecard": card, "last_eval": last_eval}


async def api_agent(request: Request):
    """One agent: brief, tools, last runs, lessons, task stats."""
    name = request.query_params.get("name", "")
    briefs = {b.name: b for b in list_agents()}
    if name not in briefs:
        return JSONResponse({"error": "unknown agent"}, status_code=404)
    b = briefs[name]
    runs = [r for r in (await asyncio.to_thread(_read_runs))["runs"] if r["agent"] == name][:5]
    lessons = [m.to_dict()["content"] for m in brain.recall("", limit=5, tags=["reflection", name], kind="lesson")]
    tasks = [t for t in brain.task_list(limit=300) if t["owner"] == name]
    return JSONResponse({"name": name, "office": b.office, "tier": b.tier, "model": b.model, "description": b.description,
                         "tools": b.tools, "delegates": b.delegates, "system": b.system[:1800], "runs": runs, "lessons": lessons,
                         "tasks": {"done": sum(t["status"] == "done" for t in tasks), "failed": sum(t["status"] == "failed" for t in tasks)}})


async def api_file(request: Request):
    """Read a workspace file for previews (approvals, task results)."""
    path = request.query_params.get("path", "")
    p = (WORKSPACE / path).resolve()
    if WORKSPACE.resolve() not in p.parents or not p.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    if p.suffix.lower() == ".pdf":
        from starlette.responses import FileResponse
        return FileResponse(str(p), media_type="application/pdf")
    return JSONResponse({"path": path, "content": p.read_text()[:60000]})


async def _scheduler_loop():
    while True:
        try:
            await asyncio.to_thread(scheduler.tick, brain)
        except Exception as e:  # keep the dashboard alive whatever happens
            print("scheduler tick error:", e)
        await asyncio.sleep(5)


async def api_memory(request: Request):
    body = await request.json()
    content = (body.get("content") or "").strip()
    if not content:
        return JSONResponse({"error": "empty"}, status_code=400)
    m = brain.remember(content, agent="pribin", kind=body.get("kind", "note"), importance=int(body.get("importance", 4)))
    return JSONResponse({"id": m.id})


app = Starlette(routes=[
    Route("/", index),
    Route("/api/state", api_state),
    Route("/api/events", api_events),
    Route("/api/run", api_run, methods=["POST"]),
    Route("/api/approve", api_approve, methods=["POST"]),
    Route("/api/memory", api_memory, methods=["POST"]),
    Route("/api/tasks", api_tasks, methods=["GET", "POST"]),
    Route("/api/applied", api_applied, methods=["POST"]),
    Route("/api/runs", api_runs),
    Route("/api/file", api_file),
    Route("/api/agent", api_agent),
    Route("/api/stats", api_stats),
], lifespan=_lifespan)

if __name__ == "__main__":
    print(f"Agent HQ dashboard: http://localhost:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
