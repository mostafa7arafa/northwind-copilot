"""Northwind SQL database adapter.

The agent executes model-authored SQL through this connection, so the
connection itself is the security boundary: it is opened **read-only** so a
confused — or prompt-injected — model can never ``DROP``, ``DELETE``, or
``UPDATE`` the data it is chatting about. The read-only guarantee lives here at
the connection level rather than in a fragile "does this string start with
SELECT" check, so it holds no matter what SQL the model produces.
"""

from __future__ import annotations

import sqlite3
from typing import Callable

from langchain_community.utilities import SQLDatabase
from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url

from northwind_copilot.core.config import settings


def _readonly_sqlite_creator(path: str) -> Callable[[], sqlite3.Connection]:
    """Build a DBAPI ``creator`` that opens ``path`` read-only.

    SQLite enforces read-only at the connection level via the ``mode=ro`` URI
    flag: any write (``INSERT``/``UPDATE``/``DELETE``/``DROP``) raises
    ``sqlite3.OperationalError`` instead of touching the file.

    Args:
        path: Filesystem path to the SQLite database file.

    Returns:
        A zero-arg callable returning a read-only :class:`sqlite3.Connection`,
        suitable for SQLAlchemy's ``create_engine(..., creator=...)``.
    """

    def creator() -> sqlite3.Connection:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    return creator


def build_database(database_uri: str | None = None) -> SQLDatabase:
    """Connect to a database, read-only.

    For a file-backed SQLite database (the default) the connection is opened in
    ``mode=ro`` so the agent's SQL tool cannot mutate the data. For any other
    backend (e.g. a future Postgres per-tenant deployment) the read-only
    guarantee must come from the database role's grants; this adapter connects
    normally and leaves that to deployment.

    ``sample_rows_in_table_info`` is set from configuration (0 by default) to
    keep the schema description small, since it is re-sent on every agent step.

    Args:
        database_uri: SQLAlchemy URI to connect to. Defaults to the configured
            Northwind database (the POC path); the hosted service passes a
            per-tenant dataset's SQLite URI here.

    Returns:
        A configured :class:`~langchain_community.utilities.SQLDatabase`.
    """
    database_uri = database_uri or settings.database_uri
    url = make_url(database_uri)
    is_sqlite_file = url.get_backend_name() == "sqlite" and url.database not in (
        None,
        "",
        ":memory:",
    )

    if is_sqlite_file:
        engine = create_engine(
            "sqlite://", creator=_readonly_sqlite_creator(url.database)
        )
        return SQLDatabase(
            engine, sample_rows_in_table_info=settings.sample_rows_in_table_info
        )

    return SQLDatabase.from_uri(
        database_uri,
        sample_rows_in_table_info=settings.sample_rows_in_table_info,
    )
