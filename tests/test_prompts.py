"""Unit tests for the request-scoped system-prompt assembly."""

from __future__ import annotations

from northwind_copilot.core.prompts import (
    DATA_INTEGRITY_INSTRUCTIONS,
    ECHARTS_INSTRUCTIONS,
    GENERIC_ANALYST_PROMPT,
    INSIGHTS_INSTRUCTIONS,
    LEAN_LOCAL_PROMPT,
    PRESENTATION_INSTRUCTIONS,
    SCOPE_INSTRUCTIONS,
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

    def test_local_never_gets_scope_rules(self):
        # Scope discipline targets cloud exploration; the lean local prompt
        # stays minimal.
        prompt = build_system_prompt(is_local=True, supports_charts=False)
        assert SCOPE_INSTRUCTIONS.strip() not in prompt


class TestBuildSystemPromptCloud:
    def test_cloud_uses_full_prompt_with_data_integrity(self):
        prompt = build_system_prompt(is_local=False, supports_charts=False)
        assert SYSTEM_PROMPT.split("\n")[0] in prompt
        assert DATA_INTEGRITY_INSTRUCTIONS.strip() in prompt
        assert SCOPE_INSTRUCTIONS.strip() in prompt
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


class TestBuildSystemPromptDataset:
    def test_dataset_uses_generic_base_not_northwind(self):
        prompt = build_system_prompt(
            is_local=False,
            supports_charts=True,
            dataset_summary="Table orders (10 rows):\n  - id (INTEGER)",
            business_context="Revenue = qty * price.",
        )
        # Generic analyst base, not the Northwind-specific system prompt.
        assert GENERIC_ANALYST_PROMPT.split("\n")[0] in prompt
        assert "Northwind" not in prompt
        # The dataset's schema summary and business context are injected.
        assert "Table orders" in prompt
        assert "Revenue = qty * price." in prompt
        # Shared instruction blocks still apply.
        assert DATA_INTEGRITY_INSTRUCTIONS.strip()[:20] in prompt
        assert ECHARTS_INSTRUCTIONS.strip()[:20] in prompt

    def test_dataset_without_business_context(self):
        prompt = build_system_prompt(
            is_local=False,
            supports_charts=False,
            dataset_summary="Table t (1 rows):\n  - a (TEXT)",
        )
        assert "Business context" not in prompt
        assert "Table t" in prompt

    def test_none_dataset_preserves_poc_prompt(self):
        # The POC path (no dataset) must be byte-identical to before.
        poc = build_system_prompt(is_local=False, supports_charts=True)
        assert SYSTEM_PROMPT in poc
        assert "Northwind" in poc
