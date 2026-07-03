"""Northwind SQL database adapter."""

from __future__ import annotations

from langchain_community.utilities import SQLDatabase

from northwind_copilot.core.config import settings


def build_database() -> SQLDatabase:
    """Connect to the Northwind database.

    ``sample_rows_in_table_info`` is set from configuration (0 by default) to
    keep the schema description small, since it is re-sent on every agent step.

    Returns:
        A configured :class:`~langchain_community.utilities.SQLDatabase`.
    """
    return SQLDatabase.from_uri(
        settings.database_uri,
        sample_rows_in_table_info=settings.sample_rows_in_table_info,
    )
