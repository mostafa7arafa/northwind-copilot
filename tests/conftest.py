"""Isolated local workspaces; tests never open personal or legacy databases."""

from __future__ import annotations

import dataclasses
import importlib

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from northwind_copilot.core.config import settings as real_settings


@pytest.fixture(autouse=True)
def reset_rate_limiter(monkeypatch):
    from northwind_copilot.web import security

    monkeypatch.setattr(security, "_limiter", security.RateLimiter(20))


@pytest.fixture
def workspace_settings(tmp_path, monkeypatch):
    test_settings = dataclasses.replace(
        real_settings,
        workspace_db_url=f"sqlite+aiosqlite:///{tmp_path / 'workspace.sqlite'}",
        dataset_data_dir=str(tmp_path / "datasets"),
    )
    for module_path in (
        "northwind_copilot.core.config",
        "northwind_copilot.persistence.db",
        "northwind_copilot.web.security",
        "northwind_copilot.web.app",
        "northwind_copilot.datasets.storage",
        "northwind_copilot.datasets.router",
    ):
        monkeypatch.setattr(
            importlib.import_module(module_path), "settings", test_settings
        )
    return test_settings


@pytest_asyncio.fixture
async def workspace_db(workspace_settings):
    from northwind_copilot.persistence import db

    await db.dispose_engine()
    await db.create_all()
    try:
        yield workspace_settings
    finally:
        await db.dispose_engine()


@pytest_asyncio.fixture
# Pytest resolves this dependency to initialise and tear down the workspace.
async def local_client(workspace_db):  # noqa: F841
    from northwind_copilot.web.app import app

    transport = ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with AsyncClient(
        transport=transport, base_url="http://localhost:8000"
    ) as client:
        yield client
