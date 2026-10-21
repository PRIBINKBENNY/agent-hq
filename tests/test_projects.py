import subprocess, sys, types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "office"))


def test_projects_overview_classifies_folders(tmp_path, monkeypatch):
    import tools
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    monkeypatch.setattr(tools, "brain", types.SimpleNamespace(recent=lambda **k: [types.SimpleNamespace(tags=["project:good"], created_at=1.0, agent="code-builder")]))
    root = tmp_path / "projects"; (root / "stub").mkdir(parents=True); (root / "stub" / "PLAN.md").write_text("plan")
    g = root / "good"; g.mkdir(); (g / "README.md").write_text("# Good\n\nA tool that does a thing.\n"); (g / "a.py").write_text("x"); (g / "b.py").write_text("y"); (g / "tests").mkdir(); (g / "tests" / "test_a.py").write_text("def test(): pass")
    subprocess.run(["git", "init", "-q"], cwd=g, check=True); subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=t", "add", "."], cwd=g, check=True)
    subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=t", "-c", "commit.gpgsign=false", "commit", "-qm", "feat: first"], cwd=g, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/PRIBINKBENNY/good.git"], cwd=g, check=True)
    ps = {p["name"]: p for p in tools.projects_overview()}
    assert ps["stub"]["status"] == "stub" and ps["stub"]["files"] == 1
    g_ = ps["good"]; assert g_["github"] == "https://github.com/PRIBINKBENNY/good" and g_["tests"] and g_["goal"].startswith("A tool") and g_["last_agent"] == "code-builder"
    assert g_["status"] in ("released", "ready to push") and "feat: first" in g_["last_commit"]


def test_only_planners_open_new_project_folders(tmp_path, monkeypatch):
    import tools
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path); (tmp_path / "projects" / "existing").mkdir(parents=True)
    monkeypatch.setattr(tools, "_safe", lambda p: tmp_path / p.removeprefix("workspace/"))
    r = tools.write_file("projects/new-thing/README.md", "hi", _agent="app-developer")
    assert r.startswith("refused") and "existing" in r and not (tmp_path / "projects" / "new-thing").exists()
    assert tools.write_file("projects/existing/notes.md", "hi", _agent="app-developer").startswith("wrote")
    assert tools.write_file("projects/planned-thing/PLAN.md", "plan", _agent="studio-lead").startswith("wrote")
