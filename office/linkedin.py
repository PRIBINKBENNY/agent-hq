"""
LinkedIn posting for the office (personal profile), free self-serve app.

Setup (once, ~10 minutes):
  1. https://www.linkedin.com/developers/apps -> Create app (needs a LinkedIn Page to associate; create a
     one-person page if you have none). Products tab: add "Share on LinkedIn" and
     "Sign In with LinkedIn using OpenID Connect".
  2. Auth tab: add redirect URL  http://localhost:8787/linkedin/callback  (and your tunnel URL + /linkedin/callback).
  3. Put LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET in .env, restart the dashboard, open /linkedin/connect.
The access token lasts 60 days (self-serve apps cannot refresh programmatically): reconnect when the
dashboard says so. Rate limit is roughly 100 calls per member per day.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import httpx

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "office" / "logs" / "linkedin_token.json"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API = "https://api.linkedin.com"
SCOPES = "openid profile w_member_social"


class LinkedInError(Exception):
    pass


def configured() -> bool:
    return bool((os.environ.get("LINKEDIN_CLIENT_ID") or "").strip() and (os.environ.get("LINKEDIN_CLIENT_SECRET") or "").strip())


def redirect_uri(base: Optional[str] = None) -> str:
    return (os.environ.get("LINKEDIN_REDIRECT_URI") or f"{base or 'http://localhost:8787'}/linkedin/callback").strip()


def version() -> str:
    return (os.environ.get("LINKEDIN_VERSION") or "202608").strip()


def _load() -> dict:
    try:
        return json.loads(TOKEN_FILE.read_text())
    except Exception:
        return {}


def _save(d: dict):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(d, indent=1))


def status() -> dict:
    t = _load()
    if not t.get("access_token"):
        return {"configured": configured(), "connected": False}
    left = int(t.get("expires_at", 0) - time.time())
    return {"configured": configured(), "connected": left > 0, "days_left": max(0, left // 86400), "name": t.get("name"), "sub": t.get("sub"),
            "posts_today": sum(1 for p in t.get("posts", []) if p.get("ts", 0) > time.time() - 86400)}


# ----------------------------------------------------------------- OAuth
def auth_url(base: Optional[str] = None) -> str:
    state = secrets.token_urlsafe(16)
    d = _load(); d["state"] = state; _save(d)
    return AUTH_URL + "?" + urlencode({"response_type": "code", "client_id": os.environ["LINKEDIN_CLIENT_ID"].strip(),
                                       "redirect_uri": redirect_uri(base), "scope": SCOPES, "state": state})


def exchange_code(code: str, state: str, base: Optional[str] = None, transport: Optional[httpx.BaseTransport] = None) -> dict:
    d = _load()
    if not state or state != d.get("state"):
        raise LinkedInError("state mismatch: start again from /linkedin/connect")
    with httpx.Client(timeout=20, transport=transport) as c:
        r = c.post(TOKEN_URL, data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(base),
                                    "client_id": os.environ["LINKEDIN_CLIENT_ID"].strip(), "client_secret": os.environ["LINKEDIN_CLIENT_SECRET"].strip()})
        if r.status_code >= 400:
            raise LinkedInError(f"token exchange failed {r.status_code}: {r.text[:200]}")
        tok = r.json()
        me = c.get(f"{API}/v2/userinfo", headers={"Authorization": f"Bearer {tok['access_token']}"})
        if me.status_code >= 400:
            raise LinkedInError(f"userinfo failed {me.status_code}: {me.text[:200]}")
        info = me.json()
    d.update({"access_token": tok["access_token"], "expires_at": time.time() + int(tok.get("expires_in", 60 * 86400)),
              "sub": info.get("sub"), "name": info.get("name"), "state": None, "posts": d.get("posts", [])})
    _save(d)
    return status()


# ----------------------------------------------------------------- posting
def post_text(text: str, transport: Optional[httpx.BaseTransport] = None) -> dict:
    d = _load()
    if not d.get("access_token") or d.get("expires_at", 0) < time.time():
        raise LinkedInError("not connected or token expired: open /linkedin/connect")
    text = text.strip()
    if not text:
        raise LinkedInError("empty post")
    if len(text) > 3000:
        raise LinkedInError(f"post is {len(text)} characters; LinkedIn allows 3000")
    if sum(1 for p in d.get("posts", []) if p.get("ts", 0) > time.time() - 86400) >= 5:
        raise LinkedInError("refused: already 5 posts in the last 24 hours")
    body = {"author": f"urn:li:person:{d['sub']}", "commentary": text, "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
    headers = {"Authorization": f"Bearer {d['access_token']}", "LinkedIn-Version": version(),
               "X-Restli-Protocol-Version": "2.0.0", "Content-Type": "application/json"}
    with httpx.Client(timeout=30, transport=transport) as c:
        r = c.post(f"{API}/rest/posts", headers=headers, json=body)
    if r.status_code not in (200, 201):
        raise LinkedInError(f"post failed {r.status_code}: {r.text[:300]}")
    post_id = r.headers.get("x-restli-id") or r.headers.get("x-linkedin-id") or ""
    url = f"https://www.linkedin.com/feed/update/{post_id}" if post_id else "https://www.linkedin.com/in/me/recent-activity/all/"
    d.setdefault("posts", []).append({"ts": time.time(), "id": post_id, "chars": len(text)})
    d["posts"] = d["posts"][-50:]; _save(d)
    return {"posted": True, "id": post_id, "url": url}
