"""Shared test fixtures for the hosted (multi-tenant) API paths.

The application settings are a frozen dataclass read via a module-global
``settings`` binding in each module. To exercise hosted mode against a throwaway
SQLite app database, we build an overridden ``Settings`` with
``dataclasses.replace`` and monkeypatch it into every module that reads a field
we change (``hosted_mode``, ``app_db_url``). The DB engine singleton is disposed
around each test so a fresh database is used every time.
"""

from __future__ import annotations

import dataclasses

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from northwind_copilot.core.config import settings as real_settings


@pytest.fixture
def hosted_settings(tmp_path, monkeypatch):
    """Return a hosted-mode Settings pointed at a temp SQLite app DB.

    Patches the ``settings`` binding in every module that reads the fields we
    override, so the whole request path sees hosted mode consistently.
    """
    from cryptography.fernet import Fernet

    db_path = tmp_path / "app.sqlite"
    tenants_dir = tmp_path / "tenants"
    test_settings = dataclasses.replace(
        real_settings,
        hosted_mode=True,
        app_db_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        tenant_data_dir=str(tenants_dir),
        auth_token="",
        key_encryption_secret=Fernet.generate_key().decode(),
    )
    for module_path in (
        "northwind_copilot.core.config",
        "northwind_copilot.tenancy.db",
        "northwind_copilot.web.security",
        "northwind_copilot.web.app",
        "northwind_copilot.auth.router",
        "northwind_copilot.auth.service",
        "northwind_copilot.datasets.storage",
        "northwind_copilot.datasets.router",
        "northwind_copilot.keys.service",
    ):
        import importlib

        module = importlib.import_module(module_path)
        if hasattr(module, "settings"):
            monkeypatch.setattr(module, "settings", test_settings, raising=False)
    return test_settings


@pytest_asyncio.fixture
async def hosted_db(hosted_settings):
    """Set up (and tear down) a fresh hosted-mode application database."""
    from northwind_copilot.tenancy import db as db_module

    await db_module.dispose_engine()
    await db_module.create_all()
    yield hosted_settings
    await db_module.dispose_engine()


@pytest_asyncio.fixture
async def hosted_client(hosted_db):
    """An async HTTP client bound to the app with a fresh hosted-mode DB."""
    from northwind_copilot.web.app import app

    transport = ASGITransport(app=app)
    # https base URL: the session cookie is set Secure in hosted mode, so the
    # client only sends it back over https.
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        yield client
