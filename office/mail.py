"""
Gmail for the office: read the inbox over IMAP, send over SMTP, with an App Password. Free, no Cloud project.

Setup (once, ~5 minutes), on the Google account the agents should write from:
  1. myaccount.google.com -> Security -> turn on 2-Step Verification (required for app passwords).
  2. myaccount.google.com/apppasswords -> create one called "Agent HQ" -> copy the 16 characters.
  3. .env:  GMAIL_ADDRESS=you@gmail.com   GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx   then restart the office.
  Optional: MAIL_AUTOREPLY=1 lets the mail-assistant answer inside EXISTING customer threads without an approval
  (new recipients always need Pribin's approval). MAIL_DAILY_CAP (default 20). MAIL_BLOCKLIST=comma,separated.

Rules enforced here, not in prompts: a real address, never to ourselves, never to no-reply/automated senders,
daily cap, blocklist, no placeholders, every send logged to office/logs/mail_sent.jsonl.
"""

from __future__ import annotations

import email
import email.utils
import imaplib
import json
import os
import re
import smtplib
import time
from email.header import decode_header, make_header
from email.message import EmailMessage
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
SENT_LOG = ROOT / "office" / "logs" / "mail_sent.jsonl"
IMAP_HOST, SMTP_HOST, SMTP_PORT = "imap.gmail.com", "smtp.gmail.com", 465
AUTOMATED = re.compile(r"(no-?reply|do-?not-?reply|mailer-daemon|postmaster|notification|newsletter|bounce|noreply)", re.I)
PLACEHOLDER = re.compile(r"<\s*(company|client|name|recipient|role|date|email|url)\s*>|\[(company|client|name|recipient|job title)\]|lorem ipsum", re.I)


class MailError(Exception):
    pass


# ----------------------------------------------------------------- config
def address() -> str:
    return (os.environ.get("GMAIL_ADDRESS") or "").strip().lower()


def configured() -> bool:
    return bool(address() and (os.environ.get("GMAIL_APP_PASSWORD") or "").strip())


def autoreply_enabled() -> bool:
    return (os.environ.get("MAIL_AUTOREPLY") or "0").strip().lower() in ("1", "true", "yes", "on")


def daily_cap() -> int:
    try:
        return max(0, int(os.environ.get("MAIL_DAILY_CAP") or 20))
    except ValueError:
        return 20


def blocklist() -> list[str]:
    return [x.strip().lower() for x in (os.environ.get("MAIL_BLOCKLIST") or "").split(",") if x.strip()]


def _password() -> str:
    return (os.environ.get("GMAIL_APP_PASSWORD") or "").replace(" ", "").strip()


# ----------------------------------------------------------------- helpers
def valid_address(s: str) -> Optional[str]:
    """The bare lower-case address in `s` ("Name <a@b.c>" or "a@b.c"), or None."""
    _, addr = email.utils.parseaddr(s or "")
    addr = addr.strip().lower()
    return addr if re.fullmatch(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", addr) else None


def blocked(addr: str) -> bool:
    addr = addr.lower(); dom = addr.split("@")[-1]
    return any(b == addr or b == dom or (b.startswith("@") and b[1:] == dom) for b in blocklist())


def sent_log(limit: int = 500) -> list[dict]:
    if not SENT_LOG.exists():
        return []
    rows = []
    for ln in SENT_LOG.read_text().splitlines()[-limit:]:
        try:
            rows.append(json.loads(ln))
        except Exception:
            pass
    return rows


def sent_today() -> int:
    day = time.strftime("%Y-%m-%d")
    return sum(1 for r in sent_log() if str(r.get("ts", "")).startswith(day))


def previously_emailed(addr: str) -> bool:
    addr = addr.lower()
    return any((r.get("to") or "").lower() == addr for r in sent_log(2000))


def status() -> dict:
    return {"configured": configured(), "address": (address().split("@")[0][:2] + "…@" + address().split("@")[-1]) if address() else None,
            "autoreply": autoreply_enabled(), "sent_today": sent_today(), "daily_cap": daily_cap()}


def parse_draft(text: str) -> dict:
    """Outbox drafts: header lines (To, Subject, From-agent, In-Reply-To, References, Reply-Uid), blank line, body."""
    head, _, body = text.partition("\n\n")
    hdr = {}
    for ln in head.splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1); hdr[k.strip().lower()] = v.strip()
    return {"to": hdr.get("to", ""), "subject": hdr.get("subject", ""), "agent": hdr.get("from-agent", ""),
            "in_reply_to": hdr.get("in-reply-to") or None, "references": hdr.get("references") or None,
            "reply_uid": hdr.get("reply-uid") or None, "body": body.strip()}


def _decode(v) -> str:
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return str(v or "")


def _text_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get("Content-Disposition", "").startswith("attachment"):
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
                except Exception:
                    continue
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
                    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
                except Exception:
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "ignore")
    except Exception:
        return str(msg.get_payload())


def parse_message(raw: bytes, uid: str = "") -> dict:
    msg = email.message_from_bytes(raw)
    frm = _decode(msg.get("From")); frm_addr = valid_address(frm) or ""
    body = _text_body(msg)
    body = re.sub(r"\r\n", "\n", body)
    # drop quoted history so the agent reads what was actually written this time
    body_new = re.split(r"\n(On .{5,120} wrote:|-----Original Message-----|From: .+\nSent: )", body)[0].strip()
    return {"uid": uid, "from": frm, "from_email": frm_addr, "to": _decode(msg.get("To")), "subject": _decode(msg.get("Subject")),
            "date": _decode(msg.get("Date")), "message_id": (msg.get("Message-ID") or "").strip(),
            "in_reply_to": (msg.get("In-Reply-To") or "").strip() or None, "references": (msg.get("References") or "").strip() or None,
            "automated": bool(AUTOMATED.search(frm) or msg.get("List-Unsubscribe") or msg.get("Auto-Submitted") or
                              (msg.get("Precedence") or "").lower() in ("bulk", "list", "junk")),
            "body": body_new[:3000], "body_chars": len(body)}


# ----------------------------------------------------------------- IMAP
def _imap(factory: Optional[Callable] = None):
    if not configured():
        raise MailError("Gmail not configured: set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env")
    box = (factory or imaplib.IMAP4_SSL)(IMAP_HOST)
    box.login(address(), _password())
    return box


def inbox(limit: int = 20, unread_only: bool = True, since_days: int = 7, factory: Optional[Callable] = None) -> list[dict]:
    """Newest first. Each message: uid, from, from_email, subject, date, message_id, in_reply_to, automated, body (new text only)."""
    box = _imap(factory)
    try:
        box.select("INBOX")
        since = time.strftime("%d-%b-%Y", time.localtime(time.time() - since_days * 86400))
        crit = f'(SINCE {since}{" UNSEEN" if unread_only else ""})'
        typ, data = box.uid("search", None, crit)
        uids = (data[0] or b"").split()
        out = []
        for uid in reversed(uids[-int(limit):]):
            typ, parts = box.uid("fetch", uid, "(BODY.PEEK[])")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            if raw:
                out.append(parse_message(raw, uid.decode()))
        return out
    finally:
        try:
            box.logout()
        except Exception:
            pass


def read(uid: str, factory: Optional[Callable] = None) -> dict:
    box = _imap(factory)
    try:
        box.select("INBOX")
        typ, parts = box.uid("fetch", uid.encode() if isinstance(uid, str) else uid, "(BODY.PEEK[])")
        raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
        if not raw:
            raise MailError(f"no message with uid {uid}")
        m = parse_message(raw, str(uid))
        m["body"] = re.sub(r"\r\n", "\n", _text_body(email.message_from_bytes(raw)))[:8000]
        return m
    finally:
        try:
            box.logout()
        except Exception:
            pass


def mark_seen(uid: str, factory: Optional[Callable] = None):
    box = _imap(factory)
    try:
        box.select("INBOX"); box.uid("store", uid.encode() if isinstance(uid, str) else uid, "+FLAGS", "(\\Seen)")
    finally:
        try:
            box.logout()
        except Exception:
            pass


# ----------------------------------------------------------------- SMTP
def check_sendable(to: str, subject: str, body: str, allow_self: bool = False) -> str:
    """The deterministic gate every send passes. Returns the clean address or raises MailError.
    allow_self: only for a draft Pribin approved himself (e.g. a test to his own inbox); never for agent replies,
    which would otherwise answer their own messages in a loop."""
    if not configured():
        raise MailError("Gmail not configured: set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env")
    addr = valid_address(to)
    if not addr:
        raise MailError(f"'{to}' is not an email address; the draft needs a real recipient address")
    if addr == address() and not allow_self:
        raise MailError("refusing to email ourselves")
    if AUTOMATED.search(addr):
        raise MailError(f"refusing to email an automated address ({addr})")
    if blocked(addr):
        raise MailError(f"{addr} is on MAIL_BLOCKLIST")
    if not subject.strip() or not body.strip():
        raise MailError("subject and body are required")
    if len(body) > 6000:
        raise MailError(f"body is {len(body)} characters; keep emails under 6000")
    if PLACEHOLDER.search(subject + "\n" + body):
        raise MailError("the text still contains placeholders like <company> or [Job Title]")
    if sent_today() >= daily_cap():
        raise MailError(f"daily cap reached ({daily_cap()} emails today)")
    return addr


def send(to: str, subject: str, body: str, in_reply_to: Optional[str] = None, references: Optional[str] = None,
         agent: str = "mail-assistant", mode: str = "approved", factory: Optional[Callable] = None) -> dict:
    addr = check_sendable(to, subject, body, allow_self=(mode == "approved"))
    msg = EmailMessage()
    msg["From"] = address(); msg["To"] = addr; msg["Subject"] = subject.strip()
    msg["Date"] = email.utils.formatdate(localtime=True); msg["Message-ID"] = email.utils.make_msgid(domain="agent-hq.local")
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to; msg["References"] = (references or in_reply_to)
    msg.set_content(body.strip() + "\n")
    smtp = (factory or smtplib.SMTP_SSL)(SMTP_HOST, SMTP_PORT, timeout=30)
    try:
        smtp.login(address(), _password())
        smtp.send_message(msg)
    finally:
        try:
            smtp.quit()
        except Exception:
            pass
    row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "to": addr, "subject": subject.strip()[:120], "agent": agent, "mode": mode,
           "message_id": msg["Message-ID"], "in_reply_to": in_reply_to, "chars": len(body)}
    SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(SENT_LOG, "a") as f:
        f.write(json.dumps(row) + "\n")
    return {"sent": True, **row}


def can_autoreply(msg: dict, known_contact: Callable[[str], bool]) -> tuple[bool, str]:
    """Only inside an existing conversation with someone we know, and only when Pribin switched it on."""
    if not autoreply_enabled():
        return False, "MAIL_AUTOREPLY is off: replies need Pribin's approval"
    addr = msg.get("from_email") or ""
    if not addr or msg.get("automated"):
        return False, "automated or unidentified sender"
    if addr == address():
        return False, "our own message"
    if blocked(addr):
        return False, "sender is on MAIL_BLOCKLIST"
    if not (msg.get("in_reply_to") or previously_emailed(addr)):
        return False, "first contact from this address: a new conversation needs Pribin's approval"
    if not known_contact(addr):
        return False, "sender is not a known client or contact in the pipeline or brain"
    return True, "existing conversation with a known contact"
