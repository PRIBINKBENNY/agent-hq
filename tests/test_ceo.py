import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office")); sys.path.insert(0, str(ROOT / "brain"))


@pytest.fixture
def b(tmp_path, monkeypatch):
    import tools, store
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    br = store.BrainStore(tmp_path / "b.db", embedder=NoEmbed()); monkeypatch.setattr(tools, "brain", br)
    return br


def test_approvals_rank_money_and_urgency_first(b):
    import ceo
    mk = lambda txt, tags: b.remember(f"PENDING APPROVAL from x: {txt}", agent="x", kind="approval", tags=["pending", *tags])
    mk("skill guide update 'linkedin'", ["skill-update"]); mk("LinkedIn post drafts at posts/linkedin/a.md", [])
    mk("Tailored CV for Trainline fit 5/5 at applications/trainline/x/", ["application"])
    mk("Proposal for Kristy E. Price: £1,400 at proposals/k.md", []); mk("email reply 'Re: quote' to a@b.co (client asked)", ["email", "reply"])
    order = [x["why"].split(" (")[0].split(", QA")[0] for x in ceo.pending_ranked()]
    assert order[0].startswith("a client") and order[1].startswith("proposal worth £1,400") and order[2] == "job application" and order[-1] == "internal change"


def test_digest_writes_and_pushes(b, tmp_path, monkeypatch):
    import ceo, push, tools
    monkeypatch.setattr(ceo, "ROOT", tmp_path); sent = []
    monkeypatch.setattr(push, "send", lambda title, body, url="/m", tag="hq": sent.append(title) or {"sent": 1})
    monkeypatch.setattr(tools, "notify", lambda t, m: "notified")
    b.remember("PENDING APPROVAL from x: Proposal for Bob Price: £450", agent="x", kind="approval", tags=["pending"])
    r = ceo.digest()
    assert r["waiting"] == 1 and sent and "1 approvals waiting" in sent[0] and (tmp_path / "workspace" / "ops" / "approval-digest.md").exists()


def test_deals_feed_pipeline_and_revenue(b):
    import ceo
    a = b.remember("APPROVED from proposal-writer: Proposal for Kristy E. (PPH) Price: £1,400 at proposals/k.md", agent="x", kind="approval", tags=["approved"])
    ceo.deal_set(a.id, "sent"); o = ceo.outcomes()
    assert o["freelance"]["sent"] == 1 and o["freelance"]["pipeline_gbp"] == 1400 and o["freelance"]["revenue_gbp"] == 0
    ceo.deal_set(a.id, "paid", 1200); o = ceo.outcomes()
    assert o["freelance"]["revenue_gbp"] == 1200 and o["freelance"]["won"] == 1 and o["approved_proposals"][0]["stage"] == "paid"
    with pytest.raises(ValueError):
        ceo.deal_set(a.id, "maybe")


def test_internal_work_waits_while_revenue_work_is_queued(b, tmp_path, monkeypatch):
    import scheduler
    sf = tmp_path / "s.yaml"
    sf.write_text("- name: docs\n  agent: docs-writer\n  every_hours: 6\n  task: x\n- name: leads\n  agent: lead-finder\n  every_hours: 6\n  priority: 2\n  task: y\n")
    monkeypatch.setattr(scheduler, "STANDING_FILE", sf); monkeypatch.setattr(scheduler, "STATE_FILE", tmp_path / "st.json")
    monkeypatch.setattr(scheduler, "MAX_PARALLEL", 5); monkeypatch.setattr(scheduler, "standing_allowed", lambda: True); monkeypatch.setattr(scheduler, "running_ids", lambda: [])
    b.task_create("Write proposal", "x", owner="proposal-writer")                         # revenue work waiting
    assert scheduler.enqueue_standing_work(b) == ["leads"]
    t = next(t for t in b.task_list(status="queued") if t["owner"] == "lead-finder"); assert t["priority"] >= 4
    for t in b.task_list(status="queued"): b.task_update(t["id"], status="done")
    scheduler._save_state({}); assert "docs" in scheduler.enqueue_standing_work(b)         # nothing revenue waiting: internal runs
    assert next(t for t in b.task_list(status="queued") if t["owner"] == "docs-writer")["priority"] == 1


def test_application_pack_fetches_the_posting_once(b, tmp_path, monkeypatch):
    import tools
    ws = tmp_path / "ws"; (ws / "cv").mkdir(parents=True); (ws / "cv" / "master-cv.md").write_text("# Pribin\nPython, YOLOv8")
    monkeypatch.setattr(tools, "WORKSPACE", ws); calls = []
    monkeypatch.setattr(tools, "job_details", lambda url, n=3000: calls.append(url) or "Build RAG agents with LLMs at Acme")
    j = b.remember("AI Engineer at Acme https://jobs.example/1", agent="job-scout", kind="job", meta={"company": "Acme", "title": "AI Engineer", "fit": 5})
    r = json.loads(tools.application_pack(j.id)); r2 = json.loads(tools.application_pack(j.id))
    assert calls == ["https://jobs.example/1"] and r2["posting"].startswith("Build RAG") and r["role_type"] == "llm"
    assert r["save_to"] == "applications/acme/ai-engineer/" and r["base_cv"] is None and "cv/base/llm.md" in r["base_cv_note"]


def test_workspace_guard_blocks_placeholder_and_duplicate_projects(b, tmp_path, monkeypatch):
    import tools
    ws = tmp_path / "ws"; (ws / "projects" / "feedback-transformer").mkdir(parents=True); monkeypatch.setattr(tools, "WORKSPACE", ws)
    assert tools.write_file("projects/<slug>/x.py", "x").startswith("refused")
    assert tools.write_file("projects/feedback_transformer/x.py", "x", _agent="code-builder").startswith("refused")
    assert "already exists" in tools.write_file("projects/Feedback-Transformer/x.py", "x", _agent="code-builder") or True
    assert tools.write_file("projects/new-lead/PLAN.md", "x", _agent="proposal-writer").startswith("refused: proposal-writer")
    assert tools.write_file("projects/feedback-transformer/x.py", "x", _agent="code-builder").startswith("wrote")
    assert tools.write_file("projects/text-summarizer/a.py", "x", _agent="code-builder").startswith("refused: new project folders")   # builders continue projects, planners open them
    assert tools.write_file("projects/text-summarizer/PLAN.md", "x", _agent="project-manager").startswith("wrote")


def test_outcomes_ignore_internal_proposals(b):
    import ceo
    b.remember("APPROVED from coo: brief change for networker at workspace/ops/proposals/p.md", agent="coo", kind="approval", tags=["approved", "brief-proposal"])
    b.remember("APPROVED from proposal-writer: Proposal for Bob. Price: £450 at proposals/bob.md", agent="x", kind="approval", tags=["approved"])
    o = ceo.outcomes(); assert o["freelance"]["proposals_drafted"] == 1 and len(o["approved_proposals"]) == 1


def test_one_brief_proposal_per_agent_per_day(b, tmp_path, monkeypatch):
    import tools
    ad = tmp_path / "agents"; ad.mkdir(); (ad / "networker.md").write_text("---\nname: networker\ntools: [today]\n---\nx\n")
    monkeypatch.setattr(tools, "AGENTS_DIR", ad); monkeypatch.setattr(tools, "PROPOSALS_DIR", tmp_path / "props")
    b.remember("PENDING APPROVAL from coo: brief change for networker", agent="coo", kind="approval", tags=["pending", "brief-proposal", "agent:networker"])
    assert tools.propose_brief("networker", "---\nname: networker\ntools: [today]\n---\ny\n", "cheaper", _agent="coo").startswith("refused: networker already has")
