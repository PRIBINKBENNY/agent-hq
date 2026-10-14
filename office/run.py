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
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--task-id", type=int, help="board task this run belongs to (set by the scheduler)")
    a = p.parse_args()

    if a.list:
        for b in list_agents():
            print(f"{b.name:<20} {b.office:<16} {b.tier:<7} tools={len(b.tools)} delegates={b.delegates or '-'}")
            if b.description:
                print(f"{'':<20} {b.description}")
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
