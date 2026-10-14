import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office"))
sys.path.insert(0, str(ROOT / "brain"))

import events  # noqa: E402
import scheduler  # noqa: E402


def test_events_emit_and_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(events, "EVENTS_FILE", tmp_path / "ev.jsonl")
    for i in range(5):
        events.emit("think", "a", "run1", 0, turn=i)
    tail = events.read_tail(3)
    assert [e["turn"] for e in tail] == [2, 3, 4]
    assert tail[-1]["agent"] == "a" and tail[-1]["run_id"] == "run1"


def test_schedule_due_logic():
    job = {"every": "daily", "at": "08:00"}
    morning = datetime(2026, 10, 14, 9, 0)
    assert scheduler._due(job, None, morning) is True
    assert scheduler._due(job, None, datetime(2026, 10, 14, 7, 59)) is False
    ran_today = datetime(2026, 10, 14, 8, 5).timestamp()
    assert scheduler._due(job, ran_today, morning) is False
    ran_yesterday = datetime(2026, 10, 13, 8, 5).timestamp()
    assert scheduler._due(job, ran_yesterday, morning) is True
    assert scheduler._due({"every": "weekdays", "at": "08:00"}, None, datetime(2026, 10, 17, 9, 0)) is False  # Saturday
    assert scheduler._due({"every": "hourly"}, morning.timestamp() - 3601, morning) is True


def test_schedule_file_parses():
    import yaml
    jobs = yaml.safe_load((ROOT / "office" / "schedule.yaml").read_text())
    assert jobs and all("name" in j and (("agent" in j and "task" in j) or "command" in j) for j in jobs)


def test_weekly_due_and_after_dependency(tmp_path, monkeypatch):
    sunday_8pm = datetime(2026, 10, 18, 20, 5)      # a Sunday
    job = {"every": "weekly", "day": "sunday", "at": "20:00"}
    assert scheduler._due(job, None, sunday_8pm) is True
    assert scheduler._due(job, None, datetime(2026, 10, 17, 20, 5)) is False          # Saturday
    assert scheduler._due(job, (sunday_8pm.timestamp() - 2 * 86400), sunday_8pm) is False  # ran 2 days ago

    # dependency: morning-digest waits for morning-job-scan's task to finish
    import yaml
    from store import BrainStore, Embedder
    class NoEmbed(Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    brain = BrainStore(tmp_path / "b.db", embedder=NoEmbed())
    sched = tmp_path / "s.yaml"; state = tmp_path / "state.json"
    sched.write_text(yaml.safe_dump([
        {"name": "scan", "every": "daily", "at": "00:00", "agent": "job-scout", "task": "scan"},
        {"name": "digest", "every": "daily", "at": "00:00", "after": "scan", "agent": "chief-of-staff", "task": "digest"}]))
    monkeypatch.setattr(scheduler, "SCHEDULE_FILE", sched); monkeypatch.setattr(scheduler, "STATE_FILE", state)
    assert scheduler.enqueue_due_jobs(brain) == ["scan"]          # digest held back
    t = brain.task_claim_next(); brain.task_update(t["id"], status="done", result="ok")
    assert scheduler.enqueue_due_jobs(brain) == ["digest"]        # now released
    assert scheduler.enqueue_due_jobs(brain) == []                # once per day
