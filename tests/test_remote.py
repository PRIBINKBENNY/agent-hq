import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office")); sys.path.insert(0, str(ROOT / "brain"))
os.environ["DASHBOARD_TOKEN"] = "test-token-123"

import pytest
from starlette.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    import dashboard
    dashboard.TOKEN = "test-token-123"
    with TestClient(dashboard.app, base_url="http://testserver") as c:   # testserver is not a local IP -> remote rules apply
        yield c


def test_remote_requires_token(client):
    r = client.get("/api/state", follow_redirects=False)
    assert r.status_code == 401
    r = client.get("/m", follow_redirects=False)
    assert r.status_code in (302, 307) and "/login" in r.headers["location"]
    assert client.get("/login").status_code == 200
    assert client.get("/manifest.json").status_code == 200 and client.get("/sw.js").status_code == 200   # public PWA assets


def test_token_login_sets_cookie_and_bearer_works(client):
    r = client.post("/login", data={"token": "wrong", "next": "/m"}, follow_redirects=False)
    assert r.status_code == 401
    r = client.post("/login", data={"token": "test-token-123", "next": "/m"}, follow_redirects=False)
    assert r.status_code == 303 and r.cookies.get("hq") == "test-token-123"
    assert client.get("/m").status_code == 200                                  # cookie kept by the client
    fresh = TestClient(__import__("dashboard").app, base_url="http://testserver")
    assert fresh.get("/api/state", headers={"authorization": "Bearer test-token-123"}).status_code == 200


def test_push_subscribe_and_vapid(client, tmp_path, monkeypatch):
    import push
    monkeypatch.setattr(push, "SUBS_FILE", tmp_path / "subs.json")
    assert client.get("/api/vapid").status_code == 200
    r = client.post("/api/push/subscribe", json={"endpoint": "https://push.example/abc", "keys": {"p256dh": "x", "auth": "y"}})
    assert r.status_code == 200 and r.json()["subscribers"] == 1
    assert client.post("/api/push/subscribe", json={}).status_code == 400
    assert push.unsubscribe("https://push.example/abc") == 0


def test_approval_detail_and_typed_follow_ups(client, tmp_path, monkeypatch):
    import dashboard, tools, store
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    b = store.BrainStore(tmp_path / "b.db", embedder=NoEmbed())
    monkeypatch.setattr(dashboard, "brain", b); monkeypatch.setattr(dashboard, "WORKSPACE", tmp_path)
    (tmp_path / "applications" / "acme" / "ml").mkdir(parents=True)
    (tmp_path / "applications" / "acme" / "ml" / "cv.md").write_text("# CV\nreal content")
    (tmp_path / "applications" / "acme" / "ml" / "QA.md").write_text("PASS")
    app = b.remember("PENDING APPROVAL from application-tailor: application ready at workspace/applications/acme/ml/ (cv.md)", agent="application-tailor", kind="approval", tags=["pending", "application"])
    mail = b.remember("PENDING APPROVAL from mail-assistant: email draft 'Follow-up' to Acme at workspace/outbox/x.md", agent="mail-assistant", kind="approval", tags=["pending", "email"])
    h = {"authorization": "Bearer test-token-123"}
    d = client.get(f"/api/approval?id={app.id}", headers=h).json()
    assert d["kind"] == "application" and d["files"][0]["name"] == "cv.md" and "real content" in d["files"][0]["content"] and d["qa"] == "PASS"
    # approving an application creates a tracker follow-up; approving an email creates nothing (no chains)
    r = client.post("/api/approve", json={"id": app.id, "decision": "approved"}, headers=h).json()
    assert r["follow_up_task"] is not None and "Do NOT draft any email" in b.task_get(r["follow_up_task"])["detail"]
    r = client.post("/api/approve", json={"id": mail.id, "decision": "approved"}, headers=h).json()
    assert r["follow_up_task"] is None


def test_draft_email_refuses_placeholders(tmp_path, monkeypatch):
    import tools, store
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    monkeypatch.setattr(tools, "brain", store.BrainStore(tmp_path / "b.db", embedder=NoEmbed())); monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    assert tools.draft_email("<company>", "Follow-up", "Dear <name>,").startswith("refused")
    assert tools.draft_email("workspace/outbox/x.md", "Hi", "body").startswith("refused")
    assert "draft saved" in tools.draft_email("jobs@acme.com", "Follow-up on my application", "Dear Acme team, ...", _agent="mail-assistant")
