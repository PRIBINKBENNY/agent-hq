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
    import json
    b = _brain(tmp_path); scheduler._reconciled = True
    tf = tmp_path / "tuning.json"; tf.write_text(json.dumps({"max_parallel": 2})); monkeypatch.setattr(scheduler, "TUNING_FILE", tf); monkeypatch.setenv("OFFICE_MAX_PARALLEL", "2")
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


def test_reconcile_adopts_live_runs_and_requeues_dead_ones(tmp_path, monkeypatch):
    import os
    b = _brain(tmp_path); scheduler._running.clear()
    live = b.task_create("live", "x", owner="job-scout"); dead = b.task_create("dead", "x", owner="tracker")
    for t in (live, dead):
        b.task_update(t["id"], status="running")
    me = os.getpid()
    def fake_pgrep(cmd, **kw):
        class R: stdout = str(me) + "\n" if f"--task-id {live['id']}" in cmd[-1] else ""
        return R()
    monkeypatch.setattr(scheduler.subprocess, "run", fake_pgrep)
    info = scheduler.reconcile(b)
    assert info["adopted"] == [live["id"]] and info["requeued"] == [dead["id"]]
    assert b.task_get(dead["id"])["status"] == "queued" and scheduler.running_ids() == [live["id"]]
    scheduler._running.clear(); scheduler._reconciled = False


def test_pause_stops_new_work_but_reaps_finished(tmp_path, monkeypatch):
    import json
    b = _brain(tmp_path); scheduler._running.clear(); scheduler._reconciled = True
    tf = tmp_path / "tuning.json"; tf.write_text(json.dumps({"max_parallel": 2})); monkeypatch.setattr(scheduler, "TUNING_FILE", tf)
    monkeypatch.setattr(scheduler, "STANDING_FILE", tmp_path / "s.yaml"); monkeypatch.setattr(scheduler, "SCHEDULE_FILE", tmp_path / "j.yaml"); monkeypatch.setattr(scheduler, "STATE_FILE", tmp_path / "st.json")
    monkeypatch.setattr(scheduler, "budget", lambda: {}); monkeypatch.setattr(scheduler, "_notify", lambda *a: None); monkeypatch.setattr(scheduler, "housekeeping", lambda: {}); monkeypatch.setattr(scheduler, "check_approvals", lambda brain: 0)
    monkeypatch.setenv("OFFICE_MAX_PARALLEL", "2")
    class P:
        returncode = None
        def poll(self): return self.returncode
    monkeypatch.setattr(scheduler, "_spawn", lambda task, eng: P())
    b.task_create("t1", "x", owner="job-scout"); b.task_create("t2", "x", owner="tracker")
    assert scheduler.set_paused(True, "test")["paused"] is True
    info = scheduler.tick(b)
    assert info.get("paused") and info["started"] == [] and len(b.task_list(status="queued")) == 2    # nothing starts while paused
    scheduler.set_paused(False)
    info = scheduler.tick(b)
    assert len(info["started"]) == 2
    scheduler._running[info["started"][0]]["proc"].returncode = 0; b.task_update(info["started"][0], status="done")
    scheduler.set_paused(True, "again")
    info = scheduler.tick(b)
    assert info["finished"] == [b.task_list(status="done")[0]["id"]] and info["started"] == []        # paused: reaps, starts nothing
    # timed pause expires
    scheduler.set_paused(True, "timed", hours=-1)
    assert scheduler.paused()["paused"] is False
    scheduler._running.clear()


def test_agents_cannot_resume_unless_their_task_asks(tmp_path, monkeypatch):
    import tools, events, json as _j
    monkeypatch.setattr(scheduler, "TUNING_FILE", tmp_path / "t.json"); (tmp_path / "t.json").write_text(_j.dumps({"paused": True, "paused_reason": "x"}))
    monkeypatch.setattr(events, "EVENTS_FILE", tmp_path / "ev.jsonl")
    events.emit("start", "chief-of-staff", "r1", task="tell every agent to rest")
    assert tools.office_resume("", _agent="chief-of-staff").startswith("refused") and scheduler.paused()["paused"]
    events.emit("start", "chief-of-staff", "r2", task="Pribin says resume the office")
    assert tools.office_resume("", _agent="chief-of-staff").startswith("office resumed") and not scheduler.paused()["paused"]
    scheduler.set_paused(True, "again"); assert tools.office_resume("", _agent="pribin").startswith("office resumed")


def test_scheduler_parallelism_follows_healthy_providers_and_retries_model_outages(tmp_path, monkeypatch):
    import json as _j
    b = _brain(tmp_path); scheduler._running.clear(); scheduler._reconciled = True
    tf = tmp_path / "tuning.json"; tf.write_text(_j.dumps({"max_parallel": 2})); monkeypatch.setattr(scheduler, "TUNING_FILE", tf); monkeypatch.setenv("OFFICE_MAX_PARALLEL", "2")
    monkeypatch.setattr(scheduler, "STANDING_FILE", tmp_path / "s.yaml"); monkeypatch.setattr(scheduler, "SCHEDULE_FILE", tmp_path / "j.yaml"); monkeypatch.setattr(scheduler, "STATE_FILE", tmp_path / "st.json")
    monkeypatch.setattr(scheduler, "_notify", lambda *a: None); monkeypatch.setattr(scheduler, "housekeeping", lambda: {}); monkeypatch.setattr(scheduler, "check_approvals", lambda brain: 0)
    monkeypatch.setattr(scheduler, "budget", lambda: {"cerebras": {"day": 1, "minute": 1, "down": True, "ok": False}, "groq": {"day": 1, "minute": 1, "down": False, "ok": True}})
    class P:
        returncode = None
        def poll(self): return self.returncode
    monkeypatch.setattr(scheduler, "_spawn", lambda task, eng: P())
    for i in range(3): b.task_create(f"t{i}", "x", owner="job-scout")
    info = scheduler.tick(b)
    assert len(info["started"]) == 1                      # only one healthy provider -> one run at a time
    tid = info["started"][0]; scheduler._running[tid]["proc"].returncode = 1
    b.task_update(tid, status="failed", result="EngineError: no capable model available: every cloud provider is cooling down")
    info = scheduler.tick(b)
    t = b.task_get(tid); assert t["status"] == "queued" and "retry_after:" in t["result"]   # retried later, not abandoned
    scheduler._running.clear()


def test_sweep_stale_cancels_scheduler_work_that_waited_too_long(tmp_path, monkeypatch):
    import time
    b = _brain(tmp_path); scheduler._last_sweep = 0
    sched = tmp_path / "schedule.yaml"; sched.write_text("- name: market-pulse\n  every: hourly\n  agent: trader\n  task: x\n")
    monkeypatch.setattr(scheduler, "SCHEDULE_FILE", sched)
    now = time.time()
    old_hourly = b.task_create("Market pulse", "x", owner="trader", created_by="scheduler", source="schedule:market-pulse")
    fresh_hourly = b.task_create("Market pulse", "x", owner="trader", created_by="scheduler", source="schedule:market-pulse")
    old_standing = b.task_create("Networker: one more company", "x", owner="networker", created_by="scheduler", source="standing:networker")
    old_user = b.task_create("Write proposal", "x", owner="proposal-writer", created_by="pribin")
    for t, age_h in ((old_hourly, 4), (fresh_hourly, 1), (old_standing, 40), (old_user, 60)):
        b.conn.execute("UPDATE tasks SET created_at=? WHERE id=?", (now - age_h * 3600, t["id"])); b.conn.commit()
    swept = scheduler.sweep_stale(b, now=now)
    assert sorted(swept) == sorted([old_hourly["id"], old_standing["id"]])
    assert b.task_get(old_hourly["id"])["status"] == "cancelled" and "stale" in b.task_get(old_hourly["id"])["result"]
    assert b.task_get(fresh_hourly["id"])["status"] == "queued" and b.task_get(old_user["id"])["status"] == "queued"
    assert scheduler.sweep_stale(b, now=now + 10) == []          # rate-limited to once a minute


def test_tunnel_watch_restarts_a_dead_quick_tunnel_and_announces_the_new_url(tmp_path, monkeypatch):
    import json
    log = tmp_path / "tunnel.log"; st_file = tmp_path / "st.json"
    monkeypatch.setattr(scheduler, "TUNNEL_LOG", log); monkeypatch.setattr(scheduler, "STATE_FILE", st_file)
    st_file.write_text(json.dumps({"tunnel_url": "https://old-name.trycloudflare.com"}))
    calls = []
    class R: returncode = 0
    monkeypatch.setattr(scheduler.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or R())
    notes = []; monkeypatch.setattr(scheduler, "_notify", lambda t, m: notes.append(m))
    import push; pushed = []
    monkeypatch.setattr(push, "send", lambda title, body, url="/m", tag="hq": pushed.append(url) or {"sent": 1})
    log.write_text("INF Requesting new quick Tunnel on trycloudflare.com...\nINF |  https://old-name.trycloudflare.com  |\nINF Registered tunnel connection connIndex=0\n"
                   + 'ERR Register tunnel error from server side error="Unauthorized: Tunnel not found" connIndex=0\n' * 6)
    s = scheduler.tunnel_status()
    assert s == {"running": True, "url": "https://old-name.trycloudflare.com", "dead": True}
    info = scheduler.tunnel_watch(force=True)
    assert info.get("kicked") and any("kickstart" in c for c in calls) and log.read_text() == ""
    log.write_text('ERR Register tunnel error from server side error="Unauthorized: Tunnel not found"\n' * 6)
    assert scheduler.tunnel_watch(force=True) == {"dead": True}                       # one restart per 10 minutes
    log.write_text("INF Requesting new quick Tunnel on trycloudflare.com...\nINF |  https://new-name.trycloudflare.com  |\nINF Registered tunnel connection connIndex=0\n")
    assert scheduler.tunnel_status()["dead"] is False
    info = scheduler.tunnel_watch(force=True)
    assert info["url"] == "https://new-name.trycloudflare.com" and pushed == ["https://new-name.trycloudflare.com/m"] and notes
    assert json.loads(st_file.read_text())["tunnel_url"] == "https://new-name.trycloudflare.com"
    assert scheduler.tunnel_watch(force=True) == {}                                   # unchanged: quiet


def test_waiting_task_does_not_block_the_rest_of_the_queue(tmp_path, monkeypatch):
    import json, time
    b = _brain(tmp_path); scheduler._reconciled = True; scheduler._running.clear(); scheduler._last_sweep = time.time()
    monkeypatch.setenv("OFFICE_MAX_PARALLEL", "2"); monkeypatch.setattr(scheduler, "MAX_PARALLEL", 2)
    for name in ("STANDING_FILE", "SCHEDULE_FILE"): monkeypatch.setattr(scheduler, name, tmp_path / f"{name}.yaml")
    monkeypatch.setattr(scheduler, "STATE_FILE", tmp_path / "st.json"); monkeypatch.setattr(scheduler, "budget", lambda: {})
    monkeypatch.setattr(scheduler, "_notify", lambda *a: None); monkeypatch.setattr(scheduler, "housekeeping", lambda: {})
    monkeypatch.setattr(scheduler, "check_approvals", lambda brain: 0)
    class FakeProc:
        returncode = None
        def poll(self): return None
    started = []; monkeypatch.setattr(scheduler, "_spawn", lambda task, eng: started.append(task["id"]) or FakeProc())
    waiting = b.task_create("waiting for cooldown", "x", owner="coo", priority=5)
    b.task_update(waiting["id"], result=f"EngineError: no capable model | retry_after:{int(time.time()) + 900}")
    ready = b.task_create("ready", "x", owner="tracker", priority=1)
    info = scheduler.tick(b)
    assert started == [ready["id"]] and b.task_get(waiting["id"])["status"] == "queued"
    scheduler._running.clear()


def test_round_the_clock_filler_and_hourly_pacing(tmp_path, monkeypatch):
    import json, time
    b = _brain(tmp_path)
    sf = tmp_path / "standing.yaml"
    sf.write_text("- name: a\n  agent: tracker\n  every_hours: 6\n  task: x\n- name: b\n  agent: networker\n  every_hours: 12\n  task: y\n- name: w\n  agent: coo\n  every_hours: 168\n  task: z\n")
    tf = tmp_path / "tuning.json"; tf.write_text(json.dumps({"standing_per_hour": 2}))
    monkeypatch.setattr(scheduler, "STANDING_FILE", sf); monkeypatch.setattr(scheduler, "STATE_FILE", tmp_path / "st.json")
    monkeypatch.setattr(scheduler, "TUNING_FILE", tf); monkeypatch.setattr(scheduler, "MAX_PARALLEL", 2)
    monkeypatch.setattr(scheduler, "standing_allowed", lambda: True); monkeypatch.setattr(scheduler, "running_ids", lambda: [])
    now = time.time()
    # nothing is due (all ran 2.5h ago) but the office is idle: the item nearest to due starts early (a: 2.5/6 > 1/3), b and w do not
    scheduler._save_state({"standing:a": now - 2.5 * 3600, "standing:b": now - 2.5 * 3600, "standing:w": now - 100 * 3600})
    assert scheduler.enqueue_standing_work(b) == ["a"]
    # queue is no longer empty -> no further early starts; make it empty again and b is still too fresh (2.5/12 < 1/3)
    for t in b.task_list(status="queued"): b.task_update(t["id"], status="done")
    assert scheduler.enqueue_standing_work(b) == []
    # pacing: with two starts in the last hour the cap (2) is reached even for overdue work
    st = scheduler._load_state(); st["standing:b"] = now - 20 * 3600; st["standing_starts"] = [now - 600, now - 300]; scheduler._save_state(st)
    assert scheduler.enqueue_standing_work(b) == []
    st = scheduler._load_state(); st["standing_starts"] = [now - 3700, now - 300]; scheduler._save_state(st)   # one aged out
    assert scheduler.enqueue_standing_work(b) == ["b"]
    assert len(scheduler._load_state()["standing_starts"]) == 2


def test_capacity_failures_retry_hourly_forever_instead_of_dying(tmp_path, monkeypatch):
    import time
    b = _brain(tmp_path); scheduler._reconciled = True; scheduler._running.clear(); scheduler._last_sweep = time.time()
    monkeypatch.setenv("OFFICE_MAX_PARALLEL", "1"); monkeypatch.setattr(scheduler, "MAX_PARALLEL", 1)
    for name in ("STANDING_FILE", "SCHEDULE_FILE"): monkeypatch.setattr(scheduler, name, tmp_path / f"{name}.yaml")
    monkeypatch.setattr(scheduler, "STATE_FILE", tmp_path / "st.json"); monkeypatch.setattr(scheduler, "budget", lambda: {})
    monkeypatch.setattr(scheduler, "_notify", lambda *a: None); monkeypatch.setattr(scheduler, "housekeeping", lambda: {})
    monkeypatch.setattr(scheduler, "check_approvals", lambda brain: 0)
    class P:
        returncode = None
        def poll(self): return self.returncode
    monkeypatch.setattr(scheduler, "_spawn", lambda task, eng: P())
    t = b.task_create("coo review", "x", owner="coo")
    tid = scheduler.tick(b)["started"][0]
    scheduler._running[tid]["proc"].returncode = 1
    b.task_update(tid, status="failed", result="EngineError: no capable model available" + " | retry_after:1" * 3)   # already retried 3 times
    scheduler.tick(b)
    r = b.task_get(tid)
    assert r["status"] == "queued" and int(r["result"].rsplit("retry_after:", 1)[1]) > time.time() + 3000   # hourly now, never abandoned
    scheduler._running.clear()


def test_tasks_waiting_for_cooldown_do_not_count_as_a_full_queue(tmp_path, monkeypatch):
    import json, time
    b = _brain(tmp_path)
    sf = tmp_path / "standing.yaml"; sf.write_text("- name: a\n  agent: tracker\n  every_hours: 6\n  task: x\n")
    monkeypatch.setattr(scheduler, "STANDING_FILE", sf); monkeypatch.setattr(scheduler, "STATE_FILE", tmp_path / "st.json")
    monkeypatch.setattr(scheduler, "TUNING_FILE", tmp_path / "t.json"); monkeypatch.setattr(scheduler, "MAX_PARALLEL", 2)
    monkeypatch.setattr(scheduler, "standing_allowed", lambda: True); monkeypatch.setattr(scheduler, "running_ids", lambda: [])
    now = time.time()
    for i in range(3):   # three tasks parked until a provider cools down: the office is idle in practice
        t = b.task_create(f"parked {i}", "x", owner="coo"); b.task_update(t["id"], result=f"no capable model | retry_after:{int(now) + 900}")
    scheduler._save_state({"standing:a": now - 3 * 3600})          # not due (6h), but idle -> early start allowed
    assert scheduler.enqueue_standing_work(b) == ["a"]


def test_phone_link_redirector_is_opt_in_and_updates_gh_pages(tmp_path, monkeypatch):
    monkeypatch.delenv("PHONE_LINK_REPO", raising=False)
    assert scheduler.publish_phone_link("https://x.trycloudflare.com")["ok"] is False and scheduler.phone_link_url() == ""
    monkeypatch.setenv("PHONE_LINK_REPO", "Someone/agent-hq")
    assert scheduler.phone_link_url() == "https://someone.github.io/agent-hq/"
    html = scheduler.phone_link_html("https://x.trycloudflare.com")
    assert 'url=https://x.trycloudflare.com/m' in html and "noindex" in html and "token" not in html.lower()
    calls = []
    class R:
        returncode = 0; stdout = "abc123\n"; stderr = ""
    monkeypatch.setattr(scheduler.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or R())
    r = scheduler.publish_phone_link("https://x.trycloudflare.com")
    assert r["ok"] and r["link"] == "https://someone.github.io/agent-hq/"
    put = calls[-1]; assert "PUT" in put and "branch=gh-pages" in put and "sha=abc123" in put and "repos/Someone/agent-hq/contents/index.html" in put
