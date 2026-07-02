"""Persist the user's free-text analyst preferences.

Kept deliberately simple: a single JSON file next to the repo. The text is
appended to the system prompt on every request (see :mod:`server.prompts`).
"""

from __future__ import annotations

import json
from pathlib import Path

_STORE = Path(__file__).resolve().parent.parent / ".user_preferences.json"


def load_preferences() -> str:
    """Read the saved preference text.

    Returns:
        The stored preferences, or an empty string if none are saved.
    """
    if not _STORE.exists():
        return ""
    try:
        return json.loads(_STORE.read_text(encoding="utf-8")).get("preferences", "")
    except (json.JSONDecodeError, OSError):
        return ""


def save_preferences(text: str) -> str:
    """Persist the preference text.

    Args:
        text: The free-text preferences to store.

    Returns:
        The saved text (trimmed).
    """
    trimmed = (text or "").strip()
    _STORE.write_text(
        json.dumps({"preferences": trimmed}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return trimmed
