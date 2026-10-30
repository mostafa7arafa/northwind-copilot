"""Unit tests for configuration and the assembled system prompt."""

from __future__ import annotations

from northwind_copilot.core.config import Settings, _env, _env_bool, settings
from northwind_copilot.core.definitions import MARGIN_RATE, REVENUE_SQL
from northwind_copilot.core.prompts import SYSTEM_PROMPT, build_system_prompt


class TestEnv:
    def test_returns_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("NW_TEST_VAR", raising=False)
        assert _env("NW_TEST_VAR", "fallback") == "fallback"

    def test_returns_default_when_empty(self, monkeypatch):
        monkeypatch.setenv("NW_TEST_VAR", "")
        assert _env("NW_TEST_VAR", "fallback") == "fallback"

    def test_returns_value_when_set(self, monkeypatch):
        monkeypatch.setenv("NW_TEST_VAR", "custom")
        assert _env("NW_TEST_VAR", "fallback") == "custom"


class TestEnvBool:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("NW_TEST_BOOL", raising=False)
        assert _env_bool("NW_TEST_BOOL", True) is True
        assert _env_bool("NW_TEST_BOOL", False) is False

    def test_truthy_values(self, monkeypatch):
        for v in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("NW_TEST_BOOL", v)
            assert _env_bool("NW_TEST_BOOL", False) is True

    def test_falsey_values(self, monkeypatch):
        for v in ("0", "false", "no", "off", "nonsense"):
            monkeypatch.setenv("NW_TEST_BOOL", v)
            assert _env_bool("NW_TEST_BOOL", True) is False


class TestSettings:
    def test_defaults(self):
        assert settings.primary_model == "gemma4-12b"
        assert settings.fallback_model == "gpt-4.1-mini"
        assert settings.temperature == 0.0
        assert settings.sample_rows_in_table_info == 0

    def test_local_workspace_defaults(self):
        assert settings.dataset_data_dir == "data/datasets"
        assert settings.workspace_db_url == "sqlite+aiosqlite:///data/workspace.sqlite"
        for removed in ("hosted_mode", "app_db_url", "jwt_secret", "billing_provider"):
            assert not hasattr(settings, removed)

    def test_is_frozen(self):
        import dataclasses

        assert isinstance(settings, Settings)
        try:
            settings.temperature = 0.5  # type: ignore[misc]
        except dataclasses.FrozenInstanceError:
            return
        raise AssertionError("Settings should be immutable")


class TestSystemPrompt:
    def test_contains_core_rules(self):
        assert "sql_db_list_tables" in SYSTEM_PROMPT
        assert "search_docs" in SYSTEM_PROMPT
        assert "NEVER end your turn" in SYSTEM_PROMPT

    def test_business_formulas_interpolated(self):
        assert REVENUE_SQL in SYSTEM_PROMPT
        assert f"{int(MARGIN_RATE * 100)}%" in SYSTEM_PROMPT

    def test_null_aggregate_guidance_for_every_engine_and_dataset(self):
        for is_local, dataset_summary in (
            (True, None),
            (False, None),
            (True, "Uploaded sales table"),
            (False, "Uploaded sales table"),
        ):
            prompt = build_system_prompt(
                is_local=is_local,
                supports_charts=not is_local,
                dataset_summary=dataset_summary,
            )
            rule = (
                "- When aggregating, also SELECT COUNT(*) in the same query; "
                "a NULL aggregate with zero matching rows means no data, not zero."
            )
            assert prompt.count(rule) == 1

    def test_no_question_specific_exemplar(self):
        # Guard against re-introducing benchmark-overfitting examples.
        assert "Wilman Kala" not in SYSTEM_PROMPT
        assert "Worked example" not in SYSTEM_PROMPT
