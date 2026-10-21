import sys, types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "office"))
import pytest


def test_local_model_off_removes_ollama_from_every_chain(monkeypatch):
    import runtime
    monkeypatch.setattr(runtime, "active_providers", lambda: ["groq"])
    monkeypatch.setattr(runtime, "available_models", lambda name: None)
    monkeypatch.setattr(runtime, "provider_models", lambda name, tier: ["openai/gpt-oss-20b"])
    monkeypatch.setattr(runtime, "eval_scores", lambda: {})
    brief = types.SimpleNamespace(model="", tier="worker")
    assert ("ollama", runtime.OLLAMA_MODEL) in runtime.model_chain(brief, "auto")
    monkeypatch.setenv("OFFICE_LOCAL_MODEL", "0")
    chain = runtime.model_chain(brief, "auto")
    assert chain and all(eng != "ollama" for eng, _ in chain)
    with pytest.raises(runtime.EngineError):
        runtime.model_chain(brief, "ollama")
