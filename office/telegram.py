"""
Telegram bot: approvals and commands from any phone, no tunnel. The bot long-polls Telegram (outbound only), so it works
when the Mac is behind NAT and the quick tunnel is dead. Everything it does goes through the dashboard's own local API
with the dashboard token, so the rules are identical to pressing the buttons on the web app.

Setup (free, two minutes): message @BotFather on Telegram -> /newbot -> copy the token into .env as TELEGRAM_BOT_TOKEN,
restart, then send the bot any message: it replies with your chat id; put that in .env as TELEGRAM_CHAT_ID and restart.
Only that chat is ever answered.

Buttons on each new approval: Approve, Reject (asks for a reason, which becomes a lesson for the agent), Post v1..n for
LinkedIn drafts. Text messages: /status, /approvals, /pause, /resume, or anything else = a task for the chief of staff.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.telegram.org/bot{token}/{method}"
_awaiting_reason: dict[str, int] = {}      # chat id -> approval id waiting for a rejection reason
_state = {"offset": 0, "started": False}


def token() -> str:
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()


def chat_id() -> str:
    return (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()


def configured() -> bool:
    return bool(token())


def _local(method: str, path: str, body: dict | None = None) -> dict:
    """Call the dashboard's own API as Pribin (same rules as the web buttons)."""
    port = os.environ.get("DASHBOARD_PORT", "8787"); tok = (os.environ.get("DASHBOARD_TOKEN") or "").strip()
    h = {"Authorization": f"Bearer {tok}"} if tok else {}
    r = httpx.request(method, f"http://127.0.0.1:{port}{path}", json=body, headers=h, timeout=60)
    try:
        return r.json()
    except Exception:
        return {"error": r.text[:200]}


def _tg(method: str, **params) -> dict:
    if not configured():
        return {"ok": False, "error": "no token"}
    try:
        r = httpx.post(API.format(token=token(), method=method), json=params, timeout=35)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def send(text: str, buttons: list[list[dict]] | None = None, chat: str | None = None) -> dict:
    chat = chat or chat_id()
    if not configured() or not chat:
        return {"ok": False, "error": "telegram not configured"}
    params = {"chat_id": chat, "text": text[:3900], "disable_web_page_preview": True}
    if buttons:
        params["reply_markup"] = {"inline_keyboard": buttons}
    return _tg("sendMessage", **params)


def approval_buttons(m) -> list[list[dict]]:
    row = [{"text": "✅ Approve", "callback_data": f"ap:{m.id}"}, {"text": "❌ Reject", "callback_data": f"rj:{m.id}"}]
    rows = [row]
    paths = re.findall(r"(?:workspace/)?(posts/[\w./-]+\.md)", m.content)
    if paths and "posted" not in m.tags:
        try:
            from tools import post_variants, _safe
            n = len(post_variants(_safe(paths[0]).read_text()))
        except Exception:
            n = 1
        rows.append([{"text": f"Post v{i}", "callback_data": f"post:{m.id}:{i}"} for i in range(1, min(n, 4) + 1)])
    return rows


def notify_approval(m, why: str = "") -> dict:
    """Called by the scheduler for each new pending approval."""
    body = re.sub(r"^(QA: \w+ - )?PENDING APPROVAL from [\w-]+: ", "", m.content)
    return send(f"Approval #{m.id} from {m.agent}{(' · ' + why) if why else ''}\n\n{body[:1200]}", approval_buttons(m))


def first_post_path(mid: int) -> str | None:
    import sys
    sys.path.insert(0, str(ROOT / "brain"))
    from store import BrainStore
    m = BrainStore().get(mid); paths = re.findall(r"(?:workspace/)?(posts/[\w./-]+\.md)", m.content)
    return paths[0] if paths else None


def _handle_callback(cb: dict):
    data = cb.get("data") or ""; chat = str(cb["message"]["chat"]["id"]); cid = cb.get("id")
    if chat != chat_id():
        _tg("answerCallbackQuery", callback_query_id=cid, text="not your office"); return
    if data.startswith("ap:"):
        r = _local("POST", "/api/approve", {"id": int(data[3:]), "decision": "approved"})
        note = "approved" + (" and sent" if r.get("sent") else "") + (f" ({r['error']})" if r.get("error") else "")
        _tg("answerCallbackQuery", callback_query_id=cid, text=note[:180]); send(f"#{data[3:]} {note}", chat=chat)
    elif data.startswith("rj:"):
        _awaiting_reason[chat] = int(data[3:])
        _tg("answerCallbackQuery", callback_query_id=cid, text="why? reply with one line")
        send(f"Rejecting #{data[3:]}. Reply with the reason in one line (it becomes a lesson for the agent), or 'skip'.", chat=chat)
    elif data.startswith("post:"):
        _, mid, var = data.split(":")
        path = first_post_path(int(mid))
        r = _local("POST", "/api/linkedin/post", {"id": int(mid), "path": path, "variant": int(var)}) if path else {"error": "no post file"}
        note = "posted " + r.get("url", "") if r.get("posted") else f"not posted: {r.get('error', '?')}"
        _tg("answerCallbackQuery", callback_query_id=cid, text=note[:180]); send(note, chat=chat)
    else:
        _tg("answerCallbackQuery", callback_query_id=cid, text="unknown button")


def _handle_message(msg: dict):
    chat = str(msg["chat"]["id"]); text = (msg.get("text") or "").strip()
    if not chat_id():
        send(f"Hello. Your chat id is {chat}. Put TELEGRAM_CHAT_ID={chat} in .env and restart the office; then I will answer only you.", chat=chat); return
    if chat != chat_id():
        return                                           # strangers get silence
    if chat in _awaiting_reason:
        mid = _awaiting_reason.pop(chat); reason = "" if text.lower() == "skip" else text
        r = _local("POST", "/api/approve", {"id": mid, "decision": "rejected", "reason": reason})
        send(f"#{mid} rejected" + (f". Lesson stored for {r.get('agent', 'the agent')}." if reason else "."), chat=chat); return
    low = text.lower()
    if low in ("/status", "status"):
        s = _local("GET", "/api/state"); run = s.get("running") or []
        send(f"Office: {'PAUSED' if (s.get('paused') or {}).get('paused') else 'running'} · {len(run)} running · {len(s.get('approvals') or [])} approvals waiting · cloud {'ok' if (s.get('cloud') or {}).get('available') else 'cooling'}", chat=chat)
    elif low in ("/approvals", "approvals"):
        s = _local("GET", "/api/state"); pend = s.get("approvals") or []
        if not pend:
            send("Nothing waiting for approval.", chat=chat)
        for a in pend[:8]:
            class M:  # minimal shape for approval_buttons
                id = a["id"]; agent = a.get("agent", "?"); content = a.get("content", ""); tags = a.get("tags", [])
            send(f"#{a['id']} {a.get('why', '')}\n{re.sub(r'^(QA: \\w+ - )?PENDING APPROVAL from [\\w-]+: ', '', a.get('content', ''))[:900]}", approval_buttons(M), chat=chat)
    elif low in ("/pause", "pause"):
        _local("POST", "/api/pause", {"paused": True, "reason": "paused from Telegram"}); send("Office paused.", chat=chat)
    elif low in ("/resume", "resume"):
        _local("POST", "/api/pause", {"paused": False}); send("Office resumed.", chat=chat)
    elif low in ("/start", "/help", "help"):
        send("Commands: /status, /approvals, /pause, /resume. Anything else goes to the chief of staff as a task.", chat=chat)
    elif text:
        r = _local("POST", "/api/run", {"task": text, "agent": "chief-of-staff", "engine": "auto", "queue": True})
        send(f"Queued for the chief of staff as task #{r.get('task_id', '?')}." + (f" ({r['note']})" if r.get("note") else ""), chat=chat)


def handle_update(u: dict):
    try:
        if "callback_query" in u:
            _handle_callback(u["callback_query"])
        elif "message" in u:
            _handle_message(u["message"])
    except Exception as e:
        try:
            send(f"Telegram handler error: {str(e)[:160]}")
        except Exception:
            pass


def poll_once(timeout: int = 25) -> int:
    r = _tg("getUpdates", offset=_state["offset"], timeout=timeout, allowed_updates=["message", "callback_query"])
    ups = r.get("result") or [] if isinstance(r, dict) else []
    for u in ups:
        _state["offset"] = max(_state["offset"], int(u["update_id"]) + 1)
        handle_update(u)
    return len(ups)


def start_polling():
    """Background thread inside the dashboard process. Idempotent."""
    if not configured() or _state["started"]:
        return False
    _state["started"] = True

    def loop():
        while True:
            try:
                poll_once()
            except Exception:
                time.sleep(5)
    threading.Thread(target=loop, name="telegram-poll", daemon=True).start()
    return True
