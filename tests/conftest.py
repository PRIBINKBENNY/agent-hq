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
    yield
