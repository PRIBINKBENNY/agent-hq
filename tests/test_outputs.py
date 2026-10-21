import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "office"))


def test_outputs_recent_lists_documents_with_agent_attribution(tmp_path, monkeypatch):
    import tools
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path); monkeypatch.setattr(tools, "ROOT", tmp_path)
    (tmp_path / "interviews" / "drills").mkdir(parents=True); (tmp_path / "interviews" / "drills" / "2026-10-21.md").write_text("drill")
    (tmp_path / "projects" / "x").mkdir(parents=True); (tmp_path / "projects" / "x" / "README.md").write_text("r"); (tmp_path / "projects" / "x" / "a.py").write_text("code")
    (tmp_path / ".trash").mkdir(); (tmp_path / ".trash" / "old.md").write_text("junk")
    (tmp_path / "office" / "logs").mkdir(parents=True)
    (tmp_path / "office" / "logs" / "events.jsonl").write_text(json.dumps({"ts": time.time(), "type": "tool", "agent": "interview-coach", "tool": "write_file", "args": {"path": "interviews/drills/2026-10-21.md", "content": "x"}}) + "\n")
    out = tools.outputs_recent(7)
    paths = {o["path"]: o for o in out}
    assert "interviews/drills/2026-10-21.md" in paths and paths["interviews/drills/2026-10-21.md"]["agent"] == "interview-coach"
    assert "projects/x/README.md" in paths and "projects/x/a.py" not in paths and not any(".trash" in p for p in paths)
    assert paths["interviews/drills/2026-10-21.md"]["folder"] == "interviews" and paths["projects/x/README.md"]["folder"] == "projects/x"


def test_builder_briefs_carry_a_tool_budget():
    import runtime
    briefs = {b.name: b for b in runtime.list_agents()}
    assert briefs["code-builder"].max_tool_calls == 30 and briefs["tester"].max_tool_calls == 20 and briefs["chief-of-staff"].max_tool_calls == 0
