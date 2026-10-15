#!/usr/bin/env python3
"""
Talk to the office.

  python office/run.py "find 5 ML engineer jobs in London posted this week"
      -> goes to the Chief of Staff, who delegates to the right agents

  python office/run.py --agent job-scout "find ML jobs in London"
      -> run one agent directly

  python office/run.py --list              # agents on the roster
  python office/run.py --approvals         # what is waiting for your OK
  python office/run.py --engine ollama ... # force local (free, slow)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime import Agent, load_brief, list_agents  # noqa: E402
from tools import registry, brain  # noqa: E402


def main():
    p = argparse.ArgumentParser(prog="office")
    p.add_argument("task", nargs="?", help="what you want done")
    p.add_argument("--agent", default="chief-of-staff")
    p.add_argument("--engine", default="auto", help="auto | ollama | a provider name (cerebras, groq, mistral, gemini)")
    p.add_argument("--list", action="store_true")
    p.add_argument("--approvals", action="store_true")
    p.add_argument("--providers", action="store_true", help="show the free-tier provider pool and ping each one")
    p.add_argument("--doctor", action="store_true", help="health check: providers, launch agent, scheduler, brain, approvals, disk")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--task-id", type=int, help="board task this run belongs to (set by the scheduler)")
    a = p.parse_args()

    if a.list:
        for b in list_agents():
            print(f"{b.name:<20} {b.office:<16} {b.tier:<7} tools={len(b.tools)} delegates={b.delegates or '-'}")
            if b.description:
                print(f"{'':<20} {b.description}")
        return
    if a.doctor:
        import json as _json, subprocess, shutil, time as _t
        from runtime import active_providers, read_usage
        ok = lambda c, msg: print(("  OK   " if c else "  FAIL ") + msg)
        print("Agent HQ doctor")
        import scheduler as _sch
        pz = _sch.paused(); print(("  INFO OFFICE PAUSED: " + pz.get("reason", "")) if pz.get("paused") else "  OK   office running (not paused)")
        ok(bool(active_providers()), f"providers with keys: {', '.join(active_providers()) or 'none (Ollama only)'}")
        from runtime import provider_down as _pd
        for prov, until in _pd().items():
            print(f"  WARN {prov} parked until {_t.strftime('%H:%M', _t.localtime(until))} (answered 401/402/403: key invalid or credits exhausted)")
        u = read_usage()
        for prov, d in u.items():
            day = d.get("x-ratelimit-remaining-tokens-day") or d.get("x-ratelimit-remaining-requests") or "?"
            print(f"       {prov}: tokens/min left {d.get('x-ratelimit-remaining-tokens-minute') or d.get('x-ratelimit-remaining-tokens') or '?'}, day left {day}")
        try:
            r = subprocess.run(["launchctl", "print", f"gui/{__import__('os').getuid()}/com.pribin.agenthq"], capture_output=True, text=True, timeout=10)
            ok("state = running" in r.stdout, "launch agent running (dashboard + scheduler)")
        except Exception:
            ok(False, "launch agent not found: run ./office/launchd/install.sh")
        try:
            import httpx
            ok(httpx.get("http://127.0.0.1:8787/api/state", timeout=5).status_code == 200, "dashboard answering on :8787")
        except Exception:
            ok(False, "dashboard not answering on :8787")
        ok(shutil.which("ollama") is not None, "ollama installed (local fallback)")
        st = brain.stats(); ok(st["total_memories"] > 0, f"brain: {st['total_memories']} memories, semantic={st['semantic_search']}, {st['db_size_mb']} MB")
        pend = [m for m in brain.recent(limit=50, kind="approval") if "pending" in m.tags]
        print(f"  INFO {len(pend)} approval(s) waiting for Pribin")
        tl = brain.task_list(limit=200); run = [t for t in tl if t["status"] == "running"]; q = [t for t in tl if t["status"] == "queued"]
        stale = [t for t in run if _t.time() - (t.get("started_at") or _t.time()) > 3600]
        ok(not stale, f"tasks: {len(run)} running, {len(q)} queued" + (f", {len(stale)} stuck > 1h" if stale else ""))
        try:
            sp = _json.load(open(Path(__file__).resolve().parent / "logs" / "schedule_state.json"))
            print("  INFO last scheduled runs: " + ", ".join(f"{k} {_t.strftime('%a %H:%M', _t.localtime(v))}" for k, v in list(sp.items())[:4]) + " ...")
        except Exception:
            print("  INFO no scheduled job has run yet")
        gh = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True); ok("Logged in" in (gh.stdout + gh.stderr), "GitHub CLI logged in")
        try:
            import re as _re
            tl = (Path(__file__).resolve().parent / "logs" / "tunnel.log").read_text()
            tu = _re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", tl)
            alive = subprocess.run(["pgrep", "-f", "cloudflared tunnel"], capture_output=True).returncode == 0
            print(f"  INFO phone app URL: {tu[-1] + '/m' if tu and alive else 'no tunnel running (./office/launchd/install.sh tunnel)'}")
        except Exception:
            print("  INFO phone app: no tunnel log yet")
        env = Path(__file__).resolve().parent.parent / ".env"; ok(env.exists() and (env.stat().st_mode & 0o777) == 0o600, ".env present with mode 600")
        return
    if a.providers:
        from runtime import PROVIDERS, PROVIDER_ORDER, active_providers, provider_models, provider_key, _call_model, EngineError, RateLimited, OLLAMA_MODEL
        for name in PROVIDER_ORDER:
            if name not in PROVIDERS:
                continue
            if not provider_key(name):
                print(f"{name:<9} no key ({PROVIDERS[name]['key_env']} in .env)")
                continue
            lead, worker = provider_models(name, "lead"), provider_models(name, "worker")
            try:
                r = _call_model([{"role": "user", "content": "Reply with the single word OK."}], [], lead[0], name, "worker")
                txt = (r["choices"][0]["message"].get("content") or "").strip()[:20]
                status = f"OK  ({txt!r})"
            except RateLimited as e:
                status = f"rate-limited, retry in {e}s"
            except (EngineError, Exception) as e:
                status = f"FAILED: {str(e)[:90]}"
            print(f"{name:<9} {status:<34} lead={lead[0]}  worker={worker[0]}")
        print(f"{'ollama':<9} local fallback                     model={OLLAMA_MODEL}")
        print("order:", " -> ".join(active_providers() + ["ollama"]))
        return
    if a.approvals:
        for m in brain.recent(limit=50, kind="approval"):
            print(f"#{m.id}  {m.to_dict()['created']}  {m.content}")
        return
    if not a.task:
        p.error("give a task")

    agent = Agent(load_brief(a.agent), registry, engine=a.engine, verbose=not a.quiet)
    if a.task_id:
        try:
            brain.task_update(a.task_id, agent="scheduler", status="running", run_id=agent.run_id)
        except KeyError:
            pass
    try:
        res = agent.run(a.task)
    except Exception as e:
        from events import emit
        emit("error", agent.brief.name, agent.run_id, 0, detail=f"{type(e).__name__}: {str(e)[:200]}")
        if a.task_id:
            brain.task_update(a.task_id, agent=agent.brief.name, status="failed", result=f"{type(e).__name__}: {str(e)[:500]}")
        print(f"run failed: {type(e).__name__}: {str(e)[:300]}", file=sys.stderr)
        sys.exit(1)
    if a.task_id:
        brain.task_update(a.task_id, agent=agent.brief.name, status="done", result=res.answer[:6000])
    print("\n" + "=" * 70)
    print(f"{res.agent}  ({res.model_used}, {res.turns} turns, {len(res.tool_calls)} tool calls)")
    print("=" * 70)
    print(res.answer)


if __name__ == "__main__":
    main()
