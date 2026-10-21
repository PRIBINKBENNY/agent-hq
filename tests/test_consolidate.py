import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "office"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain"))


def _brain(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_RERANK", "0")
    from store import BrainStore
    return BrainStore(db_path=str(tmp_path / "b.sqlite"))


def test_consolidation_merges_text_duplicates_and_keeps_protected_kinds(tmp_path, monkeypatch):
    import consolidate
    b = _brain(tmp_path, monkeypatch)
    a = b.remember("Ops review 2026-10-19 08:00: office healthy, nothing to change", agent="coo", kind="event", tags=["ops-review"], dedupe=False)
    b.remember("Ops review 2026-10-20 08:00: office healthy, nothing to change", agent="coo", kind="event", tags=["ops-review", "day2"], dedupe=False)
    b.remember("Ops review 2026-10-21 08:00: office healthy, nothing to change", agent="coo", kind="event", dedupe=False)
    qa1 = b.remember("QA for approval #661: PASS", agent="fact-checker", kind="event", dedupe=False)
    qa2 = b.remember("QA for approval #785: PASS", agent="fact-checker", kind="event", dedupe=False)
    appr1 = b.remember("PENDING APPROVAL from x: quote 450", agent="x", kind="approval", dedupe=False)
    appr2 = b.remember("PENDING APPROVAL from x: quote 450", agent="x", kind="approval", dedupe=False)
    old = b.remember("Old noise event", agent="tracker", kind="event", importance=1, dedupe=False)
    b.conn.execute("UPDATE memories SET created_at=? WHERE id=?", (time.time() - 60 * 86400, old.id)); b.conn.commit()
    p = consolidate.plan(b)
    assert any(keep == a.id and len(others) == 2 for keep, others in p["merges"])
    assert old.id in p["fade"] and appr1.id not in p["fade"]
    out = consolidate.apply(b, p)
    assert out["merged_away"] == 2 and out["faded"] == 1
    k = b.get(a.id); assert k.meta.get("merged") == 2 and "day2" in k.tags
    assert b.get(appr1.id) and b.get(appr2.id)       # approvals untouched
    assert b.get(qa1.id) and b.get(qa2.id)           # different approval ids are different records
    assert b.conn.execute("select count(*) from memories where kind='event'").fetchone()[0] == 3


def test_reranker_reorders_recall_when_scores_available(tmp_path, monkeypatch):
    from store import BrainStore
    monkeypatch.setenv("BRAIN_RERANK", "1")
    b = BrainStore(db_path=str(tmp_path / "b.sqlite"))
    m1 = b.remember("Trading desk rules: max 5 trades a day, 1% risk", agent="risk-officer", kind="fact", dedupe=False)
    m2 = b.remember("Trading desk approved strategies: aapl-h1-sma, meta-h1-sma, de40-h1-rsifade", agent="trading-learner", kind="fact", dedupe=False)
    # fake cross-encoder: the strategies memory answers the question best
    monkeypatch.setattr(b.reranker, "scores", lambda q, docs, allow_local=True: [1.0 if "approved strategies" in d else 0.0 for d in docs])
    out = b.recall("which strategies are approved", limit=2)
    assert out and out[0].id == m2.id
    monkeypatch.setattr(b.reranker, "scores", lambda q, docs, allow_local=True: None)
    assert b.recall("which strategies are approved", limit=2)       # no scores: plain hybrid ranking still works
