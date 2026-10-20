import os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "office"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain"))
import pytest


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "vault"; v.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT", str(v))
    import obsidian
    monkeypatch.setattr(obsidian, "STATE", tmp_path / "state.json")
    return v


def _brain(tmp_path):
    from store import BrainStore
    return BrainStore(db_path=str(tmp_path / "b.sqlite"))


def test_export_memories_writes_notes_with_frontmatter_and_links(vault, tmp_path):
    import obsidian
    b = _brain(tmp_path)
    m = b.remember("Applied to Trainline for ML Engineer", agent="job-scout", kind="job", tags=["company:trainline", "status:applied"])
    n = obsidian.export_memories(b, since=0)
    assert n == 1
    files = list((vault / "Agent HQ" / "Brain" / "Jobs").glob(f"{m.id} *.md"))
    assert len(files) == 1
    text = files[0].read_text()
    assert text.startswith("---\n") and "kind: job" in text and '"company/trainline"' in text
    assert "[[Agents/job-scout]]" in text and "[[trainline]]" in text
    # incremental: nothing newer than now -> nothing written again
    assert obsidian.export_memories(b, since=time.time() + 1) == 0


def test_inbox_note_goes_to_brain_and_moves_to_done(vault, tmp_path):
    import obsidian
    b = _brain(tmp_path)
    inbox = vault / "Agent HQ" / "Inbox"; inbox.mkdir(parents=True)
    (inbox / "Client idea.md").write_text("---\nkind: lead\ntags: [freelance]\nimportance: 5\n---\nA letting agent in Hackney wants a chatbot #lead/hackney\n")
    stored = obsidian.ingest_inbox(b)
    assert len(stored) == 1 and "memory #" in stored[0]
    assert not (inbox / "Client idea.md").exists() and list((inbox / "Done").glob("* Client idea.md"))
    m = b.recent(limit=1, namespace="*")[0]
    assert m.kind == "lead" and m.agent == "pribin" and m.importance == 5
    assert {"obsidian", "from-pribin", "freelance", "lead/hackney"} <= set(m.tags)
    assert "letting agent in Hackney" in m.content
    # a second run stores nothing and the README is present
    assert obsidian.ingest_inbox(b) == [] and (inbox / "README.md").exists()


def test_title_strips_approval_prefix_and_unsafe_chars(vault):
    import obsidian
    class M: content = "PENDING APPROVAL from proposal-writer: Quote for Acme: £450 / site?\nbody"
    assert obsidian._title(M()) == "Quote for Acme £450 site"


def test_missing_vault_reports_error(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path / "nope"))
    import obsidian
    monkeypatch.setattr(obsidian, "STATE", tmp_path / "state.json")
    assert "vault not found" in obsidian.sync()["error"]
