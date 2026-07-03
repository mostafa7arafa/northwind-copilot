"""Endpoint tests for the FastAPI app (dependencies faked, no agent runs)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from northwind_copilot.web import app as app_module
from northwind_copilot.web.app import app

client = TestClient(app)


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_models(monkeypatch):
    async def _fake_registry():
        return {"local": {"available": False, "models": []}, "cloud": []}

    monkeypatch.setattr(app_module, "list_all_providers", _fake_registry)
    resp = client.get("/api/models")
    assert resp.status_code == 200
    assert resp.json()["local"]["available"] is False


def test_get_preferences(monkeypatch):
    monkeypatch.setattr(app_module, "load_preferences", lambda: "Prefer euros.")
    resp = client.get("/api/preferences")
    assert resp.json() == {"preferences": "Prefer euros."}


def test_put_preferences(monkeypatch):
    captured = {}

    def _save(text):
        captured["text"] = text
        return text.strip()

    monkeypatch.setattr(app_module, "save_preferences", _save)
    resp = client.post("/api/preferences", json={"preferences": "  hi  "})
    assert resp.json() == {"preferences": "hi"}
    assert captured["text"] == "  hi  "


def test_chat_streams_events(monkeypatch):
    async def _fake_stream(**kwargs):
        yield {"type": "engine", "engine": "local"}
        yield {"type": "final", "text": "done"}
        yield {"type": "done"}

    monkeypatch.setattr(app_module, "stream_chat", _fake_stream)
    monkeypatch.setattr(app_module, "load_preferences", lambda: "")
    monkeypatch.setattr(app_module, "_build_fallback", lambda: None)

    resp = client.post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "provider": "ollama",
            "model": "gemma4-12b",
        },
    )
    assert resp.status_code == 200
    body = resp.text
    assert "data:" in body
    assert '"type": "final"' in body
    assert '"type": "done"' in body


@pytest.mark.parametrize("has_key", [True, False])
def test_build_fallback_respects_key(monkeypatch, has_key):
    if has_key:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert app_module._build_fallback() is not None
    else:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert app_module._build_fallback() is None
