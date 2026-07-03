"""Unit tests for the request-scoped system-prompt assembly."""

from __future__ import annotations

from northwind_copilot.core.prompts import (
    DATA_INTEGRITY_INSTRUCTIONS,
    ECHARTS_INSTRUCTIONS,
    INSIGHTS_INSTRUCTIONS,
    LEAN_LOCAL_PROMPT,
    PRESENTATION_INSTRUCTIONS,
    SYSTEM_PROMPT,
    build_system_prompt,
)


class TestBuildSystemPromptLocal:
    def test_local_uses_lean_prompt(self):
        prompt = build_system_prompt(is_local=True, supports_charts=False)
        assert LEAN_LOCAL_PROMPT.split("\n")[0] in prompt
        # Local always gets presentation + insights, never the heavy analyst rules.
        assert PRESENTATION_INSTRUCTIONS.strip() in prompt
        assert INSIGHTS_INSTRUCTIONS.strip() in prompt
        assert "sql_db_query_checker" not in prompt

    def test_local_never_gets_echarts(self):
        # Even if some caller mistakenly says a local model draws charts.
        prompt = build_system_prompt(is_local=True, supports_charts=True)
        assert ECHARTS_INSTRUCTIONS.strip() not in prompt


class TestBuildSystemPromptCloud:
    def test_cloud_uses_full_prompt_with_data_integrity(self):
        prompt = build_system_prompt(is_local=False, supports_charts=False)
        assert SYSTEM_PROMPT.split("\n")[0] in prompt
        assert DATA_INTEGRITY_INSTRUCTIONS.strip() in prompt
        assert ECHARTS_INSTRUCTIONS.strip() not in prompt

    def test_cloud_with_charts_appends_echarts(self):
        prompt = build_system_prompt(is_local=False, supports_charts=True)
        assert ECHARTS_INSTRUCTIONS.strip() in prompt


class TestUserPreferences:
    def test_preferences_appended(self):
        prompt = build_system_prompt(
            is_local=True, supports_charts=False, user_preferences="Prefer euros."
        )
        assert "Prefer euros." in prompt
        assert "User preferences" in prompt

    def test_blank_preferences_ignored(self):
        prompt = build_system_prompt(
            is_local=False, supports_charts=True, user_preferences="   "
        )
        assert "User preferences" not in prompt
