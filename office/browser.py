"""
Browser agent (Playwright, free, local Chromium). Two jobs:
  read_page(url):       what a real browser sees (JavaScript rendered) plus an inventory of the page's form fields.
  prefill(url, fields): open the page in a VISIBLE Chromium that stays open, fill the fields, attach the CV, screenshot,
                        and stop. Nothing is ever submitted by code: Pribin reviews the window and presses the button.

The visible browser is a persistent Chromium (own profile under workspace/.browser-profile) started with a debugging
port; the tool connects, fills, disconnects, and the window outlives the agent's run. Big job boards whose terms forbid
automated applications are blocked; company career pages and the common applicant-tracking systems are fine.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "workspace"
PROFILE = WORKSPACE / ".browser-profile"
CDP_PORT = int(os.environ.get("BROWSER_CDP_PORT") or 9333)
BLOCKED = ("linkedin.com", "indeed.com", "indeed.co.uk", "glassdoor.com", "glassdoor.co.uk", "ziprecruiter.com", "reed.co.uk",
           "totaljobs.com", "cv-library.co.uk", "monster.com", "facebook.com", "x.com", "twitter.com")
SUBMIT_WORDS = re.compile(r"submit|apply now|send application|finish|complete application", re.I)
MAX_FIELDS = 60


class BrowserError(Exception):
    pass


def host_ok(url: str) -> bool:
    h = re.sub(r"^https?://", "", url or "").split("/")[0].lower()
    return bool(h) and not any(h == b or h.endswith("." + b) for b in BLOCKED)


def _field_inventory(page) -> list[dict]:
    js = """() => {
      const out = []; const seen = new Set();
      const labelFor = el => {
        if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return l.innerText.trim(); }
        const p = el.closest('label'); if (p) return p.innerText.trim();
        const aria = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby');
        if (aria) { const by = document.getElementById(aria); return (by ? by.innerText : aria).trim(); }
        return el.getAttribute('placeholder') || '';
      };
      for (const el of document.querySelectorAll('input, textarea, select')) {
        const type = (el.type || el.tagName).toLowerCase();
        if (['hidden', 'submit', 'button', 'image', 'reset'].includes(type)) continue;
        const r = el.getBoundingClientRect(); if (r.width === 0 && r.height === 0 && type !== 'file') continue;
        const key = el.name || el.id || labelFor(el); if (!key || seen.has(key + type)) continue; seen.add(key + type);
        out.push({label: labelFor(el).slice(0, 80), name: el.name || '', id: el.id || '', type, required: !!el.required,
                  options: el.tagName === 'SELECT' ? [...el.options].map(o => o.text.trim()).slice(0, 30) : undefined});
      }
      return out;
    }"""
    return page.evaluate(js)[:MAX_FIELDS]


def read_page(url: str, max_chars: int = 8000, wait_ms: int = 1500) -> dict:
    """Rendered text and form fields of a page, headless."""
    if not host_ok(url):
        raise BrowserError("that site's terms forbid automated access; use its public page or the company's own careers site")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            pg = b.new_page(viewport={"width": 1280, "height": 1600})
            pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                pg.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            pg.wait_for_timeout(wait_ms)
            text = re.sub(r"\n{3,}", "\n\n", pg.inner_text("body")).strip()
            return {"url": pg.url, "title": pg.title(), "text": text[:max_chars], "chars": len(text), "fields": _field_inventory(pg)}
        finally:
            b.close()


def _cdp_alive() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", CDP_PORT)) == 0


def ensure_visible_browser() -> str:
    """A visible Chromium with its own profile and a debugging port, started once and left open for Pribin."""
    if _cdp_alive():
        return f"http://127.0.0.1:{CDP_PORT}"
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        exe = p.chromium.executable_path
    PROFILE.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([exe, f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={PROFILE}", "--no-first-run", "--no-default-browser-check",
                      "--window-size=1280,1000", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(40):
        if _cdp_alive():
            return f"http://127.0.0.1:{CDP_PORT}"
        time.sleep(0.25)
    raise BrowserError("could not start the visible browser")


def _match(page, key: str):
    """Locate a field by label text, placeholder, name or id (case-insensitive, first match)."""
    for loc in (page.get_by_label(key, exact=False), page.get_by_placeholder(key, exact=False),
                page.locator(f"[name='{key}'], #{key}" if re.match(r"^[\w-]+$", key) else "css=__none__")):
        try:
            if loc.count() > 0:
                return loc.first
        except Exception:
            continue
    return None


def prefill(url: str, fields: dict, shot_path: Path, cv_path: Path | None = None) -> dict:
    """Fill a form in the visible browser and screenshot it. Never clicks anything that could submit."""
    if not host_ok(url):
        raise BrowserError("that site's terms forbid automated applications; apply there by hand")
    from playwright.sync_api import sync_playwright
    endpoint = ensure_visible_browser(); filled, missed = [], []
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(endpoint)
        ctx = b.contexts[0] if b.contexts else b.new_context()
        pg = ctx.new_page(); pg.goto(url, wait_until="domcontentloaded", timeout=45000)
        try:
            pg.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        for key, val in list(fields.items())[:MAX_FIELDS]:
            if SUBMIT_WORDS.search(str(key)):
                missed.append(f"{key}: refused (submit-like control)"); continue
            loc = _match(pg, str(key))
            if loc is None:
                missed.append(f"{key}: no field"); continue
            try:
                tag = loc.evaluate("el => el.tagName.toLowerCase()"); typ = (loc.get_attribute("type") or "").lower()
                if typ == "file":
                    if cv_path and cv_path.exists():
                        loc.set_input_files(str(cv_path)); filled.append(f"{key}: {cv_path.name}")
                    else:
                        missed.append(f"{key}: no file to attach")
                elif tag == "select":
                    loc.select_option(label=str(val)); filled.append(f"{key}: {val}")
                elif typ in ("checkbox", "radio"):
                    if str(val).lower() in ("true", "yes", "1", "on"):
                        loc.check(); filled.append(f"{key}: checked")
                else:
                    loc.fill(str(val)); filled.append(f"{key}: {str(val)[:60]}")
            except Exception as e:
                missed.append(f"{key}: {str(e).splitlines()[0][:80]}")
        shot_path.parent.mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(shot_path), full_page=True)
        pg.bring_to_front()
        b.close()      # disconnects only; the visible window stays open for Pribin
    return {"filled": filled, "missed": missed, "screenshot": str(shot_path.relative_to(WORKSPACE)), "note": "Nothing was submitted. Review the open browser window and press the site's own button."}
