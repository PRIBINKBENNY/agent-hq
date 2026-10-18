"""
Strategy lab sweep: walk-forward test every strategy family on every market in office/markets.py.

Deterministic (no language model, no token cost). Runs nightly from the schedule and on demand:
    .venv/bin/python office/trading_lab.py              # the whole universe
    .venv/bin/python office/trading_lab.py --only crypto  (or fx, index, commodity, stock, or an epic like GOLD)

Approval uses exactly the same gate as the desk's strategy_save tool: the playbook's principles check must pass
AND the walk-forward must be stable (60%+ of out-of-sample folds profitable). Near misses are kept as candidates
for the trading-learner to look at. An approved strategy is never downgraded here; if fresh data no longer
supports it, the report flags it and the learner's weekly review decides (with the real journal).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office")); sys.path.insert(0, str(ROOT / "brain"))
import runtime  # noqa: E402,F401  (loads .env)
import strategy as S  # noqa: E402
import tools  # noqa: E402
from markets import EXITS, UNIVERSE, strategy_name  # noqa: E402

REPORT = tools.WORKSPACE / "trading" / "lab-sweep.md"
POINTS = 3000          # about five months of round-the-clock hourly bars, longer for shares


def near_miss(rep: dict) -> bool:
    return (rep.get("trades") or 0) >= 20 and (rep.get("profit_factor") or 0) >= 1.15 and bool(rep.get("stable"))


def sweep(only: str = "", points: int = POINTS) -> dict:
    existing = {s["name"]: s for s in tools._strategies()}
    rows, approved, candidates, errors, weakened = [], [], [], [], []
    for yahoo, epic, cls in UNIVERSE:
        if only and only.lower() not in (cls, epic.lower()):
            continue
        stop, target, ts = EXITS[cls]
        for fam in S.STRATEGIES:
            name = strategy_name(epic, fam)
            try:
                rep = json.loads(tools.walk_forward(yahoo, fam, "HOUR", points, 4, stop, target, ts))
            except Exception as e:
                errors.append(f"{epic} {fam}: {str(e)[:80]}"); continue
            if "trades" not in rep:
                errors.append(f"{epic} {fam}: {str(rep)[:80]}"); continue
            chk = S.principles_check(rep); passed = chk["passed"] and bool(rep.get("stable"))
            was = (existing.get(name) or {}).get("status")
            verdict = "approved" if passed else ("candidate" if near_miss(rep) else "rejected")
            if passed and was != "approved":
                out = tools.strategy_save(name, yahoo, fam, "approved", epic=epic, notes=f"lab sweep {time.strftime('%Y-%m-%d')}", _agent="strategy-lab")
                (approved if not str(out).startswith("refused") else errors).append(f"{name}: {out}" if str(out).startswith("refused") else name)
            elif verdict == "candidate" and was not in ("approved", "retired"):
                tools.strategy_save(name, yahoo, fam, "candidate", epic=epic, notes=f"lab sweep near miss: {', '.join(chk['failed'])}", _agent="strategy-lab"); candidates.append(name)
            elif was == "approved" and not passed:
                weakened.append(f"{name} (now PF {rep.get('profit_factor')}, stable {rep.get('stable')}, failed {', '.join(chk['failed']) or 'stability'})")
            rows.append((epic, cls, fam, rep.get("trades"), rep.get("win_pct"), rep.get("profit_factor"), rep.get("max_drawdown_pct"), rep.get("stable"), verdict if was != "approved" else "approved (kept)"))
        time.sleep(0.5)        # be gentle with the free data source
    write_report(rows, approved, candidates, weakened, errors, only)
    summary = {"tested": len(rows), "approved_new": approved, "candidates_new": candidates, "weakened": weakened, "errors": errors[:10]}
    try:
        tools.brain.remember(f"Strategy lab sweep ({only or 'all markets'}): {len(rows)} tests, new approved {approved or 'none'}, "
                             f"candidates {len(candidates)}, weakened {weakened or 'none'}. Report: trading/lab-sweep.md",
                             agent="strategy-lab", kind="event", importance=3, tags=["strategy-lab", "sweep"], namespace="trading")
        if approved:
            tools.notify("New trading strategies approved", f"{len(approved)}: {', '.join(approved)[:150]} (DEMO, validated walk-forward)")
    except Exception:
        pass
    return summary


def write_report(rows, approved, candidates, weakened, errors, only):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Strategy lab sweep: {only or 'all markets'}", "", f"Run {time.strftime('%Y-%m-%d %H:%M')} · {len(rows)} walk-forward tests on hourly bars · "
             "approval = principles check passed AND stable out-of-sample. DEMO account. Not financial advice.", ""]
    lines += [f"**Newly approved:** {', '.join(approved) or 'none'}", f"**New candidates:** {', '.join(candidates) or 'none'}",
              f"**Approved but weaker on fresh data (learner to review):** {'; '.join(weakened) or 'none'}", ""]
    lines += ["| market | class | family | trades | win % | profit factor | max DD % | stable | verdict |", "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: -(r[5] or 0)):
        lines.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
    if errors:
        lines += ["", "Errors:", *[f"- {e}" for e in errors[:30]]]
    REPORT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--only", default=""); ap.add_argument("--points", type=int, default=POINTS)
    a = ap.parse_args(); print(json.dumps(sweep(a.only, a.points), indent=1))
