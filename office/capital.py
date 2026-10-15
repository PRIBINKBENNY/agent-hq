"""
Capital.com client for the trading office. DEMO account by default and enforced:
the live endpoint is used only if CAPITAL_LIVE=I_UNDERSTAND_REAL_MONEY is set explicitly.

Docs: https://open-api.capital.com/   Sessions expire after 10 min idle; we re-login on 401.
Hard limits applied in code regardless of what any agent asks for:
  * max 10% of available balance per position, max 6 open positions
  * every position must carry a stop level
  * demo-only unless the live flag above is set
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

import httpx

DEMO_URL = "https://demo-api-capital.backend-capital.com/api/v1"
LIVE_URL = "https://api-capital.backend-capital.com/api/v1"
MAX_POSITION_FRACTION = 0.10
MAX_OPEN_POSITIONS = 6


class CapitalError(Exception):
    pass


def configured() -> bool:
    return all((os.environ.get(k) or "").strip() for k in ("CAPITAL_API_KEY", "CAPITAL_IDENTIFIER", "CAPITAL_PASSWORD"))


def is_live() -> bool:
    return (os.environ.get("CAPITAL_LIVE") or "").strip() == "I_UNDERSTAND_REAL_MONEY"


class Capital:
    def __init__(self, transport: Optional[httpx.BaseTransport] = None):
        self.base = LIVE_URL if is_live() else DEMO_URL
        self.key = (os.environ.get("CAPITAL_API_KEY") or "").strip()
        self.identifier = (os.environ.get("CAPITAL_IDENTIFIER") or "").strip()
        self.password = (os.environ.get("CAPITAL_PASSWORD") or "").strip()
        self.cst: Optional[str] = None
        self.sec: Optional[str] = None
        self.client = httpx.Client(base_url=self.base, timeout=20, transport=transport)
        self._last_login = 0.0

    # ----------------------------------------------------------------- session
    def login(self):
        if not configured():
            raise CapitalError("Capital.com not configured: set CAPITAL_API_KEY, CAPITAL_IDENTIFIER, CAPITAL_PASSWORD in .env")
        if time.time() - self._last_login < 1.1:   # endpoint limit: 1 request/second
            time.sleep(1.1)
        r = self.client.post("/session", headers={"X-CAP-API-KEY": self.key},
                             json={"identifier": self.identifier, "password": self.password, "encryptedPassword": False})
        if r.status_code >= 400:
            raise CapitalError(f"login failed {r.status_code}: {r.text[:200]}")
        self.cst = r.headers.get("CST"); self.sec = r.headers.get("X-SECURITY-TOKEN"); self._last_login = time.time()
        return r.json()

    def _h(self) -> dict:
        if not self.cst:
            self.login()
        return {"X-CAP-API-KEY": self.key, "CST": self.cst or "", "X-SECURITY-TOKEN": self.sec or ""}

    def _req(self, method: str, path: str, **kw) -> Any:
        for attempt in (1, 2):
            r = self.client.request(method, path, headers=self._h(), **kw)
            if r.status_code == 401 and attempt == 1:
                self.cst = None; continue
            if r.status_code >= 400:
                raise CapitalError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
            return r.json() if r.content else {}
        raise CapitalError("unreachable")

    # ----------------------------------------------------------------- reads
    def ping(self) -> dict:
        return self._req("GET", "/ping")

    def accounts(self) -> list[dict]:
        return self._req("GET", "/accounts").get("accounts", [])

    def preferred_account(self) -> dict:
        accs = self.accounts()
        return next((a for a in accs if a.get("preferred")), accs[0] if accs else {})

    def search_markets(self, term: str, limit: int = 10) -> list[dict]:
        data = self._req("GET", "/markets", params={"searchTerm": term})
        out = []
        for m in data.get("markets", [])[:limit]:
            out.append({k: m.get(k) for k in ("epic", "instrumentName", "instrumentType", "bid", "offer", "marketStatus", "percentageChange", "expiry")})
        return out

    def market(self, epic: str) -> dict:
        d = self._req("GET", f"/markets/{epic}")
        inst, snap, rules = d.get("instrument", {}), d.get("snapshot", {}), d.get("dealingRules", {})
        return {"epic": epic, "name": inst.get("name"), "type": inst.get("type"), "currency": inst.get("currency"),
                "bid": snap.get("bid"), "offer": snap.get("offer"), "status": snap.get("marketStatus"),
                "change_pct": snap.get("percentageChange"), "high": snap.get("high"), "low": snap.get("low"),
                "min_size": (rules.get("minDealSize") or {}).get("value"), "min_stop_distance": (rules.get("minStopOrProfitDistance") or {}).get("value"),
                "leverage": (inst.get("marginFactor") if inst.get("marginFactorUnit") else None)}

    def prices(self, epic: str, resolution: str = "HOUR", max_points: int = 48) -> list[dict]:
        d = self._req("GET", f"/prices/{epic}", params={"resolution": resolution, "max": int(max_points)})
        out = []
        for p in d.get("prices", []):
            c = p.get("closePrice", {}); o = p.get("openPrice", {}); h = p.get("highPrice", {}); l = p.get("lowPrice", {})
            mid = lambda x: (x.get("bid", 0) + x.get("ask", x.get("offer", 0))) / 2 if x else None
            out.append({"t": p.get("snapshotTimeUTC") or p.get("snapshotTime"), "open": mid(o), "high": mid(h), "low": mid(l), "close": mid(c), "volume": p.get("lastTradedVolume")})
        return out

    def positions(self) -> list[dict]:
        out = []
        for p in self._req("GET", "/positions").get("positions", []):
            pos, mkt = p.get("position", {}), p.get("market", {})
            out.append({"dealId": pos.get("dealId"), "epic": mkt.get("epic"), "name": mkt.get("instrumentName"), "direction": pos.get("direction"),
                        "size": pos.get("size"), "level": pos.get("level"), "bid": mkt.get("bid"), "offer": mkt.get("offer"),
                        "upl": pos.get("upl"), "stop": pos.get("stopLevel"), "profit": pos.get("profitLevel"), "currency": pos.get("currency"),
                        "opened": pos.get("createdDateUTC") or pos.get("createdDate")})
        return out

    def confirm(self, deal_reference: str) -> dict:
        return self._req("GET", f"/confirms/{deal_reference}")

    # ----------------------------------------------------------------- writes (guarded)
    def open_position(self, epic: str, direction: str, size: float, stop_level: float, profit_level: Optional[float] = None) -> dict:
        direction = direction.upper()
        if direction not in ("BUY", "SELL"):
            raise CapitalError("direction must be BUY or SELL")
        if not stop_level:
            raise CapitalError("refused: every position must have a stop level")
        acc = self.preferred_account(); bal = acc.get("balance", {})
        available = float(bal.get("available") or bal.get("balance") or 0)
        mkt = self.market(epic)
        price = float(mkt.get("offer" if direction == "BUY" else "bid") or 0)
        if not price:
            raise CapitalError(f"no price for {epic} (market {mkt.get('status')})")
        exposure = price * float(size)
        if available and exposure > available * MAX_POSITION_FRACTION:
            max_size = round(available * MAX_POSITION_FRACTION / price, 4)
            raise CapitalError(f"refused: exposure {exposure:.2f} > {MAX_POSITION_FRACTION:.0%} of available {available:.2f}; max size {max_size}")
        if len(self.positions()) >= MAX_OPEN_POSITIONS:
            raise CapitalError(f"refused: already {MAX_OPEN_POSITIONS} open positions")
        if (direction == "BUY" and float(stop_level) >= price) or (direction == "SELL" and float(stop_level) <= price):
            raise CapitalError("refused: stop level is on the wrong side of the price")
        body = {"epic": epic, "direction": direction, "size": float(size), "guaranteedStop": False, "stopLevel": float(stop_level)}
        if profit_level:
            body["profitLevel"] = float(profit_level)
        ref = self._req("POST", "/positions", json=body).get("dealReference")
        time.sleep(0.8)
        conf = self.confirm(ref) if ref else {}
        return {"dealReference": ref, "status": conf.get("dealStatus") or conf.get("status"), "dealId": conf.get("dealId"),
                "level": conf.get("level"), "size": conf.get("size"), "direction": direction, "epic": epic,
                "reason": conf.get("reason"), "mode": "LIVE" if is_live() else "DEMO"}

    def close_position(self, deal_id: str) -> dict:
        ref = self._req("DELETE", f"/positions/{deal_id}").get("dealReference")
        time.sleep(0.8)
        conf = self.confirm(ref) if ref else {}
        return {"dealReference": ref, "status": conf.get("dealStatus") or conf.get("status"), "dealId": deal_id, "mode": "LIVE" if is_live() else "DEMO"}

    def update_position(self, deal_id: str, stop_level: Optional[float] = None, profit_level: Optional[float] = None) -> dict:
        body = {}
        if stop_level:
            body["stopLevel"] = float(stop_level)
        if profit_level:
            body["profitLevel"] = float(profit_level)
        return self._req("PUT", f"/positions/{deal_id}", json=body)
