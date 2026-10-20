"""
Mail watch (no tokens): an hourly IMAP look at the inbox. Only when a REAL unread message exists (not newsletters,
notifications or automated senders) does it wake the mail-assistant with a task naming the senders. Replaces the
old every-2-hours LLM triage, which ran ~95 times a week and found nothing.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office")); sys.path.insert(0, str(ROOT / "brain"))
import runtime  # noqa: F401  (.env)
import mail
from store import BrainStore

STATE = ROOT / "office" / "logs" / "mail_watch.json"


def watch() -> dict:
    if not mail.configured():
        return {"skipped": "mail not configured"}
    try:
        seen = set(json.loads(STATE.read_text()).get("seen", []))
    except Exception:
        seen = set()
    rows = [r for r in mail.inbox(limit=30, unread_only=True, since_days=7) if not r.get("automated")]
    fresh = [r for r in rows if r["uid"] not in seen]
    out = {"ts": time.strftime("%Y-%m-%d %H:%M"), "real_unread": len(rows), "new": len(fresh), "woke": False}
    if fresh:
        b = BrainStore()
        queued = [t for t in b.task_list(status="queued", limit=100) + b.task_list(status="running", limit=50)
                  if t["owner"] == "mail-assistant" and t["title"].startswith("Mail: answer")]
        if not queued:
            who = "; ".join(f"{r['from'][:40]}: {r['subject'][:60]}" for r in fresh[:8])
            b.task_create(f"Mail: answer {len(fresh)} new message{'s' if len(fresh) > 1 else ''}",
                          f"The inbox watch found real unread mail: {who}. For each: mail_read, brain_recall the context, then mail_reply with a "
                          "short, specific answer (sending waits for Pribin's approval unless MAIL_AUTOREPLY allows it). Skip anything automated.",
                          owner="mail-assistant", created_by="scheduler", priority=5, source="mail-watch")
            out["woke"] = True
        seen |= {r["uid"] for r in fresh}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"seen": sorted(seen)[-500:], "last": out["ts"]}))
    return out


if __name__ == "__main__":
    print(json.dumps(watch()))
