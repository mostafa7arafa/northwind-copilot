"""Unit tests for the chat-model factories (construction only, no calls)."""

from __future__ import annotations

from dataclasses import replace

from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from northwind_copilot.core.config import settings
from northwind_copilot.infra.llm import build_fallback_model, build_primary_model


class TestPrimaryModel:
    def test_builds_deterministic_ollama(self):
        model = build_primary_model()
        assert isinstance(model, ChatOllama)
        assert model.model == settings.primary_model
        assert model.temperature == settings.temperature


class TestFallbackModel:
    def test_none_without_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert build_fallback_model() is None

    def test_openai_with_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
        model = build_fallback_model()
        assert isinstance(model, ChatOpenAI)
        assert model.model_name == settings.fallback_model

    def test_default_gpt6_disables_reasoning(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
        from northwind_copilot.web.app import _build_fallback

        for model in (build_fallback_model(), _build_fallback()):
            assert isinstance(model, ChatOpenAI)
            assert settings.fallback_model == "gpt-6-luna"
            assert model.model_name == "gpt-6-luna"
            assert model.temperature == settings.temperature
            assert model._default_params["reasoning_effort"] == "none"

    def test_non_gpt6_omits_reasoning_effort(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
        patched = replace(settings, fallback_model="gpt-4.1-mini")
        monkeypatch.setattr("northwind_copilot.infra.llm.settings", patched)
        monkeypatch.setattr("northwind_copilot.web.app.settings", patched)
        from northwind_copilot.web.app import _build_fallback

        for model in (build_fallback_model(), _build_fallback()):
            assert isinstance(model, ChatOpenAI)
            assert model.model_name == "gpt-4.1-mini"
            assert model.temperature == settings.temperature
            assert "reasoning_effort" not in model._default_params
