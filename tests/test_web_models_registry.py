"""Unit tests for the model registry (Ollama daemon + provider assembly faked)."""

from __future__ import annotations

import asyncio

import httpx

from northwind_copilot.web import models_registry


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _FakeClient:
    def __init__(self, payload=None, exc=None, **kwargs):
        self._payload = payload
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        if self._exc is not None:
            raise self._exc
        return _FakeResp(self._payload)


class TestListOllamaModels:
    def test_maps_installed_models(self, monkeypatch):
        payload = {"models": [{"name": "gemma4-12b", "size": 8_000_000_000}, {}]}
        monkeypatch.setattr(
            models_registry.httpx,
            "AsyncClient",
            lambda **k: _FakeClient(payload=payload),
        )
        out = asyncio.run(models_registry.list_ollama_models())
        assert out == [{"id": "gemma4-12b", "label": "gemma4-12b", "note": "8.0 GB"}]

    def test_unreachable_daemon_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            models_registry.httpx,
            "AsyncClient",
            lambda **k: _FakeClient(exc=httpx.ConnectError("down")),
        )
        assert asyncio.run(models_registry.list_ollama_models()) == []


class TestListAllProviders:
    def test_shape_and_key_flags(self, monkeypatch):
        async def _fake_ollama():
            return [{"id": "m", "label": "m", "note": "local"}]

        monkeypatch.setattr(models_registry, "list_ollama_models", _fake_ollama)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        out = asyncio.run(models_registry.list_all_providers())
        assert out["local"]["available"] is True
        providers = {c["provider"] for c in out["cloud"]}
        assert providers == {"openai", "openrouter"}
        openai = next(c for c in out["cloud"] if c["provider"] == "openai")
        assert openai["needs_key"] is True  # no env key set

    def test_cloud_defaults_and_current_openai_models(self, monkeypatch):
        async def _fake_ollama():
            return []

        monkeypatch.setattr(models_registry, "list_ollama_models", _fake_ollama)
        out = asyncio.run(models_registry.list_all_providers())
        expected = [
            "gpt-6-luna",
            "gpt-6.1-terra",
            "gpt-6.1-sol",
            "gpt-6-astra",
        ]
        for provider in out["cloud"]:
            prefix = "openai/" if provider["provider"] == "openrouter" else ""
            ids = [model["id"] for model in provider["models"]]
            assert ids[:4] == [prefix + model for model in expected]
            assert len(ids) == len(set(ids))
            assert prefix + "gpt-4.1-mini" in ids
