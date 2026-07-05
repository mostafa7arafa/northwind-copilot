"""Tests for server-side conversation persistence and history assembly."""

from __future__ import annotations

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
    async def _signup(self, client, email):
        return await client.post(
            "/api/auth/signup",
            json={"email": email, "password": "password123", "name": "T"},
        )

    async def _seed_conversation(self, hosted_db, org_id, user_id):
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import Conversation, Turn

        async with get_sessionmaker()() as session:
            convo = Conversation(org_id=org_id, user_id=user_id, title="Seeded")
            session.add(convo)
            await session.flush()
            session.add(Turn(conversation_id=convo.id, question="Q1", answer="A1"))
            await session.commit()
            return convo.id

    async def test_list_and_get_conversation(self, hosted_client, hosted_db):
        me = (await self._signup(hosted_client, "a@x.com")).json()
        convo_id = await self._seed_conversation(hosted_db, me["org_id"], me["id"])

        listing = await hosted_client.get("/api/conversations")
        assert listing.status_code == 200
        assert any(c["id"] == convo_id for c in listing.json())

        detail = await hosted_client.get(f"/api/conversations/{convo_id}")
        assert detail.status_code == 200
        assert detail.json()["turns"][0]["question"] == "Q1"

    async def test_rename_and_delete(self, hosted_client, hosted_db):
        me = (await self._signup(hosted_client, "b@x.com")).json()
        convo_id = await self._seed_conversation(hosted_db, me["org_id"], me["id"])
        renamed = await hosted_client.patch(
            f"/api/conversations/{convo_id}", json={"title": "Renamed"}
        )
        assert renamed.json()["title"] == "Renamed"
        assert (
            await hosted_client.delete(f"/api/conversations/{convo_id}")
        ).status_code == 204
        assert (
            await hosted_client.get(f"/api/conversations/{convo_id}")
        ).status_code == 404

    async def test_other_org_cannot_read_conversation(self, hosted_client, hosted_db):
        owner = (await self._signup(hosted_client, "owner@x.com")).json()
        convo_id = await self._seed_conversation(
            hosted_db, owner["org_id"], owner["id"]
        )
        hosted_client.cookies.clear()
        await self._signup(hosted_client, "intruder@x.com")
        assert (
            await hosted_client.get(f"/api/conversations/{convo_id}")
        ).status_code == 404
        assert (await hosted_client.get("/api/conversations")).json() == []
