"""
Run traces in OpenTelemetry (OTLP/JSON) shape, built from the office's own event log. Each run is a trace: a root
span for the run, a child span per tool call (start = the tool event, end = its result), delegations as nested spans,
model fallbacks and thoughts as span events. No collector, no database: the dashboard draws the waterfall from
/api/trace, and `python office/traces.py --export` writes office/logs/traces/<run_id>.json files that Phoenix,
Langfuse or any OTLP viewer can import later.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "office" / "logs" / "events.jsonl"
OUT = ROOT / "office" / "logs" / "traces"


def _id(s: str, n: int) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:n]


def _ns(ts) -> int:
    return int(float(ts) * 1e9)


def events_for(run_id: str) -> list[dict]:
    out = []
    if not EVENTS.exists():
        return out
    with EVENTS.open() as f:
        for line in f:
            if run_id not in line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("run_id") == run_id:
                out.append(e)
    out.sort(key=lambda e: float(e.get("ts", 0)))
    return out


def spans_for_run(run_id: str) -> dict:
    """OTLP/JSON for one run. Also returns a flat 'waterfall' list the dashboard draws directly."""
    ev = events_for(run_id)
    if not ev:
        return {"error": f"no events for run {run_id}"}
    trace_id = _id(run_id, 32); spans = []; flat = []
    start = [e for e in ev if e["type"] == "start"]; done = [e for e in ev if e["type"] == "done"]
    t0 = float(start[0]["ts"]) if start else float(ev[0]["ts"]); t1 = float(done[-1]["ts"]) if done else float(ev[-1]["ts"])
    agent = (start[0] if start else ev[0]).get("agent", "?")
    root_id = _id(run_id + ":root", 16)
    root = {"traceId": trace_id, "spanId": root_id, "name": f"run {agent}", "kind": 1, "startTimeUnixNano": _ns(t0), "endTimeUnixNano": _ns(t1),
            "attributes": [{"key": "agent", "value": {"stringValue": agent}}, {"key": "task", "value": {"stringValue": (start[0].get("task") if start else "")[:300]}},
                           {"key": "model", "value": {"stringValue": (done[-1].get("model") if done else "")}},
                           {"key": "tokens", "value": {"intValue": int(done[-1].get("tokens", 0)) if done else 0}}],
            "events": [], "status": {"code": 1 if done and not str(done[-1].get("answer", "")).startswith("No final answer") else 2}}
    spans.append(root); flat.append({"name": root["name"], "start": 0.0, "end": round(t1 - t0, 2), "depth": 0, "ok": root["status"]["code"] == 1, "kind": "run"})
    open_tools: dict[tuple, dict] = {}; n = 0
    for e in ev:
        t = float(e["ts"]); typ = e["type"]; depth = int(e.get("depth", 0))
        if typ == "tool":
            key = (e.get("agent"), depth, e.get("tool")); n += 1
            sp = {"traceId": trace_id, "spanId": _id(f"{run_id}:{n}", 16), "parentSpanId": root_id, "name": f"tool {e.get('tool')}", "kind": 3,
                  "startTimeUnixNano": _ns(t), "endTimeUnixNano": _ns(t), "attributes": [{"key": "agent", "value": {"stringValue": e.get("agent", "")}},
                  {"key": "args", "value": {"stringValue": str(e.get("args", ""))[:300]}}], "status": {"code": 0}}
            open_tools[key] = sp; spans.append(sp)
            flat.append({"name": e.get("tool"), "start": round(t - t0, 2), "end": round(t - t0, 2), "depth": depth + 1, "ok": True, "kind": "tool", "agent": e.get("agent"), "args": str(e.get("args", ""))[:120]})
        elif typ == "tool_result":
            key = (e.get("agent"), depth, e.get("tool")); sp = open_tools.pop(key, None)
            if sp:
                sp["endTimeUnixNano"] = _ns(t); ok = str(e.get("ok", "True")) != "False"; sp["status"] = {"code": 1 if ok else 2}
                sp["attributes"].append({"key": "result", "value": {"stringValue": str(e.get("preview", ""))[:200]}})
                for fl in reversed(flat):
                    if fl["kind"] == "tool" and fl["name"] == e.get("tool") and fl["end"] == fl["start"]:
                        fl["end"] = round(t - t0, 2); fl["ok"] = ok; fl["result"] = str(e.get("preview", ""))[:120]; break
        elif typ in ("fallback", "think", "delegate", "say"):
            root["events"].append({"timeUnixNano": _ns(t), "name": typ, "attributes": [{"key": "detail", "value": {"stringValue": str({k: v for k, v in e.items() if k not in ("ts", "type", "run_id")})[:200]}}]})
            if typ in ("fallback", "delegate"):
                flat.append({"name": f"{typ}: {str(e.get('to') or e.get('model') or e.get('agent_to') or '')[:40]}", "start": round(t - t0, 2), "end": round(t - t0, 2), "depth": depth + 1, "ok": typ != "fallback", "kind": typ})
    return {"run_id": run_id, "agent": agent, "seconds": round(t1 - t0, 2), "waterfall": flat,
            "otlp": {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "agent-hq"}}]},
                                        "scopeSpans": [{"scope": {"name": "office.runtime"}, "spans": spans}]}]}}


def export_all(limit: int = 500) -> int:
    OUT.mkdir(parents=True, exist_ok=True); ids = []
    if EVENTS.exists():
        with EVENTS.open() as f:
            for line in f:
                if '"type": "done"' in line or '"type":"done"' in line:
                    try:
                        ids.append(json.loads(line).get("run_id"))
                    except json.JSONDecodeError:
                        pass
    n = 0
    for rid in [i for i in dict.fromkeys(reversed(ids)) if i][:limit]:
        p = OUT / f"{rid}.json"
        if p.exists():
            continue
        t = spans_for_run(rid)
        if "otlp" in t:
            p.write_text(json.dumps(t["otlp"])); n += 1
    return n


if __name__ == "__main__":
    if "--export" in sys.argv:
        print(f"exported {export_all()} traces to {OUT}")
    else:
        print(json.dumps(spans_for_run(sys.argv[1]), indent=1)[:3000])
