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
        {"name": "scan", "every": "daily", "at": "00:00", "window_hours": 24, "agent": "job-scout", "task": "scan"},
        {"name": "digest", "every": "daily", "at": "00:00", "window_hours": 24, "after": "scan", "agent": "chief-of-staff", "task": "digest"}]))
    monkeypatch.setattr(scheduler, "SCHEDULE_FILE", sched); monkeypatch.setattr(scheduler, "STATE_FILE", state)
    assert scheduler.enqueue_due_jobs(brain) == ["scan"]          # digest held back
    t = brain.task_claim_next(); brain.task_update(t["id"], status="done", result="ok")
    assert scheduler.enqueue_due_jobs(brain) == ["digest"]        # now released
    assert scheduler.enqueue_due_jobs(brain) == []                # once per day


def test_firing_window_skips_late_wake():
    job = {"every": "weekdays", "at": "10:00"}
    assert scheduler._due(job, None, datetime(2026, 10, 14, 11, 0)) is True       # within 6h window
    assert scheduler._due(job, None, datetime(2026, 10, 14, 23, 2)) is False      # Mac woke at 23:02: wait for tomorrow
    assert scheduler._due({**job, "window_hours": 14}, None, datetime(2026, 10, 14, 23, 2)) is True


def test_housekeeping_removes_old_logs(tmp_path, monkeypatch):
    import os, time as _t
    monkeypatch.setattr(scheduler, "LOG_DIR", tmp_path); monkeypatch.setattr(scheduler, "ROOT", tmp_path); scheduler._last_housekeeping = 0
    old = tmp_path / "task-1.log"; old.write_text("x"); os.utime(old, (_t.time() - 20 * 86400,) * 2)
    new = tmp_path / "task-2.log"; new.write_text("y")
    (tmp_path / "workspace" / ".handoff").mkdir(parents=True); h = tmp_path / "workspace" / ".handoff" / "a.md"; h.write_text("h"); os.utime(h, (_t.time() - 10 * 86400,) * 2)
    r = scheduler.housekeeping()
    assert r["task_logs"] == 1 and r["handoff"] == 1 and new.exists() and not old.exists() and not h.exists()
    assert scheduler.housekeeping() == {}     # rate-limited to every 6 hours


def _brain(tmp_path):
    from store import BrainStore, Embedder
    class NoEmbed(Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    return BrainStore(tmp_path / "b.db", embedder=NoEmbed())


def test_standing_work_fills_the_queue_and_respects_intervals(tmp_path, monkeypatch):
    import yaml
    b = _brain(tmp_path)
    sf = tmp_path / "standing.yaml"; sf.write_text(yaml.safe_dump([
        {"name": "a", "agent": "job-scout", "every_hours": 4, "task": "scout"},
        {"name": "b", "agent": "tracker", "every_hours": 6, "task": "track"},
        {"name": "night", "agent": "tester", "every_hours": 1, "hours": "01-02", "task": "tests"}]))
    monkeypatch.setattr(scheduler, "STANDING_FILE", sf); monkeypatch.setattr(scheduler, "STATE_FILE", tmp_path / "st.json")
    monkeypatch.setattr(scheduler, "MAX_PARALLEL", 2); monkeypatch.setattr(scheduler, "budget", lambda: {})
    class Noon:  # fixed time: 12:00 on a Wednesday
        @staticmethod
        def now(): return datetime(2026, 10, 14, 12, 0)
    monkeypatch.setattr(scheduler, "datetime", Noon)
    assert sorted(scheduler.enqueue_standing_work(b)) == ["a", "b"]      # both overdue (never ran); 'night' outside its window
    assert scheduler.enqueue_standing_work(b) == []                        # queue already has MAX_PARALLEL items
    for t in b.task_list(status="queued"):
        b.task_update(t["id"], status="done")
    assert scheduler.enqueue_standing_work(b) == []                        # intervals not yet elapsed


def test_budget_governor_blocks_standing_work_when_low(monkeypatch):
    monkeypatch.setattr(scheduler, "budget", lambda: {"cerebras": {"day": 0.1, "minute": 0.9, "ok": False}, "groq": {"day": 0.2, "minute": 0.5, "ok": False}})
    assert scheduler.standing_allowed() is False
    monkeypatch.setattr(scheduler, "budget", lambda: {"cerebras": {"day": 0.1, "minute": 0.9, "ok": False}, "groq": {"day": 0.8, "minute": 0.5, "ok": True}})
    assert scheduler.standing_allowed() is True
    assert scheduler.pick_engine() == "groq"                               # only the healthy provider gets new runs


def test_tick_runs_up_to_max_parallel(tmp_path, monkeypatch):
    b = _brain(tmp_path)
    monkeypatch.setattr(scheduler, "MAX_PARALLEL", 2); monkeypatch.setattr(scheduler, "STANDING_FILE", tmp_path / "none.yaml")
    monkeypatch.setattr(scheduler, "SCHEDULE_FILE", tmp_path / "none2.yaml"); monkeypatch.setattr(scheduler, "STATE_FILE", tmp_path / "st.json")
    monkeypatch.setattr(scheduler, "budget", lambda: {}); monkeypatch.setattr(scheduler, "_notify", lambda *a: None)
    monkeypatch.setattr(scheduler, "housekeeping", lambda: {}); monkeypatch.setattr(scheduler, "check_approvals", lambda brain: 0)
    scheduler._running.clear()
    class FakeProc:
        def __init__(self): self.returncode = None
        def poll(self): return self.returncode
    spawned = []
    monkeypatch.setattr(scheduler, "_spawn", lambda task, eng: spawned.append(task["id"]) or FakeProc())
    for i in range(3):
        b.task_create(f"t{i}", "x", owner="job-scout", priority=3 - i)
    info = scheduler.tick(b)
    assert len(info["started"]) == 2 and len(scheduler.running_ids()) == 2 and len(b.task_list(status="queued")) == 1
    scheduler._running[spawned[0]]["proc"].returncode = 0                    # one finishes (run.py would have marked it done)
    b.task_update(spawned[0], status="done")
    info = scheduler.tick(b)
    assert info["finished"] == [spawned[0]] and len(info["started"]) == 1 and len(scheduler.running_ids()) == 2
    scheduler._running.clear()
