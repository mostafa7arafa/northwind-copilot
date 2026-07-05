"""Async engine and session management for the application database.

A single process-wide async engine is created lazily from ``settings.app_db_url``
(SQLite+aiosqlite in dev/tests, Postgres+asyncpg in production). ``get_session``
is the FastAPI dependency that yields a request-scoped ``AsyncSession``.

Schema is managed by Alembic in production. ``create_all`` is provided only for
the SQLite dev/test path, where running a migration stack per test is overkill.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from northwind_copilot.core.config import settings
from northwind_copilot.tenancy.models import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(settings.app_db_url, future=True, echo=False)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory, initialising the engine if needed."""
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session.

    Commits on success and rolls back on error, so route handlers don't each
    have to manage the transaction boundary.
    """
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    """Create all tables (dev/test convenience; production uses Alembic)."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """Dispose the engine (used by tests to reset between DB URLs)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
