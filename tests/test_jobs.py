import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "office")); sys.path.insert(0, str(ROOT / "brain"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    import tools, store, dashboard
    class NoEmbed(store.Embedder):
        def __init__(self): self.model_name = "none"; self.available = False; self._model = None
    b = store.BrainStore(tmp_path / "b.db", embedder=NoEmbed())
    monkeypatch.setattr(tools, "brain", b); monkeypatch.setattr(dashboard, "brain", b)
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path); monkeypatch.setattr(dashboard, "WORKSPACE", tmp_path)
    return tools, dashboard, b, tmp_path


def test_log_job_dedupes_and_structures(env):
    tools, dashboard, b, ws = env
    r = tools.log_job("Junior ML Engineer", "Trainline", "https://x.test/jobs/1", 5, needs="Python, PyTorch", posted="2026-10-13", _agent="job-scout")
    assert r.startswith("job #")
    assert tools.log_job("Junior ML Engineer", "Trainline", "https://x.test/jobs/1", 5).startswith("already logged")
    m = b.recent(limit=1, kind="job")[0]
    assert m.meta["company"] == "Trainline" and m.meta["slug"] == "trainline" and m.meta["fit"] == 5 and "company:trainline" in m.tags and "status:found" in m.tags
    assert tools.job_status(m.id, "nonsense").startswith("refused")
    assert tools.job_status(m.id, "applied", _agent="pribin").endswith("applied")
    assert b.get(m.id).meta["status"] == "applied" and "status:applied" in b.get(m.id).tags


def test_jobs_view_links_applications_and_orders_by_stage(env):
    tools, dashboard, b, ws = env
    tools.log_job("Role A", "Acme", "https://x.test/a", 4)
    tools.log_job("Role B", "Beta Ltd", "https://x.test/b", 5)
    (ws / "applications" / "acme" / "role-a").mkdir(parents=True)
    (ws / "applications" / "acme" / "role-a" / "cv.md").write_text("cv"); (ws / "applications" / "acme" / "role-a" / "cv.pdf").write_bytes(b"%PDF")
    acme = [m for m in b.recent(limit=5, kind="job") if m.meta["company"] == "Acme"][0]
    tools.job_status(acme.id, "applied")
    jobs = dashboard._jobs()
    assert jobs[0]["company"] == "Acme" and jobs[0]["status"] == "applied"                 # applied sorts before found
    assert jobs[0]["application"]["pdf"].endswith("cv.pdf") and jobs[0]["url"] == "https://x.test/a"
    assert jobs[1]["company"] == "Beta Ltd" and jobs[1]["application"] is None and jobs[1]["fit"] == 5
