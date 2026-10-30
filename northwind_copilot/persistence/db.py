"""Async SQLite workspace sessions; never migrate or reuse a SaaS database."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from northwind_copilot.core.config import settings
from northwind_copilot.persistence.models import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _validate_workspace() -> None:
    """Reject legacy paths before opening them; inspect other files read-only."""
    url = make_url(settings.workspace_db_url)
    if url.drivername != "sqlite+aiosqlite" or not url.database:
        raise ValueError("The workspace requires a local sqlite+aiosqlite database.")
    if url.query:
        raise ValueError("Workspace database URL query options are not supported.")
    if url.database == ":memory:":
        return
    path = Path(url.database).resolve()
    if path.name == "app.sqlite" or "tenants" in path.parts:
        raise ValueError("Refusing legacy SaaS database path; choose a new workspace.")
    if path.exists():
        # No connection capable of writing is made until schema validation passes.
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            }
            if tables - Base.metadata.tables.keys():
                raise ValueError("Refusing an incompatible or legacy SaaS database.")
            for table in tables:
                columns = {
                    row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')
                }
                expected = set(Base.metadata.tables[table].columns.keys())
                if columns != expected:
                    raise ValueError("Refusing an incompatible or legacy SaaS schema.")
    path.parent.mkdir(parents=True, exist_ok=True)


def get_engine() -> AsyncEngine:
    """Return the lazily created, validated workspace engine."""
    global _engine, _sessionmaker
    if _engine is None:
        _validate_workspace()
        _engine = create_async_engine(settings.workspace_db_url)

        @event.listens_for(_engine.sync_engine, "connect")
        def configure_connection(connection, _record):
            cursor = connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=5000")
            finally:
                cursor.close()

        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory."""
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """Commit successful requests and roll back failed requests."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    """Create the fresh local schema, without migrations or legacy conversion."""
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """Release connections, including when switching test workspaces."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
