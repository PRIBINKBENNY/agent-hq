"""
Hourly trading watch, every day of the week: scan every approved strategy across every market, and wake the
desk only when there is something to do. Deterministic (no language model, no token cost).

- A fresh signal on a market that is open (Capital.com status TRADEABLE) becomes ONE task for the
  strategy-analyst, who hands it to the risk-officer and the trader as before. Each bar is proposed once.
- Open positions get a "manage" task for the trader (one at a time).
- Closed markets (weekend shares, indices, FX, gold) are skipped; crypto keeps trading at weekends.
Everything the desk enforces (1% risk, RR >= 1.5, 2 trades a day, daily loss limit, DEMO only) still applies
inside capital_open; this script never places an order itself.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office")); sys.path.insert(0, str(ROOT / "brain"))
import runtime  # noqa: E402,F401  (loads .env)
import tools  # noqa: E402

STATE = tools.WORKSPACE / "trading" / "watch_state.json"
LAST = tools.WORKSPACE / "trading" / "watch-last.json"


def _load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def market_open(epic: str) -> bool:
    try:
        return json.loads(tools.registry.call("capital_market", {"epic": epic}, agent="trading-watch")).get("status") == "TRADEABLE"
    except Exception:
        return False


def watch() -> dict:
    st = _load(); seen = st.setdefault("proposed", {}); out = {"ts": time.strftime("%Y-%m-%d %H:%M"), "proposed": [], "skipped_closed": [], "positions": 0}
    scan = json.loads(tools.signal_scan())
    out["scanned"] = len(scan.get("scanned", [])); out["limits"] = scan.get("limits", {})
    fresh = []
    for p in scan.get("proposals", []):
        key = p["strategy"]
        if seen.get(key) == p.get("bar"):
            continue                                       # this bar was already proposed
        time.sleep(0.4)
        if not market_open(p["epic"]):
            out["skipped_closed"].append(p["epic"]); continue
        seen[key] = p.get("bar"); fresh.append(p)
    queued = tools.brain.task_list(status="queued", limit=100) + tools.brain.task_list(status="running", limit=50)
    if fresh and (scan.get("limits") or {}).get("can_trade", True):
        lines = "\n".join(f"- {p['strategy']}: {p['signal']} {p['epic']} entry {p['entry']} stop {p['stop']} target {p['target']} "
                          f"RR {p['rr']} size for 1% risk {p.get('size_for_1pct_risk')} ({p['reason']})" for p in fresh)
        valid_until = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + 2 * 3600))
        tools.brain.task_create(f"Risk review: {', '.join(p['epic'] + ' ' + p['signal'] for p in fresh)} (signal fired)",
                                "The hourly watch found fresh signals from APPROVED strategies on OPEN markets, within the desk limits:\n" + lines +
                                f"\n\nVALID UNTIL {valid_until} London time: after that the signal is stale and must NOT be traded.\n"
                                "Risk officer, follow your process for each signal: check the rules, then brain_remember the verdict as "
                                "kind='decision', tags ['risk', '<epic>'], content starting 'APPROVE: <BUY/SELL> <size> <epic> stop <x> target <y>' "
                                "or 'VETO: <rule>'. If APPROVE, task_create 'Execute: <epic> <BUY/SELL>' owner trader with the decision text, its "
                                "memory id and the VALID UNTIL time. Do it now: the signal expires. DEMO account.",
                                owner="risk-officer", created_by="scheduler", priority=5, source="trading-watch")
        out["proposed"] = [f"{p['epic']} {p['signal']}" for p in fresh]
    try:
        pos = json.loads(tools.registry.call("capital_positions", {}, agent="trading-watch")); out["positions"] = len(pos) if isinstance(pos, list) else 0
    except Exception:
        out["positions"] = 0
    if out["positions"] and not any(t.get("owner") == "trader" and "Manage open" in (t.get("title") or "") for t in queued):
        tools.brain.task_create("Manage open DEMO positions", "Hourly watch: positions are open. Check each against its stop, target and time-stop; "
                                "move stops only in the trade's favour; close what the plan says to close. DEMO account.",
                                owner="trader", created_by="scheduler", priority=4, source="trading-watch")
    st["last"] = out["ts"]; STATE.parent.mkdir(parents=True, exist_ok=True); STATE.write_text(json.dumps(st, indent=1)); LAST.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    print(json.dumps(watch(), indent=1))
