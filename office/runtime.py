"""
Office runtime: runs one agent brief against Groq (free tier) with automatic
fallback to a smaller Groq model and finally to local Ollama.

An agent = a markdown brief (office/agents/<name>.md) with YAML frontmatter:
    name, office, tier (lead|worker), tools [...], delegates [...]
The body is the system prompt.

Engines (OpenAI-compatible chat completions, tool calling):
    groq    https://api.groq.com/openai/v1   needs GROQ_API_KEY in .env
    ollama  http://localhost:11434/v1        free, local, slower
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
import yaml
import uuid
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from events import emit  # noqa: E402

AGENTS_DIR = ROOT / "office" / "agents"
LOG_DIR = ROOT / "office" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")  # native API: supports think=false
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")   # small, tool-capable, no thinking phase


def _env_list(name: str, default: str) -> list[str]:
    return [m.strip() for m in os.environ.get(name, default).split(",") if m.strip()]


# Free-tier providers, all OpenAI-compatible. A provider is active only when its key is set.
# Order = preference; the runtime hops to the next one on a rate limit or error.
PROVIDERS: dict[str, dict] = {
    "cerebras": {
        "url": "https://api.cerebras.ai/v1/chat/completions", "models_url": "https://api.cerebras.ai/v1/models",
        "key_env": "CEREBRAS_API_KEY",
        "lead": _env_list("CEREBRAS_LEAD_MODELS", "gpt-oss-120b,qwen-3.8-27b"),
        "worker": _env_list("CEREBRAS_WORKER_MODELS", "qwen-3.8-27b,gpt-oss-120b"),
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions", "models_url": "https://api.groq.com/openai/v1/models",
        "key_env": "GROQ_API_KEY",
        "lead": _env_list("GROQ_LEAD_MODELS", "openai/gpt-oss-120b,qwen/qwen3.8-27b,openai/gpt-oss-20b"),
        "worker": _env_list("GROQ_WORKER_MODELS", "openai/gpt-oss-20b,qwen/qwen3.8-27b,openai/gpt-oss-120b"),
    },
    "mistral": {
        "url": "https://api.mistral.ai/v1/chat/completions", "models_url": "https://api.mistral.ai/v1/models",
        "key_env": "MISTRAL_API_KEY",
        "lead": _env_list("MISTRAL_LEAD_MODELS", "mistral-large-latest,mistral-medium-latest"),
        "worker": _env_list("MISTRAL_WORKER_MODELS", "mistral-small-latest,mistral-medium-latest"),
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "models_url": "https://generativelanguage.googleapis.com/v1beta/openai/models",
        "key_env": "GEMINI_API_KEY",
        "lead": _env_list("GEMINI_LEAD_MODELS", "gemini-2.5-flash,gemini-2.5-pro"),
        "worker": _env_list("GEMINI_WORKER_MODELS", "gemini-2.5-flash-lite,gemini-2.5-flash"),
    },
    # free with an email sign-up, no card: NVIDIA's hosted open models (about 40 requests/min)
    "nvidia": {
        "url": "https://integrate.api.nvidia.com/v1/chat/completions", "models_url": "https://integrate.api.nvidia.com/v1/models",
        "key_env": "NVIDIA_API_KEY",
        "lead": _env_list("NVIDIA_LEAD_MODELS", "meta/llama-3.3-70b-instruct,nvidia/llama-3.3-nemotron-super-49b-v1,qwen/qwen3-235b-a22b"),
        "worker": _env_list("NVIDIA_WORKER_MODELS", "meta/llama-3.1-8b-instruct,meta/llama-3.3-70b-instruct"),
    },
    # free sign-up, no card: SambaNova Cloud (fast Llama / DeepSeek)
    "sambanova": {
        "url": "https://api.sambanova.ai/v1/chat/completions", "models_url": "https://api.sambanova.ai/v1/models",
        "key_env": "SAMBANOVA_API_KEY",
        "lead": _env_list("SAMBANOVA_LEAD_MODELS", "Meta-Llama-3.3-70B-Instruct,DeepSeek-V3-0324"),
        "worker": _env_list("SAMBANOVA_WORKER_MODELS", "Meta-Llama-3.1-8B-Instruct,Meta-Llama-3.3-70B-Instruct"),
    },
    # free Cloudflare account, no card: Workers AI (10,000 neurons/day); needs the account id in the URL
    "cloudflare": {
        "url": f"https://api.cloudflare.com/client/v4/accounts/{os.environ.get('CLOUDFLARE_ACCOUNT_ID', 'ACCOUNT_ID')}/ai/v1/chat/completions",
        "models_url": f"https://api.cloudflare.com/client/v4/accounts/{os.environ.get('CLOUDFLARE_ACCOUNT_ID', 'ACCOUNT_ID')}/ai/v1/models",
        "key_env": "CLOUDFLARE_API_TOKEN",
        "lead": _env_list("CLOUDFLARE_LEAD_MODELS", "@cf/meta/llama-3.3-70b-instruct-fp8-fast"),
        "worker": _env_list("CLOUDFLARE_WORKER_MODELS", "@cf/meta/llama-3.1-8b-instruct-fast,@cf/meta/llama-3.3-70b-instruct-fp8-fast"),
    },
}
PROVIDER_ORDER = _env_list("PROVIDER_ORDER", "cerebras,groq,gemini,mistral,nvidia,sambanova,cloudflare")


_STORE = None


def _store():
    """One BrainStore per process (fresh connections on every call were piling up locks)."""
    global _STORE
    if _STORE is None:
        sys.path.insert(0, str(ROOT / "brain"))
        from store import BrainStore
        _STORE = BrainStore()
    return _STORE


def provider_key(name: str) -> str:
    p = PROVIDERS.get(name)
    return (os.environ.get(p["key_env"]) or "").strip() if p else ""


def active_providers() -> list[str]:
    return [n for n in PROVIDER_ORDER if n in PROVIDERS and provider_key(n)]


_MODELS_CACHE: dict[str, Optional[set[str]]] = {}


def available_models(name: str) -> Optional[set[str]]:
    """Ask the provider which models it serves (cached). None = could not check, trust the config."""
    if name in _MODELS_CACHE:
        return _MODELS_CACHE[name]
    p = PROVIDERS[name]; out = None
    try:
        r = httpx.get(p["models_url"], headers={"Authorization": f"Bearer {provider_key(name)}"}, timeout=15)
        if r.status_code == 200:
            data = r.json().get("data", [])
            out = {str(m.get("id", "")).removeprefix("models/") for m in data}
    except Exception:
        out = None
    _MODELS_CACHE[name] = out
    return out


def provider_models(name: str, tier: str) -> list[str]:
    cfg = PROVIDERS[name]["lead" if tier == "lead" else "worker"]
    avail = available_models(name)
    if not avail:
        return cfg
    ok = [m for m in cfg if m in avail]
    if ok:
        return ok
    # none of the configured names exist any more: pick what the provider does serve
    chat = sorted(m for m in avail if not any(x in m for x in ("whisper", "embed", "guard", "tts", "orpheus", "safeguard", "moderation", "ocr")))
    return chat[:2]


# backwards-compatible names used by the dashboard
LEAD_MODELS = PROVIDERS["groq"]["lead"]
WORKER_MODELS = PROVIDERS["groq"]["worker"]

TUNING_FILE = ROOT / "office" / "tuning.json"


def tuning() -> dict:
    try:
        return json.loads(TUNING_FILE.read_text())
    except Exception:
        return {}


MAX_TURNS = int(os.environ.get("OFFICE_MAX_TURNS") or tuning().get("max_turns", 20))
READ_TOOLS = {"read_file", "list_files", "brain_recall", "brain_recent", "brain_query", "job_details", "web_fetch", "fact_check",
              "cv_truth_check", "market_data", "task_list", "github_status", "job_search", "web_search"}
TOOL_RESULT_CAP = int(os.environ.get("OFFICE_TOOL_RESULT_CAP", "3000"))
RUN_TOKEN_BUDGET = int(os.environ.get("OFFICE_RUN_TOKEN_BUDGET") or tuning().get("run_token_budget", 60000))   # soft cap per run
_COOLDOWN: dict[tuple[str, str], float] = {}   # (engine, model) -> unix ts when usable again


# --------------------------------------------------------------------------- #
# Briefs
# --------------------------------------------------------------------------- #
@dataclass
class Brief:
    name: str
    office: str
    tier: str
    tools: list[str]
    delegates: list[str]
    system: str
    description: str = ""
    model: Optional[str] = None     # pin a specific model (optional)
    local_ok: bool = False          # may run on the local 3B model when every cloud provider is cooling down


def load_brief(name: str) -> Brief:
    path = AGENTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"no agent brief: {path}")
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{path} needs YAML frontmatter")
    meta = yaml.safe_load(m.group(1)) or {}
    return Brief(
        name=meta.get("name", name),
        office=meta.get("office", "unknown"),
        tier=meta.get("tier", "worker"),
        tools=list(meta.get("tools", [])),
        delegates=list(meta.get("delegates", [])),
        local_ok=bool(meta.get("local_ok", False)),
        system=m.group(2).strip(),
        description=meta.get("description", ""),
        model=meta.get("model"),
    )


def list_agents() -> list[Brief]:
    return [load_brief(p.stem) for p in sorted(AGENTS_DIR.glob("*.md"))]


# --------------------------------------------------------------------------- #
# Engines
# --------------------------------------------------------------------------- #
PROVIDER_DOWN_FILE = LOG_DIR / "provider_down.json"


def provider_down() -> dict:
    """{provider: until_ts} for providers that answered 401/402/403 (key invalid, credits gone). Shared across processes."""
    try:
        d = json.loads(PROVIDER_DOWN_FILE.read_text())
        return {k: v for k, v in d.items() if v > time.time()}
    except Exception:
        return {}


COOL_FILE = LOG_DIR / "provider_cool.json"


def persisted_cooldowns() -> dict:
    """{'provider:model': until_ts} for long rate-limit cooldowns, shared across processes."""
    try:
        return {k: v for k, v in json.loads(COOL_FILE.read_text()).items() if v > time.time()}
    except Exception:
        return {}


def persist_cooldown(provider: str, model: str, until: float):
    if until - time.time() < 90:
        return
    d = persisted_cooldowns(); d[f"{provider}:{model}"] = until
    try:
        COOL_FILE.parent.mkdir(parents=True, exist_ok=True); COOL_FILE.write_text(json.dumps(d))
    except Exception:
        pass


def cloud_available() -> tuple[bool, float]:
    """(True, 0) if some cloud model can be called now; otherwise (False, soonest_time_it_will_be)."""
    down = provider_down(); cool = persisted_cooldowns(); soonest = None
    for prov in active_providers():
        if prov in down:
            soonest = min(soonest or down[prov], down[prov]); continue
        models = (PROVIDERS[prov]["lead"] + PROVIDERS[prov]["worker"])
        for m in models:
            until = cool.get(f"{prov}:{m}", 0)
            if until <= time.time():
                return True, 0.0
            soonest = min(soonest or until, until)
    return (False, soonest or time.time() + 600) if active_providers() else (False, time.time() + 3600)


DOWN_HIST_FILE = LOG_DIR / "provider_down_hist.json"


def provider_down_repeated(window_hours: float = 48, times: int = 3) -> list[str]:
    """Providers parked `times` or more times in the window: the key is dead, not just a blip."""
    try:
        hist = json.loads(DOWN_HIST_FILE.read_text())
    except Exception:
        return []
    cut = time.time() - window_hours * 3600
    return [p for p, ts in hist.items() if sum(1 for t in ts if t > cut) >= times]


def mark_provider_down(provider: str, hours: float = 6, reason: str = ""):
    try:
        hist = json.loads(DOWN_HIST_FILE.read_text())
    except Exception:
        hist = {}
    recent = [t for t in hist.get(provider, []) if t > time.time() - 48 * 3600] + [time.time()]
    hist[provider] = recent[-10:]
    try:
        DOWN_HIST_FILE.parent.mkdir(parents=True, exist_ok=True); DOWN_HIST_FILE.write_text(json.dumps(hist))
    except Exception:
        pass
    if len(recent) >= 3:                      # third strike in two days: this key is dead, stop poking it every 6h
        hours = max(hours, 24); reason = (reason[:100] + " | repeated: remove the key from .env or top up credits")
    d = provider_down(); d[provider] = time.time() + hours * 3600
    try:
        PROVIDER_DOWN_FILE.parent.mkdir(parents=True, exist_ok=True); PROVIDER_DOWN_FILE.write_text(json.dumps(d))
    except Exception:
        pass
    try:
        emit("fallback", "runtime", "runtime", model=provider, reason=f"{provider} parked for {hours}h: {reason[:120]}")
    except Exception:
        pass


class RateLimited(Exception):
    pass


def parse_duration(text: Optional[str]) -> Optional[float]:
    """'7', '7.5s', '577ms', '1m2.3s', '2h3m14.1s' -> seconds. None if unparseable."""
    if not text:
        return None
    t = str(text).strip().lower()
    if re.fullmatch(r"[\d.]+", t):
        return float(t)
    total, found = 0.0, False
    for num, unit in re.findall(r"([\d.]+)\s*(ms|h|m|s)", t):
        found = True
        v = float(num)
        total += v / 1000 if unit == "ms" else v * 3600 if unit == "h" else v * 60 if unit == "m" else v
    return total if found else None


class EngineError(Exception):
    pass


USAGE_FILE = LOG_DIR / "usage.json"


def _record_usage(provider: str, model: str, headers: httpx.Headers):
    """Keep the latest x-ratelimit-* headers per provider so the dashboard and picker can see budget."""
    rl = {k.lower(): v for k, v in headers.items() if k.lower().startswith("x-ratelimit-")}
    if not rl:
        return
    try:
        data = json.loads(USAGE_FILE.read_text()) if USAGE_FILE.exists() else {}
    except Exception:
        data = {}
    data[provider] = {"model": model, "ts": time.time(), **rl}
    try:
        USAGE_FILE.write_text(json.dumps(data, indent=1))
    except Exception:
        pass
    def num(k):
        try:
            return float(rl[k]) if k in rl else None
        except ValueError:
            return None
    now = time.time()
    # nearly out of per-minute tokens: cool this model down until the window resets
    rem = num("x-ratelimit-remaining-tokens-minute") if "x-ratelimit-remaining-tokens-minute" in rl else num("x-ratelimit-remaining-tokens")
    reset = parse_duration(rl.get("x-ratelimit-reset-tokens-minute") or rl.get("x-ratelimit-reset-tokens")) or 60
    if rem is not None and rem < 1500:
        _COOLDOWN[(provider, model)] = now + min(reset, 65)
    # out of per-minute requests (Cerebras: 5/min): wait for the minute
    req_min = num("x-ratelimit-remaining-requests-minute")
    if req_min is not None and req_min <= 0:
        _COOLDOWN[(provider, model)] = max(_COOLDOWN.get((provider, model), 0), now + 61)
    # nearly out for the day: step aside for an hour so other providers carry the load, re-check later
    day_tok = num("x-ratelimit-remaining-tokens-day"); day_req = num("x-ratelimit-remaining-requests-day") or num("x-ratelimit-remaining-requests")
    if (day_tok is not None and day_tok < 40000) or (day_req is not None and day_req < 40):
        for key in list(_COOLDOWN) + [(provider, model)]:
            if key[0] == provider:
                _COOLDOWN[key] = max(_COOLDOWN.get(key, 0), now + 3600)


def read_usage() -> dict:
    try:
        return json.loads(USAGE_FILE.read_text()) if USAGE_FILE.exists() else {}
    except Exception:
        return {}


def _chat(url: str, headers: dict, payload: dict, timeout: float = 120, provider: str = "", model: str = "") -> dict:
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(url, headers=headers, json=payload)
    except httpx.HTTPError as e:
        raise EngineError(f"network: {type(e).__name__}: {str(e)[:160]}")
    if provider:
        _record_usage(provider, model, r.headers)
    if r.status_code == 429:
        wait = parse_duration(r.headers.get("retry-after"))
        if wait is None:
            m = re.search(r"try again in ([0-9hms.]+)", r.text)
            wait = parse_duration(m.group(1)) if m else None
        if wait is None:
            wait = parse_duration(r.headers.get("x-ratelimit-reset-tokens")) or parse_duration(r.headers.get("x-ratelimit-reset-requests"))
        raise RateLimited(str(wait if wait is not None else 30.0))
    if r.status_code == 413:
        raise RateLimited("payload too large")
    if r.status_code in (401, 402, 403) and provider:
        mark_provider_down(provider, 6, f"{r.status_code} {r.text[:100]}")
    if r.status_code >= 400:
        raise EngineError(f"{r.status_code}: {r.text[:300]}")
    return r.json()


def _call_model(messages: list[dict], tools: list[dict], model: str, engine: str, tier: str = "worker",
                tool_choice: str = "auto") -> dict:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 4096,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice
    if engine == "ollama":
        return _ollama_native(messages, [] if tool_choice == "none" else tools, model)
    p = PROVIDERS.get(engine)
    if not p:
        raise EngineError(f"unknown engine {engine}")
    key = provider_key(engine)
    if not key:
        raise EngineError(f"{p['key_env']} not set (put it in .env)")
    extras = {}
    if "gpt-oss" in model and engine in ("groq", "cerebras"):
        extras["reasoning_effort"] = "medium" if tier == "lead" else "low"
    try:
        return _chat(p["url"], {"Authorization": f"Bearer {key}"}, {**payload, **extras}, provider=engine, model=model)
    except EngineError as e:
        if extras and str(e).startswith("400"):   # provider rejected an optional param: retry plain
            return _chat(p["url"], {"Authorization": f"Bearer {key}"}, payload, provider=engine, model=model)
        raise


def _ollama_native(messages: list[dict], tools: list[dict], model: str) -> dict:
    """Ollama /api/chat with thinking disabled; result normalised to OpenAI shape."""
    msgs = []
    for m in messages:
        mm = {"role": m["role"], "content": m.get("content") or ""}
        if m.get("tool_calls"):
            mm["tool_calls"] = [{"function": {
                "name": tc["function"]["name"],
                "arguments": json.loads(tc["function"]["arguments"]) if isinstance(tc["function"].get("arguments"), str)
                             else (tc["function"].get("arguments") or {}),
            }} for tc in m["tool_calls"]]
        msgs.append(mm)
    payload = {"model": model, "messages": msgs, "stream": False, "think": False,
               "options": {"temperature": 0.3, "num_predict": 1500, "num_ctx": 8192}}
    if tools:
        payload["tools"] = tools
    try:
        with httpx.Client(timeout=600) as c:
            r = c.post(OLLAMA_URL, json=payload)
    except httpx.HTTPError as e:
        raise EngineError(f"ollama network: {type(e).__name__}: {str(e)[:160]}")
    if r.status_code >= 400:
        raise EngineError(f"ollama {r.status_code}: {r.text[:300]}")
    data = r.json()
    msg = data.get("message", {})
    tool_calls = []
    for i, tc in enumerate(msg.get("tool_calls") or []):
        fn = tc.get("function", {})
        args = fn.get("arguments", {})
        tool_calls.append({"id": f"call_{i}", "type": "function", "function": {
            "name": fn.get("name", ""), "arguments": json.dumps(args) if not isinstance(args, str) else args}})
    return {"choices": [{"message": {"role": "assistant", "content": msg.get("content", ""),
                                     "tool_calls": tool_calls or None},
                         "finish_reason": data.get("done_reason", "stop")}]}


_CLAIMS = [
    (r"\b(saved|wrote|written|writing|added to|appended|append|updated|created|edited)\b[^.\n]{0,80}\b[\w/-]+\.(md|py|json|txt|html|csv|ics|yaml)\b",
     {"write_file", "draft_email", "calendar_event"}, "wrote a file"),
    (r"\b(stored|saved|logged|recorded)\b[^.\n]{0,60}\b(brain|memory)\b", {"brain_remember"}, "stored something in the brain"),
    (r"\b(stored|logged|recorded)\b[^.\n]{0,40}\b(as|kind)\s*=?\s*\"?(event|fact|job|lead|lesson|decision)\b", {"brain_remember"}, "stored something in the brain"),
    (r"\b(approval|approve)\b[^.\n]{0,40}\b(requested|logged|sent|submitted)\b", {"request_approval", "draft_email"}, "requested approval"),
    (r"\b(committed|git commit)\b", {"git"}, "committed with git"),
    (r"\b(queued|added)\b[^.\n]{0,40}\b(task|board)\b", {"task_create"}, "created a task"),
    (r"\b(system|office|all tools|all agents|all systems|everything)\b[^.\n]{0,40}\b(operational|healthy|nominal|ready|up and running|running (fine|normally|smoothly)|working (fine|normally))\b",
     {"office_status", "ops_metrics", "scorecard"}, "checked the office status"),
]


def unbacked_claim(answer: str, calls: list[dict], allowed_tools: list[str]) -> Optional[str]:
    """Return a description of an action the answer claims but no tool call backs, if any."""
    used = {c["tool"] for c in calls if not str(c.get("result_preview", "")).lstrip().lower().startswith(("error", "refused"))}
    for pat, tools, label in _CLAIMS:
        if not (tools & set(allowed_tools)):
            continue  # agent cannot do this action anyway; its wording is just prose
        if re.search(pat, answer, re.I) and not (used & tools):
            return label
    return None


def trim_context(messages: list[dict], keep_full: int = 2, stub_chars: int = 260) -> list[dict]:
    """Copy of messages where all but the last `keep_full` tool results are shortened.
    Keeps per-minute token use small on free tiers; the agent already acted on the old results."""
    tool_idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    cut = set(tool_idx[:-keep_full]) if len(tool_idx) > keep_full else set()
    out = []
    for i, m in enumerate(messages):
        if i in cut and len(m.get("content") or "") > stub_chars:
            out.append({**m, "content": m["content"][:stub_chars] + " …[older result trimmed]"})
        else:
            out.append(m)
    return out


def model_chain(brief: Brief, engine_pref: str) -> list[tuple[str, str]]:
    """[(engine, model), ...] in the order to try: each active provider's models for this tier, then local."""
    chain: list[tuple[str, str]] = []
    if engine_pref == "ollama":
        return [("ollama", brief.model or OLLAMA_MODEL)]
    providers = active_providers() if engine_pref == "auto" else ([engine_pref] if provider_key(engine_pref) else [])
    pins = [m.strip() for m in (brief.model or "").split(",") if m.strip()]
    for name in providers:
        avail = available_models(name)
        for pin in pins:
            if avail is None or pin in avail:
                chain.append((name, pin))           # pinned model, where this provider serves it
        for m in provider_models(name, brief.tier):
            chain.append((name, m))
    chain.append(("ollama", OLLAMA_MODEL))
    seen, out = set(), []
    for c in chain:
        if c not in seen:
            seen.add(c); out.append(c)
    return out


# --------------------------------------------------------------------------- #
# Agent loop
# --------------------------------------------------------------------------- #
@dataclass
class RunResult:
    agent: str
    task: str
    answer: str
    model_used: str
    turns: int
    tool_calls: list[dict] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    continued_as: Optional[int] = None


class Agent:
    def __init__(self, brief: Brief, registry: "ToolRegistry", engine: str = "auto", depth: int = 0,
                 verbose: bool = True, run_id: Optional[str] = None):
        self.brief = brief
        self.registry = registry
        self.engine = engine
        self.depth = depth
        self.verbose = verbose
        self.run_id = run_id or uuid.uuid4().hex[:8]

    def _emit(self, type: str, **detail):
        emit(type, self.brief.name, self.run_id, self.depth, **detail)

    def _pick(self, chain: list[tuple[str, str]], prefer: Optional[tuple[str, str]] = "first") -> tuple[str, str]:
        """Best usable model: the preferred one if it is not cooling down, else the first remote model
        that is not cooling down; if every remote model is cooling down and the shortest wait is
        under 45s, sleep and reuse it; otherwise the local fallback."""
        now = time.time(); down = provider_down(); pc = persisted_cooldowns()
        cool = lambda c: max(_COOLDOWN.get(c, 0), down.get(c[0], 0), pc.get(f"{c[0]}:{c[1]}", 0))
        usable = [c for c in chain if cool(c) <= now]
        if prefer not in (None, "first") and prefer in usable:
            return prefer
        remote_usable = [c for c in usable if c[0] != "ollama"]
        pins = {m.strip() for m in (self.brief.model or "").split(",") if m.strip()}
        if pins and remote_usable and remote_usable[0][1] not in pins:
            # the strong pinned model is cooling: short wait beats a weaker model for a lead
            pinned = [c for c in chain if c[1] in pins]
            if pinned:
                soonest = min(pinned, key=cool)
                wait = cool(soonest) - now
                if 0 < wait <= 60:
                    self._say(f"waiting {wait:.0f}s for pinned {soonest[0]}:{soonest[1]}")
                    time.sleep(wait + 0.5)
                    return soonest
        if remote_usable:
            return remote_usable[0]
        remote_all = [c for c in chain if c[0] != "ollama"]
        if remote_all:
            soonest = min(remote_all, key=cool)
            wait = cool(soonest) - now
            limit = 180 if self.brief.tier == "lead" else 45
            if wait <= limit:
                self._say(f"all remote models cooling down, waiting {wait:.0f}s for {soonest[0]}:{soonest[1]}")
                time.sleep(max(0.5, wait + 0.5))
                return soonest
        if self.brief.tier == "lead" and remote_all and not self.brief.local_ok and os.environ.get("OFFICE_LEAD_LOCAL_FALLBACK", "0") != "1":
            raise EngineError("no capable model available: every cloud provider is cooling down and lead agents do not run on the local 3B model. Retry later.")
        return usable[-1] if usable else chain[-1]

    def _say(self, msg: str):
        if self.verbose:
            indent = "  " * self.depth
            print(f"{indent}[{self.brief.name}] {msg}", file=sys.stderr, flush=True)

    def _tool_specs(self) -> list[dict]:
        specs = []
        for name in self.brief.tools:
            t = self.registry.get(name)
            if t:
                specs.append({"type": "function", "function": {
                    "name": t.name, "description": t.description, "parameters": t.parameters}})
        if self.brief.delegates:
            specs.append({"type": "function", "function": {
                "name": "delegate",
                "description": "Hand a task to one of your agents and wait for their result. "
                               f"Available: {', '.join(self.brief.delegates)}.",
                "parameters": {"type": "object", "properties": {
                    "agent": {"type": "string", "enum": self.brief.delegates},
                    "task": {"type": "string", "description": "Clear, self-contained instructions, including any context they need."},
                }, "required": ["agent", "task"]}}})
        return specs

    def _lessons(self) -> str:
        """The agent's own most recent reflection lessons, so experience changes behaviour."""
        try:
            ms = _store().recall("", limit=3, tags=["reflection", self.brief.name], kind="lesson", namespace="reflection")
            if not ms:
                return ""
            return "\nLessons from your own recent runs (apply them):\n" + "\n".join(f"- {m.content.split(':', 1)[-1].strip()[:220]}" for m in ms) + "\n"
        except Exception:
            return ""

    def _system_prompt(self) -> str:
        return (
            f"You are '{self.brief.name}', part of the {self.brief.office} office of Pribin's AI agent company.\n"
            f"Today is {time.strftime('%A %d %B %Y')}. Never put past years in search queries.\n"
            f"{self.brief.system}\n{self._lessons()}\n"
            "House rules:\n"
            "- Use brain_recall before starting so you build on what the team already knows.\n"
            "- Use brain_remember for anything another agent or Pribin will need later. One idea per memory.\n"
            "- Never submit applications, send emails, post publicly, trade, or spend money. Prepare, then request_approval. "
            "Exception Pribin pre-approved: committing and pushing code to his own GitHub repos with git_push.\n"
            "- Be concrete and brief. When done, reply with your final result as plain text (no tool call)."
        )

    def run(self, task: str, context: Optional[str] = None) -> RunResult:
        messages = [{"role": "system", "content": self._system_prompt()}]
        if context:
            messages.append({"role": "user", "content": f"Context:\n{context}"})
        messages.append({"role": "user", "content": task})
        tools = self._tool_specs()
        chain = model_chain(self.brief, self.engine)
        engine, model = self._pick(chain)
        calls: list[dict] = []
        seen: dict[tuple, int] = {}
        rl_hits = 0
        nudged_claims = False
        nudged_json = False
        t0 = time.time(); tok_in = tok_out = 0
        self._say(f"task: {task[:120]}")
        self._emit("start", task=task[:300], office=self.brief.office)

        for turn in range(1, MAX_TURNS + 1):
            engine, model = self._pick(chain, prefer=(engine, model))
            attempts = 0
            while True:
                try:
                    self._emit("think", model=f"{engine}:{model}", turn=turn)
                    resp = _call_model(trim_context(messages), tools, model, engine, self.brief.tier)
                    rl_hits = 0
                    break
                except RateLimited as e:
                    ra = str(e)
                    wait = float(ra) if re.fullmatch(r"[\d.]+", ra) else 30.0
                    _COOLDOWN[(engine, model)] = time.time() + wait; persist_cooldown(engine, model, time.time() + wait)
                    rl_hits += 1
                    self._say(f"{engine}:{model} rate-limited for {wait:.0f}s (hit {rl_hits})")
                    if rl_hits >= 8 and chain[-1][0] == "ollama":
                        self._say("too many rate limits this run, finishing on local model")
                        for c in chain:
                            if c[0] != "ollama":
                                _COOLDOWN[c] = time.time() + 120
                    nxt = self._pick(chain, prefer=None)
                    if nxt != (engine, model):
                        engine, model = nxt
                        self._say(f"switching to {engine}:{model}")
                        self._emit("fallback", model=f"{engine}:{model}", reason=f"rate limit, {wait:.0f}s cooldown")
                except EngineError as e:
                    self._say(f"{engine}:{model} error: {str(e)[:120]}")
                    _COOLDOWN[(engine, model)] = time.time() + 120
                    attempts += 1
                    if attempts >= len(chain):
                        self._emit("error", detail=str(e)[:300])
                        raise
                    engine, model = self._pick(chain, prefer=None)
                    self._say(f"switching to {engine}:{model}")
                    self._emit("fallback", model=f"{engine}:{model}", reason=str(e)[:120])

            u = resp.get("usage") or {}
            tok_in += int(u.get("prompt_tokens") or 0); tok_out += int(u.get("completion_tokens") or 0)
            msg = resp["choices"][0]["message"]
            content = (msg.get("content") or "").strip()
            if tok_in + tok_out > RUN_TOKEN_BUDGET and (msg.get("tool_calls") or []):
                self._say(f"token budget {RUN_TOKEN_BUDGET} exceeded after {turn} turns; wrapping up")
                self._emit("fallback", model=f"{engine}:{model}", reason="token budget reached, handing off")
                break
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()  # qwen thinking tags
            tool_calls = msg.get("tool_calls") or []

            looks_like_tool_json = bool(re.match(r'^\s*\{\s*"name"\s*:', content)) or ('"parameters"' in content[:200] and content.lstrip().startswith("{"))
            if not tool_calls and (not content or looks_like_tool_json) and turn < MAX_TURNS and not nudged_json:
                nudged_json = True
                self._say("empty or tool-JSON reply, nudging")
                messages.append({"role": "assistant", "content": content or "(empty)"})
                messages.append({"role": "user", "content": "That was not a valid tool call and not a final answer. Call the tool through the tool interface (not as text), or give your final answer in plain words."})
                continue

            if not tool_calls and turn < MAX_TURNS and not nudged_claims:
                claim = unbacked_claim(content, calls, self.brief.tools)
                if claim:
                    nudged_claims = True
                    self._say(f"answer claims '{claim}' with no matching tool call, sending it back")
                    self._emit("fallback", model=f"{engine}:{model}", reason=f"claimed {claim} without doing it")
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": f"Your reply says you {claim}, but you made no such tool call. "
                                     "Do it now with the right tool, then give the final result again. Never report actions you did not perform."})
                    continue

            if not tool_calls:
                if not content:
                    content = "No final answer was produced. Tool calls made: " + (", ".join(c["tool"] for c in calls) or "none")
                self._say(f"done in {turn} turn(s) on {engine}:{model}")
                secs = round(time.time() - t0, 1)
                self._log(task, content, f"{engine}:{model}", calls, tok_in, tok_out, secs)
                self._emit("done", answer=content[:600], model=f"{engine}:{model}", turns=turn, tool_calls=len(calls),
                           tokens=tok_in + tok_out, seconds=secs)
                self._reflect(task, content, calls, engine, model)
                return RunResult(self.brief.name, task, content, f"{engine}:{model}", turn, calls, tok_in, tok_out, secs)

            messages.append({"role": "assistant", "content": content or None, "tool_calls": tool_calls})
            for tc in tool_calls:
                fn = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                self._say(f"-> {fn}({json.dumps(args)[:100]})")
                if fn == "delegate":
                    self._emit("delegate", to=args.get("agent", ""), task=str(args.get("task", ""))[:300])
                else:
                    self._emit("tool", tool=fn, args=json.dumps(args)[:200])
                try:
                    if fn == "delegate":
                        result = self._delegate(args.get("agent", ""), args.get("task", ""))
                    else:
                        result = self.registry.call(fn, args, agent=self.brief.name)
                except Exception as e:  # tool errors go back to the model, not up the stack
                    result = f"ERROR: {type(e).__name__}: {e}"
                result = str(result)
                self._emit("tool_result", tool=fn, preview=result[:160], ok=not result.startswith("ERROR"))
                if len(result) > TOOL_RESULT_CAP:
                    result = result[:TOOL_RESULT_CAP] + f"\n...[truncated, {len(result)} chars total]"
                sig = (fn, json.dumps(args, sort_keys=True))
                seen[sig] = seen.get(sig, 0) + 1
                if fn in READ_TOOLS and seen[sig] >= 3:
                    result = (f"You already called {fn} with exactly these arguments {seen[sig] - 1} times this run. "
                              "Nothing has changed. Use what you learned and move on to the next step; do not repeat reads.")
                    self._say(f"repeat read blocked: {fn}")
                calls.append({"tool": fn, "args": args, "result_preview": result[:200],
                              "result_full": result[:1800] if fn in READ_TOOLS else result[:300]})
                messages.append({"role": "tool", "tool_call_id": tc.get("id", fn), "name": fn, "content": result})

        self._say("hit max turns, asking for a final answer")
        messages.append({"role": "user", "content": "Stop using tools. Report in this exact shape: DONE: <what is finished and verified>. "
                         "REMAINING: <what is still left, step by step, with file paths>. If nothing is left write REMAINING: none."})
        content = ""
        for attempt in range(len(chain) + 1):
            try:
                self._emit("think", model=f"{engine}:{model}", turn=MAX_TURNS + 1)
                try:
                    resp = _call_model(trim_context(messages), tools, model, engine, self.brief.tier, tool_choice="none")
                except EngineError as e:
                    if not str(e).startswith("400"):
                        raise
                    resp = _call_model(trim_context(messages), [], model, engine, self.brief.tier)
                u = resp.get("usage") or {}
                tok_in += int(u.get("prompt_tokens") or 0); tok_out += int(u.get("completion_tokens") or 0)
                content = (resp["choices"][0]["message"].get("content") or "").strip()
                break
            except RateLimited as e:
                wait = float(str(e)) if re.fullmatch(r"[\d.]+", str(e)) else 30.0
                _COOLDOWN[(engine, model)] = time.time() + wait; persist_cooldown(engine, model, time.time() + wait)
                engine, model = self._pick(chain, prefer=None)
            except EngineError:
                _COOLDOWN[(engine, model)] = time.time() + 120
                engine, model = self._pick(chain, prefer=None)
        if not content:
            content = "Run ended at the turn limit before a final summary could be produced. Tool calls made: " + \
                      ", ".join(c["tool"] for c in calls)
        secs = round(time.time() - t0, 1)
        cont = self._continue(task, content, calls)
        self._log(task, content, f"{engine}:{model}", calls, tok_in, tok_out, secs)
        self._emit("done", answer=content[:600], model=f"{engine}:{model}", turns=MAX_TURNS, tool_calls=len(calls),
                   tokens=tok_in + tok_out, seconds=secs, continued_as=cont)
        return RunResult(self.brief.name, task, content, f"{engine}:{model}", MAX_TURNS, calls, tok_in, tok_out, secs, cont)

    def _continue(self, task: str, content: str, calls: list[dict]) -> Optional[int]:
        """Turn-limit handoff: queue a follow-up task with the REMAINING steps so long work never dies."""
        if self.depth != 0:
            return None
        m = re.search(r"REMAINING:\s*(.+)", content, re.S | re.I)
        remaining = (m.group(1).strip() if m else "").strip()
        if remaining.lower().startswith("none"):
            return None
        if not remaining:
            # the model did not produce the report (often it tried to keep calling tools): continue anyway
            remaining = "The previous hop hit its turn limit without a clear report. Finish every step of the ORIGINAL TASK that is not yet done; start from the handoff notes."
        hop = int((re.search(r"CONTINUATION_HOP:\s*(\d+)", task) or [None, "0"])[1]) + 1
        if hop > 3:
            self._say("continuation chain limit (3) reached; not queuing another")
            return None
        root = re.sub(r"^(Continue:\s*)+", "", task.split("\n", 1)[0])[:90]
        orig = re.search(r"ORIGINAL TASK:\n(.*?)\n\nALREADY DONE", task, re.S)
        original = orig.group(1).strip() if orig else task
        # handoff notes: the useful results this run already fetched, so the next hop reads ONE file instead of re-reading everything
        notes_dir = ROOT / "workspace" / ".handoff"; notes_dir.mkdir(parents=True, exist_ok=True)
        notes_path = notes_dir / f"{self.run_id}.md"
        prev = re.search(r"HANDOFF NOTES: read_file (\.handoff/[\w-]+\.md)", task)
        prev_text = ""
        if prev and (ROOT / "workspace" / prev.group(1)).exists():
            prev_text = (ROOT / "workspace" / prev.group(1)).read_text()[-6000:]
        lines = [f"# Handoff notes for '{root}' (hop {hop})", "", "## What this hop concluded", content[:1500], "", "## Results already fetched (do not fetch again)"]
        for c in calls[-10:]:
            if c["tool"] in READ_TOOLS and c.get("result_full"):
                lines += [f"### {c['tool']} {json.dumps(c['args'])[:160]}", c["result_full"], ""]
        if prev_text:
            lines += ["", "## Notes from the previous hop", prev_text]
        notes_path.write_text("\n".join(lines))
        try:
            t = _store().task_create(
                f"Continue: {root}",
                f"This continues an earlier run that hit its turn limit. CONTINUATION_HOP: {hop}\n\n"
                f"HANDOFF NOTES: read_file .handoff/{self.run_id}.md FIRST (one call). It contains everything already read and concluded. "
                f"Do not re-read those files or repeat those recalls.\n\nORIGINAL TASK (every step must end up done, including any approval/export/notify steps):\n{original[:2000]}\n\n"
                f"ALREADY DONE (do not redo):\n{content[:1200]}\n\nDO NOW:\n{remaining[:1500]}",
                owner=self.brief.name, created_by=self.brief.name, priority=4, source="continuation")
            self._say(f"queued continuation task #{t['id']}")
            return t["id"]
        except Exception as e:
            self._say(f"continuation failed: {e}")
            return None

    def _reflect(self, task: str, answer: str, calls: list[dict], engine: str, model: str):
        """One cheap extra call after a real top-level run: what should this agent do differently next time?"""
        if self.depth != 0 or len(calls) < 3 or os.environ.get("OFFICE_REFLECT", "1") != "1":
            return
        try:
            prompt = [{"role": "system", "content": "You review your own work in one sentence. Be specific and useful, or say NONE."},
                      {"role": "user", "content": f"Task: {task[:600]}\nTools used: {', '.join(c['tool'] for c in calls)[:400]}\n"
                                                  f"Final answer: {answer[:800]}\n\nOne concrete lesson for next time (what to do differently), or NONE."}]
            resp = _call_model(prompt, [], model, engine, "worker")
            lesson = (resp["choices"][0]["message"].get("content") or "").strip()
            if lesson and not lesson.upper().startswith("NONE") and len(lesson) < 400:
                _store().remember(f"Lesson ({self.brief.name}): {lesson}", agent=self.brief.name, kind="lesson", importance=2,
                                      tags=["reflection", self.brief.name], ttl_seconds=60 * 86400, namespace="reflection")
                self._emit("tool", tool="reflect", args=lesson[:160])
        except Exception:
            pass

    def _delegate(self, agent_name: str, task: str) -> str:
        if agent_name not in self.brief.delegates:
            return f"ERROR: you may only delegate to {self.brief.delegates}"
        if self.depth >= 3:
            return "ERROR: delegation depth exceeded"
        sub = Agent(load_brief(agent_name), self.registry, self.engine, depth=self.depth + 1,
                    verbose=self.verbose, run_id=self.run_id)
        res = sub.run(task, context=f"Delegated by {self.brief.name}.")
        return f"[{agent_name} result]\n{res.answer}"

    def _log(self, task: str, answer: str, model: str, calls: list[dict], tok_in: int = 0, tok_out: int = 0, secs: float = 0):
        entry = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "agent": self.brief.name, "model": model, "run_id": self.run_id,
                 "task": task, "answer": answer, "tool_calls": calls, "tokens_in": tok_in, "tokens_out": tok_out, "seconds": secs}
        with open(LOG_DIR / f"{time.strftime('%Y-%m-%d')}.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")


# --------------------------------------------------------------------------- #
# Tool registry
# --------------------------------------------------------------------------- #
@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., Any]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, name: str, description: str, parameters: dict):
        def deco(fn):
            self._tools[name] = Tool(name, description, parameters, fn)
            return fn
        return deco

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def call(self, name: str, args: dict, agent: str = "unknown") -> Any:
        t = self._tools.get(name)
        if not t:
            return f"ERROR: unknown tool {name}"
        # keep only declared parameters; models sometimes send junk keys like "" for no-arg tools
        allowed = set((t.parameters or {}).get("properties", {}).keys())
        clean = {k: v for k, v in (args or {}).items() if k in allowed}
        return t.fn(**clean, _agent=agent) if "_agent" in t.fn.__code__.co_varnames else t.fn(**clean)
