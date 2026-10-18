"""
Brain store: the shared memory every agent reads and writes.

Storage is a single SQLite file. Each memory is indexed two ways:
  * FTS5 full-text index  -> exact words, names, IDs, code (BM25 ranking)
  * local vector embedding -> meaning, paraphrases, "things like this"
Recall fuses both rankings (reciprocal rank fusion) so a query works whether
the agent remembers the exact phrase or only the idea.

Everything runs on this machine. No API keys, no quotas, no network after the
embedding model has been downloaded once.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

DEFAULT_DB = Path(os.environ.get("BRAIN_DB", Path(__file__).resolve().parent / "data" / "brain.db"))
EMBED_MODEL = os.environ.get("BRAIN_EMBED_MODEL", "BAAI/bge-small-en-v1.5")  # 384 dims, ~130MB, runs on CPU


# --------------------------------------------------------------------------- #
# Embeddings (optional, local). Falls back to keyword-only if fastembed is
# missing so the brain never stops working.
# --------------------------------------------------------------------------- #
class Embedder:
    def __init__(self, model_name: str = EMBED_MODEL):
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()
        self.available = True
        try:
            import fastembed  # noqa: F401
        except ImportError:
            self.available = False

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding
                    cache = Path(__file__).resolve().parent / "data" / "models"
                    cache.mkdir(parents=True, exist_ok=True)
                    self._model = TextEmbedding(model_name=self.model_name, cache_dir=str(cache))
        return self._model

    def _remote(self, texts: list[str], query: bool) -> Optional[np.ndarray]:
        """Agent processes borrow the dashboard's loaded model (same model, same vectors) instead of loading
        their own copy (~200 MB each). Falls back to the local model if the dashboard does not answer."""
        url = os.environ.get("BRAIN_EMBED_URL")
        if not url:
            return None
        try:
            import httpx
            r = httpx.post(url, json={"texts": texts, "query": query, "model": self.model_name}, timeout=30)
            if r.status_code == 200:
                return np.array(r.json()["vectors"], dtype=np.float32)
        except Exception:
            pass
        return None

    def embed(self, texts: list[str]) -> Optional[np.ndarray]:
        if not self.available or not texts:
            return None
        v = self._remote(texts, False)
        if v is not None:
            return v
        model = self._load()
        vecs = np.array(list(model.embed(texts)), dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vecs / norms

    def embed_query(self, text: str) -> Optional[np.ndarray]:
        if not self.available:
            return None
        v = self._remote([text], True)
        if v is not None:
            return v[0]
        model = self._load()
        vec = np.array(list(model.query_embed(text)), dtype=np.float32)[0]
        n = np.linalg.norm(vec)
        return vec / n if n else vec


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Memory:
    id: int
    content: str
    agent: str
    kind: str                     # fact | decision | task | event | note | profile
    tags: list[str]
    importance: int               # 1..5
    namespace: str                # team or project scope, "global" by default
    created_at: float
    updated_at: float
    expires_at: Optional[float]
    source: Optional[str]
    score: Optional[float] = None
    access_count: int = 0
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.created_at))
        return d


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS memories (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    content      TEXT    NOT NULL,
    agent        TEXT    NOT NULL DEFAULT 'unknown',
    kind         TEXT    NOT NULL DEFAULT 'note',
    tags         TEXT    NOT NULL DEFAULT '[]',
    importance   INTEGER NOT NULL DEFAULT 3,
    namespace    TEXT    NOT NULL DEFAULT 'global',
    created_at   REAL    NOT NULL,
    updated_at   REAL    NOT NULL,
    expires_at   REAL,
    source       TEXT,
    access_count INTEGER NOT NULL DEFAULT 0,
    meta         TEXT    NOT NULL DEFAULT '{}',
    embedding    BLOB
);

CREATE INDEX IF NOT EXISTS idx_mem_ns      ON memories(namespace);
CREATE INDEX IF NOT EXISTS idx_mem_agent   ON memories(agent);
CREATE INDEX IF NOT EXISTS idx_mem_kind    ON memories(kind);
CREATE INDEX IF NOT EXISTS idx_mem_created ON memories(created_at);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content, tags, agent, kind,
    content='memories', content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memories_fts(rowid, content, tags, agent, kind)
  VALUES (new.id, new.content, new.tags, new.agent, new.kind);
END;
CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content, tags, agent, kind)
  VALUES ('delete', old.id, old.content, old.tags, old.agent, old.kind);
END;
CREATE TRIGGER IF NOT EXISTS mem_au AFTER UPDATE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content, tags, agent, kind)
  VALUES ('delete', old.id, old.content, old.tags, old.agent, old.kind);
  INSERT INTO memories_fts(rowid, content, tags, agent, kind)
  VALUES (new.id, new.content, new.tags, new.agent, new.kind);
END;

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    detail      TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'queued',   -- queued | running | blocked | done | failed | cancelled
    owner       TEXT    NOT NULL DEFAULT 'chief-of-staff',
    created_by  TEXT    NOT NULL DEFAULT 'pribin',
    priority    INTEGER NOT NULL DEFAULT 3,
    namespace   TEXT    NOT NULL DEFAULT 'global',
    created_at  REAL    NOT NULL,
    updated_at  REAL    NOT NULL,
    started_at  REAL,
    finished_at REAL,
    result      TEXT,
    run_id      TEXT,
    source      TEXT                                  -- ui | approval | schedule:<name> | agent
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

CREATE TABLE IF NOT EXISTS activity (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL NOT NULL,
    agent      TEXT NOT NULL,
    action     TEXT NOT NULL,
    memory_id  INTEGER,
    detail     TEXT
);
CREATE INDEX IF NOT EXISTS idx_act_ts ON activity(ts);
"""


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #
class BrainStore:
    def __init__(self, db_path: Path | str = DEFAULT_DB, embedder: Optional[Embedder] = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._local = threading.local()
        self.conn.executescript(SCHEMA)
        self.embedder = embedder or Embedder()

    @property
    def conn(self) -> sqlite3.Connection:
        """One SQLite connection per thread. Sharing one across threads interleaves cursors and
        returns rows from the wrong query (seen as tuple/None errors in the dashboard)."""
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(str(self.db_path), timeout=60)          # many agents write at once: queue, do not fail
            c.row_factory = sqlite3.Row
            self._local.conn = c
        return c

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _row_to_memory(row: sqlite3.Row, score: Optional[float] = None) -> Memory:
        return Memory(
            id=row["id"],
            content=row["content"],
            agent=row["agent"],
            kind=row["kind"],
            tags=json.loads(row["tags"] or "[]"),
            importance=row["importance"],
            namespace=row["namespace"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            source=row["source"],
            access_count=row["access_count"],
            meta=json.loads(row["meta"] or "{}"),
            score=score,
        )

    @staticmethod
    def _norm_tags(tags: Optional[Iterable[str]]) -> list[str]:
        if not tags:
            return []
        if isinstance(tags, str):
            tags = [t for t in tags.replace(";", ",").split(",")]
        return sorted({t.strip().lower() for t in tags if t and t.strip()})

    def _log(self, agent: str, action: str, memory_id: Optional[int] = None, detail: Optional[str] = None):
        self.conn.execute(
            "INSERT INTO activity(ts, agent, action, memory_id, detail) VALUES (?,?,?,?,?)",
            (time.time(), agent, action, memory_id, detail),
        )

    def _purge_expired(self):
        with self._lock:
            cur = self.conn.execute("DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < ?", (time.time(),))
            self.conn.commit()   # never leave the write lock open (callers may return early)
            return cur.rowcount

    # ------------------------------------------------------------------ write
    def remember(
        self,
        content: str,
        agent: str = "unknown",
        kind: str = "note",
        tags: Optional[Iterable[str]] = None,
        importance: int = 3,
        namespace: str = "global",
        ttl_seconds: Optional[float] = None,
        source: Optional[str] = None,
        meta: Optional[dict] = None,
        dedupe: bool = True,
    ) -> Memory:
        content = content.strip()
        if not content:
            raise ValueError("content is empty")
        importance = max(1, min(5, int(importance)))
        tags_l = self._norm_tags(tags)
        now = time.time()

        with self._lock:
            if dedupe:
                row = self.conn.execute(
                    "SELECT * FROM memories WHERE namespace=? AND content=? LIMIT 1", (namespace, content)
                ).fetchone()
                if row:
                    merged = sorted(set(json.loads(row["tags"]) + tags_l))
                    self.conn.execute(
                        "UPDATE memories SET tags=?, importance=MAX(importance,?), updated_at=? WHERE id=?",
                        (json.dumps(merged), importance, now, row["id"]),
                    )
                    self._log(agent, "remember_dup", row["id"])
                    self.conn.commit()
                    return self.get(row["id"])

            vec = self.embedder.embed([content])
            blob = vec[0].tobytes() if vec is not None else None
            cur = self.conn.execute(
                """INSERT INTO memories(content, agent, kind, tags, importance, namespace,
                                        created_at, updated_at, expires_at, source, meta, embedding)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    content, agent, kind, json.dumps(tags_l), importance, namespace,
                    now, now, (now + ttl_seconds) if ttl_seconds else None, source,
                    json.dumps(meta or {}), blob,
                ),
            )
            mid = cur.lastrowid
            self._log(agent, "remember", mid, kind)
            self.conn.commit()
            return self.get(mid)

    def update(
        self,
        memory_id: int,
        agent: str = "unknown",
        content: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
        add_tags: Optional[Iterable[str]] = None,
        importance: Optional[int] = None,
        kind: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> Memory:
        with self._lock:
            row = self.conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not row:
                raise KeyError(f"memory {memory_id} not found")
            sets, vals = [], []
            if content is not None and content.strip() != row["content"]:
                content = content.strip()
                sets.append("content=?"); vals.append(content)
                vec = self.embedder.embed([content])
                sets.append("embedding=?"); vals.append(vec[0].tobytes() if vec is not None else None)
            if tags is not None:
                sets.append("tags=?"); vals.append(json.dumps(self._norm_tags(tags)))
            elif add_tags:
                merged = sorted(set(json.loads(row["tags"]) + self._norm_tags(add_tags)))
                sets.append("tags=?"); vals.append(json.dumps(merged))
            if importance is not None:
                sets.append("importance=?"); vals.append(max(1, min(5, int(importance))))
            if kind is not None:
                sets.append("kind=?"); vals.append(kind)
            if meta is not None:
                merged_meta = {**json.loads(row["meta"] or "{}"), **meta}
                sets.append("meta=?"); vals.append(json.dumps(merged_meta))
            if sets:
                sets.append("updated_at=?"); vals.append(time.time())
                vals.append(memory_id)
                self.conn.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id=?", vals)
                self._log(agent, "update", memory_id)
                self.conn.commit()
            return self.get(memory_id)

    def forget(self, memory_id: int, agent: str = "unknown") -> bool:
        with self._lock:
            cur = self.conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
            if cur.rowcount:
                self._log(agent, "forget", memory_id)
            self.conn.commit()
            return bool(cur.rowcount)

    # ------------------------------------------------------------------- read
    def get(self, memory_id: int, touch: bool = False) -> Memory:
        row = self.conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        if not row:
            raise KeyError(f"memory {memory_id} not found")
        if touch:
            self.conn.execute("UPDATE memories SET access_count=access_count+1 WHERE id=?", (memory_id,))
            self.conn.commit()
        return self._row_to_memory(row)

    def _filters(self, namespace, agent, kind, tags, min_importance, since):
        clauses, vals = ["(expires_at IS NULL OR expires_at > ?)"], [time.time()]
        if namespace and namespace != "*":
            clauses.append("namespace=?"); vals.append(namespace)
        if agent:
            clauses.append("agent=?"); vals.append(agent)
        if kind:
            clauses.append("kind=?"); vals.append(kind)
        if min_importance:
            clauses.append("importance>=?"); vals.append(int(min_importance))
        if since:
            clauses.append("created_at>=?"); vals.append(float(since))
        for t in self._norm_tags(tags):
            clauses.append("tags LIKE ?"); vals.append(f'%"{t}"%')
        return " AND ".join(clauses), vals

    def recall(
        self,
        query: str,
        limit: int = 8,
        namespace: str = "global",
        agent: Optional[str] = None,
        kind: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
        min_importance: Optional[int] = None,
        since: Optional[float] = None,
    ) -> list[Memory]:
        """Hybrid search: BM25 keyword + vector similarity, fused by RRF, then boosted by importance/recency."""
        query = (query or "").strip()
        limit = max(1, min(100, int(limit)))
        where, vals = self._filters(namespace, agent, kind, tags, min_importance, since)
        self._purge_expired()
        pool = max(limit * 5, 40)
        ranks: dict[int, float] = {}
        K = 60.0

        # 1) keyword ranking
        if query:
            fts_q = " OR ".join(f'"{w}"' for w in query.replace('"', " ").split() if w)
            try:
                rows = self.conn.execute(
                    f"""SELECT m.id FROM memories_fts f JOIN memories m ON m.id = f.rowid
                        WHERE memories_fts MATCH ? AND {where}
                        ORDER BY bm25(memories_fts, 10.0, 3.0, 1.0, 1.0) LIMIT ?""",
                    [fts_q, *vals, pool],
                ).fetchall()
                for r, row in enumerate(rows):
                    ranks[row["id"]] = ranks.get(row["id"], 0) + 1.0 / (K + r)
            except sqlite3.OperationalError:
                pass

        # 2) semantic ranking
        qvec = self.embedder.embed_query(query) if query else None
        if qvec is not None:
            rows = self.conn.execute(
                f"SELECT id, embedding FROM memories WHERE embedding IS NOT NULL AND {where}", vals
            ).fetchall()
            if rows:
                ids = np.array([r["id"] for r in rows])
                mat = np.frombuffer(b"".join(r["embedding"] for r in rows), dtype=np.float32).reshape(len(rows), -1)
                sims = mat @ qvec
                order = np.argsort(-sims)[:pool]
                for r, idx in enumerate(order):
                    if sims[idx] < 0.25:      # drop clearly unrelated items
                        break
                    ranks[int(ids[idx])] = ranks.get(int(ids[idx]), 0) + 1.2 / (K + r)

        # 3) no query -> most recent / important
        if not query:
            rows = self.conn.execute(
                f"SELECT * FROM memories WHERE {where} ORDER BY importance DESC, created_at DESC LIMIT ?",
                [*vals, limit],
            ).fetchall()
            return [self._row_to_memory(r) for r in rows]

        if not ranks:
            return []

        ids = list(ranks)
        rows = self.conn.execute(
            f"SELECT * FROM memories WHERE id IN ({','.join('?' * len(ids))})", ids
        ).fetchall()
        now = time.time()
        scored = []
        for row in rows:
            base = ranks[row["id"]]
            age_days = (now - row["created_at"]) / 86400
            boost = 1.0 + 0.08 * (row["importance"] - 3) + 0.10 / (1.0 + age_days / 30)
            scored.append((base * boost, row))
        scored.sort(key=lambda x: -x[0])
        out = []
        for s, row in scored[:limit]:
            out.append(self._row_to_memory(row, score=round(float(s), 5)))
        if out:
            self.conn.execute(
                f"UPDATE memories SET access_count=access_count+1 WHERE id IN ({','.join('?' * len(out))})",
                [m.id for m in out],
            )
            self.conn.commit()
        return out

    def recent(self, limit: int = 20, namespace: str = "global", agent=None, kind=None, tags=None, since=None) -> list[Memory]:
        where, vals = self._filters(namespace, agent, kind, tags, None, since)
        rows = self.conn.execute(
            f"SELECT * FROM memories WHERE {where} ORDER BY created_at DESC LIMIT ?", [*vals, int(limit)]
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def activity(self, limit: int = 30) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM activity ORDER BY ts DESC LIMIT ?", (int(limit),)).fetchall()
        return [
            {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"])),
                "agent": r["agent"], "action": r["action"], "memory_id": r["memory_id"], "detail": r["detail"],
            }
            for r in rows
        ]

    def stats(self) -> dict:
        c = self.conn
        total = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        by_ns = dict(c.execute("SELECT namespace, COUNT(*) FROM memories GROUP BY namespace").fetchall())
        by_agent = dict(c.execute("SELECT agent, COUNT(*) FROM memories GROUP BY agent ORDER BY 2 DESC").fetchall())
        by_kind = dict(c.execute("SELECT kind, COUNT(*) FROM memories GROUP BY kind").fetchall())
        embedded = c.execute("SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL").fetchone()[0]
        size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "total_memories": total,
            "embedded": embedded,
            "semantic_search": self.embedder.available,
            "embed_model": self.embedder.model_name if self.embedder.available else None,
            "by_namespace": by_ns,
            "by_agent": by_agent,
            "by_kind": by_kind,
            "db_path": str(self.db_path),
            "db_size_mb": round(size / 1e6, 2),
        }

    # ------------------------------------------------------------------ tasks
    @staticmethod
    def _task_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        for k in ("created_at", "updated_at", "started_at", "finished_at"):
            d[k.replace("_at", "")] = time.strftime("%Y-%m-%d %H:%M", time.localtime(d[k])) if d.get(k) else None
        return d

    def task_create(self, title: str, detail: str = "", owner: str = "chief-of-staff", created_by: str = "pribin",
                    priority: int = 3, namespace: str = "global", source: str = "agent") -> dict:
        now = time.time()
        with self._lock:
            cur = self.conn.execute(
                """INSERT INTO tasks(title, detail, status, owner, created_by, priority, namespace, created_at, updated_at, source)
                   VALUES (?,?, 'queued', ?,?,?,?,?,?,?)""",
                (title.strip(), detail or "", owner, created_by, max(1, min(5, int(priority))), namespace, now, now, source))
            self._log(created_by, "task_create", cur.lastrowid, title[:120])
            self.conn.commit()
            return self.task_get(cur.lastrowid)

    def task_get(self, task_id: int) -> dict:
        r = self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not r:
            raise KeyError(f"task {task_id} not found")
        return self._task_row(r)

    def task_update(self, task_id: int, agent: str = "unknown", **fields) -> dict:
        allowed = {"title", "detail", "status", "owner", "priority", "result", "run_id"}
        sets, vals = [], []
        for k, v in fields.items():
            if k in allowed and v is not None:
                sets.append(f"{k}=?"); vals.append(v)
        now = time.time()
        if fields.get("status") == "running":
            sets.append("started_at=?"); vals.append(now)
        if fields.get("status") in ("done", "failed", "cancelled"):
            sets.append("finished_at=?"); vals.append(now)
        sets.append("updated_at=?"); vals.append(now); vals.append(task_id)
        with self._lock:
            self.conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", vals)
            self._log(agent, "task_update", task_id, fields.get("status"))
            self.conn.commit()
        return self.task_get(task_id)

    def task_list(self, status: Optional[str] = None, limit: int = 50, namespace: Optional[str] = None) -> list[dict]:
        clauses, vals = [], []
        if status:
            clauses.append("status=?"); vals.append(status)
        if namespace and namespace != "*":
            clauses.append("namespace=?"); vals.append(namespace)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.conn.execute(
            f"""SELECT * FROM tasks {where}
                ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 WHEN 'blocked' THEN 2 ELSE 3 END,
                         priority DESC, created_at DESC LIMIT ?""", [*vals, int(limit)]).fetchall()
        return [self._task_row(r) for r in rows]

    def task_claim_next(self, exclude: Iterable[int] = ()) -> Optional[dict]:
        """Atomically take the highest-priority queued task (for the scheduler), skipping `exclude` ids."""
        ex = [int(x) for x in exclude]
        with self._lock:
            r = self.conn.execute(
                f"SELECT id FROM tasks WHERE status='queued'{(' AND id NOT IN (' + ','.join('?' * len(ex)) + ')') if ex else ''} "
                "ORDER BY priority DESC, created_at ASC LIMIT 1", ex).fetchone()
            if not r:
                return None
            self.conn.execute("UPDATE tasks SET status='running', started_at=?, updated_at=? WHERE id=?",
                              (time.time(), time.time(), r["id"]))
            self.conn.commit()
            return self.task_get(r["id"])

    def reindex(self) -> int:
        """Embed any memories missing a vector (e.g. after installing fastembed)."""
        if not self.embedder.available:
            return 0
        rows = self.conn.execute("SELECT id, content FROM memories WHERE embedding IS NULL").fetchall()
        if not rows:
            return 0
        n = 0
        for i in range(0, len(rows), 64):
            chunk = rows[i:i + 64]
            vecs = self.embedder.embed([r["content"] for r in chunk])
            for r, v in zip(chunk, vecs):
                self.conn.execute("UPDATE memories SET embedding=? WHERE id=?", (v.tobytes(), r["id"]))
                n += 1
        self.conn.commit()
        return n
