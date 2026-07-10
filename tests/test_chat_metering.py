"""End-to-end metering through the hosted chat endpoint (mocked agent)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select


async def _signup(client, email):
    resp = await client.post(
        "/api/auth/signup",
        json={"email": email, "password": "password123", "name": "T"},
    )
    assert resp.status_code == 201
    return resp.json()


def _fake_stream(input_tokens=10_000, output_tokens=2_000):
    """A stand-in for stream_chat that reports token usage like the agent."""

    class _Msg:
        def __init__(self):
            self.id = "m1"
            self.usage_metadata = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }

    async def fake(**kwargs):
        meter = kwargs.get("usage_meter")
        if meter is not None:
            meter.observe(_Msg())
        yield {
            "type": "engine",
            "engine": "cloud",
            "provider": "openrouter",
            "model": "openai/gpt-4.1-mini",
        }
        yield {"type": "final", "text": "42."}
        yield {"type": "done"}

    return fake


def _patch_chat(monkeypatch, stream):
    from northwind_copilot.web import app as app_module

    monkeypatch.setattr(app_module, "stream_chat", stream)
    monkeypatch.setattr(app_module, "load_preferences", lambda: "")


async def _chat(client, **overrides):
    payload = {
        "messages": [{"role": "user", "content": "how much revenue?"}],
        "provider": "openrouter",
        "model": "openai/gpt-4.1-mini",
        **overrides,
    }
    return await client.post("/api/chat", json=payload)


class TestHostedChatMetering:
    async def test_trial_turn_emits_usage_before_done_and_persists_event(
        self, hosted_client, hosted_db, monkeypatch
    ):
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import Turn, UsageEvent

        me = await _signup(hosted_client, "chat@x.com")
        _patch_chat(monkeypatch, _fake_stream())

        resp = await _chat(hosted_client)
        assert resp.status_code == 200
        body = resp.text
        assert '"type": "usage"' in body
        assert body.index('"type": "usage"') < body.index('"type": "done"')
        # Trial: `remaining` counts queries left (30 - 1).
        assert '"remaining": 29' in body

        async with get_sessionmaker()() as session:
            event = (await session.execute(select(UsageEvent))).scalars().one()
            assert event.org_id == me["org_id"]
            assert event.input_tokens == 10_000
            assert event.output_tokens == 2_000
            assert not event.byok
            assert Decimal(event.credits) > 0
            # The usage event is linked to the persisted turn.
            turn = (await session.execute(select(Turn))).scalars().one()
            assert event.turn_id == turn.id

    async def test_byok_turn_is_recorded_but_free(
        self, hosted_client, hosted_db, monkeypatch
    ):
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import CreditLedger, Org, UsageEvent

        me = await _signup(hosted_client, "byok@x.com")
        async with get_sessionmaker()() as session:
            org = await session.get(Org, me["org_id"])
            org.plan = "starter"
            await session.commit()
        stored = await hosted_client.put(
            "/api/keys/openrouter", json={"key": "sk-or-mine-8888"}
        )
        assert stored.status_code == 200

        _patch_chat(monkeypatch, _fake_stream())
        resp = await _chat(hosted_client)
        assert resp.status_code == 200
        assert '"byok": true' in resp.text

        async with get_sessionmaker()() as session:
            event = (await session.execute(select(UsageEvent))).scalars().one()
            assert event.byok
            assert Decimal(event.credits) == Decimal("0")
            assert (await session.execute(select(CreditLedger))).first() is None

    async def test_paid_turn_debits_the_ledger(
        self, hosted_client, hosted_db, monkeypatch
    ):
        from northwind_copilot.metering.credits import grant_credits
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import CreditLedger, Org

        me = await _signup(hosted_client, "paid-chat@x.com")
        async with get_sessionmaker()() as session:
            org = await session.get(Org, me["org_id"])
            org.plan = "starter"
            await grant_credits(session, org_id=me["org_id"], amount=Decimal("300"))
            await session.commit()

        _patch_chat(monkeypatch, _fake_stream())
        resp = await _chat(hosted_client)
        assert resp.status_code == 200
        assert '"type": "usage"' in resp.text

        async with get_sessionmaker()() as session:
            org = await session.get(Org, me["org_id"])
            assert Decimal(org.credit_balance) < Decimal("300")
            reasons = [
                r.reason
                for r in (await session.execute(select(CreditLedger))).scalars().all()
            ]
            assert reasons == ["grant", "usage"]

    async def test_expired_trial_is_rejected_preflight(
        self, hosted_client, hosted_db, monkeypatch
    ):
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import Org

        me = await _signup(hosted_client, "expired@x.com")
        async with get_sessionmaker()() as session:
            org = await session.get(Org, me["org_id"])
            org.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=1)
            await session.commit()

        _patch_chat(monkeypatch, _fake_stream())
        resp = await _chat(hosted_client)
        assert resp.status_code == 402

    async def test_out_of_credits_is_rejected_preflight(
        self, hosted_client, hosted_db, monkeypatch
    ):
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import Org

        me = await _signup(hosted_client, "broke@x.com")
        async with get_sessionmaker()() as session:
            org = await session.get(Org, me["org_id"])
            org.plan = "pro"  # paid plan, zero balance
            await session.commit()

        _patch_chat(monkeypatch, _fake_stream())
        resp = await _chat(hosted_client)
        assert resp.status_code == 402

    async def test_turn_without_usage_costs_nothing(
        self, hosted_client, hosted_db, monkeypatch
    ):
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import UsageEvent

        await _signup(hosted_client, "free-turn@x.com")

        async def silent(**kwargs):  # errors out before any model call
            yield {"type": "error", "message": "boom", "detail": "error_id=x"}
            yield {"type": "done"}

        _patch_chat(monkeypatch, silent)
        resp = await _chat(hosted_client)
        assert resp.status_code == 200
        assert '"type": "usage"' not in resp.text

        async with get_sessionmaker()() as session:
            assert (await session.execute(select(UsageEvent))).first() is None
