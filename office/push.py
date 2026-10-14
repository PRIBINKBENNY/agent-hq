"""
Web push to the phone app (free: VAPID keys, no Apple developer account needed).
Subscriptions are stored in office/logs/push_subs.json. Used by the dashboard (subscribe)
and the scheduler (notify on approvals / finished tasks).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUBS_FILE = ROOT / "office" / "logs" / "push_subs.json"


def _load() -> list[dict]:
    try:
        return json.loads(SUBS_FILE.read_text())
    except Exception:
        return []


def _save(subs: list[dict]):
    SUBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUBS_FILE.write_text(json.dumps(subs, indent=1))


def public_key() -> str:
    return (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()


def subscribe(sub: dict) -> int:
    subs = [s for s in _load() if s.get("endpoint") != sub.get("endpoint")]
    subs.append(sub)
    _save(subs)
    return len(subs)


def unsubscribe(endpoint: str) -> int:
    subs = [s for s in _load() if s.get("endpoint") != endpoint]
    _save(subs)
    return len(subs)


def send(title: str, body: str, url: str = "/m", tag: str = "hq") -> dict:
    """Push to every subscribed phone. Drops subscriptions the push service says are gone."""
    priv = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()
    if not priv:
        return {"sent": 0, "error": "VAPID_PRIVATE_KEY not set"}
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return {"sent": 0, "error": "pywebpush not installed"}
    subs = _load(); sent = 0; gone = []
    payload = json.dumps({"title": title[:80], "body": body[:200], "url": url, "tag": tag})
    for s in subs:
        try:
            webpush(subscription_info=s, data=payload, vapid_private_key=priv,
                    vapid_claims={"sub": os.environ.get("VAPID_CLAIMS_EMAIL", "mailto:agent-hq@example.com")}, ttl=3600)
            sent += 1
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (404, 410):
                gone.append(s.get("endpoint"))
        except Exception:
            pass
    if gone:
        _save([s for s in subs if s.get("endpoint") not in gone])
    return {"sent": sent, "removed": len(gone), "subscribers": len(subs) - len(gone)}
