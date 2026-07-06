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


async def _signup(client, email):
    resp = await client.post(
        "/api/auth/signup",
        json={"email": email, "password": "password123", "name": "T"},
    )
    assert resp.status_code == 201
    return resp.json()


async def _upload(client, name="sales", csv=b"region,amount\neast,10\nwest,20\n"):
    resp = await client.post(
        "/api/datasets",
        files={"file": (f"{name}.csv", csv, "text/csv")},
        data={"name": name},
    )
    assert resp.status_code == 201
    return resp.json()


class TestMultiFileApi:
    async def test_add_file_joins_the_dataset(self, hosted_client, hosted_db):
        await _signup(hosted_client, "multi@x.com")
        ds = await _upload(hosted_client)
        added = await hosted_client.post(
            f"/api/datasets/{ds['id']}/files",
            files={"file": ("targets.csv", b"region,target\neast,15\n", "text/csv")},
        )
        assert added.status_code == 200
        body = added.json()
        assert body["table_count"] == 2
        assert "targets" in body["schema_summary"]

        # The two files are now joinable in one SQL statement.
        joined = await hosted_client.post(
            f"/api/datasets/{ds['id']}/query",
            json={
                "sql": "SELECT d.region, d.amount, t.target "
                "FROM data d JOIN targets t ON d.region = t.region"
            },
        )
        assert joined.status_code == 200
        assert joined.json()["rows"] == [["east", 10, 15]]

    async def test_other_org_cannot_add_files(self, hosted_client, hosted_db):
        await _signup(hosted_client, "owner-mf@x.com")
        ds = await _upload(hosted_client)
        hosted_client.cookies.clear()
        await _signup(hosted_client, "intruder-mf@x.com")
        resp = await hosted_client.post(
            f"/api/datasets/{ds['id']}/files",
            files={"file": ("x.csv", b"a\n1\n", "text/csv")},
        )
        assert resp.status_code == 404

    async def test_bad_append_reports_and_keeps_dataset_ready(
        self, hosted_client, hosted_db
    ):
        await _signup(hosted_client, "badappend@x.com")
        ds = await _upload(hosted_client)
        resp = await hosted_client.post(
            f"/api/datasets/{ds['id']}/files",
            files={"file": ("junk.csv", b"", "text/csv")},
        )
        assert resp.status_code == 400
        detail = (await hosted_client.get(f"/api/datasets/{ds['id']}")).json()
        assert detail["status"] == "ready"
        assert detail["table_count"] == 1


class TestQueryApi:
    async def test_select_returns_structured_table(self, hosted_client, hosted_db):
        await _signup(hosted_client, "sqlrun@x.com")
        ds = await _upload(hosted_client)
        resp = await hosted_client.post(
            f"/api/datasets/{ds['id']}/query",
            json={"sql": "SELECT region, amount FROM data ORDER BY amount DESC"},
        )
        assert resp.status_code == 200
        assert resp.json()["columns"] == ["region", "amount"]
        assert resp.json()["rows"][0] == ["west", 20]

    async def test_non_select_is_rejected(self, hosted_client, hosted_db):
        await _signup(hosted_client, "nowrite@x.com")
        ds = await _upload(hosted_client)
        for sql in ("DROP TABLE data", "DELETE FROM data", "PRAGMA schema_version"):
            resp = await hosted_client.post(
                f"/api/datasets/{ds['id']}/query", json={"sql": sql}
            )
            assert resp.status_code == 400, sql
        # The data is untouched.
        ok = await hosted_client.post(
            f"/api/datasets/{ds['id']}/query",
            json={"sql": "SELECT COUNT(*) FROM data"},
        )
        assert ok.json()["rows"] == [[2]]

    async def test_other_org_cannot_query(self, hosted_client, hosted_db):
        await _signup(hosted_client, "owner-q@x.com")
        ds = await _upload(hosted_client)
        hosted_client.cookies.clear()
        await _signup(hosted_client, "intruder-q@x.com")
        resp = await hosted_client.post(
            f"/api/datasets/{ds['id']}/query", json={"sql": "SELECT 1"}
        )
        assert resp.status_code == 404


class TestLanguageRule:
    def test_dataset_prompt_answers_in_users_language(self):
        from northwind_copilot.core.prompts import build_system_prompt

        prompt = build_system_prompt(
            is_local=False, supports_charts=True, dataset_summary="Table t: a"
        )
        assert "user's language" in prompt
        assert "Arabic" in prompt

    def test_poc_prompt_is_unchanged(self):
        from northwind_copilot.core.prompts import SYSTEM_PROMPT, build_system_prompt

        prompt = build_system_prompt(is_local=False, supports_charts=False)
        assert "Arabic" not in prompt
        assert "Arabic" not in SYSTEM_PROMPT


class TestGoldenSelection:
    async def test_keyword_match_ranks_first(self, hosted_db):
        from northwind_copilot.datasets.golden import select_examples
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import Dataset, GoldenExample, Org, User

        async with get_sessionmaker()() as session:
            user = User(email="g@x.com", password_hash="x")
            session.add(user)
            await session.flush()
            org = Org(name="g", owner_user_id=user.id)
            session.add(org)
            await session.flush()
            ds = Dataset(org_id=org.id, name="d", source_type="csv", status="ready")
            session.add(ds)
            await session.flush()
            for q, s in [
                ("total revenue by region", "SELECT region, SUM(amount) ..."),
                ("count of customers", "SELECT COUNT(DISTINCT customer) ..."),
                ("monthly revenue trend", "SELECT month, SUM(amount) ..."),
            ]:
                session.add(
                    GoldenExample(dataset_id=ds.id, org_id=org.id, question=q, sql=s)
                )
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
    async def _seed_turn(self, me, dataset_id=None):
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import Conversation, Turn

        async with get_sessionmaker()() as session:
            convo = Conversation(
                org_id=me["org_id"],
                user_id=me["id"],
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

    async def test_thumbs_up_creates_a_golden_example(self, hosted_client, hosted_db):
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import GoldenExample

        me = await _signup(hosted_client, "fb@x.com")
        ds = await _upload(hosted_client)
        convo_id, turn_id = await self._seed_turn(me, dataset_id=ds["id"])

        resp = await hosted_client.post(
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

    async def test_thumbs_down_retracts_the_example(self, hosted_client, hosted_db):
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import GoldenExample

        me = await _signup(hosted_client, "fb2@x.com")
        ds = await _upload(hosted_client)
        convo_id, turn_id = await self._seed_turn(me, dataset_id=ds["id"])
        url = f"/api/conversations/{convo_id}/turns/{turn_id}/feedback"
        await hosted_client.post(url, json={"vote": "up"})
        await hosted_client.post(url, json={"vote": "down"})

        async with get_sessionmaker()() as session:
            assert (await session.execute(select(GoldenExample))).first() is None

    async def test_datasetless_turn_records_vote_without_example(
        self, hosted_client, hosted_db
    ):
        me = await _signup(hosted_client, "fb3@x.com")
        convo_id, turn_id = await self._seed_turn(me, dataset_id=None)
        resp = await hosted_client.post(
            f"/api/conversations/{convo_id}/turns/{turn_id}/feedback",
            json={"vote": "up"},
        )
        assert resp.json() == {"vote": "up", "golden_example": False}

    async def test_other_org_cannot_vote(self, hosted_client, hosted_db):
        me = await _signup(hosted_client, "fbowner@x.com")
        convo_id, turn_id = await self._seed_turn(me)
        hosted_client.cookies.clear()
        await _signup(hosted_client, "fbintruder@x.com")
        resp = await hosted_client.post(
            f"/api/conversations/{convo_id}/turns/{turn_id}/feedback",
            json={"vote": "up"},
        )
        assert resp.status_code == 404


class TestTurnEvent:
    async def test_chat_emits_the_turn_id_before_done(
        self, hosted_client, hosted_db, monkeypatch
    ):
        from northwind_copilot.web import app as app_module

        await _signup(hosted_client, "turnid@x.com")

        async def fake(**kwargs):
            yield {"type": "final", "text": "42."}
            yield {"type": "done"}

        monkeypatch.setattr(app_module, "stream_chat", fake)
        monkeypatch.setattr(app_module, "load_preferences", lambda: "")
        resp = await hosted_client.post(
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
