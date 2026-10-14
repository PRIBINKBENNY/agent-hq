"""
Brain MCP server: one shared memory every agent reads and writes.

Run:   python brain/server.py            (stdio, for Claude Code / Claude Desktop / any MCP client)
Env:   BRAIN_DB=/path/to/brain.db        (optional, default brain/data/brain.db)
       BRAIN_EMBED_MODEL=BAAI/bge-small-en-v1.5   (optional)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP  # noqa: E402
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP  # noqa: E402
from store import BrainStore  # noqa: E402

mcp = FastMCP(
    "brain",
    instructions=(
        "This is the team's shared brain. Before starting a task, call recall with a short description of "
        "what you are about to do so you know what other agents already learned or decided. After you finish "
        "or learn something another agent might need, call remember. Keep memories short, factual, and "
        "self-contained (one idea per memory). Always pass your agent name."
    ),
)
store = BrainStore()


def _fmt(m) -> dict:
    d = m.to_dict()
    for k in ("created_at", "updated_at", "expires_at", "meta", "access_count"):
        d.pop(k, None)
    if d.get("score") is None:
        d.pop("score", None)
    return d


@mcp.tool()
def remember(
    content: str,
    agent: str,
    kind: str = "note",
    tags: Optional[list[str]] = None,
    importance: int = 3,
    namespace: str = "global",
    ttl_hours: Optional[float] = None,
    source: Optional[str] = None,
) -> dict:
    """Store something in the shared brain so every agent can find it later.

    Args:
        content: The memory itself. One clear idea, written so it makes sense on its own.
                 Good: "Client prefers blue (#1E5EFF) for all brand assets, decided 2026-10-14."
        agent: Your agent name (e.g. "researcher", "copywriter", "lead-creative").
        kind: fact | decision | task | event | note | profile | lesson
        tags: Short lowercase labels, e.g. ["client-acme", "branding"].
        importance: 1 (trivial) to 5 (critical, everyone must know).
        namespace: Scope. "global" is shared by all; use a project/team name to keep things separate.
        ttl_hours: Optional. Memory auto-deletes after this many hours (for temporary state).
        source: Optional. Where this came from (URL, file path, "user said", ...).
    """
    m = store.remember(
        content=content, agent=agent, kind=kind, tags=tags, importance=importance,
        namespace=namespace, ttl_seconds=(ttl_hours * 3600) if ttl_hours else None, source=source,
    )
    return {"stored": True, "memory": _fmt(m)}


@mcp.tool()
def recall(
    query: str,
    agent: str = "unknown",
    limit: int = 8,
    namespace: str = "global",
    kind: Optional[str] = None,
    tags: Optional[list[str]] = None,
    from_agent: Optional[str] = None,
    min_importance: Optional[int] = None,
    since_hours: Optional[float] = None,
) -> dict:
    """Search the shared brain. Works on meaning, not just exact words.

    Combines keyword search (names, IDs, exact phrases) with semantic search (ideas,
    paraphrases), then boosts important and recent memories.

    Args:
        query: What you want to know, in plain language. Empty string = latest important memories.
        agent: Your agent name (for the activity log).
        limit: Max results (1-100).
        namespace: "global" or a project/team name. "*" searches everything.
        kind: Filter: fact | decision | task | event | note | profile | lesson
        tags: Only memories carrying all of these tags.
        from_agent: Only memories written by this agent.
        min_importance: Only memories with importance >= this.
        since_hours: Only memories created in the last N hours.
    """
    since = (time.time() - since_hours * 3600) if since_hours else None
    results = store.recall(
        query=query, limit=limit, namespace=namespace, agent=from_agent, kind=kind,
        tags=tags, min_importance=min_importance, since=since,
    )
    store._log(agent, "recall", None, query[:200])
    store.conn.commit()
    return {"count": len(results), "memories": [_fmt(m) for m in results]}


@mcp.tool()
def update_memory(
    memory_id: int,
    agent: str,
    content: Optional[str] = None,
    tags: Optional[list[str]] = None,
    add_tags: Optional[list[str]] = None,
    importance: Optional[int] = None,
    kind: Optional[str] = None,
) -> dict:
    """Correct or enrich an existing memory instead of storing a conflicting duplicate.

    Args:
        memory_id: The id returned by remember/recall.
        agent: Your agent name.
        content: New text (replaces the old text).
        tags: Replace all tags.
        add_tags: Add tags, keep existing ones.
        importance: New importance 1-5.
        kind: New kind.
    """
    m = store.update(memory_id, agent=agent, content=content, tags=tags, add_tags=add_tags,
                     importance=importance, kind=kind)
    return {"updated": True, "memory": _fmt(m)}


@mcp.tool()
def forget(memory_id: int, agent: str) -> dict:
    """Delete a memory that is wrong or no longer relevant."""
    return {"deleted": store.forget(memory_id, agent=agent), "memory_id": memory_id}


@mcp.tool()
def recent(
    limit: int = 20,
    namespace: str = "global",
    kind: Optional[str] = None,
    from_agent: Optional[str] = None,
    tags: Optional[list[str]] = None,
    since_hours: Optional[float] = None,
) -> dict:
    """What has the team learned lately? Newest memories first, no query needed.
    Good for a quick catch-up when you start a shift."""
    since = (time.time() - since_hours * 3600) if since_hours else None
    results = store.recent(limit=limit, namespace=namespace, agent=from_agent, kind=kind, tags=tags, since=since)
    return {"count": len(results), "memories": [_fmt(m) for m in results]}


@mcp.tool()
def activity(limit: int = 30) -> dict:
    """Who did what in the brain recently (remember / recall / update / forget), newest first."""
    return {"events": store.activity(limit)}


@mcp.tool()
def brain_stats() -> dict:
    """Size of the brain, memories per agent / kind / namespace, and whether semantic search is on."""
    return store.stats()


@mcp.tool()
def reindex() -> dict:
    """Embed any memories that are missing a vector (run once after enabling semantic search)."""
    return {"embedded": store.reindex()}


if __name__ == "__main__":
    mcp.run()
