#!/usr/bin/env python3
"""
Agent eval: a fixed task set with known-correct behaviour, run against each active provider.

  .venv/bin/python office/eval/run_eval.py            # all tasks, every provider with a key, plus ollama
  .venv/bin/python office/eval/run_eval.py --quick    # first 5 tasks, first provider only
  .venv/bin/python office/eval/run_eval.py --provider cerebras --tasks date,recall-profile

Scores per (provider, task): expected tools called, forbidden tools avoided, regex on the answer,
expected files written, and whether the runtime's claim guard fired (an unbacked claim). Writes
office/eval/results/<date>.json and prints a table. Fabrication rate = tasks with an unbacked claim
or a forbidden regex hit / tasks run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "office")); sys.path.insert(0, str(ROOT / "brain"))

import runtime  # noqa: E402
from runtime import Agent, load_brief, active_providers, OLLAMA_MODEL  # noqa: E402
from tools import registry, WORKSPACE  # noqa: E402

RESULTS = ROOT / "office" / "eval" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)


def run_one(task: dict, provider: str) -> dict:
    brief = load_brief(task["agent"])
    brief.model = None                      # evaluate the provider's own default chain
    agent = Agent(brief, registry, engine=provider, verbose=False)
    claimed = {"fired": False}
    orig = runtime.unbacked_claim
    def spy(answer, calls, allowed):
        r = orig(answer, calls, allowed)
        if r:
            claimed["fired"] = True
        return r
    runtime.unbacked_claim = spy
    t0 = time.time(); err = None
    try:
        res = agent.run(task["task"])
        answer, used = res.answer, [c["tool"] for c in res.tool_calls]
        model, tokens = res.model_used, res.tokens_in + res.tokens_out
    except Exception as e:
        answer, used, model, tokens, err = "", [], "", 0, f"{type(e).__name__}: {str(e)[:120]}"
    finally:
        runtime.unbacked_claim = orig
    checks = {}
    if task.get("expect_tools"):
        checks["expected_tool"] = any(t in used for t in task["expect_tools"])
    if task.get("forbid_tools"):
        checks["no_forbidden_tool"] = not any(t in used for t in task["forbid_tools"])
    if task.get("expect_regex"):
        checks["answer_matches"] = bool(re.search(task["expect_regex"], answer))
    if task.get("forbid_regex"):
        checks["no_forbidden_text"] = not re.search(task["forbid_regex"], answer)
    if task.get("expect_file"):
        f = WORKSPACE / task["expect_file"]
        ok = f.exists() and (not task.get("expect_file_regex") or re.search(task["expect_file_regex"], f.read_text()))
        checks["file_written"] = bool(ok)
        if f.exists():
            f.unlink()
    checks["no_unbacked_claim"] = not claimed["fired"]
    passed = all(checks.values()) and err is None
    fabricated = claimed["fired"] or checks.get("no_forbidden_text") is False
    return {"task": task["id"], "provider": provider, "model": model, "pass": passed, "fabricated": fabricated,
            "checks": checks, "error": err, "seconds": round(time.time() - t0, 1), "tokens": tokens,
            "tools": used, "answer": answer[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--provider", help="cerebras | groq | mistral | gemini | ollama (default: all active + ollama)")
    ap.add_argument("--tasks", help="comma-separated task ids")
    a = ap.parse_args()
    tasks = json.loads((ROOT / "office" / "eval" / "tasks.json").read_text())
    if a.tasks:
        want = set(a.tasks.split(",")); tasks = [t for t in tasks if t["id"] in want]
    providers = [a.provider] if a.provider else active_providers() + ["ollama"]
    if a.quick:
        tasks = tasks[:5]; providers = providers[:1]
    rows = []
    for prov in providers:
        for t in tasks:
            r = run_one(t, prov); rows.append(r)
            print(f"{prov:<9} {t['id']:<18} {'PASS' if r['pass'] else 'FAIL':<5} {'FAB' if r['fabricated'] else '   '} {r['seconds']:>6}s  {r['model']}"
                  + (f"  {r['error']}" if r["error"] else ""), flush=True)
    summary = {}
    for prov in providers:
        mine = [r for r in rows if r["provider"] == prov]
        summary[prov] = {"tasks": len(mine), "pass_rate": round(sum(r["pass"] for r in mine) / max(1, len(mine)), 2),
                         "fabrication_rate": round(sum(r["fabricated"] for r in mine) / max(1, len(mine)), 2),
                         "avg_seconds": round(sum(r["seconds"] for r in mine) / max(1, len(mine)), 1)}
    out = {"date": time.strftime("%Y-%m-%d %H:%M"), "summary": summary, "rows": rows}
    path = RESULTS / f"{time.strftime('%Y-%m-%d_%H%M')}.json"
    path.write_text(json.dumps(out, indent=1))
    print("\nSUMMARY"); [print(f"  {k:<9} pass {v['pass_rate']:.0%}  fabrication {v['fabrication_rate']:.0%}  avg {v['avg_seconds']}s") for k, v in summary.items()]
    print("saved", path.relative_to(ROOT))
    try:
        from store import BrainStore
        BrainStore().remember("Agent eval " + out["date"] + ": " + "; ".join(f"{k} pass {v['pass_rate']:.0%} fab {v['fabrication_rate']:.0%}" for k, v in summary.items()),
                              agent="eval", kind="event", importance=3, tags=["eval"])
    except Exception:
        pass


if __name__ == "__main__":
    main()
