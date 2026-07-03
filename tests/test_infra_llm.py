"""Unit tests for the chat-model factories (construction only, no calls)."""

from __future__ import annotations

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
