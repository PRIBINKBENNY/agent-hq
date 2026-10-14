#!/usr/bin/env python3
"""
Talk to the brain from the terminal (same database the MCP server uses).

  python brain/cli.py remember "Client wants blue" --agent me --tags client,branding --importance 4
  python brain/cli.py recall "what colour does the client like"
  python brain/cli.py recent
  python brain/cli.py stats
  python brain/cli.py activity
  python brain/cli.py forget 12
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from store import BrainStore  # noqa: E402


def show(memories):
    if not memories:
        print("(nothing)")
        return
    for m in memories:
        score = f"  score={m.score}" if m.score is not None else ""
        tags = f"  [{', '.join(m.tags)}]" if m.tags else ""
        print(f"#{m.id}  ★{m.importance}  {m.kind:<8} {m.agent:<14} {m.to_dict()['created']}{score}")
        print(f"     {m.content}{tags}")


def main():
    p = argparse.ArgumentParser(prog="brain")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("remember"); a.add_argument("content")
    a.add_argument("--agent", default="cli"); a.add_argument("--kind", default="note")
    a.add_argument("--tags", default=""); a.add_argument("--importance", type=int, default=3)
    a.add_argument("--namespace", default="global"); a.add_argument("--source")

    r = sub.add_parser("recall"); r.add_argument("query", nargs="?", default="")
    r.add_argument("--limit", type=int, default=8); r.add_argument("--namespace", default="global")
    r.add_argument("--kind"); r.add_argument("--tags", default=""); r.add_argument("--agent")

    rc = sub.add_parser("recent"); rc.add_argument("--limit", type=int, default=20)
    rc.add_argument("--namespace", default="global")

    f = sub.add_parser("forget"); f.add_argument("id", type=int)
    sub.add_parser("stats"); sub.add_parser("activity"); sub.add_parser("reindex")

    args = p.parse_args()
    store = BrainStore()

    if args.cmd == "remember":
        m = store.remember(args.content, agent=args.agent, kind=args.kind, tags=args.tags,
                           importance=args.importance, namespace=args.namespace, source=args.source)
        print(f"stored #{m.id}")
    elif args.cmd == "recall":
        show(store.recall(args.query, limit=args.limit, namespace=args.namespace, kind=args.kind,
                          tags=args.tags, agent=args.agent))
    elif args.cmd == "recent":
        show(store.recent(limit=args.limit, namespace=args.namespace))
    elif args.cmd == "forget":
        print("deleted" if store.forget(args.id, agent="cli") else "not found")
    elif args.cmd == "stats":
        print(json.dumps(store.stats(), indent=2))
    elif args.cmd == "activity":
        for e in store.activity(30):
            print(f"{e['ts']}  {e['agent']:<14} {e['action']:<13} {e['memory_id'] or '':<5} {e['detail'] or ''}")
    elif args.cmd == "reindex":
        print(f"embedded {store.reindex()} memories")


if __name__ == "__main__":
    main()
