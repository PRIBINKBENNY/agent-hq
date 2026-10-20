import json, sys, time, types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "office"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain"))


def test_research_status_reads_folders_not_handwritten_names(tmp_path, monkeypatch):
    import tools
    monkeypatch.setattr(tools, "RESEARCH_DIR", tmp_path)
    (tmp_path / "latency-handoff").mkdir(); (tmp_path / "latency-handoff" / "proposal.md").write_text("p"); (tmp_path / "latency-handoff" / "literature.md").write_text("l")
    (tmp_path / "log-finetune").mkdir(); (tmp_path / "log-finetune" / "proposal.md").write_text("p")
    (tmp_path / "log-finetune" / "experiments").mkdir(); (tmp_path / "log-finetune" / "experiments" / "results.json").write_text("{}")
    rows = json.loads(tools.research_status())
    assert [(r["project"], r["stage"]) for r in rows] == [("latency-handoff", "literature"), ("log-finetune", "experiments")]
    assert "experimenter" in rows[0]["next"] and "paper-writer" in rows[1]["next"]
    assert "latency-handoff | literature" in (tmp_path / "STATUS.md").read_text()


def test_mail_watch_wakes_assistant_only_for_real_new_mail(tmp_path, monkeypatch):
    import mail_watch, mail
    monkeypatch.setattr(mail_watch, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(mail, "configured", lambda: True)
    inbox = [{"uid": "1", "from": "Newsletter <news@x.com>", "subject": "Weekly", "automated": True},
             {"uid": "2", "from": "Sam Patel <sam@hackneylets.co.uk>", "subject": "Re: enquiry assistant", "automated": False}]
    monkeypatch.setattr(mail, "inbox", lambda **kw: inbox)
    created = []
    class B:
        def task_list(self, status=None, limit=100): return []
        def task_create(self, title, detail, **kw): created.append((title, kw["owner"])); return {"id": 1}
    monkeypatch.setattr(mail_watch, "BrainStore", lambda: B())
    out = mail_watch.watch()
    assert out["woke"] and out["real_unread"] == 1 and created == [("Mail: answer 1 new message", "mail-assistant")]
    # second pass: same mail already seen -> no new task
    out2 = mail_watch.watch()
    assert not out2["woke"] and out2["new"] == 0 and len(created) == 1


def test_qa_skips_internal_approvals(monkeypatch):
    import scheduler
    tasks = []
    class B:
        def recent(self, limit=30, kind=None):
            return [types.SimpleNamespace(id=10, agent="coo", tags=["pending", "brief-proposal"], content="PENDING APPROVAL from coo: brief change, see ops/proposals/x.md and proposals/x.md"),
                    types.SimpleNamespace(id=11, agent="proposal-writer", tags=["pending"], content="PENDING APPROVAL from proposal-writer: proposal for Acme, proposals/2026-acme.md")]
        def task_create(self, title, detail, **kw): tasks.append(title); return {"id": 1}
        def update(self, *a, **k): pass
    monkeypatch.setattr(scheduler, "_notify", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "_last_approval_id", 0)
    assert scheduler.check_approvals(B()) == 2
    assert tasks == ["QA check approval #11"]   # the brief proposal is internal: no fact-check run


def test_redact_secrets_hides_env_values_and_key_shapes(monkeypatch):
    import runtime
    monkeypatch.setenv("FAKE_SERVICE_API_KEY", "abcdefgh12345678XYZ")
    fake_key = "gsk" + "_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ123"     # built at runtime so the publish scanner never sees a key-shaped literal
    out = runtime.redact_secrets(f"key is abcdefgh12345678XYZ and {fake_key} and Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789 ok")
    assert "abcdefgh12345678XYZ" not in out and fake_key not in out and "abcdefghijklmnopqrstuvwxyz0123456789" not in out
    assert out.count("[REDACTED]") == 3 and out.endswith("ok")
    assert runtime.redact_secrets("plain text, 2,000 tokens, version 1.2.3") == "plain text, 2,000 tokens, version 1.2.3"


def test_demote_by_eval_moves_bad_models_back(monkeypatch):
    import runtime
    monkeypatch.setattr(runtime, "eval_scores", lambda: {"groq:bad": (0.2, 5), "groq:good": (1.0, 5), "groq:few": (0.0, 1)})
    chain = [("groq", "bad"), ("groq", "good"), ("groq", "few"), ("groq", "unknown"), ("ollama", "qwen2.5:3b")]
    assert runtime.demote_by_eval(chain) == [("groq", "good"), ("groq", "few"), ("groq", "unknown"), ("groq", "bad"), ("ollama", "qwen2.5:3b")]
    monkeypatch.setattr(runtime, "eval_scores", lambda: {})
    assert runtime.demote_by_eval(chain) == chain
