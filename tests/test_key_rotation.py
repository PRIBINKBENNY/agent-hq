import sys, types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "office"))
import pytest


def test_provider_keys_reads_numbered_and_comma_separated(monkeypatch):
    import runtime
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY", "k1"); monkeypatch.setenv("OLLAMA_CLOUD_API_KEY_2", "k2, k3"); monkeypatch.setenv("OLLAMA_CLOUD_API_KEY_3", "")
    assert runtime.provider_keys("ollamacloud") == ["k1", "k2", "k3"]
    runtime._KEY_COOL.clear(); assert runtime.provider_key("ollamacloud") == "k1"
    runtime.rest_key("ollamacloud", "k1", 60); assert runtime.provider_key("ollamacloud") == "k2"
    runtime._KEY_COOL.clear()


def test_rate_limited_key_rotates_to_backup(monkeypatch):
    import runtime
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY", "k1"); monkeypatch.setenv("OLLAMA_CLOUD_API_KEY_2", "k2"); runtime._KEY_COOL.clear()
    monkeypatch.setattr(runtime, "available_models", lambda name: None)
    calls = []
    def fake_chat(url, headers, payload, timeout=120, provider="", model=""):
        calls.append(headers.get("Authorization"))
        if headers.get("Authorization") == "Bearer k1":
            raise runtime.RateLimited("42")
        return {"choices": [{"message": {"content": "ok", "role": "assistant"}}], "usage": {}}
    monkeypatch.setattr(runtime, "_chat", fake_chat)
    monkeypatch.setattr(runtime, "emit", lambda *a, **k: None)
    r = runtime._call_model([{"role": "user", "content": "hi"}], [], "gpt-oss:120b", "ollamacloud", "worker")
    assert r["choices"][0]["message"]["content"] == "ok" and calls == ["Bearer k1", "Bearer k2"]
    assert runtime._KEY_COOL[("ollamacloud", "k1")] > 0 and runtime.provider_key("ollamacloud") == "k2"
    # both keys limited -> the error propagates with the last wait
    calls.clear(); monkeypatch.setattr(runtime, "_chat", lambda *a, **k: (_ for _ in ()).throw(runtime.RateLimited("7")))
    runtime._KEY_COOL.clear()
    with pytest.raises(runtime.RateLimited):
        runtime._call_model([{"role": "user", "content": "hi"}], [], "gpt-oss:120b", "ollamacloud", "worker")
    runtime._KEY_COOL.clear()


def test_rest_key_persists_by_index_and_key_state_reports_it(monkeypatch, tmp_path):
    import runtime
    monkeypatch.setattr(runtime, "KEY_COOL_FILE", tmp_path / "key_cool.json"); runtime._KEY_COOL.clear()
    monkeypatch.setenv("GROQ_API_KEY", "g1"); monkeypatch.setenv("GROQ_API_KEY_2", "g2")
    for i in (3, 4, 5): monkeypatch.delenv(f"GROQ_API_KEY_{i}", raising=False)   # the real .env may hold more backups
    runtime.rest_key("groq", "g1", 120)
    import json; data = json.loads((tmp_path / "key_cool.json").read_text())
    assert list(data) == ["groq:0"] and "g1" not in (tmp_path / "key_cool.json").read_text()
    runtime._KEY_COOL.clear()                                   # another process would start empty: the file still says key 1 rests
    assert runtime.provider_key("groq") == "g2"
    st = runtime.key_state()["groq"]; assert st["keys"] == 2 and st["active"] == 2 and st["resting"][0]["key"] == 1 and 100 < st["resting"][0]["seconds"] <= 120
    runtime._KEY_COOL.clear()
