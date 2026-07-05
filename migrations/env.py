"""Alembic migration environment for the application database.

Reads the database URL from the app settings and targets the SQLAlchemy models'
metadata, so ``alembic revision --autogenerate`` and ``alembic upgrade`` both
work against whichever backend ``APP_DATABASE_URL`` names (SQLite or Postgres).
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from northwind_copilot.core.config import settings

# Import all model modules so their tables register on Base.metadata.
from northwind_copilot.tenancy.models import Base  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.app_db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit migrations as SQL without a live connection."""
    context.configure(
        url=settings.app_db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Batch mode makes ALTERs work on SQLite (dev) as well as Postgres.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live async connection."""
    connectable = async_engine_from_config(
        {"sqlalchemy.url": settings.app_db_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
