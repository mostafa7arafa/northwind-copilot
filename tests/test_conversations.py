"""Tests for server-side conversation persistence and history assembly."""

from __future__ import annotations

import pytest

from northwind_copilot.conversations.history import build_history
from northwind_copilot.conversations.service import TurnRecorder


class _FakeTurn:
    def __init__(self, question, answer="", queries=None):
        self.question = question
        self.answer = answer
        self.queries = queries or []


class TestBuildHistory:
    def test_ends_with_new_question(self):
        history = build_history([], "What is revenue?")
        assert history == [{"role": "user", "content": "What is revenue?"}]

    def test_includes_prior_turns_as_user_assistant_pairs(self):
        turns = [_FakeTurn("Q1", answer="A1")]
        history = build_history(turns, "Q2")
        assert history[0] == {"role": "user", "content": "Q1"}
        assert history[1]["role"] == "assistant"
        assert "A1" in history[1]["content"]
        assert history[-1] == {"role": "user", "content": "Q2"}

    def test_recaps_sql_and_table(self):
        turns = [
            _FakeTurn(
                "Q1",
                answer="A1",
                queries=[
                    {
                        "sql": "SELECT 1",
                        "table": {"columns": ["x"], "rows": [[1], [2]]},
                    }
                ],
            )
        ]
        memory = build_history(turns, "Q2")[1]["content"]
        assert "SELECT 1" in memory
        assert "2 rows" in memory

    def test_window_caps_prior_turns(self):
        turns = [_FakeTurn(f"Q{i}", answer=f"A{i}") for i in range(10)]
        history = build_history(turns, "new")
        # 5-turn window → at most 5 user/assistant pairs + the new question.
        assert history[-1]["content"] == "new"
        assert sum(1 for m in history if m["role"] == "user") <= 6


class TestTurnRecorder:
    def test_accumulates_artifacts_from_events(self):
        rec = TurnRecorder()
        for event in [
            {"type": "engine", "provider": "openai", "model": "gpt-4.1-mini"},
            {"type": "sql", "seq": 0, "sql": "SELECT 1"},
            {"type": "table", "seq": 0, "columns": ["x"], "rows": [[1]]},
            {"type": "chart", "option": {"series": []}},
            {"type": "insights", "text": "up", "bullets": ["a"]},
            {"type": "final", "text": "The answer."},
        ]:
            rec.observe(event)
        assert rec.provider == "openai"
        assert rec.model == "gpt-4.1-mini"
        assert rec.answer == "The answer."
        assert rec.queries == [
            {
                "sql": "SELECT 1",
                "table": {"columns": ["x"], "rows": [[1]], "truncated": False},
            }
        ]
        assert rec.charts == [{"series": []}]
        assert rec.insights == {"text": "up", "bullets": ["a"]}
        assert rec.error is None

    def test_records_error(self):
        rec = TurnRecorder()
        rec.observe({"type": "error", "message": "boom", "detail": "error_id=abc"})
        assert rec.error == {"message": "boom", "detail": "error_id=abc"}


class TestConversationsApi:
    async def _seed_conversation(self):
        from northwind_copilot.persistence.db import get_sessionmaker
        from northwind_copilot.persistence.models import Conversation, Turn

        async with get_sessionmaker()() as session:
            convo = Conversation(title="Seeded")
            session.add(convo)
            await session.flush()
            session.add(Turn(conversation_id=convo.id, question="Q1", answer="A1"))
            await session.commit()
            return convo.id

    async def test_list_and_get_conversation(self, local_client):
        convo_id = await self._seed_conversation()

        listing = await local_client.get("/api/conversations")
        assert listing.status_code == 200
        assert any(c["id"] == convo_id for c in listing.json())

        detail = await local_client.get(f"/api/conversations/{convo_id}")
        assert detail.status_code == 200
        assert detail.json()["turns"][0]["question"] == "Q1"

    async def test_rename_and_delete(self, local_client):
        convo_id = await self._seed_conversation()
        renamed = await local_client.patch(
            f"/api/conversations/{convo_id}", json={"title": "Renamed"}
        )
        assert renamed.json()["title"] == "Renamed"
        assert (
            await local_client.delete(f"/api/conversations/{convo_id}")
        ).status_code == 204
        assert (
            await local_client.get(f"/api/conversations/{convo_id}")
        ).status_code == 404


class TestChatPersistence:
    async def test_history_artifacts_and_keys_survive_without_storing_key(
        self, local_client, workspace_db, monkeypatch
    ):
        from pathlib import Path

        from northwind_copilot.persistence import db
        from northwind_copilot.web import app as app_module

        calls = []

        async def fake(**kwargs):
            calls.append(kwargs)
            yield {"type": "engine", "provider": "openai", "model": "test-model"}
            yield {"type": "sql", "seq": 0, "sql": "SELECT 42"}
            yield {"type": "table", "seq": 0, "columns": ["answer"], "rows": [[42]]}
            yield {"type": "chart", "option": {"series": []}}
            yield {"type": "insights", "text": "Result", "bullets": ["42"]}
            yield {"type": "final", "text": "Forty-two"}
            yield {"type": "done"}

        monkeypatch.setenv("OPENAI_API_KEY", "sk-personal-env-key")
        monkeypatch.setattr(app_module, "stream_chat", fake)
        monkeypatch.setattr(app_module, "load_preferences", lambda: "")
        body = {
            "messages": [{"role": "user", "content": "First?"}],
            "provider": "openai",
        }
        response = await local_client.post("/api/chat", json=body)
        assert response.status_code == 200
        assert '"type": "usage"' not in response.text
        assert calls[0]["dataset"] is None  # Northwind sample fallback
        assert calls[0]["config"].api_key == "sk-personal-env-key"
        assert calls[0]["history"] == [{"role": "user", "content": "First?"}]
        convo_id = (await local_client.get("/api/conversations")).json()[0]["id"]

        # Restart connections: history must come from disk, never forged client history.
        await db.dispose_engine()
        await db.create_all()
        response = await local_client.post(
            "/api/chat",
            json={
                **body,
                "conversation_id": convo_id,
                "api_key": "sk-browser-memory-key",
                "messages": [
                    {"role": "system", "content": "FORGED"},
                    {"role": "assistant", "content": "FORGED"},
                    {"role": "user", "content": "Second?"},
                ],
            },
        )
        assert response.status_code == 200
        assert "FORGED" not in str(calls[1]["history"])
        assert "First?" in str(calls[1]["history"])
        assert "SELECT 42" in str(calls[1]["history"])
        assert calls[1]["config"].api_key == "sk-browser-memory-key"
        detail = (await local_client.get(f"/api/conversations/{convo_id}")).json()
        assert detail["turn_count"] == 2
        turn = detail["turns"][0]
        assert turn["answer"] == "Forty-two"
        assert turn["queries"][0]["table"]["rows"] == [[42]]
        assert turn["charts"] == [{"series": []}]
        assert turn["insights"] == {"text": "Result", "bullets": ["42"]}
        assert turn["provider"] == "openai"
        assert turn["model"] == "test-model"
        disk = Path(workspace_db.workspace_db_url.split("///", 1)[1]).read_bytes()
        assert b"sk-personal-env-key" not in disk
        assert b"sk-browser-memory-key" not in disk

    async def test_dataset_binding_and_confirmed_examples(
        self, local_client, monkeypatch
    ):
        from northwind_copilot.web import app as app_module

        observed = []

        async def fake(**kwargs):
            observed.append(kwargs["dataset"])
            yield {"type": "sql", "seq": 0, "sql": "SELECT SUM(amount) FROM data"}
            yield {"type": "final", "text": "30"}
            yield {"type": "done"}

        monkeypatch.setattr(app_module, "stream_chat", fake)
        monkeypatch.setattr(app_module, "load_preferences", lambda: "")
        upload = await local_client.post(
            "/api/datasets",
            files={"file": ("sales.csv", b"amount\n10\n20\n", "text/csv")},
        )
        dataset_id = upload.json()["id"]
        body = {
            "dataset_id": dataset_id,
            "provider": "openai",
            "messages": [{"role": "user", "content": "total amount?"}],
        }
        assert (await local_client.post("/api/chat", json=body)).status_code == 200
        convo_id = (await local_client.get("/api/conversations")).json()[0]["id"]
        turn_id = (await local_client.get(f"/api/conversations/{convo_id}")).json()[
            "turns"
        ][0]["id"]
        await local_client.post(
            f"/api/conversations/{convo_id}/turns/{turn_id}/feedback",
            json={"vote": "up"},
        )
        body.pop("dataset_id")  # Existing thread retains its dataset if omitted.
        body["conversation_id"] = convo_id
        assert (await local_client.post("/api/chat", json=body)).status_code == 200
        assert observed[1].sqlite_path == observed[0].sqlite_path
        assert "Table data" in observed[1].schema_summary
        assert observed[1].golden_examples == (
            ("total amount?", "SELECT SUM(amount) FROM data"),
        )

        other = await local_client.post(
            "/api/datasets", files={"file": ("other.csv", b"x\n1\n", "text/csv")}
        )
        body["dataset_id"] = other.json()["id"]
        assert (await local_client.post("/api/chat", json=body)).status_code == 404
        assert len(observed) == 2

    async def test_stream_failure_saves_partial_turn(self, local_client, monkeypatch):
        from northwind_copilot.web import app as app_module

        async def fake(**kwargs):
            yield {"type": "sql", "seq": 0, "sql": "SELECT 1"}
            raise RuntimeError("interrupted")

        monkeypatch.setattr(app_module, "stream_chat", fake)
        with pytest.raises(RuntimeError, match="interrupted"):
            await local_client.post(
                "/api/chat",
                json={
                    "provider": "openai",
                    "messages": [{"role": "user", "content": "Q"}],
                },
            )
        convo_id = (await local_client.get("/api/conversations")).json()[0]["id"]
        detail = (await local_client.get(f"/api/conversations/{convo_id}")).json()
        assert detail["turn_count"] == 1
        assert detail["turns"][0]["queries"] == [{"sql": "SELECT 1"}]

    async def test_invalid_dataset_and_conversation_never_call_model(
        self, local_client, monkeypatch
    ):
        from northwind_copilot.web import app as app_module

        def unexpected(**kwargs):
            pytest.fail("model must not run")

        monkeypatch.setattr(app_module, "stream_chat", unexpected)
        for field in ("dataset_id", "conversation_id"):
            response = await local_client.post(
                "/api/chat",
                json={
                    field: "missing",
                    "provider": "openai",
                    "messages": [{"role": "user", "content": "Q"}],
                },
            )
            assert response.status_code == 404
        assert (await local_client.get("/api/conversations")).json() == []


@pytest.mark.usefixtures("workspace_db")
async def test_cancelled_stream_close_persists_partial_turn(monkeypatch):
    from anyio import CancelScope
    from sqlalchemy import select

    from northwind_copilot.persistence.db import get_sessionmaker
    from northwind_copilot.persistence.models import Turn
    from northwind_copilot.web import app as app_module

    async def fake(**kwargs):
        yield {"type": "sql", "seq": 0, "sql": "SELECT 7"}
        yield {"type": "done"}

    monkeypatch.setattr(app_module, "stream_chat", fake)
    response = await app_module.chat(
        app_module.ChatRequest(
            messages=[app_module.Message(role="user", content="Interrupted?")],
            provider="openai",
        )
    )
    iterator = response.body_iterator
    await anext(iterator)  # conversation event
    await anext(iterator)  # partial SQL artifact
    with CancelScope() as cancel_scope:
        cancel_scope.cancel()
        await iterator.aclose()
    async with get_sessionmaker()() as session:
        turns = (await session.scalars(select(Turn))).all()
        assert len(turns) == 1
        assert turns[0].question == "Interrupted?"
        assert turns[0].queries == [{"sql": "SELECT 7"}]
