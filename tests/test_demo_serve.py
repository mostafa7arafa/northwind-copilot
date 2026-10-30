"""Check isolated single-user demo startup without launching a server or LLM."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace


def test_demo_uses_disposable_workspace_without_auth(tmp_path, monkeypatch):
    from northwind_copilot.web import preferences

    monkeypatch.setenv("DEMO_WORK_DIR", str(tmp_path))
    # Restore this process-global override after the recording entry point runs.
    monkeypatch.setattr(preferences, "_STORE", preferences._STORE)
    monkeypatch.chdir(Path.cwd())
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=lambda *args, **kw: calls.append((args, kw))),
    )
    for key in (
        "WORKSPACE_DATABASE_URL",
        "DATASET_DATA_DIR",
        "LANGSMITH_API_KEY",
        "LANGCHAIN_API_KEY",
        "LANGSMITH_TRACING",
        "LANGCHAIN_TRACING_V2",
    ):
        monkeypatch.setenv(key, "")
    path = Path(__file__).resolve().parents[1] / "scripts/demo/serve.py"
    monkeypatch.syspath_prepend(str(path.parents[2]))
    spec = importlib.util.spec_from_file_location("demo_serve", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()

    assert calls == [
        (
            ("northwind_copilot.web.app:app",),
            {
                "host": "127.0.0.1",
                "port": 8000,
                "proxy_headers": False,
            },
        )
    ]
    assert (
        os.environ["WORKSPACE_DATABASE_URL"]
        == f"sqlite+aiosqlite:///{tmp_path}/workspace.sqlite"
    )
    assert os.environ["DATASET_DATA_DIR"] == str(tmp_path / "datasets")
    assert preferences._STORE == tmp_path / "preferences.json"
    assert json.loads(preferences._STORE.read_text())["preferences"]
    assert not (tmp_path / "auth-token").exists()
