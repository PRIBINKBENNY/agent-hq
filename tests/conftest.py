"""Keep the test suite out of the real office: events, logs and handoff notes go to a temp dir."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office")); sys.path.insert(0, str(ROOT / "brain"))


@pytest.fixture(autouse=True)
def _isolate_side_effects(tmp_path, monkeypatch):
    import events
    monkeypatch.setattr(events, "EVENTS_FILE", tmp_path / "events.jsonl")
    monkeypatch.setenv("OFFICE_REFLECT", "0")
    monkeypatch.delenv("OFFICE_LEAD_LOCAL_FALLBACK", raising=False)   # .env may switch it on; tests assert the strict default
    import scheduler
    monkeypatch.setattr(scheduler, "TUNNEL_LOG", tmp_path / "tunnel.log")   # never look at (or restart) the real tunnel from a test
    import runtime
    monkeypatch.setattr(runtime, "LOG_DIR", tmp_path / "logs"); (tmp_path / "logs").mkdir(exist_ok=True)   # run logs stay out of office/logs
    # live provider cooldowns and parked keys must not leak into tests (a real Groq rate limit failed the scheduler tests)
    monkeypatch.setattr(runtime, "COOL_FILE", tmp_path / "cool.json"); monkeypatch.setattr(runtime, "PROVIDER_DOWN_FILE", tmp_path / "down.json")
    monkeypatch.setattr(runtime, "DOWN_HIST_FILE", tmp_path / "down_hist.json"); runtime._COOLDOWN.clear()
    monkeypatch.setattr(scheduler, "TUNING_FILE", tmp_path / "tuning.json")   # tests run on default knobs, not Pribin's live settings
    monkeypatch.setattr(scheduler, "free_memory_gb", lambda: 99.0)            # the memory brake reads the real Mac otherwise
    yield
