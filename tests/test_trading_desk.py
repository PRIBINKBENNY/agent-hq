import json
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office")); sys.path.insert(0, str(ROOT / "brain"))


def test_universe_is_complete_and_consistent():
    from markets import UNIVERSE, EXITS, strategy_name, asset_class
    epics = [e for _, e, _ in UNIVERSE]
    assert len(epics) == len(set(epics)) == 37
    classes = {c for *_, c in UNIVERSE}
    assert classes == {"fx", "index", "commodity", "crypto", "stock"} and all(t / s >= 1.5 for s, t, _ in EXITS.values())
    assert strategy_name("GOLD", "sma_cross") == "gold-h1-sma" and asset_class("btcusd") == "crypto"


def test_history_routes_yahoo_tickers(monkeypatch):
    import tools, pandas as pd
    asked = []
    class T:
        def __init__(self, sym): asked.append(sym)
        def history(self, **k): return pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0]}, index=pd.to_datetime(["2026-10-16 10:00"]))
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=T))
    for sym in ("yf:NVDA", "BTC-USD", "EURUSD=X", "^FTSE"):
        assert tools._bars(sym, "HOUR", 10)[0]["close"] == 1.0
    assert asked == ["NVDA", "BTC-USD", "EURUSD=X", "^FTSE"]


@pytest.fixture
def watch_env(tmp_path, monkeypatch):
    import tools, store, trading_watch as W
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    b = store.BrainStore(tmp_path / "b.db", embedder=NoEmbed()); monkeypatch.setattr(tools, "brain", b)
    monkeypatch.setattr(W, "STATE", tmp_path / "state.json"); monkeypatch.setattr(W, "LAST", tmp_path / "last.json")
    open_markets = {"BTCUSD"}
    monkeypatch.setattr(W, "market_open", lambda epic: epic in open_markets)
    positions = []
    def call(name, args, agent="x"):
        assert name == "capital_positions"; return json.dumps(positions)
    monkeypatch.setattr(tools.registry, "call", call)
    prop = lambda s, e, bar: {"strategy": s, "epic": e, "signal": "BUY", "entry": 1, "stop": 0.98, "target": 1.04, "rr": 2, "size_for_1pct_risk": 1, "reason": "x", "bar": bar}
    scan = {"proposals": [prop("btcusd-h1-rsifade", "BTCUSD", "b1"), prop("gold-h1-sma", "GOLD", "g1")], "scanned": [1, 2], "limits": {"can_trade": True}}
    monkeypatch.setattr(tools, "signal_scan", lambda: json.dumps(scan))
    return W, b, scan, positions, prop


def test_watch_wakes_the_desk_once_per_bar_and_skips_closed_markets(watch_env):
    W, b, scan, positions, prop = watch_env
    out = W.watch()
    assert out["proposed"] == ["BTCUSD BUY"] and out["skipped_closed"] == ["GOLD"]
    tasks = b.task_list(status="queued"); assert len(tasks) == 1 and tasks[0]["owner"] == "strategy-analyst" and "BTCUSD" in tasks[0]["title"]
    assert W.watch()["proposed"] == []                                   # same bar: not proposed again
    scan["proposals"][0] = prop("btcusd-h1-rsifade", "BTCUSD", "b2")
    assert W.watch()["proposed"] == ["BTCUSD BUY"]                        # next bar fires again
    positions.append({"dealId": "1"}); W.watch(); W.watch()
    assert sum(1 for t in b.task_list(status="queued") if t["owner"] == "trader") == 1   # one manage task at a time
    scan["limits"] = {"can_trade": False}; scan["proposals"][0] = prop("btcusd-h1-rsifade", "BTCUSD", "b3")
    n = len(b.task_list(status="queued")); W.watch(); assert len(b.task_list(status="queued")) == n   # desk limits hit: nobody is woken


def test_scheduled_scripts_run_outside_the_parallel_limit(tmp_path, monkeypatch):
    import scheduler, runtime, store
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    b = store.BrainStore(tmp_path / "b.db", embedder=NoEmbed()); scheduler._reconciled = True; scheduler._running.clear(); scheduler._last_sweep = time.time()
    monkeypatch.setenv("OFFICE_MAX_PARALLEL", "1"); monkeypatch.setattr(scheduler, "MAX_PARALLEL", 1)
    for name in ("STANDING_FILE", "SCHEDULE_FILE"): monkeypatch.setattr(scheduler, name, tmp_path / f"{name}.yaml")
    monkeypatch.setattr(scheduler, "STATE_FILE", tmp_path / "st.json"); monkeypatch.setattr(scheduler, "budget", lambda: {})
    monkeypatch.setattr(scheduler, "_notify", lambda *a: None); monkeypatch.setattr(scheduler, "housekeeping", lambda: {})
    monkeypatch.setattr(scheduler, "check_approvals", lambda brain: 0); monkeypatch.setattr(runtime, "cloud_available", lambda: (False, time.time() + 600))
    monkeypatch.delenv("OFFICE_LEAD_LOCAL_FALLBACK", raising=False)
    class P:
        returncode = None
        def poll(self): return None
    monkeypatch.setattr(scheduler, "_spawn", lambda task, eng: P())
    b.task_create("watch", "python office/trading_watch.py", owner="command", created_by="scheduler")
    b.task_create("agent work", "x", owner="coo")
    info = scheduler.tick(b)
    assert len(info["started"]) == 1 and b.task_list(status="queued")[0]["owner"] == "coo"   # script ran although no cloud model is free
    scheduler._running.clear()


def test_cloud_only_agents_never_fall_back_to_the_local_model(monkeypatch):
    import runtime as rt
    from runtime import Agent, Brief, ToolRegistry
    monkeypatch.setenv("OFFICE_LEAD_LOCAL_FALLBACK", "1"); monkeypatch.setenv("OFFICE_LEAD_WAIT_MAX", "1")
    rt._COOLDOWN.clear(); rt._COOLDOWN[("groq", "big")] = time.time() + 900
    chain = [("groq", "big"), ("ollama", "local")]
    assert Agent(Brief("coo", "o", "lead", [], [], "s"), ToolRegistry(), engine="auto", verbose=False)._pick(chain) == ("ollama", "local")
    with pytest.raises(rt.EngineError):
        Agent(Brief("trader", "o", "lead", [], [], "s", cloud_only=True), ToolRegistry(), engine="auto", verbose=False)._pick(chain)
    for a in ("trader", "trading-learner", "market-researcher", "strategy-analyst", "risk-officer"):
        br = rt.load_brief(a); assert br.cloud_only and br.tier == "lead" and br.model.startswith("gpt-oss:120b")
    rt._COOLDOWN.clear()


def test_script_jobs_survive_a_project_path_with_spaces(tmp_path, monkeypatch):
    import scheduler, store, subprocess
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    db = tmp_path / "b.db"; b = store.BrainStore(db, embedder=NoEmbed())
    t = b.task_create("echo", "echo hello", owner="command", created_by="scheduler")
    seen = {}
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **k: seen.setdefault("cmd", cmd) or None)
    scheduler._spawn(t)
    script = seen["cmd"][2]; import shlex as sh
    assert sh.quote(sys.executable) in script and script.count(sh.quote(sys.executable)) == 2
