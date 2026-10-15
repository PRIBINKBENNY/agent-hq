"""
Deterministic strategy engine for the trading desk: indicators, rule-based strategies, a bar-by-bar
backtester, walk-forward validation, and the book's "power principles" check. No model is involved
here; the learner agent decides WHAT to test, this module decides what the numbers are.

Bars: list of dicts {t, open, high, low, close}. Strategies emit +1 (long), -1 (short) or 0 on the
bar close; the backtester enters on the NEXT bar's open, pays the spread, honours stop, target and
time-stop (stop wins if both are hit inside one bar). P/L is reported in R-multiples and as account
return at a fixed risk per trade, the way the playbook sizes trades.
"""

from __future__ import annotations

import itertools
import math
from datetime import datetime
from typing import Callable

# ----------------------------------------------------------------------------- indicators
def sma(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals); s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals); k = 2 / (n + 1); e = None
    for i, v in enumerate(vals):
        e = v if e is None else v * k + e * (1 - k)
        if i >= n - 1:
            out[i] = e
    return out


def rsi(vals: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(vals); gains = losses = 0.0; ag = al = None
    for i in range(1, len(vals)):
        ch = vals[i] - vals[i - 1]; g = max(ch, 0); l = max(-ch, 0)
        if i <= n:
            gains += g; losses += l
            if i == n:
                ag, al = gains / n, losses / n
        else:
            ag = (ag * (n - 1) + g) / n; al = (al * (n - 1) + l) / n
        if ag is not None:
            out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def williams_r(bars: list[dict], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(bars)
    for i in range(n - 1, len(bars)):
        hh = max(b["high"] for b in bars[i - n + 1:i + 1]); ll = min(b["low"] for b in bars[i - n + 1:i + 1])
        out[i] = -100 * (hh - bars[i]["close"]) / (hh - ll) if hh != ll else -50.0
    return out


def atr(bars: list[dict], n: int = 14) -> list[float | None]:
    trs = []
    for i, b in enumerate(bars):
        pc = bars[i - 1]["close"] if i else b["close"]
        trs.append(max(b["high"] - b["low"], abs(b["high"] - pc), abs(b["low"] - pc)))
    return sma(trs, n)


def macd(vals: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    ef, es = ema(vals, fast), ema(vals, slow)
    line = [None if (a is None or b is None) else a - b for a, b in zip(ef, es)]
    valid = [x for x in line if x is not None]
    sig_valid = ema(valid, signal); sig: list[float | None] = [None] * len(line); j = 0
    for i, x in enumerate(line):
        if x is not None:
            sig[i] = sig_valid[j]; j += 1
    return line, sig


# ----------------------------------------------------------------------------- strategies
def _cross(a_prev, b_prev, a, b) -> int:
    if None in (a_prev, b_prev, a, b):
        return 0
    if a_prev <= b_prev and a > b:
        return 1
    if a_prev >= b_prev and a < b:
        return -1
    return 0


def sig_sma_cross(bars, fast: int = 10, slow: int = 20, trend_sma: int = 0) -> list[int]:
    c = [b["close"] for b in bars]; f, s = sma(c, fast), sma(c, slow); tr = sma(c, trend_sma) if trend_sma else None
    out = [0] * len(bars)
    for i in range(1, len(bars)):
        x = _cross(f[i - 1], s[i - 1], f[i], s[i])
        if x and tr is not None and tr[i] is not None:
            x = x if (x > 0 and c[i] > tr[i]) or (x < 0 and c[i] < tr[i]) else 0
        out[i] = x
    return out


def sig_breakout(bars, lookback: int = 20) -> list[int]:
    """Channel / turtle breakout: close beyond the prior N-bar high or low."""
    out = [0] * len(bars)
    for i in range(lookback, len(bars)):
        hh = max(b["high"] for b in bars[i - lookback:i]); ll = min(b["low"] for b in bars[i - lookback:i])
        out[i] = 1 if bars[i]["close"] > hh else -1 if bars[i]["close"] < ll else 0
    return out


def sig_macd(bars, fast: int = 12, slow: int = 26, signal: int = 9) -> list[int]:
    line, sig = macd([b["close"] for b in bars], fast, slow, signal)
    return [0] + [_cross(line[i - 1], sig[i - 1], line[i], sig[i]) for i in range(1, len(bars))]


def sig_rsi_fade(bars, period: int = 14, lo: float = 30, hi: float = 70) -> list[int]:
    """Trend-fading: buy when RSI re-crosses up through `lo`, sell when it re-crosses down through `hi`."""
    r = rsi([b["close"] for b in bars], period); out = [0] * len(bars)
    for i in range(1, len(bars)):
        if r[i - 1] is None or r[i] is None:
            continue
        out[i] = 1 if (r[i - 1] < lo <= r[i]) else -1 if (r[i - 1] > hi >= r[i]) else 0
    return out


def sig_williams(bars, period: int = 14, lo: float = -80, hi: float = -20) -> list[int]:
    w = williams_r(bars, period); out = [0] * len(bars)
    for i in range(1, len(bars)):
        if w[i - 1] is None or w[i] is None:
            continue
        out[i] = 1 if (w[i - 1] < lo <= w[i]) else -1 if (w[i - 1] > hi >= w[i]) else 0
    return out


STRATEGIES: dict[str, dict] = {
    "sma_cross": {"fn": sig_sma_cross, "kind": "trend-following", "params": {"fast": 10, "slow": 20, "trend_sma": 0},
                  "grid": {"fast": [5, 10, 20], "slow": [20, 50], "trend_sma": [0, 50]}},
    "breakout": {"fn": sig_breakout, "kind": "trend-following", "params": {"lookback": 20}, "grid": {"lookback": [10, 20, 40]}},
    "macd": {"fn": sig_macd, "kind": "trend-following", "params": {"fast": 12, "slow": 26, "signal": 9}, "grid": {"fast": [8, 12], "slow": [21, 26], "signal": [9]}},
    "rsi_fade": {"fn": sig_rsi_fade, "kind": "trend-fading", "params": {"period": 14, "lo": 30, "hi": 70}, "grid": {"period": [10, 14], "lo": [25, 30], "hi": [70, 75]}},
    "williams": {"fn": sig_williams, "kind": "trend-fading", "params": {"period": 14, "lo": -80, "hi": -20}, "grid": {"period": [10, 14, 20]}},
}


def signals(bars: list[dict], strategy: str, params: dict | None = None) -> list[int]:
    spec = STRATEGIES[strategy]; p = {**spec["params"], **{k: v for k, v in (params or {}).items() if k in spec["params"]}}
    return spec["fn"](bars, **p)


# ----------------------------------------------------------------------------- backtest
def backtest(bars: list[dict], strategy: str, params: dict | None = None, stop_pct: float = 1.0, target_pct: float = 2.0,
             time_stop_bars: int = 0, spread_pct: float = 0.05, risk_pct: float = 1.0, exit_on_opposite: bool = True) -> dict:
    sig = signals(bars, strategy, params); trades: list[dict] = []; pos = None
    for i in range(1, len(bars)):
        b = bars[i]
        if pos:
            d = pos["dir"]; e = pos["entry"]
            stop = e * (1 - d * stop_pct / 100); target = e * (1 + d * target_pct / 100)
            hit_stop = b["low"] <= stop if d > 0 else b["high"] >= stop
            hit_target = b["high"] >= target if d > 0 else b["low"] <= target
            exit_px = None; why = None
            if hit_stop:
                exit_px, why = stop, "stop"
            elif hit_target:
                exit_px, why = target, "target"
            elif time_stop_bars and i - pos["i"] >= time_stop_bars:
                exit_px, why = b["close"], "time"
            elif exit_on_opposite and sig[i] == -d:
                exit_px, why = b["close"], "reverse"
            if exit_px is not None:
                pnl_pct = d * (exit_px - e) / e * 100 - spread_pct
                trades.append({"i_in": pos["i"], "i_out": i, "t_in": bars[pos["i"]]["t"], "t_out": b["t"], "dir": d, "entry": round(e, 5),
                               "exit": round(exit_px, 5), "pnl_pct": round(pnl_pct, 4), "r": round(pnl_pct / stop_pct, 3), "why": why})
                pos = None
        if pos is None and sig[i - 1] in (1, -1) and i < len(bars):
            pos = {"dir": sig[i - 1], "entry": b["open"], "i": i}
    return report(trades, bars, stop_pct, target_pct, risk_pct, strategy, params)


def report(trades: list[dict], bars: list[dict], stop_pct: float, target_pct: float, risk_pct: float = 1.0, strategy: str = "", params: dict | None = None) -> dict:
    n = len(trades)
    if n == 0:
        return {"strategy": strategy, "params": params or {}, "trades": 0, "note": "no trades", "stop_pct": stop_pct, "target_pct": target_pct}
    wins = [t for t in trades if t["pnl_pct"] > 0]; losses = [t for t in trades if t["pnl_pct"] <= 0]
    gp = sum(t["r"] for t in wins); gl = -sum(t["r"] for t in losses)
    # account equity at fixed % risk per trade (compounded), and max drawdown of that equity curve
    eq = 1.0; peak = 1.0; mdd = 0.0
    for t in trades:
        eq *= 1 + t["r"] * risk_pct / 100; peak = max(peak, eq); mdd = max(mdd, (peak - eq) / peak)
    weeks = _weeks(bars)
    return {
        "strategy": strategy, "params": params or {}, "stop_pct": stop_pct, "target_pct": target_pct, "rr": round(target_pct / stop_pct, 2),
        "trades": n, "win_pct": round(100 * len(wins) / n, 1), "avg_win_r": round(gp / len(wins), 3) if wins else 0.0,
        "avg_loss_r": round(-gl / len(losses), 3) if losses else 0.0, "profit_factor": round(gp / gl, 3) if gl else (9.99 if gp else 0.0),
        "expectancy_r": round(sum(t["r"] for t in trades) / n, 3), "net_r": round(sum(t["r"] for t in trades), 2),
        "net_pct_at_risk": round((eq - 1) * 100, 2), "max_drawdown_pct": round(mdd * 100, 2), "risk_pct": risk_pct,
        "bars": len(bars), "weeks": weeks, "trades_per_week": round(n / weeks, 2) if weeks else None,
        "exits": {k: sum(1 for t in trades if t["why"] == k) for k in ("stop", "target", "time", "reverse")},
        "first": bars[0]["t"], "last": bars[-1]["t"], "trade_list": trades[-5:],
    }


def _weeks(bars: list[dict]) -> float | None:
    try:
        a = _ts(bars[0]["t"]); b = _ts(bars[-1]["t"])
        return max(0.2, round((b - a) / (7 * 86400), 2))
    except Exception:
        return None


def _ts(t) -> float:
    if isinstance(t, (int, float)):
        return float(t)
    s = str(t).replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt).timestamp()
        except ValueError:
            continue
    return datetime.fromisoformat(s).timestamp()


# ----------------------------------------------------------------------------- power principles (from the playbook)
PRINCIPLES = {"min_trades": 40, "min_win_pct": 50.0, "min_profit_factor": 1.3, "min_rr": 1.5, "max_drawdown_pct": 20.0, "min_trades_per_week": 4.0}


def principles_check(rep: dict, rules: dict | None = None) -> dict:
    r = {**PRINCIPLES, **(rules or {})}
    if rep.get("trades", 0) == 0:
        return {"passed": False, "checks": {"trades": False}, "failed": ["no trades"]}
    checks = {
        f"trades >= {r['min_trades']}": rep["trades"] >= r["min_trades"],
        f"win_pct >= {r['min_win_pct']}": rep["win_pct"] >= r["min_win_pct"],
        f"profit_factor >= {r['min_profit_factor']}": rep["profit_factor"] >= r["min_profit_factor"],
        f"rr >= {r['min_rr']}": rep["rr"] >= r["min_rr"],
        f"max_drawdown <= {r['max_drawdown_pct']}%": rep["max_drawdown_pct"] <= r["max_drawdown_pct"],
    }
    if rep.get("trades_per_week") is not None:
        checks[f"trades_per_week >= {r['min_trades_per_week']}"] = rep["trades_per_week"] >= r["min_trades_per_week"]
    return {"passed": all(checks.values()), "checks": checks, "failed": [k for k, v in checks.items() if not v]}


# ----------------------------------------------------------------------------- walk-forward
def grid(strategy: str, custom: dict | None = None) -> list[dict]:
    g = custom or STRATEGIES[strategy]["grid"]; keys = list(g)
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*[g[k] for k in keys])]
    if strategy == "sma_cross":
        combos = [c for c in combos if c["fast"] < c["slow"]]
    return combos


def walk_forward(bars: list[dict], strategy: str, param_grid: dict | None = None, segments: int = 4, stop_pct: float = 1.0,
                 target_pct: float = 2.0, time_stop_bars: int = 0, min_trades: int = 10, spread_pct: float = 0.05) -> dict:
    """Optimise on everything before each segment, test on the segment; report the combined out-of-sample result."""
    n = len(bars); seg = n // segments; oos_trades: list[dict] = []; folds = []
    if seg < 50:
        return {"error": f"need at least {segments * 50} bars, have {n}"}
    for k in range(1, segments):
        cut = k * seg; end = min(n, cut + seg); train = bars[:cut]; test = bars[cut - 60:end]   # overlap so indicators warm up
        best = None
        for p in grid(strategy, param_grid):
            rep = backtest(train, strategy, p, stop_pct, target_pct, time_stop_bars, spread_pct)
            if rep.get("trades", 0) < min_trades:
                continue
            score = rep["profit_factor"] * min(1.0, rep["trades"] / 40)
            if best is None or score > best[0]:
                best = (score, p, rep)
        if not best:
            folds.append({"fold": k, "note": "no parameter set reached min_trades in-sample"}); continue
        _, p, train_rep = best
        test_rep = backtest(test, strategy, p, stop_pct, target_pct, time_stop_bars, spread_pct)
        t_trades = _collect(test, strategy, p, stop_pct, target_pct, time_stop_bars, spread_pct)
        t_trades = [t for t in t_trades if t["i_in"] >= 60]   # only trades that start inside the test window
        oos_trades += t_trades
        folds.append({"fold": k, "params": p, "in_sample_pf": train_rep["profit_factor"], "in_sample_trades": train_rep["trades"],
                      "oos_trades": len(t_trades), "oos_net_r": round(sum(t["r"] for t in t_trades), 2),
                      "oos_pf": test_rep.get("profit_factor"), "profitable": sum(t["r"] for t in t_trades) > 0})
    oos = report(oos_trades, bars, stop_pct, target_pct, 1.0, strategy, {"walk_forward": True})
    done = [f for f in folds if "params" in f]
    oos["folds"] = folds
    oos["stable"] = bool(done) and sum(1 for f in done if f["profitable"]) / len(done) >= 0.6
    oos["recommended_params"] = _mode_params(done)
    oos["principles"] = principles_check(oos)
    return oos


def _collect(bars, strategy, p, stop_pct, target_pct, time_stop_bars, spread_pct) -> list[dict]:
    rep = backtest(bars, strategy, p, stop_pct, target_pct, time_stop_bars, spread_pct)
    # backtest keeps only the last 5 trades in the report; re-run to get all of them cheaply
    sig = signals(bars, strategy, p); trades = []; pos = None
    for i in range(1, len(bars)):
        b = bars[i]
        if pos:
            d = pos["dir"]; e = pos["entry"]; stop = e * (1 - d * stop_pct / 100); target = e * (1 + d * target_pct / 100)
            hit_stop = b["low"] <= stop if d > 0 else b["high"] >= stop; hit_target = b["high"] >= target if d > 0 else b["low"] <= target
            exit_px = stop if hit_stop else target if hit_target else b["close"] if (time_stop_bars and i - pos["i"] >= time_stop_bars) or sig[i] == -d else None
            if exit_px is not None:
                pnl = d * (exit_px - e) / e * 100 - spread_pct
                trades.append({"i_in": pos["i"], "i_out": i, "dir": d, "pnl_pct": round(pnl, 4), "r": round(pnl / stop_pct, 3), "why": "x"}); pos = None
        if pos is None and sig[i - 1] in (1, -1):
            pos = {"dir": sig[i - 1], "entry": b["open"], "i": i}
    return trades


def _mode_params(folds: list[dict]) -> dict | None:
    if not folds:
        return None
    counts: dict[str, int] = {}; by: dict[str, dict] = {}
    for f in folds:
        k = str(sorted(f["params"].items())); counts[k] = counts.get(k, 0) + 1; by[k] = f["params"]
    return by[max(counts, key=counts.get)]


def latest_signal(bars: list[dict], strategy: str, params: dict | None = None) -> int:
    s = signals(bars, strategy, params)
    return s[-1] if s else 0
