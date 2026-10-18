import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office")); sys.path.insert(0, str(ROOT / "brain"))


@pytest.fixture
def ops(tmp_path, monkeypatch):
    import tools, store, yaml
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    b = store.BrainStore(tmp_path / "b.db", embedder=NoEmbed()); monkeypatch.setattr(tools, "brain", b)
    monkeypatch.setattr(tools, "TUNING_FILE", tmp_path / "tuning.json"); (tmp_path / "tuning.json").write_text(json.dumps({"max_parallel": 2, "run_token_budget": 60000}))
    monkeypatch.setattr(tools, "STANDING_FILE", tmp_path / "standing.yaml")
    (tmp_path / "standing.yaml").write_text(yaml.safe_dump([{"name": "scout-rotation", "agent": "job-scout", "every_hours": 6, "task": "x"}]))
    agents = tmp_path / "agents"; agents.mkdir(); (agents / "tracker.md").write_text("---\nname: tracker\noffice: ops\ntier: worker\ntools: []\ndelegates: []\n---\nold brief\n")
    monkeypatch.setattr(tools, "AGENTS_DIR", agents); monkeypatch.setattr(tools, "PROPOSALS_DIR", tmp_path / "proposals"); monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    return tools, b


def test_tune_is_bounded_and_logged(ops):
    tools, b = ops
    assert tools.tune("max_parallel", "more throughput", value=3).endswith("2 -> 3")
    assert tools.tune("max_parallel", "too many", value=40).startswith("refused")
    assert tools.tune("nonsense", "x", value=1).startswith("refused")
    assert "every_hours=12.0" in tools.tune("standing:scout-rotation", "budget low", value=12)
    assert tools.tune("standing:scout-rotation", "x", value=500).startswith("refused")
    assert tools.tune("standing:nope", "x", value=5).startswith("refused")
    assert json.loads(tools.TUNING_FILE.read_text())["max_parallel"] == 3
    assert sum(1 for m in b.recent(limit=10) if "COO tune" in m.content) == 2


def test_brief_proposal_requires_approval_then_applies(ops):
    tools, b = ops
    new = "---\nname: tracker\noffice: ops\ntier: worker\ntools: []\ndelegates: []\n---\nnew, tighter brief\n"
    assert tools.propose_brief("tracker", "not a brief", "r").startswith("refused")
    r = tools.propose_brief("tracker", new, "averages 46k tokens/run", _agent="coo")
    assert "approval #" in r
    m = [x for x in b.recent(limit=5, kind="approval")][0]
    assert "brief-proposal" in m.tags and "pending" in m.tags
    assert tools.apply_proposal(m.id).startswith("refused")                      # not approved
    b.update(m.id, tags=[t for t in m.tags if t != "pending"] + ["approved"])
    assert tools.apply_proposal(m.id, _agent="chief-of-staff").startswith("applied")
    assert (tools.AGENTS_DIR / "tracker.md").read_text() == new
    assert list((tools.AGENTS_DIR / ".backups").glob("tracker-*.md"))
    assert tools.apply_proposal(m.id) == "already applied"


def test_ops_metrics_shape(ops, monkeypatch):
    tools, b = ops
    import scheduler
    monkeypatch.setattr(scheduler, "budget", lambda: {"cerebras": {"day": 0.9, "minute": 0.9, "ok": True}})
    d = json.loads(tools.ops_metrics(24))
    for k in ("runs", "tokens", "by_agent", "tasks", "continuations", "timeouts", "approvals_pending", "budget", "knobs", "knob_bounds", "standing"):
        assert k in d
    assert d["knobs"]["max_parallel"] == 2 and d["standing"][0]["name"] == "scout-rotation"


def test_git_push_undoes_a_fresh_repo_when_the_first_commit_fails(tmp_path, monkeypatch):
    import tools
    proj = tmp_path / "proj"; proj.mkdir(); (proj / "README.md").write_text("hi\n")
    monkeypatch.setattr(tools, "_gh_user", lambda: "someone"); monkeypatch.setattr(tools, "_safe", lambda p: proj)
    real = tools._run
    def fake_run(cmd, cwd, timeout):
        if "commit" in cmd:
            return "fatal: simulated commit failure\n[exit 128]\n"
        return real(cmd, cwd, timeout)
    monkeypatch.setattr(tools, "_run", fake_run)
    out = tools.git_push("proj", message="first")
    assert out.startswith("ERROR: commit failed") and not (proj / ".git").exists()     # no half-made repo left behind


def test_a_broken_brief_never_stops_the_office(tmp_path, monkeypatch):
    import runtime as rt
    d = tmp_path / "agents"; d.mkdir()
    (d / "good.md").write_text("---\nname: good\ntier: lead\ntools: [today]\n---\nDo good work.\n")
    (d / "bad.md").write_text("---\nname: bad\ndescription: Finds paths: people to connect with\n---\nx\n")   # the 2026-10-18 crash
    monkeypatch.setattr(rt, "AGENTS_DIR", d)
    names = [b.name for b in rt.list_agents()]
    assert names == ["good"] and "bad" in rt.BRIEF_ERRORS


def test_brief_proposals_change_instructions_only_and_roll_back(tmp_path, monkeypatch):
    import tools, store, runtime as rt
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    b = store.BrainStore(tmp_path / "b.db", embedder=NoEmbed()); monkeypatch.setattr(tools, "brain", b)
    ad = tmp_path / "agents"; ad.mkdir(); pd = tmp_path / "props"; pd.mkdir()
    for mod in (tools, rt): monkeypatch.setattr(mod, "AGENTS_DIR", ad)
    monkeypatch.setattr(tools, "PROPOSALS_DIR", pd)
    head = "---\nname: networker\ntier: lead\ncloud_only: true\ntools: [today, request_approval]\nskills: [linkedin]\n---\n"
    (ad / "networker.md").write_text(head + "Old instructions. request_approval before anything goes out.\n")
    bad_brief = "---\nname: networker\ndescription: Finds paths: people\ntools: [today]\nmax_turns: 12\n---\nNew, shorter instructions; request_approval first.\n"
    (pd / "p.md").write_text("# proposal\n\n## Full proposed brief\n\n" + bad_brief)
    m = b.remember("APPROVED from coo: brief change for networker at workspace/ops/proposals/p.md", agent="coo", kind="approval",
                   tags=["approved", "brief-proposal", "agent:networker"])
    out = tools.apply_proposal(m.id)
    text = (ad / "networker.md").read_text()
    assert "Brief updated" in out or "updated" in out.lower() or "applied" in out.lower()
    assert text.startswith(head) and "New, shorter instructions" in text and "max_turns" not in text   # settings kept, body replaced
    assert rt.load_brief("networker").cloud_only and "request_approval" in rt.load_brief("networker").tools


def test_coo_cannot_undo_unlimited_mode(tmp_path, monkeypatch):
    import tools, json as _j
    tf = tmp_path / "t.json"; tf.write_text(_j.dumps({"unlimited": True, "max_parallel": 31, "standing_per_hour": 0})); monkeypatch.setattr(tools, "TUNING_FILE", tf)
    assert tools.tune("max_parallel", "save quota", value=1).startswith("refused: unlimited")
    assert tools.tune("standing_per_hour", "pace", value=4).startswith("refused: unlimited")
