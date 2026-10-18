import json
import sys
import time
from email.message import EmailMessage
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office")); sys.path.insert(0, str(ROOT / "brain"))
import mail  # noqa: E402


class FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout=30): self.host = host
    def login(self, u, p): self.creds = (u, p)
    def send_message(self, msg): FakeSMTP.sent.append(msg)
    def quit(self): pass


def _raw(frm="Kristy E <kristy@acme-shop.co.uk>", subject="Re: chatbot quote", body="Can you start next week?", msgid="<m1@acme>", reply_to=None, extra=None):
    m = EmailMessage(); m["From"] = frm; m["To"] = "me@gmail.com"; m["Subject"] = subject; m["Message-ID"] = msgid; m["Date"] = "Sat, 17 Oct 2026 10:00:00 +0100"
    if reply_to: m["In-Reply-To"] = reply_to
    for k, v in (extra or {}).items(): m[k] = v
    m.set_content(body + "\n\nOn Fri, 16 Oct 2026 Pribin wrote:\n> old quoted text")
    return m.as_bytes()


class FakeIMAP:
    store: dict = {}
    flagged: list = []

    def __init__(self, host): pass
    def login(self, u, p): pass
    def select(self, box): pass
    def logout(self): pass
    def uid(self, cmd, *args):
        if cmd == "search":
            return "OK", [" ".join(FakeIMAP.store).encode()]
        if cmd == "fetch":
            uid = args[0].decode() if isinstance(args[0], bytes) else args[0]
            return "OK", [(b"1 (BODY[] {n}", FakeIMAP.store[uid]), b")"]
        if cmd == "store":
            FakeIMAP.flagged.append(args[0]); return "OK", []


@pytest.fixture
def gmail(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "me@gmail.com"); monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.delenv("MAIL_AUTOREPLY", raising=False); monkeypatch.delenv("MAIL_BLOCKLIST", raising=False); monkeypatch.delenv("MAIL_DAILY_CAP", raising=False)
    monkeypatch.setattr(mail, "SENT_LOG", tmp_path / "sent.jsonl")
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTP); monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", FakeIMAP)
    FakeSMTP.sent = []; FakeIMAP.store = {"7": _raw(), "8": _raw(frm="Shop News <noreply@news.example.com>", subject="Weekly deals", extra={"List-Unsubscribe": "<x>"}, msgid="<n1@news>")}
    FakeIMAP.flagged = []
    return tmp_path


def test_status_parse_and_gates(gmail, monkeypatch):
    assert mail.configured() and mail.status()["address"] == "me…@gmail.com" and mail.status()["autoreply"] is False
    d = mail.parse_draft("To: a@b.co\nSubject: Hi there\nFrom-agent: mail-assistant\nIn-Reply-To: <m1@acme>\n\nBody line one.\n\nTwo.\n")
    assert d["to"] == "a@b.co" and d["subject"] == "Hi there" and d["in_reply_to"] == "<m1@acme>" and d["body"].startswith("Body line one.")
    for bad, why in (("DeepMind", "not an email address"), ("me@gmail.com", "ourselves"), ("noreply@x.com", "automated")):
        with pytest.raises(mail.MailError, match=why):
            mail.check_sendable(bad, "s", "b")
    with pytest.raises(mail.MailError, match="placeholders"):
        mail.check_sendable("a@b.co", "Hi", "Dear [Job Title] team")
    monkeypatch.setenv("MAIL_BLOCKLIST", "acme-shop.co.uk")
    with pytest.raises(mail.MailError, match="BLOCKLIST"):
        mail.check_sendable("kristy@acme-shop.co.uk", "s", "b")


def test_send_logs_threads_and_caps(gmail, monkeypatch):
    r = mail.send("Kristy <kristy@acme-shop.co.uk>", "Re: quote", "Yes, Monday works.", in_reply_to="<m1@acme>", agent="mail-assistant")
    assert r["sent"] and r["to"] == "kristy@acme-shop.co.uk" and FakeSMTP.sent[0]["In-Reply-To"] == "<m1@acme>" and FakeSMTP.sent[0]["From"] == "me@gmail.com"
    assert mail.sent_today() == 1 and mail.previously_emailed("kristy@acme-shop.co.uk") and not mail.previously_emailed("x@y.z")
    monkeypatch.setenv("MAIL_DAILY_CAP", "1")
    with pytest.raises(mail.MailError, match="daily cap"):
        mail.send("other@firm.com", "s", "b")


def test_inbox_parses_new_text_and_flags_automated(gmail):
    rows = mail.inbox(limit=10)
    by = {r["uid"]: r for r in rows}
    assert by["7"]["from_email"] == "kristy@acme-shop.co.uk" and by["7"]["body"] == "Can you start next week?" and by["7"]["automated"] is False
    assert by["8"]["automated"] is True
    full = mail.read("7"); assert "old quoted text" in full["body"]
    mail.mark_seen("7"); assert FakeIMAP.flagged == [b"7"]


def test_autoreply_rules(gmail, monkeypatch):
    msg = mail.inbox()[0] if mail.inbox()[0]["uid"] == "7" else mail.inbox()[1]
    known = lambda a: a.endswith("acme-shop.co.uk")
    assert mail.can_autoreply(msg, known)[0] is False                      # off by default
    monkeypatch.setenv("MAIL_AUTOREPLY", "1")
    ok, why = mail.can_autoreply(msg, known); assert ok is False and "first contact" in why   # no thread yet
    mail.send("kristy@acme-shop.co.uk", "quote", "Here is the quote.")          # now there is a conversation
    assert mail.can_autoreply(msg, known) == (True, "existing conversation with a known contact")
    assert mail.can_autoreply(msg, lambda a: False)[0] is False            # unknown sender
    auto = dict(msg, automated=True); assert mail.can_autoreply(auto, known)[0] is False


def test_tools_mail_reply_and_mail_send_are_gated(gmail, tmp_path, monkeypatch):
    import tools, store
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    b = store.BrainStore(tmp_path / "b.db", embedder=NoEmbed()); monkeypatch.setattr(tools, "brain", b)
    ws = tmp_path / "ws"; (ws / "outbox").mkdir(parents=True); (ws / "pipeline").mkdir()
    monkeypatch.setattr(tools, "WORKSPACE", ws)
    (ws / "pipeline" / "clients.md").write_text("| Kristy E | acme-shop.co.uk | proposed |\n")
    import push; monkeypatch.setattr(push, "send", lambda *a, **k: {"sent": 0})
    # auto-reply off: the reply becomes an approval, nothing is sent
    out = tools.mail_reply("7", "Yes, Monday works. Pribin K Benny", _agent="mail-assistant")
    assert "approval #" in out and FakeSMTP.sent == []
    mid = int(out.split("approval #")[1].split()[0])
    path = out.split("draft saved to ")[1].split(";")[0]
    assert tools.mail_send(mid, path, _agent="mail-assistant").startswith("refused")      # not approved yet
    assert tools.mail_send(mid, path, _agent="job-scout").startswith("refused: only")    # wrong agent
    b.update(mid, tags=["approved", "email"])
    r = json.loads(tools.mail_send(mid, path, _agent="mail-assistant"))
    assert r["sent"] and r["to"] == "kristy@acme-shop.co.uk" and FakeSMTP.sent[-1]["In-Reply-To"] == "<m1@acme>"
    assert "sent" in b.get(mid).tags and b.get(mid).content.startswith("SENT")
    assert tools.mail_send(mid, path, _agent="mail-assistant").startswith("refused: already sent")
    # auto-reply on + existing thread with a known client: goes out immediately, Pribin is notified
    monkeypatch.setenv("MAIL_AUTOREPLY", "1")
    r2 = json.loads(tools.mail_reply("7", "Great, see you Monday.", _agent="mail-assistant"))
    assert r2["sent"] and len(FakeSMTP.sent) == 2 and any("Auto-replied" in m.content for m in b.recent(limit=3))
    # a newsletter never gets an answer, even with auto-reply on
    assert tools.mail_reply("8", "thanks", _agent="mail-assistant").startswith("refused")


def test_draft_to_company_name_cannot_be_sent(gmail, tmp_path, monkeypatch):
    import tools, store
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    b = store.BrainStore(tmp_path / "b.db", embedder=NoEmbed()); monkeypatch.setattr(tools, "brain", b)
    ws = tmp_path / "ws"; (ws / "outbox").mkdir(parents=True); monkeypatch.setattr(tools, "WORKSPACE", ws)
    (ws / "outbox" / "x.md").write_text("To: DeepMind\nSubject: Follow-up\nFrom-agent: mail-assistant\n\nHello.\n")
    m = b.remember("APPROVED from mail-assistant: email draft 'Follow-up' to DeepMind at workspace/outbox/x.md", agent="mail-assistant", kind="approval", tags=["approved", "email"])
    with pytest.raises(mail.MailError, match="not an email address"):
        tools.send_approved_email(m.id)
    assert FakeSMTP.sent == []


def test_self_send_only_when_pribin_approved(gmail):
    with pytest.raises(mail.MailError, match="ourselves"):
        mail.send("me@gmail.com", "loop", "x", mode="autoreply")
    r = mail.send("me@gmail.com", "Test to my own inbox", "Approved test.", mode="approved")
    assert r["sent"] and r["to"] == "me@gmail.com"
    own = {"from_email": "me@gmail.com", "automated": False, "in_reply_to": "<x>"}
    import os; os.environ["MAIL_AUTOREPLY"] = "1"
    try:
        assert mail.can_autoreply(own, lambda a: True) == (False, "our own message")
    finally:
        os.environ.pop("MAIL_AUTOREPLY", None)
