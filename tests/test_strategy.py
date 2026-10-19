import json
import math
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office")); sys.path.insert(0, str(ROOT / "brain"))
import strategy as S  # noqa: E402


def synth(n=600, seed=1, trend=0.0008, noise=0.004):
    """Synthetic bars with a gentle drift so trend strategies have something to catch."""
    random.seed(seed); px = 100.0; bars = []
    for i in range(n):
        o = px; c = o * (1 + trend + random.gauss(0, noise)); h = max(o, c) * (1 + abs(random.gauss(0, noise / 2))); l = min(o, c) * (1 - abs(random.gauss(0, noise / 2)))
        bars.append({"t": f"2026-01-{1 + i // 24:02d}T{i % 24:02d}:00:00", "open": o, "high": h, "low": l, "close": c}); px = c
    return bars


def test_indicators_basic():
    vals = [1, 2, 3, 4, 5, 6]
    assert S.sma(vals, 3)[-1] == 5 and S.sma(vals, 3)[1] is None
    assert S.ema(vals, 3)[-1] is not None
    r = S.rsi([float(x) for x in range(1, 40)], 14); assert r[-1] == 100.0          # only gains
    bars = synth(100); assert len(S.atr(bars, 14)) == 100 and S.atr(bars, 14)[-1] > 0
    line, sig = S.macd([b["close"] for b in bars]); assert line[-1] is not None and sig[-1] is not None


def test_backtest_report_fields_and_stop_wins_ties():
    bars = synth(600)
    rep = S.backtest(bars, "sma_cross", {"fast": 5, "slow": 20}, stop_pct=1.0, target_pct=2.0, time_stop_bars=12)
    for k in ("trades", "win_pct", "profit_factor", "max_drawdown_pct", "expectancy_r", "trades_per_week", "exits"):
        assert k in rep
    assert rep["trades"] > 5 and rep["rr"] == 2.0
    # a bar that spans both stop and target counts as a stop
    b2 = [{"t": "2026-01-01T00:00:00", "open": 100, "high": 100, "low": 100, "close": 100}] * 30
    sig_bars = [dict(b) for b in b2]
    sig_bars[20]["close"] = 101; sig_bars[21] = {"t": "x", "open": 101, "high": 101, "low": 101, "close": 101}; sig_bars[22] = {"t": "y", "open": 101, "high": 110, "low": 90, "close": 101}
    trades = S._collect(sig_bars, "breakout", {"lookback": 10}, 1.0, 2.0, 0, 0.0)
    assert trades and trades[0]["why"] == "x" and trades[0]["r"] < 0


def test_principles_check_and_walk_forward_shape():
    good = {"trades": 60, "win_pct": 55.0, "profit_factor": 1.5, "rr": 2.0, "max_drawdown_pct": 8.0, "trades_per_week": 5.0}
    assert S.principles_check(good)["passed"]
    bad = {**good, "profit_factor": 1.1, "trades": 20}
    chk = S.principles_check(bad); assert not chk["passed"] and len(chk["failed"]) == 2
    wf = S.walk_forward(synth(800), "sma_cross", segments=4, stop_pct=1.0, target_pct=2.0, time_stop_bars=12)
    assert "folds" in wf and "stable" in wf and "principles" in wf and len(wf["folds"]) == 3
    assert S.walk_forward(synth(120), "macd")["error"].startswith("need at least")


def test_strategy_save_refuses_unproven_and_signal_scan_uses_only_approved(tmp_path, monkeypatch):
    import tools, store
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    monkeypatch.setattr(tools, "brain", store.BrainStore(tmp_path / "b.db", embedder=NoEmbed()))
    monkeypatch.setattr(tools, "STRATEGIES_DIR", tmp_path / "strategies"); monkeypatch.setattr(tools, "JOURNAL_FILE", tmp_path / "j.jsonl"); monkeypatch.setattr(tools, "DESK_STATE", tmp_path / "d.json")
    monkeypatch.setattr(tools, "LAB_CACHE", tmp_path / "lab.json")
    weak = {"trades": 25, "win_pct": 40.0, "profit_factor": 1.1, "rr": 2.0, "max_drawdown_pct": 9.0, "trades_per_week": 3.0, "stable": False,
            "recommended_params": {"fast": 10, "slow": 20}, "stop_pct": 1.0, "target_pct": 2.0, "time_stop_bars": 12}
    assert tools.strategy_save("gold-h1", "GOLD", "sma_cross", "approved").startswith("refused: no walk_forward")      # nothing cached yet
    tools._lab_cache("GOLD|sma_cross|HOUR", weak)
    assert tools.strategy_save("gold-h1", "GOLD", "sma_cross", "approved").startswith("refused: cannot approve")
    assert tools.strategy_save("gold-h1", "GOLD", "sma_cross", "candidate", target_pct=1.2).startswith("refused: reward")   # RR too low
    r = tools.strategy_save("gold-h1", "GOLD", "sma_cross", "candidate"); assert r.startswith("strategy gold-h1 saved as candidate") and "time-stop 12" in r
    strong = {**weak, "trades": 60, "win_pct": 55.0, "profit_factor": 1.6, "trades_per_week": 5.0, "stable": True, "recommended_params": {"lookback": 20}}
    tools._lab_cache("GC=F|breakout|HOUR", strong)
    r = tools.strategy_save("gold-h1-b", "GC=F", "breakout", "approved", epic="GOLD"); assert "approved" in r and "trades GOLD" in r
    assert tools.strategy_save("gold-h1-b", "GC=F", "breakout", "retired", notes="PF < 1 after 40 trades") == "strategy gold-h1-b retired"
    r = tools.strategy_save("gold-h1-b", "GC=F", "breakout", "approved", epic="GOLD")   # re-approve for the scan test below
    monkeypatch.setattr(tools, "_bars", lambda sym, res="HOUR", n=300: synth(300, seed=3))
    monkeypatch.setattr(tools, "_cap", lambda: type("C", (), {"preferred_account": staticmethod(lambda: {"balance": {"available": 10000}})})())
    r = json.loads(tools.signal_scan())
    assert [s["strategy"] for s in r["scanned"]] == ["gold-h1-b"]         # the candidate is not scanned
    assert all(x.get("epic", "GOLD") == "GOLD" for x in r["proposals"])
    assert r["limits"]["can_trade"] is True and r["available"] == 10000


def test_desk_limits_block_after_five_trades_and_weekly_goal(tmp_path, monkeypatch):
    import tools, time
    monkeypatch.setattr(tools, "JOURNAL_FILE", tmp_path / "j.jsonl"); monkeypatch.setattr(tools, "DESK_STATE", tmp_path / "d.json")
    (tmp_path / "d.json").write_text(json.dumps({"week_start_balance": 1000}))
    assert tools.desk_limits()["can_trade"]
    for _ in range(4): tools._journal_write({"event": "open", "epic": "GOLD"})
    assert tools.desk_limits()["can_trade"]                                           # 4 of 5 used: still allowed
    tools._journal_write({"event": "open", "epic": "GOLD"})
    lim = tools.desk_limits(); assert not lim["can_trade"] and "5 trades today" in lim["blocks"][0]
    (tmp_path / "j.jsonl").write_text(""); tools._journal_write({"event": "close", "epic": "GOLD", "pnl": 35.0})
    lim = tools.desk_limits(); assert lim["week_pct"] == 3.5 and not lim["can_trade"] and "weekly goal" in lim["blocks"][0]
    st = json.loads(tools.trade_journal("stats")); assert st["overall"]["trades"] == 1 and st["overall"]["win_pct"] == 100.0


def test_profitable_trades_reward_the_office(tmp_path, monkeypatch):
    import tools, store, events
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    monkeypatch.setattr(tools, "brain", store.BrainStore(tmp_path / "b.db", embedder=NoEmbed()))
    monkeypatch.setattr(tools, "TREASURY_FILE", tmp_path / "treasury.json"); monkeypatch.setattr(events, "EVENTS_FILE", tmp_path / "ev.jsonl")
    s = tools.record_trade_outcome(12.5, 1.6, "gold-h1-sma", "GOLD")
    assert s["credits"] == 12.5 and s["xp"] == 180 and s["wins"] == 1 and s["streak"] == 1 and s["level"] == 2
    s = tools.record_trade_outcome(-8.0, -1.0, "gold-h1-sma", "GOLD")
    assert s["credits"] == 4.5 and s["xp"] == 180 and s["losses"] == 1 and s["streak"] == 0      # a loss costs credits, never xp
    evs = [json.loads(l) for l in (tmp_path / "ev.jsonl").read_text().splitlines()]
    assert [e["type"] for e in evs] == ["reward"] and evs[0]["pnl"] == 12.5 and evs[0]["level_up"] is True
    assert json.loads(tools.treasury_status())["wins"] == 1



def test_frequency_is_a_desk_rule_not_a_per_strategy_rule():
    import strategy as S
    rep = {"trades": 92, "win_pct": 50.0, "profit_factor": 1.83, "rr": 2.0, "max_drawdown_pct": 3.9, "trades_per_week": 1.1}
    assert S.principles_check(rep)["passed"]                                      # e.g. META sma: strong, trades about once a week
    assert not S.principles_check({**rep, "trades_per_week": 0.3})["passed"]     # a strategy that almost never trades is still refused
    assert not S.principles_check({**rep, "profit_factor": 1.2})["passed"] and S.DESK_MIN_TRADES_PER_WEEK == 4.0
