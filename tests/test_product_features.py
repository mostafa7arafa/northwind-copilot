"""Tests for the product differentiators: multi-file datasets, SQL re-run,
language rule, and feedback → golden examples."""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import select

from northwind_copilot.datasets import ingest as ingest_mod


def _tables(path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()


class TestIngestAppend:
    def test_csv_append_adds_a_named_table(self, tmp_path):
        dest = tmp_path / "d.sqlite"
        ingest_mod.ingest("csv", b"a,b\n1,2\n", dest)
        result = ingest_mod.append("csv", b"x,y\n3,4\n5,6\n", dest, name_hint="targets")
        assert result.table_count == 1
        assert result.row_count == 2
        assert _tables(dest) == {"data", "targets"}

    def test_append_never_clobbers_an_existing_table(self, tmp_path):
        dest = tmp_path / "d.sqlite"
        ingest_mod.ingest("csv", b"a\n1\n", dest)  # table "data"
        ingest_mod.append("csv", b"b\n2\n", dest, name_hint="data")
        assert _tables(dest) == {"data", "data_2"}
        conn = sqlite3.connect(dest)
        try:  # the original table is untouched
            assert conn.execute("SELECT a FROM data").fetchall() == [(1,)]
        finally:
            conn.close()

    def test_sqlite_append_copies_tables(self, tmp_path):
        src = tmp_path / "src.sqlite"
        conn = sqlite3.connect(src)
        conn.execute("CREATE TABLE regions (id INT)")
        conn.execute("INSERT INTO regions VALUES (1), (2)")
        conn.commit()
        conn.close()

        dest = tmp_path / "d.sqlite"
        ingest_mod.ingest("csv", b"a\n1\n", dest)
        result = ingest_mod.append("sqlite", src.read_bytes(), dest)
        assert result.table_count == 1
        assert "regions" in _tables(dest)

    def test_append_to_missing_dataset_fails(self, tmp_path):
        with pytest.raises(ingest_mod.IngestError):
            ingest_mod.append("csv", b"a\n1\n", tmp_path / "nope.sqlite")

    def test_dataset_stats_recounts_from_the_file(self, tmp_path):
        dest = tmp_path / "d.sqlite"
        ingest_mod.ingest("csv", b"a\n1\n2\n", dest)
        ingest_mod.append("csv", b"b\n3\n", dest, name_hint="more")
        tables, rows = ingest_mod.dataset_stats(dest)
        assert (tables, rows) == (2, 3)


async def _upload(client, name="sales", csv=b"region,amount\neast,10\nwest,20\n"):
    resp = await client.post(
        "/api/datasets",
        files={"file": (f"{name}.csv", csv, "text/csv")},
        data={"name": name},
    )
    assert resp.status_code == 201
    return resp.json()


class TestMultiFileApi:
    async def test_add_file_joins_the_dataset(self, local_client):
        ds = await _upload(local_client)
        added = await local_client.post(
            f"/api/datasets/{ds['id']}/files",
            files={"file": ("targets.csv", b"region,target\neast,15\n", "text/csv")},
        )
        assert added.status_code == 200
        body = added.json()
        assert body["table_count"] == 2
        assert "targets" in body["schema_summary"]

        # The two files are now joinable in one SQL statement.
        joined = await local_client.post(
            f"/api/datasets/{ds['id']}/query",
            json={
                "sql": "SELECT d.region, d.amount, t.target "
                "FROM data d JOIN targets t ON d.region = t.region"
            },
        )
        assert joined.status_code == 200
        assert joined.json()["rows"] == [["east", 10, 15]]

    async def test_bad_append_reports_and_keeps_dataset_ready(self, local_client):
        ds = await _upload(local_client)
        resp = await local_client.post(
            f"/api/datasets/{ds['id']}/files",
            files={"file": ("junk.csv", b"", "text/csv")},
        )
        assert resp.status_code == 400
        detail = (await local_client.get(f"/api/datasets/{ds['id']}")).json()
        assert detail["status"] == "ready"
        assert detail["table_count"] == 1


class TestQueryApi:
    async def test_select_returns_structured_table(self, local_client):
        ds = await _upload(local_client)
        resp = await local_client.post(
            f"/api/datasets/{ds['id']}/query",
            json={"sql": "SELECT region, amount FROM data ORDER BY amount DESC"},
        )
        assert resp.status_code == 200
        assert resp.json()["columns"] == ["region", "amount"]
        assert resp.json()["rows"][0] == ["west", 20]

    async def test_non_select_is_rejected(self, local_client):
        ds = await _upload(local_client)
        for sql in ("DROP TABLE data", "DELETE FROM data", "PRAGMA schema_version"):
            resp = await local_client.post(
                f"/api/datasets/{ds['id']}/query", json={"sql": sql}
            )
            assert resp.status_code == 400, sql
        # The data is untouched.
        ok = await local_client.post(
            f"/api/datasets/{ds['id']}/query",
            json={"sql": "SELECT COUNT(*) FROM data"},
        )
        assert ok.json()["rows"] == [[2]]


class TestLanguageRule:
    def test_dataset_prompt_anchors_to_latest_question(self):
        from northwind_copilot.core.prompts import build_system_prompt

        prompt = build_system_prompt(
            is_local=False, supports_charts=True, dataset_summary="Table t: a"
        )
        # The rule anchors to the current question and names Arabic only as the
        # switch case, so an English conversation stays English.
        assert "MOST RECENT question" in prompt
        assert "do not switch languages because an earlier message" in prompt
        assert "Arabic" in prompt  # the wedge still works for Arabic questions

    def test_poc_prompt_is_unchanged(self):
        from northwind_copilot.core.prompts import SYSTEM_PROMPT, build_system_prompt

        prompt = build_system_prompt(is_local=False, supports_charts=False)
        assert "Arabic" not in prompt
        assert "Arabic" not in SYSTEM_PROMPT


class TestGoldenSelection:
    @pytest.mark.usefixtures("workspace_db")
    async def test_keyword_match_ranks_first(self):
        from northwind_copilot.datasets.golden import select_examples
        from northwind_copilot.persistence.db import get_sessionmaker
        from northwind_copilot.persistence.models import Dataset, GoldenExample

        async with get_sessionmaker()() as session:
            ds = Dataset(name="d", source_type="csv", status="ready")
            session.add(ds)
            await session.flush()
            for q, s in [
                ("total revenue by region", "SELECT region, SUM(amount) ..."),
                ("count of customers", "SELECT COUNT(DISTINCT customer) ..."),
                ("monthly revenue trend", "SELECT month, SUM(amount) ..."),
            ]:
                session.add(GoldenExample(dataset_id=ds.id, question=q, sql=s))
            await session.commit()
            examples = await select_examples(
                session, ds.id, "what was revenue per region last year?", k=2
            )
        assert examples[0][0] == "total revenue by region"
        assert len(examples) == 2

    def test_prompt_injects_examples_on_dataset_path_only(self):
        from northwind_copilot.core.prompts import build_system_prompt

        pairs = (("total revenue", "SELECT SUM(amount) FROM data"),)
        with_ex = build_system_prompt(
            is_local=False,
            supports_charts=True,
            dataset_summary="Table data: amount",
            golden_examples=pairs,
        )
        assert "Confirmed examples" in with_ex
        assert "SELECT SUM(amount) FROM data" in with_ex
        without = build_system_prompt(
            is_local=False,
            supports_charts=True,
            dataset_summary="Table data: amount",
        )
        assert "Confirmed examples" not in without
        poc = build_system_prompt(
            is_local=False, supports_charts=True, golden_examples=pairs
        )
        assert "Confirmed examples" not in poc


class TestFeedbackApi:
    async def _seed_turn(self, dataset_id=None):
        from northwind_copilot.persistence.db import get_sessionmaker
        from northwind_copilot.persistence.models import Conversation, Turn

        async with get_sessionmaker()() as session:
            convo = Conversation(
                dataset_id=dataset_id,
                title="t",
            )
            session.add(convo)
            await session.flush()
            turn = Turn(
                conversation_id=convo.id,
                question="revenue by region?",
                answer="East leads.",
                queries=[{"sql": "SELECT region, SUM(amount) FROM data GROUP BY 1"}],
            )
            session.add(turn)
            await session.commit()
            return convo.id, turn.id

    async def test_thumbs_up_creates_a_golden_example(self, local_client):
        from northwind_copilot.persistence.db import get_sessionmaker
        from northwind_copilot.persistence.models import GoldenExample

        ds = await _upload(local_client)
        convo_id, turn_id = await self._seed_turn(dataset_id=ds["id"])

        resp = await local_client.post(
            f"/api/conversations/{convo_id}/turns/{turn_id}/feedback",
            json={"vote": "up"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"vote": "up", "golden_example": True}

        async with get_sessionmaker()() as session:
            ex = (await session.execute(select(GoldenExample))).scalars().one()
            assert ex.dataset_id == ds["id"]
            assert ex.question == "revenue by region?"
            assert "SUM(amount)" in ex.sql

    async def test_thumbs_down_retracts_the_example(self, local_client):
        from northwind_copilot.persistence.db import get_sessionmaker
        from northwind_copilot.persistence.models import GoldenExample

        ds = await _upload(local_client)
        convo_id, turn_id = await self._seed_turn(dataset_id=ds["id"])
        url = f"/api/conversations/{convo_id}/turns/{turn_id}/feedback"
        await local_client.post(url, json={"vote": "up"})
        await local_client.post(url, json={"vote": "down"})

        async with get_sessionmaker()() as session:
            assert (await session.execute(select(GoldenExample))).first() is None

    async def test_datasetless_turn_records_vote_without_example(self, local_client):
        convo_id, turn_id = await self._seed_turn(dataset_id=None)
        resp = await local_client.post(
            f"/api/conversations/{convo_id}/turns/{turn_id}/feedback",
            json={"vote": "up"},
        )
        assert resp.json() == {"vote": "up", "golden_example": False}


class TestTurnEvent:
    async def test_chat_emits_the_turn_id_before_done(self, local_client, monkeypatch):
        from northwind_copilot.web import app as app_module

        async def fake(**kwargs):
            yield {"type": "final", "text": "42."}
            yield {"type": "done"}

        monkeypatch.setattr(app_module, "stream_chat", fake)
        monkeypatch.setattr(app_module, "load_preferences", lambda: "")
        resp = await local_client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "provider": "openrouter",
                "model": "openai/gpt-4.1-mini",
            },
        )
        body = resp.text
        assert '"type": "turn"' in body
        assert body.index('"type": "turn"') < body.index('"type": "done"')


class TestFeedbackIntegrity:
    async def test_revote_is_idempotent_and_turn_must_belong_to_thread(
        self, local_client
    ):
        from northwind_copilot.persistence.db import get_sessionmaker
        from northwind_copilot.persistence.models import (
            Conversation,
            GoldenExample,
            Turn,
            TurnFeedback,
        )

        ds = await _upload(local_client)
        async with get_sessionmaker()() as session:
            first = Conversation(dataset_id=ds["id"])
            other = Conversation()
            session.add_all([first, other])
            await session.flush()
            turn = Turn(
                conversation_id=first.id,
                question="total?",
                queries=[{"sql": "SELECT 1"}],
            )
            session.add(turn)
            await session.commit()
            convo_id, other_id, turn_id = first.id, other.id, turn.id
        url = f"/api/conversations/{convo_id}/turns/{turn_id}/feedback"
        assert (await local_client.post(url, json={"vote": "up"})).status_code == 200
        assert (await local_client.post(url, json={"vote": "up"})).status_code == 200
        async with get_sessionmaker()() as session:
            assert len((await session.scalars(select(GoldenExample))).all()) == 1
            assert (await session.get(TurnFeedback, turn_id)).vote == 1
        mismatch = f"/api/conversations/{other_id}/turns/{turn_id}/feedback"
        assert (
            await local_client.post(mismatch, json={"vote": "up"})
        ).status_code == 404
        assert (
            await local_client.post(url, json={"vote": "invalid"})
        ).status_code == 422
        assert (
            await local_client.delete(f"/api/conversations/{convo_id}")
        ).status_code == 204
        async with get_sessionmaker()() as session:
            assert await session.get(Turn, turn_id) is None
            assert await session.get(TurnFeedback, turn_id) is None
