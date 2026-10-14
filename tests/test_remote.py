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
