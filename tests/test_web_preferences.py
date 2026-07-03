"""Unit tests for preference persistence (store redirected to a temp file)."""

from __future__ import annotations

from northwind_copilot.web import preferences


class TestPreferences:
    def test_load_missing_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(preferences, "_STORE", tmp_path / "prefs.json")
        assert preferences.load_preferences() == ""

    def test_save_then_load_roundtrip(self, monkeypatch, tmp_path):
        store = tmp_path / "prefs.json"
        monkeypatch.setattr(preferences, "_STORE", store)
        saved = preferences.save_preferences("  Prefer euros.  ")
        assert saved == "Prefer euros."  # trimmed
        assert preferences.load_preferences() == "Prefer euros."

    def test_load_corrupt_json_returns_empty(self, monkeypatch, tmp_path):
        store = tmp_path / "prefs.json"
        store.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(preferences, "_STORE", store)
        assert preferences.load_preferences() == ""
