"""Workspace initialization, restart persistence, and legacy-data safety."""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import inspect, select

from northwind_copilot.persistence import db
from northwind_copilot.persistence.models import (
    Base,
    Conversation,
    Dataset,
    GoldenExample,
    Turn,
    TurnFeedback,
)


async def test_fresh_workspace_has_only_product_tables_and_reopens(workspace_db):
    async with db.get_engine().connect() as conn:
        tables = await conn.run_sync(lambda sync: inspect(sync).get_table_names())
    assert set(tables) == {
        "datasets",
        "conversations",
        "turns",
        "turn_feedback",
        "golden_examples",
    }
    for table in Base.metadata.tables.values():
        assert not {"org_id", "user_id"} & set(table.columns.keys())

    async with db.get_sessionmaker()() as session:
        dataset = Dataset(name="Sales", source_type="csv")
        session.add(dataset)
        await session.flush()
        convo = Conversation(dataset_id=dataset.id, title="Analysis")
        session.add(convo)
        await session.flush()
        turn = Turn(conversation_id=convo.id, question="Q", answer="A")
        session.add(turn)
        await session.flush()
        session.add(TurnFeedback(turn_id=turn.id, vote=1))
        session.add(
            GoldenExample(
                dataset_id=dataset.id,
                source_turn_id=turn.id,
                question="Q",
                sql="SELECT 1",
            )
        )
        await session.commit()
        ids = (dataset.id, convo.id, turn.id)

    await db.dispose_engine()
    await db.create_all()
    async with db.get_sessionmaker()() as session:
        assert (await session.get(Dataset, ids[0])).name == "Sales"
        assert (await session.get(Conversation, ids[1])).title == "Analysis"
        assert (await session.get(Turn, ids[2])).answer == "A"
        assert (await session.get(TurnFeedback, ids[2])).vote == 1
        assert (await session.scalars(select(GoldenExample))).one().sql == "SELECT 1"
    assert Path(workspace_db.workspace_db_url.split("///", 1)[1]).is_file()


async def test_every_connection_enables_wal_and_busy_timeout(workspace_db):
    async with db.get_engine().connect() as first, db.get_engine().connect() as second:
        for conn in (first, second):
            assert (
                await conn.exec_driver_sql("PRAGMA journal_mode")
            ).scalar_one() == "wal"
            assert (
                await conn.exec_driver_sql("PRAGMA busy_timeout")
            ).scalar_one() == 5000
            assert (await conn.exec_driver_sql("PRAGMA foreign_keys")).scalar_one() == 1


@pytest.mark.parametrize("legacy_name", ["app.sqlite", "tenants/old.sqlite"])
async def test_legacy_paths_rejected_without_opening(
    workspace_settings, monkeypatch, tmp_path, legacy_name
):
    await db.dispose_engine()
    legacy_path = tmp_path / legacy_name
    monkeypatch.setattr(
        db,
        "settings",
        dataclasses.replace(
            workspace_settings, workspace_db_url=f"sqlite+aiosqlite:///{legacy_path}"
        ),
    )

    def unexpected_connect(*args, **kwargs):
        pytest.fail("legacy path must be rejected before connecting")

    monkeypatch.setattr(db.sqlite3, "connect", unexpected_connect)
    with pytest.raises(ValueError, match="legacy SaaS database path"):
        await db.create_all()
    assert not legacy_path.exists()


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE users (id TEXT)",
        "CREATE TABLE datasets (id TEXT, org_id TEXT)",
        "CREATE TABLE datasets (id TEXT)",
    ],
)
async def test_legacy_or_incompatible_schema_rejected_without_mutation(
    workspace_settings, monkeypatch, tmp_path, ddl
):
    await db.dispose_engine()
    path = tmp_path / "copied.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute(ddl)
    before = path.read_bytes()
    monkeypatch.setattr(
        db,
        "settings",
        dataclasses.replace(
            workspace_settings, workspace_db_url=f"sqlite+aiosqlite:///{path}"
        ),
    )
    with pytest.raises(ValueError, match="incompatible or legacy SaaS"):
        await db.create_all()
    assert path.read_bytes() == before
    assert not Path(str(path) + "-journal").exists()
    assert not Path(str(path) + "-wal").exists()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://localhost/app",
        "sqlite:///data/new.sqlite",
        "sqlite+aiosqlite:///data/new.sqlite?mode=rw",
    ],
)
async def test_nonlocal_or_custom_driver_options_rejected(
    workspace_settings, monkeypatch, url
):
    await db.dispose_engine()
    monkeypatch.setattr(
        db, "settings", dataclasses.replace(workspace_settings, workspace_db_url=url)
    )
    with pytest.raises(ValueError):
        await db.create_all()


@pytest.mark.usefixtures("workspace_db")
async def test_failed_request_rolls_back():
    dependency = db.get_session()
    session = await anext(dependency)
    session.add(Dataset(name="Rolled back", source_type="csv"))
    await session.flush()
    with pytest.raises(RuntimeError):
        await dependency.athrow(RuntimeError("request failed"))
    async with db.get_sessionmaker()() as session:
        assert (await session.scalars(select(Dataset))).all() == []
