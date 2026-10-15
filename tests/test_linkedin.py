import json
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office"))
import linkedin  # noqa: E402


@pytest.fixture
def li(tmp_path, monkeypatch):
    monkeypatch.setattr(linkedin, "TOKEN_FILE", tmp_path / "tok.json")
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "cid"); monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "sec")
    calls = []
    def handler(req: httpx.Request):
        calls.append(req)
        if req.url.path.endswith("/accessToken"):
            return httpx.Response(200, json={"access_token": "tok123", "expires_in": 5184000})
        if req.url.path.endswith("/userinfo"):
            return httpx.Response(200, json={"sub": "abc", "name": "Pribin"})
        if req.url.path.endswith("/rest/posts"):
            body = json.loads(req.content)
            assert body["author"] == "urn:li:person:abc" and body["lifecycleState"] == "PUBLISHED"
            assert req.headers["LinkedIn-Version"] == linkedin.version() and req.headers["X-Restli-Protocol-Version"] == "2.0.0"
            return httpx.Response(201, headers={"x-restli-id": "urn:li:share:999"})
        return httpx.Response(404)
    return httpx.MockTransport(handler), calls


def test_oauth_flow_and_status(li):
    tr, calls = li
    assert linkedin.status()["connected"] is False
    url = linkedin.auth_url("http://localhost:8787")
    assert "w_member_social" in url and "redirect_uri=http%3A%2F%2Flocalhost%3A8787%2Flinkedin%2Fcallback" in url
    state = linkedin._load()["state"]
    with pytest.raises(linkedin.LinkedInError):
        linkedin.exchange_code("code", "wrong-state", transport=tr)
    st = linkedin.exchange_code("code", state, transport=tr)
    assert st["connected"] and st["name"] == "Pribin" and st["days_left"] >= 59


def test_post_text_and_limits(li):
    tr, calls = li
    with pytest.raises(linkedin.LinkedInError, match="not connected"):
        linkedin.post_text("hello", transport=tr)
    linkedin._save({"access_token": "tok123", "expires_at": time.time() + 1000, "sub": "abc", "posts": []})
    r = linkedin.post_text("Hello LinkedIn", transport=tr)
    assert r["posted"] and r["id"] == "urn:li:share:999"
    with pytest.raises(linkedin.LinkedInError, match="3000"):
        linkedin.post_text("x" * 3001, transport=tr)
    linkedin._save({**linkedin._load(), "posts": [{"ts": time.time()} for _ in range(5)]})
    with pytest.raises(linkedin.LinkedInError, match="5 posts"):
        linkedin.post_text("one more", transport=tr)


def test_linkedin_post_tool_requires_pribins_approval(li, tmp_path, monkeypatch):
    tr, calls = li
    import tools, store
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    b = store.BrainStore(tmp_path / "b.db", embedder=NoEmbed()); monkeypatch.setattr(tools, "brain", b)
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path / "ws"); (tmp_path / "ws" / "posts" / "linkedin").mkdir(parents=True)
    (tmp_path / "ws" / "posts" / "linkedin" / "a.md").write_text("# Variant A\n\nI built an office of agents.\n")
    monkeypatch.setattr(linkedin, "post_text", lambda text, transport=None: {"posted": True, "id": "x", "url": "u"} if "office of agents" in text and not text.startswith("#") else (_ for _ in ()).throw(AssertionError(text)))
    pending = b.remember("PENDING APPROVAL from linkedin-writer: LinkedIn post drafts", agent="linkedin-writer", kind="approval", tags=["pending"])
    assert tools.linkedin_post(pending.id, "posts/linkedin/a.md").startswith("refused")          # not approved yet
    b.update(pending.id, tags=["approved"])
    assert tools.linkedin_post(pending.id, "posts/linkedin/zzz.md").startswith("refused")        # no such draft
    r = json.loads(tools.linkedin_post(pending.id, "posts/linkedin/a.md", _agent="pribin"))
    assert r["posted"] and "posted" in b.get(pending.id).tags
    assert any("Posted to LinkedIn" in m.content for m in b.recent(limit=3))
