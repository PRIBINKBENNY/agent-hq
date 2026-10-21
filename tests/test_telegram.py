import sys, types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "office"))


def _setup(monkeypatch, chat="111"):
    import telegram
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t"); monkeypatch.setenv("TELEGRAM_CHAT_ID", chat)
    sent, local, tg = [], [], []
    monkeypatch.setattr(telegram, "_tg", lambda method, **p: tg.append((method, p)) or {"ok": True, "result": []})
    monkeypatch.setattr(telegram, "send", lambda text, buttons=None, chat=None: sent.append((text, buttons, chat)) or {"ok": True})
    def fake_local(method, path, body=None):
        local.append((method, path, body))
        return {"ok": True, "agent": "proposal-writer", "task_id": 9, "posted": True, "url": "https://li/x",
                "running": [], "approvals": [{"id": 5, "agent": "x", "content": "PENDING APPROVAL from x: hi", "tags": ["pending"], "why": "proposal"}], "paused": {"paused": False}, "cloud": {"available": True}}
    monkeypatch.setattr(telegram, "_local", fake_local)
    telegram._awaiting_reason.clear()
    return telegram, sent, local, tg


def test_strangers_get_silence_and_unknown_chat_learns_its_id(monkeypatch):
    telegram, sent, local, tg = _setup(monkeypatch, chat="111")
    telegram.handle_update({"message": {"chat": {"id": 999}, "text": "/status"}})
    assert not sent and not local
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    telegram.handle_update({"message": {"chat": {"id": 999}, "text": "hello"}})
    assert "chat id is 999" in sent[-1][0] and not local


def test_commands_and_tasks(monkeypatch):
    telegram, sent, local, tg = _setup(monkeypatch)
    telegram.handle_update({"message": {"chat": {"id": 111}, "text": "/status"}})
    assert local[-1][1] == "/api/state" and "running" in sent[-1][0]
    telegram.handle_update({"message": {"chat": {"id": 111}, "text": "find me 3 letting agents in Hackney"}})
    assert local[-1][1] == "/api/run" and local[-1][2]["agent"] == "chief-of-staff" and "task #9" in sent[-1][0]
    telegram.handle_update({"message": {"chat": {"id": 111}, "text": "/pause"}})
    assert local[-1] == ("POST", "/api/pause", {"paused": True, "reason": "paused from Telegram"})


def test_approve_reject_with_reason_and_post_buttons(monkeypatch):
    telegram, sent, local, tg = _setup(monkeypatch)
    cb = lambda data: {"callback_query": {"id": "c1", "data": data, "message": {"chat": {"id": 111}}}}
    telegram.handle_update(cb("ap:42"))
    assert local[-1] == ("POST", "/api/approve", {"id": 42, "decision": "approved"})
    telegram.handle_update(cb("rj:43"))
    assert telegram._awaiting_reason["111"] == 43 and not any(p == "/api/approve" and b.get("id") == 43 for _, p, b in local)
    telegram.handle_update({"message": {"chat": {"id": 111}, "text": "the quote is too low"}})
    assert local[-1] == ("POST", "/api/approve", {"id": 43, "decision": "rejected", "reason": "the quote is too low"}) and "Lesson stored" in sent[-1][0]
    monkeypatch.setattr(telegram, "first_post_path", lambda mid: "posts/linkedin/x.md")
    telegram.handle_update(cb("post:44:2"))
    assert local[-1] == ("POST", "/api/linkedin/post", {"id": 44, "path": "posts/linkedin/x.md", "variant": 2}) and "posted" in sent[-1][0]
    # a stranger pressing a button is refused
    telegram.handle_update({"callback_query": {"id": "c2", "data": "ap:1", "message": {"chat": {"id": 999}}}})
    assert tg[-1][1]["text"] == "not your office" and local[-1][2]["id"] == 44


def test_approval_buttons_include_post_variants(monkeypatch, tmp_path):
    import telegram, tools
    f = tmp_path / "p.md"; f.write_text("### Variant 1\naaa\n### Variant 2\nbbb\n")
    monkeypatch.setattr(tools, "_safe", lambda p: f)
    m = types.SimpleNamespace(id=7, agent="linkedin-writer", content="PENDING APPROVAL from linkedin-writer: file posts/linkedin/p.md", tags=["pending"])
    rows = telegram.approval_buttons(m)
    assert rows[0][0]["callback_data"] == "ap:7" and [b["callback_data"] for b in rows[1]] == ["post:7:1", "post:7:2"]
