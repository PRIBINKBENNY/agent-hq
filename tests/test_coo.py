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
    assert tools.tune("max_parallel", "too many", value=9).startswith("refused")
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
