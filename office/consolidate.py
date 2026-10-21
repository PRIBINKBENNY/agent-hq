"""
Nightly memory consolidation: merge near-duplicate memories, let stale low-value events fade, keep provenance.
Rules (code, not prompts):
  - only kinds event, note, fact, lesson, lead are touched; approvals, deals, jobs, decisions, profile, contacts never
  - the trading library (namespace 'trading') is never touched
  - duplicates = same kind, same normalised opening (first 80 chars, lowercased, dates/times stripped) OR embedding
    cosine >= 0.94 within the same kind and agent; the oldest survives with merged tags and meta.merged += n
  - fade = events with importance <= 2, older than 45 days, never recalled (access_count 0)
Runs at 03:30 from the schedule; prints a summary and stores one 'consolidation' event.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office")); sys.path.insert(0, str(ROOT / "brain"))

MERGE_KINDS = ("event", "note", "fact", "lesson", "lead")
SKIP_NS = ("trading",)
COS = 0.94
FADE_DAYS, FADE_IMPORTANCE = 45, 2


def _norm(text: str) -> str:
    """Dates and times are noise; other numbers (ids, counts) are identity: 'QA for approval #661' != '#785'."""
    t = re.sub(r"\b20\d\d-\d\d-\d\d(?:[ t]\d\d:\d\d(?::\d\d)?)?\b|\b\d\d:\d\d\b", "#", (text or "").lower())
    return re.sub(r"[^a-z0-9# ]+", " ", t).strip()[:80]


def plan(brain) -> dict:
    rows = brain.conn.execute("SELECT id, kind, agent, namespace, content, tags, importance, created_at, access_count, embedding FROM memories "
                              f"WHERE kind IN ({','.join('?' * len(MERGE_KINDS))}) ORDER BY created_at", MERGE_KINDS).fetchall()
    rows = [r for r in rows if r["namespace"] not in SKIP_NS]
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(f"{r['kind']}|{_norm(r['content'])}", []).append(r)
    merges: list[tuple[int, list[int]]] = [(g[0]["id"], [x["id"] for x in g[1:]]) for g in groups.values() if len(g) > 1]
    taken = {i for _, ids in merges for i in ids} | {k for k, _ in merges}
    # embedding near-duplicates within kind+agent (skip anything already in a text group)
    by_ka: dict[str, list] = {}
    for r in rows:
        if r["id"] not in taken and r["embedding"]:
            by_ka.setdefault(f"{r['kind']}|{r['agent']}", []).append(r)
    for grp in by_ka.values():
        if len(grp) < 2:
            continue
        mat = np.frombuffer(b"".join(r["embedding"] for r in grp), dtype=np.float32).reshape(len(grp), -1)
        sims = mat @ mat.T; used = set()
        ids = [frozenset(re.findall(r"#\d+", r["content"])) for r in grp]      # '#661' and '#785' are different records, however similar
        for i in range(len(grp)):
            if i in used:
                continue
            dup = [j for j in range(i + 1, len(grp)) if j not in used and sims[i, j] >= COS and ids[i] == ids[j]]
            if dup:
                used.update(dup); used.add(i); merges.append((grp[i]["id"], [grp[j]["id"] for j in dup]))
    cutoff = time.time() - FADE_DAYS * 86400
    fade = [r["id"] for r in rows if r["kind"] == "event" and r["importance"] <= FADE_IMPORTANCE and r["created_at"] < cutoff and r["access_count"] == 0
            and r["id"] not in taken]
    return {"merges": merges, "fade": fade, "scanned": len(rows)}


def apply(brain, p: dict) -> dict:
    merged = 0
    for keep, others in p["merges"]:
        k = brain.get(keep); tags = set(k.tags or []); meta = dict(k.meta or {}); last = k.created_at
        for oid in others:
            try:
                o = brain.get(oid)
            except KeyError:
                continue
            tags |= set(o.tags or []); last = max(last, o.created_at); brain.forget(oid, agent="consolidation"); merged += 1
        meta["merged"] = int(meta.get("merged", 0)) + len(others); meta["last_seen"] = time.strftime("%Y-%m-%d", time.localtime(last))
        brain.update(keep, agent="consolidation", tags=sorted(tags), meta=meta)
    for fid in p["fade"]:
        brain.forget(fid, agent="consolidation")
    return {"merged_away": merged, "faded": len(p["fade"]), "scanned": p["scanned"]}


def run() -> dict:
    from store import BrainStore
    b = BrainStore(); out = apply(b, plan(b))
    b.remember(f"Consolidation: {out['merged_away']} duplicates merged, {out['faded']} stale events faded, {out['scanned']} scanned.",
               agent="consolidation", kind="event", importance=2, tags=["consolidation", "ops"], dedupe=False)
    return out


if __name__ == "__main__":
    import runtime  # noqa: F401
    if "--plan" in sys.argv:
        from store import BrainStore
        p = plan(BrainStore()); print(json.dumps({"merge_groups": len(p["merges"]), "to_merge_away": sum(len(o) for _, o in p["merges"]), "fade": len(p["fade"]), "scanned": p["scanned"]}))
    else:
        print(json.dumps(run()))
