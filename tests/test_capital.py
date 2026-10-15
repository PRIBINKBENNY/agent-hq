import json
import os
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office"))
import capital  # noqa: E402


def fake_api(state):
    """An httpx MockTransport that behaves like Capital.com's demo API."""
    def handler(req: httpx.Request):
        p = req.url.path
        if p.endswith("/session"):
            if req.headers.get("X-CAP-API-KEY") != "key":
                return httpx.Response(401, json={"errorCode": "error.invalid.api.key"})
            return httpx.Response(200, json={"accountType": "CFD"}, headers={"CST": "cst1", "X-SECURITY-TOKEN": "sec1"})
        if req.headers.get("CST") != "cst1":
            return httpx.Response(401, json={"errorCode": "error.invalid.session.token"})
        if p.endswith("/ping"):
            return httpx.Response(200, json={"status": "OK"})
        if p.endswith("/accounts"):
            return httpx.Response(200, json={"accounts": [{"accountId": "1", "accountName": "Demo", "preferred": True, "currency": "GBP",
                                                            "balance": {"balance": 10000, "available": 10000, "profitLoss": 0}}]})
        if "/markets/" in p:
            return httpx.Response(200, json={"instrument": {"name": "Vodafone", "type": "SHARES", "currency": "GBP"},
                                             "snapshot": {"bid": 117.5, "offer": 117.8, "marketStatus": "TRADEABLE", "percentageChange": 0.4},
                                             "dealingRules": {"minDealSize": {"value": 1}, "minStopOrProfitDistance": {"value": 0.1}}})
        if p.endswith("/markets"):
            return httpx.Response(200, json={"markets": [{"epic": "VOD", "instrumentName": "Vodafone", "bid": 117.5, "offer": 117.8}]})
        if "/prices/" in p:
            return httpx.Response(200, json={"prices": [{"snapshotTimeUTC": f"2026-10-15T0{i}:00", "closePrice": {"bid": 100 + i, "ask": 100.2 + i},
                                                          "openPrice": {"bid": 100, "ask": 100.2}, "highPrice": {"bid": 101, "ask": 101}, "lowPrice": {"bid": 99, "ask": 99}} for i in range(5)]})
        if p.endswith("/positions") and req.method == "GET":
            return httpx.Response(200, json={"positions": state["positions"]})
        if p.endswith("/positions") and req.method == "POST":
            body = json.loads(req.content); state["last_open"] = body
            state["positions"].append({"position": {"dealId": "d1", "direction": body["direction"], "size": body["size"], "level": 117.8, "upl": 0, "stopLevel": body.get("stopLevel")},
                                       "market": {"epic": body["epic"], "instrumentName": "Vodafone", "bid": 117.5, "offer": 117.8}})
            return httpx.Response(200, json={"dealReference": "o_123"})
        if "/positions/" in p and req.method == "DELETE":
            state["positions"] = []
            return httpx.Response(200, json={"dealReference": "p_123"})
        if "/confirms/" in p:
            return httpx.Response(200, json={"dealStatus": "ACCEPTED", "dealId": "d1", "level": 117.8, "size": 5})
        return httpx.Response(404, json={"errorCode": "not found"})
    return httpx.MockTransport(handler)


@pytest.fixture
def cap(monkeypatch):
    monkeypatch.setenv("CAPITAL_API_KEY", "key"); monkeypatch.setenv("CAPITAL_IDENTIFIER", "me@x.com"); monkeypatch.setenv("CAPITAL_PASSWORD", "pw")
    monkeypatch.delenv("CAPITAL_LIVE", raising=False)
    state = {"positions": []}
    c = capital.Capital(transport=fake_api(state))
    return c, state


def test_demo_is_default_and_live_needs_explicit_flag(monkeypatch):
    monkeypatch.delenv("CAPITAL_LIVE", raising=False)
    assert capital.Capital(transport=httpx.MockTransport(lambda r: httpx.Response(200))).base == capital.DEMO_URL
    monkeypatch.setenv("CAPITAL_LIVE", "yes please")
    assert capital.Capital(transport=httpx.MockTransport(lambda r: httpx.Response(200))).base == capital.DEMO_URL   # wrong phrase -> still demo
    monkeypatch.setenv("CAPITAL_LIVE", "I_UNDERSTAND_REAL_MONEY")
    assert capital.Capital(transport=httpx.MockTransport(lambda r: httpx.Response(200))).base == capital.LIVE_URL


def test_login_reads_and_market_data(cap):
    c, _ = cap
    assert c.ping() == {"status": "OK"} and c.cst == "cst1"
    assert c.preferred_account()["balance"]["available"] == 10000
    assert c.search_markets("vod")[0]["epic"] == "VOD"
    m = c.market("VOD"); assert m["offer"] == 117.8 and m["min_size"] == 1
    pr = c.prices("VOD"); assert len(pr) == 5 and pr[-1]["close"] == pytest.approx(104.1)


def test_open_position_guards(cap):
    c, state = cap
    with pytest.raises(capital.CapitalError, match="stop level"):
        c.open_position("VOD", "BUY", 5, stop_level=0)
    with pytest.raises(capital.CapitalError, match="exposure"):
        c.open_position("VOD", "BUY", 100, stop_level=110)          # 100 * 117.8 = 11780 > 10% of 10000
    with pytest.raises(capital.CapitalError, match="wrong side"):
        c.open_position("VOD", "BUY", 5, stop_level=120)
    r = c.open_position("VOD", "BUY", 5, stop_level=112, profit_level=125)
    assert r["status"] == "ACCEPTED" and r["mode"] == "DEMO" and state["last_open"]["stopLevel"] == 112
    assert c.positions()[0]["dealId"] == "d1"
    state["positions"] = state["positions"] * 6
    with pytest.raises(capital.CapitalError, match="6 open"):
        c.open_position("VOD", "BUY", 1, stop_level=112)
    state["positions"] = state["positions"][:1]
    assert c.close_position("d1")["status"] == "ACCEPTED" and c.positions() == []


def test_capital_open_tool_requires_risk_approval(cap, monkeypatch, tmp_path):
    import tools, store
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    b = store.BrainStore(tmp_path / "b.db", embedder=NoEmbed())
    monkeypatch.setattr(tools, "brain", b)
    c, _ = cap; tools._CAP = c
    veto = b.remember("VETO: BUY VOD breaks the 10% rule", agent="risk-officer", kind="decision", tags=["risk", "vod"])
    ok = b.remember("APPROVE: BUY 5 VOD at 117.8 stop 112.0 target 125.0", agent="risk-officer", kind="decision", tags=["risk", "vod"])
    fake = b.remember("APPROVE: BUY 5 VOD", agent="trader", kind="decision")
    assert tools.capital_open("VOD", "BUY", 5, 112, veto.id, "test").startswith("refused")
    assert tools.capital_open("VOD", "BUY", 5, 112, fake.id, "test").startswith("refused")      # not from the risk officer
    assert tools.capital_open("BP", "BUY", 5, 112, ok.id, "test").startswith("refused")         # decision is about VOD, not BP
    r = json.loads(tools.capital_open("VOD", "BUY", 5, 112, ok.id, "MA crossover", _agent="trader"))
    assert r["status"] == "ACCEPTED" and r["mode"] == "DEMO"
    assert any("DEMO trade" in m.content for m in b.recent(limit=5))
    del tools._CAP
