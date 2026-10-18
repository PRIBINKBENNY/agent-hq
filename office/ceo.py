"""
CEO layer: what turns the office's work into money.

- rank_approval(): how much an approval is worth acting on today (money value, urgency, age), so the dashboard,
  the phone and the daily digest show the most valuable item first.
- digest(): the twice-daily approval digest (push to the phone + Mac notification + workspace/ops/approval-digest.md).
  Run as a script from the schedule: no language model, no token cost.
- outcomes(): the outcome dashboard (applications -> responses -> interviews -> offers; proposals -> sent -> won -> paid;
  pipeline and revenue in GBP; tokens per outcome), used by the dashboard, the COO and the chief of staff.
- Deals: a proposal's life after approval (sent, won, lost, paid) is recorded as a brain memory of kind "deal".
"""

from __future__ import annotations

import glob
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office")); sys.path.insert(0, str(ROOT / "brain"))

REVENUE_AGENTS = {"application-tailor", "proposal-writer", "lead-finder", "mail-assistant", "job-scout", "networker",
                  "interview-coach", "fact-checker", "tracker", "chief-of-staff"}
INTERNAL_AGENTS = {"docs-writer", "release-manager", "agent-builder", "app-developer", "web-builder", "reviewer", "tester",
                   "debugger", "code-builder", "studio-lead", "project-manager", "content-writer", "linkedin-writer", "ml-researcher"}
DEAL_STAGES = ("sent", "won", "lost", "paid")


def _brain():
    import tools
    return tools.brain


def price_of(text: str) -> float:
    """First GBP amount in a proposal or approval text (e.g. 'Price: £1,400')."""
    m = re.search(r"£\s?([\d,]+(?:\.\d+)?)", text or "")
    return float(m.group(1).replace(",", "")) if m else 0.0


def rank_approval(m) -> tuple[float, str]:
    """(score, why). Higher = act first. Money and time-sensitivity first, internal changes last."""
    txt = (m.content or "").lower(); tags = set(m.tags or []); age_h = (time.time() - (m.created_at or time.time())) / 3600
    if "skill-update" in tags or "brief-proposal" in tags:   # tags first: an update ABOUT LinkedIn is not a post
        base, why = 10, "internal change"
    elif "reply" in tags or ("email" in tags and "client" in txt):
        base, why = 90, "a client or contact is waiting for a reply"
    elif "/proposals/" in txt or "proposal" in txt:
        val = price_of(m.content); base, why = 72 + min(15, val / 100), f"proposal worth £{val:,.0f}" if val else "proposal"   # speed wins freelance work
    elif "application" in tags or "/applications/" in txt or "cover letter" in txt or "cv" in tags:
        fit = re.search(r"fit\s*(\d)", txt); f = int(fit.group(1)) if fit else 3
        base, why = 50 + f * 6, f"job application (fit {f}/5)"
    elif "email" in tags:
        base, why = 55, "email draft"
    elif "linkedin" in txt or "/posts/" in txt:
        base, why = 35, "LinkedIn post"
    elif "/networking/" in txt or "outreach" in txt:
        base, why = 40, "networking outreach"
    else:
        base, why = 25, "other"
    if "qa-fail" in tags:
        base -= 25; why += ", QA found problems"
    return base + min(15, age_h / 4), why                       # waiting longer pushes it up, a little


def pending_ranked() -> list[dict]:
    b = _brain(); out = []
    for m in b.recent(limit=200, kind="approval", namespace="*"):
        if "pending" not in m.tags:
            continue
        s, why = rank_approval(m)
        out.append({"id": m.id, "score": round(s, 1), "why": why, "text": re.sub(r"^(QA: \w+ - )?PENDING APPROVAL from [\w-]+: ", "", m.content)[:160],
                    "age_h": round((time.time() - m.created_at) / 3600, 1)})
    return sorted(out, key=lambda x: -x["score"])


def digest(send: bool = True) -> dict:
    items = pending_ranked()
    lines = [f"# Approval digest {time.strftime('%a %d %b %H:%M')}", "",
             f"{len(items)} waiting. Most valuable first; about {max(1, round(len(items) * 0.7))} minutes on the dashboard or phone.", ""]
    for i, it in enumerate(items[:15], 1):
        lines.append(f"{i}. #{it['id']} ({it['why']}, waiting {it['age_h']:.0f}h): {it['text']}")
    out = ROOT / "workspace" / "ops" / "approval-digest.md"; out.parent.mkdir(parents=True, exist_ok=True); out.write_text("\n".join(lines) + "\n")
    res = {"waiting": len(items), "top": items[:3]}
    if send and items:
        head = items[0]
        body = f"Top: {head['why']}. " + (f"Then {items[1]['why']}." if len(items) > 1 else "")
        try:
            import push
            res["push"] = push.send(f"{len(items)} approvals waiting (~{max(1, round(len(items) * 0.7))} min)", body, url="/m", tag="digest")
        except Exception as e:
            res["push_error"] = str(e)[:120]
        try:
            import tools
            tools.notify(f"{len(items)} approvals waiting", body)
        except Exception:
            pass
    return res


# ----------------------------------------------------------------------------- deals (freelance after approval)
def deal_set(approval_id: int, stage: str, value: float | None = None, note: str = "", agent: str = "pribin") -> dict:
    if stage not in DEAL_STAGES:
        raise ValueError(f"stage must be one of {DEAL_STAGES}")
    b = _brain(); a = b.get(int(approval_id))
    client = re.search(r"(?:proposal for|proposal to|for)\s+([A-Z][\w .&'-]{1,40}?)(?:\s*\(|\s+—|\s+-|:|\.|$)", a.content)
    client = client.group(1).strip() if client else f"approval #{a.id}"
    val = float(value) if value is not None else price_of(a.content)
    existing = next((m for m in b.recent(limit=300, kind="deal", namespace="*") if (m.meta or {}).get("approval_id") == a.id), None)
    meta = {"approval_id": a.id, "client": client, "value": val, "stage": stage, "stage_at": time.strftime("%Y-%m-%d %H:%M"), "note": note[:200]}
    text = f"Deal with {client}: {stage}, £{val:,.0f} (approval #{a.id}). {note[:120]}".strip()
    if existing:
        b.update(existing.id, agent=agent, content=text, meta={**(existing.meta or {}), **meta}, add_tags=[f"deal:{stage}"])
        did = existing.id
    else:
        did = b.remember(text, agent=agent, kind="deal", importance=5, tags=["deal", f"deal:{stage}"], meta=meta).id
    return {"deal": did, **meta}


def outcomes(days: int = 30) -> dict:
    b = _brain(); since = time.time() - days * 86400
    jobs = [m for m in b.recent(limit=600, kind="job", namespace="*")]
    def jstatus(m):
        return (m.meta or {}).get("status") or next((t.split(":", 1)[1] for t in m.tags if t.startswith("status:")), "found")
    st = [jstatus(m) for m in jobs]
    applied_jobs = sum(1 for s in st if s in ("applied", "interview", "offer", "rejected"))
    applied_events = {next((t for t in m.tags if t.startswith("company:")), m.content[:40]) for m in b.recent(limit=400, namespace="*", tags=["status:applied"])}
    applied = max(applied_jobs, len(applied_events))           # "I applied" on an approval records an event, not always the job
    responses = sum(1 for s in st if s in ("interview", "offer", "rejected")); interviews = sum(1 for s in st if s in ("interview", "offer")); offers = st.count("offer")
    approvals = [m for m in b.recent(limit=400, kind="approval", namespace="*") if m.created_at >= since]
    proposals = [m for m in approvals if "/proposals/" in m.content.lower() or "proposal" in m.content.lower()]
    deals = [m.meta or {} for m in b.recent(limit=300, kind="deal", namespace="*")]
    by_stage = {s: [d for d in deals if d.get("stage") == s] for s in DEAL_STAGES}
    pipeline = sum(d.get("value", 0) for d in by_stage["sent"] + by_stage["won"]); revenue = sum(d.get("value", 0) for d in by_stage["paid"])
    won_value = sum(d.get("value", 0) for d in by_stage["won"] + by_stage["paid"])
    posts = [m for m in approvals if "linkedin" in m.content.lower() or "/posts/" in m.content.lower()]
    tokens, per_agent = 0, {}
    for f in glob.glob(str(ROOT / "office" / "logs" / "20*.jsonl")):
        for ln in open(f):
            try:
                e = json.loads(ln); ts = time.mktime(time.strptime(e["ts"], "%Y-%m-%d %H:%M:%S"))
            except Exception:
                continue
            if ts < since:
                continue
            t = int(e.get("tokens_in", 0)) + int(e.get("tokens_out", 0)); tokens += t; per_agent[e["agent"]] = per_agent.get(e["agent"], 0) + t
    rev_tokens = sum(v for a, v in per_agent.items() if a in REVENUE_AGENTS)
    pct = lambda a, b2: round(100 * a / b2, 1) if b2 else None
    return {
        "window_days": days,
        "jobs": {"found": len(jobs), "applied": applied, "responses": responses, "interviews": interviews, "offers": offers,
                 "response_rate_pct": pct(responses, applied), "interview_rate_pct": pct(interviews, applied)},
        "freelance": {"proposals_drafted": len(proposals), "proposals_approved": sum(1 for m in proposals if "approved" in m.tags or "sent" in m.tags),
                      "sent": len(by_stage["sent"]) + len(by_stage["won"]) + len(by_stage["lost"]) + len(by_stage["paid"]),
                      "won": len(by_stage["won"]) + len(by_stage["paid"]), "lost": len(by_stage["lost"]),
                      "pipeline_gbp": round(pipeline), "won_gbp": round(won_value), "revenue_gbp": round(revenue)},
        "brand": {"posts_drafted": len(posts), "posts_approved": sum(1 for m in posts if "approved" in m.tags), "posts_published": sum(1 for m in posts if "posted" in m.tags)},
        "approvals_waiting": len(pending_ranked()),
        "approved_proposals": [{"id": m.id, "text": re.sub(r"^(APPROVED|SENT) from [\w-]+: ", "", m.content)[:140], "value": price_of(m.content),
                                "stage": next((d.get("stage") for d in deals if d.get("approval_id") == m.id), None)}
                               for m in b.recent(limit=400, kind="approval", namespace="*")
                               if ("approved" in m.tags or "sent" in m.tags) and ("/proposals/" in m.content.lower() or "proposal" in m.content.lower())][:15],
        "efficiency": {"tokens": tokens, "revenue_work_share_pct": pct(rev_tokens, tokens),
                       "tokens_per_application": (lambda n: round(per_agent.get("application-tailor", 0) / n) if n else None)(
                           len(list((ROOT / "workspace" / "applications").glob("*/*/cv.md")))),   # tailor's tokens per tailored CV
                       "tokens_per_proposal": round(per_agent.get("proposal-writer", 0) / len(proposals)) if proposals else None,
                       "top_spenders": sorted(per_agent.items(), key=lambda kv: -kv[1])[:6]},
    }


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "digest":
        import runtime  # noqa: F401  (.env for push keys)
        print(json.dumps(digest(), indent=1))
    else:
        print(json.dumps(outcomes(), indent=1))
