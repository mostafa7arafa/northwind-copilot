"""Unit tests for the per-request engine builder."""

from __future__ import annotations

import pytest
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from northwind_copilot.infra.llm import build_primary_model
from northwind_copilot.query.agent_factory import (
    EngineConfig,
    build_agent_for,
    build_model,
)


class TestEngineConfig:
    def test_local_flags(self):
        cfg = EngineConfig(provider="ollama", model="gemma4-12b")
        assert cfg.is_local is True
        assert cfg.supports_charts is False

    def test_cloud_flags(self):
        assert EngineConfig(provider="openai", model="gpt-4.1-mini").supports_charts
        assert EngineConfig(provider="openrouter", model="x").supports_charts
        assert not EngineConfig(provider="openai", model="x").is_local


class TestBuildModel:
    def test_ollama(self):
        model = build_model(EngineConfig(provider="ollama", model="gemma4-12b"))
        assert isinstance(model, ChatOllama)

    def test_openai(self):
        model = build_model(
            EngineConfig(provider="openai", model="gpt-4.1-mini", api_key="sk-x")
        )
        assert isinstance(model, ChatOpenAI)

    def test_openrouter_sets_base_url(self):
        model = build_model(
            EngineConfig(provider="openrouter", model="x", api_key="sk-x")
        )
        assert isinstance(model, ChatOpenAI)
        assert "openrouter.ai" in str(model.openai_api_base)

    def test_unknown_provider_raises(self):
        cfg = EngineConfig(provider="mystery", model="x")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="Unknown provider"):
            build_model(cfg)


class TestBuildAgentFor:
    def test_local_drops_query_checker_tool(self):
        cfg = EngineConfig(provider="ollama", model="gemma4-12b")
        agent = build_agent_for(cfg, fallback=build_primary_model())
        assert hasattr(agent, "astream")

    def test_cloud_agent_builds(self):
        cfg = EngineConfig(provider="openai", model="gpt-4.1-mini", api_key="sk-x")
        agent = build_agent_for(cfg, user_preferences="Use euros.")
        assert hasattr(agent, "astream")
