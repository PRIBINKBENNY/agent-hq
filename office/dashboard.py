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
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

TOKEN = (os.environ.get("DASHBOARD_TOKEN") or "").strip()
LOCAL_IPS = {"127.0.0.1", "::1", "localhost"}


class AuthMiddleware(BaseHTTPMiddleware):
    """Trusted from this Mac; from anywhere else (tunnel, LAN, phone) a token cookie or Bearer header is required."""
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path in ("/login", "/manifest.json", "/sw.js", "/icon.png", "/api/vapid") or path.startswith("/static/"):
            return await call_next(request)
        client = request.client.host if request.client else ""
        via_tunnel = any(h in request.headers for h in ("cf-connecting-ip", "x-forwarded-for", "tailscale-user-login"))
        if client in LOCAL_IPS and not via_tunnel:
            return await call_next(request)
        if not TOKEN:
            return Response("Set DASHBOARD_TOKEN in .env to allow remote access.", status_code=403)
        auth = request.headers.get("authorization", "")
        if request.cookies.get("hq") == TOKEN or auth == f"Bearer {TOKEN}":
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"error": "unauthorised"}, status_code=401)
        return RedirectResponse(f"/login?next={path}")


LOGIN_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Agent HQ</title>
<style>body{margin:0;background:#080b14;color:#e6eaf2;font:16px -apple-system,system-ui,sans-serif;display:grid;place-items:center;height:100vh}
form{background:#10151f;border:1px solid #232b3a;border-radius:14px;padding:26px;width:min(340px,90vw)}h1{font-size:18px;margin:0 0 14px}
input{width:100%;box-sizing:border-box;background:#080b14;border:1px solid #232b3a;color:#e6eaf2;padding:12px;border-radius:9px;font-size:16px;margin-bottom:10px}
button{width:100%;background:#5b8def;border:0;color:#fff;padding:12px;border-radius:9px;font-size:16px;font-weight:700}</style></head>
<body><form method="post" action="/login"><h1>Agent HQ</h1><input type="password" name="token" placeholder="Access token" autofocus><input type="hidden" name="next" value="NEXT"><button>Enter</button></form></body></html>"""


async def login(request: Request):
    nxt = request.query_params.get("next", "/m")
    if request.method == "POST":
        form = await request.form()
        if TOKEN and form.get("token", "").strip() == TOKEN:
            resp = RedirectResponse(form.get("next") or "/m", status_code=303)
            resp.set_cookie("hq", TOKEN, max_age=90 * 86400, httponly=True, samesite="lax", secure=request.url.scheme == "https")
            return resp
        return HTMLResponse(LOGIN_HTML.replace("NEXT", nxt).replace("<h1>Agent HQ</h1>", "<h1>Agent HQ</h1><p style='color:#ef5b6e;margin:0 0 10px'>Wrong token</p>"), status_code=401)
    return HTMLResponse(LOGIN_HTML.replace("NEXT", nxt))

from events import EVENTS_FILE, read_tail  # noqa: E402
from runtime import list_agents, OLLAMA_MODEL, active_providers, provider_models, read_usage  # noqa: E402
from tools import WORKSPACE  # noqa: E402
from store import BrainStore  # noqa: E402
import scheduler  # noqa: E402
import push  # noqa: E402

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
        "running_tasks": scheduler.running_ids(), "max_parallel": scheduler.MAX_PARALLEL, "budget": scheduler.budget(),
        "now": time.time(),
    }


async def index(_: Request):
    return HTMLResponse(HTML_PATH.read_text())


STATIC = ROOT / "office" / "static"


async def mobile(_: Request):
    return HTMLResponse((STATIC / "mobile.html").read_text())


async def manifest(_: Request):
    return Response((STATIC / "manifest.json").read_text(), media_type="application/manifest+json")


async def sw(_: Request):
    return Response((STATIC / "sw.js").read_text(), media_type="application/javascript", headers={"Service-Worker-Allowed": "/"})


async def icon(_: Request):
    from starlette.responses import FileResponse
    return FileResponse(str(STATIC / "icon.png"), media_type="image/png")


async def api_vapid(_: Request):
    return JSONResponse({"key": push.public_key()})


async def api_push_subscribe(request: Request):
    sub = await request.json()
    if not sub.get("endpoint"):
        return JSONResponse({"error": "bad subscription"}, status_code=400)
    return JSONResponse({"subscribers": push.subscribe(sub)})


async def api_push_test(_: Request):
    return JSONResponse(await asyncio.to_thread(push.send, "Agent HQ", "Notifications are working.", "/m", "test"))


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
    """No free slot: the scheduler's parallel slots are full (UI runs then queue and start within seconds)."""
    direct = sum(1 for p in _procs.values() if p.poll() is None)
    return len(scheduler.running_ids()) + direct >= scheduler.MAX_PARALLEL


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


_caffeinate: subprocess.Popen | None = None


@contextlib.asynccontextmanager
async def _lifespan(app):
    global _caffeinate
    task = asyncio.create_task(_scheduler_loop())
    if sys.platform == "darwin" and os.environ.get("HQ_KEEP_AWAKE", "1") == "1":
        try:  # keep the Mac awake (on mains power) for as long as the office runs; no sudo needed
            _caffeinate = subprocess.Popen(["/usr/bin/caffeinate", "-s", "-i", "-w", str(os.getpid())])
        except Exception:
            _caffeinate = None
    try:
        yield
    finally:
        task.cancel()
        if _caffeinate:
            _caffeinate.terminate()


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


_trading_cache: dict = {"ts": 0, "data": None}


def _trading() -> dict:
    from tools import registry as _reg
    import capital
    out = {"configured": capital.configured(), "mode": "LIVE" if capital.is_live() else "DEMO", "account": None, "positions": [], "recent": []}
    if out["configured"]:
        try:
            out["account"] = json.loads(_reg.call("capital_account", {}))
            pos = _reg.call("capital_positions", {})
            out["positions"] = json.loads(pos) if pos.startswith("[") else []
        except Exception as e:
            out["error"] = str(e)[:160]
    out["recent"] = [m.to_dict() for m in brain.recent(limit=8, tags=["trade"])] + \
                    [m.to_dict() for m in brain.recent(limit=6, kind="decision") if "risk" in m.tags][:6]
    out["recent"].sort(key=lambda m: m["created_at"], reverse=True)
    out["signals"] = [m.to_dict() for m in brain.recent(limit=5, tags=["signal"])]
    return out


async def api_trading(_: Request):
    if _trading_cache["data"] is not None and time.time() - _trading_cache["ts"] < 60:
        return JSONResponse(_trading_cache["data"])
    data = await asyncio.to_thread(_trading)
    _trading_cache.update(ts=time.time(), data=data)
    return JSONResponse(data)


async def api_schedule(_: Request):
    """Upcoming scheduled jobs with their next expected time."""
    import yaml
    from datetime import datetime, timedelta
    jobs = yaml.safe_load(scheduler.SCHEDULE_FILE.read_text()) or []
    st = scheduler._load_state(); now = datetime.now(); out = []
    for j in jobs:
        if not j.get("enabled", True):
            continue
        every = j.get("every", "daily"); last = st.get(j["name"])
        if every == "hourly":
            nxt = (datetime.fromtimestamp(last) + timedelta(hours=1)) if last else now
            if j.get("hours"):
                lo, hi = [int(x) for x in str(j["hours"]).split("-")]
                if nxt.hour > hi or nxt.weekday() >= 5:
                    d = nxt + timedelta(days=1)
                    while d.weekday() >= 5:
                        d += timedelta(days=1)
                    nxt = d.replace(hour=lo, minute=0, second=0)
                elif nxt.hour < lo:
                    nxt = nxt.replace(hour=lo, minute=0, second=0)
        else:
            hh, mm = [int(x) for x in j.get("at", "08:00").split(":")]
            cand = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            ran_today = last and datetime.fromtimestamp(last).date() == now.date()
            if cand <= now or ran_today:
                cand += timedelta(days=1)
            if every == "weekdays":
                while cand.weekday() >= 5:
                    cand += timedelta(days=1)
            if every == "weekly":
                want = scheduler.DAYS.index(j.get("day", "sunday").lower())
                while cand.weekday() != want:
                    cand += timedelta(days=1)
            nxt = cand
        out.append({"name": j["name"], "title": j.get("title", j["name"]), "agent": j.get("agent", "command"), "every": every,
                    "next": nxt.strftime("%a %H:%M"), "next_ts": nxt.timestamp(), "last": datetime.fromtimestamp(last).strftime("%a %H:%M") if last else None})
    out.sort(key=lambda x: x["next_ts"])
    return JSONResponse({"jobs": out, "busy": scheduler.busy()})


async def api_brain_search(request: Request):
    q = request.query_params.get("q", "").strip()
    kind = request.query_params.get("kind") or None
    res = await asyncio.to_thread(brain.recall, q, 12, "*", None, kind)
    return JSONResponse({"results": [m.to_dict() for m in res]})


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


app = Starlette(middleware=[Middleware(AuthMiddleware)], routes=[
    Route("/login", login, methods=["GET", "POST"]),
    Route("/m", mobile),
    Route("/manifest.json", manifest),
    Route("/sw.js", sw),
    Route("/icon.png", icon),
    Route("/api/vapid", api_vapid),
    Route("/api/push/subscribe", api_push_subscribe, methods=["POST"]),
    Route("/api/push/test", api_push_test, methods=["POST"]),
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
    Route("/api/trading", api_trading),
    Route("/api/schedule", api_schedule),
    Route("/api/brain/search", api_brain_search),
    Route("/api/stats", api_stats),
], lifespan=_lifespan)

if __name__ == "__main__":
    print(f"Agent HQ dashboard: http://localhost:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
