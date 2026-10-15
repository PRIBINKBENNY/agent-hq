import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
from store import BrainStore, Embedder  # noqa: E402


class NoEmbed(Embedder):
    """Keyword-only store for fast tests."""
    def __init__(self):
        self.model_name = "none"; self.available = False; self._model = None


@pytest.fixture
def store(tmp_path):
    return BrainStore(tmp_path / "t.db", embedder=NoEmbed())


def test_remember_and_keyword_recall(store):
    m = store.remember("Client Acme prefers blue for all brand assets", agent="lead", kind="decision", tags=["acme"], importance=5)
    assert m.id == 1 and m.tags == ["acme"] and m.importance == 5
    hits = store.recall("blue brand", limit=5)
    assert hits and hits[0].id == m.id


def test_dedupe_merges_tags(store):
    a = store.remember("same fact", agent="x", tags=["one"])
    b = store.remember("same fact", agent="y", tags=["two"])
    assert a.id == b.id and b.tags == ["one", "two"]
    assert store.stats()["total_memories"] == 1


def test_filters_and_namespace(store):
    store.remember("global note about python", kind="note")
    store.remember("client note about python", kind="note", namespace="client-a")
    assert len(store.recall("python", namespace="global")) == 1
    assert len(store.recall("python", namespace="*")) == 2
    assert len(store.recall("python", kind="decision")) == 0


def test_update_forget_and_ttl(store):
    m = store.remember("temp state", ttl_seconds=-1)   # already expired
    assert store.recall("temp") == []
    m2 = store.remember("wrong fact")
    store.update(m2.id, content="right fact", add_tags=["fixed"])
    assert store.get(m2.id).content == "right fact" and "fixed" in store.get(m2.id).tags
    assert store.forget(m2.id) is True and store.forget(m2.id) is False


def test_task_board(store):
    t = store.task_create("do thing", "details", owner="job-scout", priority=5, source="test")
    assert t["status"] == "queued"
    low = store.task_create("low", owner="x", priority=1)
    nxt = store.task_claim_next()
    assert nxt["id"] == t["id"] and nxt["status"] == "running"
    store.task_update(t["id"], status="done", result="ok")
    assert store.task_get(t["id"])["status"] == "done"
    assert [x["id"] for x in store.task_list(status="queued")] == [low["id"]]
    assert store.task_claim_next()["id"] == low["id"]
    assert store.task_claim_next() is None


def test_recall_with_no_results_releases_write_lock(tmp_path):
    """Regression: an empty recall used to leave a DELETE uncommitted, blocking other connections."""
    db = tmp_path / "lock.db"
    a = BrainStore(db, embedder=NoEmbed())
    assert a.recall("nothing here") == []
    b = BrainStore(db, embedder=NoEmbed())
    m = b.remember("written by a second connection")     # would raise 'database is locked' before the fix
    assert m.id == 1


def test_concurrent_reads_from_threads_are_safe(tmp_path):
    """Regression: a shared connection across threads returned rows from the wrong query."""
    import threading
    s = BrainStore(tmp_path / "t.db", embedder=NoEmbed())
    for i in range(40):
        s.remember(f"memory number {i} about topic {i % 5}", kind="note" if i % 2 else "fact", tags=[f"t{i % 5}"])
        s.task_create(f"task {i}", "d", owner=f"agent{i % 3}")
    errors = []
    def reader(n):
        try:
            for _ in range(60):
                for m in s.recent(limit=30, kind="fact"):
                    assert m.kind == "fact" and isinstance(m.id, int)
                for t in s.task_list(limit=50):
                    assert "title" in t and t["title"].startswith("task")
                s.recall("topic 3", limit=5)
                s.stats()
        except Exception as e:
            errors.append(repr(e))
    threads = [threading.Thread(target=reader, args=(i,)) for i in range(8)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert errors == []
