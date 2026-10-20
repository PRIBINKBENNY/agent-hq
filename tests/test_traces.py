import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "office"))


def test_spans_for_run_builds_root_and_tool_spans(tmp_path, monkeypatch):
    import traces
    ev = tmp_path / "events.jsonl"
    rows = [{"ts": 100.0, "type": "start", "agent": "tracker", "run_id": "abc12345", "depth": 0, "task": "do x"},
            {"ts": 100.5, "type": "tool", "agent": "tracker", "run_id": "abc12345", "depth": 0, "tool": "read_file", "args": {"path": "a.md"}},
            {"ts": 101.5, "type": "tool_result", "agent": "tracker", "run_id": "abc12345", "depth": 0, "tool": "read_file", "preview": "hello", "ok": True},
            {"ts": 101.6, "type": "fallback", "agent": "tracker", "run_id": "abc12345", "depth": 0, "model": "groq:x"},
            {"ts": 102.0, "type": "tool", "agent": "tracker", "run_id": "abc12345", "depth": 0, "tool": "write_file", "args": {"path": "b.md"}},
            {"ts": 102.2, "type": "tool_result", "agent": "tracker", "run_id": "abc12345", "depth": 0, "tool": "write_file", "preview": "ERROR: nope", "ok": False},
            {"ts": 103.0, "type": "done", "agent": "tracker", "run_id": "abc12345", "depth": 0, "answer": "DONE", "model": "groq:y", "tokens": 1234},
            {"ts": 103.0, "type": "done", "agent": "other", "run_id": "zzz", "depth": 0, "answer": "x"}]
    ev.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setattr(traces, "EVENTS", ev); monkeypatch.setattr(traces, "OUT", tmp_path / "traces")
    t = traces.spans_for_run("abc12345")
    assert t["agent"] == "tracker" and t["seconds"] == 3.0
    spans = t["otlp"]["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert [s["name"] for s in spans] == ["run tracker", "tool read_file", "tool write_file"]
    assert spans[1]["endTimeUnixNano"] - spans[1]["startTimeUnixNano"] == 1_000_000_000 and spans[1]["status"]["code"] == 1
    assert spans[2]["status"]["code"] == 2 and spans[2]["parentSpanId"] == spans[0]["spanId"]
    assert len(spans[0]["events"]) == 1 and spans[0]["events"][0]["name"] == "fallback"
    wf = {w["name"]: w for w in t["waterfall"]}
    assert wf["read_file"]["end"] == 1.5 and wf["write_file"]["ok"] is False and wf["run tracker"]["depth"] == 0
    assert traces.export_all() == 2 and (tmp_path / "traces" / "abc12345.json").exists()   # both finished runs
    assert "error" in traces.spans_for_run("nothere")
