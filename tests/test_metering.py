"""Tests for token metering: pricing, accumulation, and the credit ledger."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from northwind_copilot.metering.pricing import (
    DEFAULT_PRICE,
    credits_for,
    price_for,
)
from northwind_copilot.metering.usage import UsageAccumulator


class TestPricing:
    def test_known_model(self):
        assert price_for("gpt-4.1-mini") != DEFAULT_PRICE

    def test_openrouter_prefix_is_normalised(self):
        assert price_for("openai/gpt-4.1-mini") == price_for("gpt-4.1-mini")

    def test_unknown_model_uses_conservative_default(self):
        assert price_for("some/mystery-model") == DEFAULT_PRICE

    def test_credits_math(self):
        # 100k in + 20k out on gpt-4.1-mini = $0.04 + $0.032 = $0.072 → 7.2 cr.
        assert credits_for("gpt-4.1-mini", 100_000, 20_000) == Decimal("7.2000")

    def test_zero_usage_costs_nothing(self):
        assert credits_for("gpt-4.1-mini", 0, 0) == Decimal("0.0000")


class _Msg:
    def __init__(self, msg_id, input_tokens, output_tokens):
        self.id = msg_id
        self.usage_metadata = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }


class TestUsageAccumulator:
    def test_sums_across_messages(self):
        meter = UsageAccumulator()
        meter.observe(_Msg("a", 100, 10))
        meter.observe(_Msg("b", 200, 20))
        assert (meter.input_tokens, meter.output_tokens) == (300, 30)
        assert meter.has_usage

    def test_deduplicates_by_message_id(self):
        meter = UsageAccumulator()
        meter.observe(_Msg("a", 100, 10))
        meter.observe(_Msg("a", 100, 10))
        assert meter.input_tokens == 100

    def test_ignores_messages_without_usage(self):
        meter = UsageAccumulator()
        meter.observe(object())
        assert not meter.has_usage


async def _make_org(plan="trial", balance=0, trial_ends=None):
    """Create a user+org directly in the app DB; returns the org id."""
    from northwind_copilot.tenancy.db import get_sessionmaker
    from northwind_copilot.tenancy.models import Org, User

    async with get_sessionmaker()() as session:
        user = User(email=f"{plan}{balance}@t.co", password_hash="x")
        session.add(user)
        await session.flush()
        org = Org(
            name="t",
            owner_user_id=user.id,
            plan=plan,
            credit_balance=balance,
            trial_ends_at=trial_ends,
        )
        session.add(org)
        await session.commit()
        return org.id


def _meter(input_tokens=10_000, output_tokens=2_000) -> UsageAccumulator:
    meter = UsageAccumulator()
    meter.observe(_Msg("m1", input_tokens, output_tokens))
    return meter


class TestCheckAndReserve:
    async def test_byok_bypasses_everything(self, hosted_db):
        from northwind_copilot.metering.credits import check_and_reserve
        from northwind_copilot.tenancy.db import get_sessionmaker

        org_id = await _make_org(plan="starter", balance=0)
        async with get_sessionmaker()() as session:
            await check_and_reserve(session, org_id=org_id, plan="starter", byok=True)

    async def test_paid_plan_requires_positive_balance(self, hosted_db):
        from northwind_copilot.metering.credits import check_and_reserve
        from northwind_copilot.tenancy.db import get_sessionmaker

        org_id = await _make_org(plan="starter", balance=0)
        async with get_sessionmaker()() as session:
            with pytest.raises(HTTPException) as err:
                await check_and_reserve(
                    session, org_id=org_id, plan="starter", byok=False
                )
        assert err.value.status_code == 402

    async def test_paid_plan_with_balance_passes(self, hosted_db):
        from northwind_copilot.metering.credits import check_and_reserve
        from northwind_copilot.tenancy.db import get_sessionmaker

        org_id = await _make_org(plan="pro", balance=5)
        async with get_sessionmaker()() as session:
            await check_and_reserve(session, org_id=org_id, plan="pro", byok=False)

    async def test_expired_trial_is_rejected(self, hosted_db):
        from northwind_copilot.metering.credits import check_and_reserve
        from northwind_copilot.tenancy.db import get_sessionmaker

        org_id = await _make_org(
            plan="trial",
            trial_ends=datetime.now(timezone.utc) - timedelta(days=1),
        )
        async with get_sessionmaker()() as session:
            with pytest.raises(HTTPException) as err:
                await check_and_reserve(
                    session, org_id=org_id, plan="trial", byok=False
                )
        assert err.value.status_code == 402

    async def test_trial_query_cap(self, hosted_db):
        from northwind_copilot.billing.entitlements import get_entitlements
        from northwind_copilot.metering.credits import check_and_reserve
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import UsageEvent

        org_id = await _make_org(
            plan="trial",
            trial_ends=datetime.now(timezone.utc) + timedelta(days=7),
        )
        limit = get_entitlements("trial").trial_queries
        async with get_sessionmaker()() as session:
            for _ in range(limit):
                session.add(UsageEvent(org_id=org_id, byok=False))
            await session.commit()
        async with get_sessionmaker()() as session:
            with pytest.raises(HTTPException) as err:
                await check_and_reserve(
                    session, org_id=org_id, plan="trial", byok=False
                )
        assert err.value.status_code == 402


class TestSettle:
    async def test_metered_turn_debits_ledger_and_balance(self, hosted_db):
        from northwind_copilot.metering.credits import settle
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import CreditLedger, Org, UsageEvent

        org_id = await _make_org(plan="starter", balance=300)
        async with get_sessionmaker()() as session:
            cost, remaining = await settle(
                session,
                org_id=org_id,
                plan="starter",
                turn_id=None,
                provider="openrouter",
                model="openai/gpt-4.1-mini",
                usage=_meter(),
                byok=False,
            )
            await session.commit()
        assert cost > 0
        assert remaining == Decimal("300") - cost

        async with get_sessionmaker()() as session:
            org = await session.get(Org, org_id)
            assert Decimal(org.credit_balance) == remaining
            ledger = (
                (
                    await session.execute(
                        select(CreditLedger).where(CreditLedger.org_id == org_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(ledger) == 1
            assert Decimal(ledger[0].delta) == -cost
            assert ledger[0].reason == "usage"
            event = (
                (
                    await session.execute(
                        select(UsageEvent).where(UsageEvent.org_id == org_id)
                    )
                )
                .scalars()
                .one()
            )
            assert event.input_tokens == 10_000
            assert not event.byok

    async def test_byok_turn_records_event_but_never_charges(self, hosted_db):
        from northwind_copilot.metering.credits import settle
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import CreditLedger, Org, UsageEvent

        org_id = await _make_org(plan="pro", balance=100)
        async with get_sessionmaker()() as session:
            cost, remaining = await settle(
                session,
                org_id=org_id,
                plan="pro",
                turn_id=None,
                provider="openai",
                model="gpt-4.1",
                usage=_meter(),
                byok=True,
            )
            await session.commit()
        assert cost == Decimal("0")
        assert remaining is None
        async with get_sessionmaker()() as session:
            event = (
                (
                    await session.execute(
                        select(UsageEvent).where(UsageEvent.org_id == org_id)
                    )
                )
                .scalars()
                .one()
            )
            assert event.byok
            assert Decimal(event.credits) == Decimal("0")
            assert (
                await session.execute(
                    select(CreditLedger).where(CreditLedger.org_id == org_id)
                )
            ).first() is None
            org = await session.get(Org, org_id)
            assert Decimal(org.credit_balance) == Decimal("100")

    async def test_trial_turn_records_cost_without_ledger(self, hosted_db):
        from northwind_copilot.metering.credits import settle
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import CreditLedger, UsageEvent

        org_id = await _make_org(plan="trial")
        async with get_sessionmaker()() as session:
            cost, remaining = await settle(
                session,
                org_id=org_id,
                plan="trial",
                turn_id=None,
                provider="openrouter",
                model="openai/gpt-4.1-mini",
                usage=_meter(),
                byok=False,
            )
            await session.commit()
        assert cost > 0
        assert remaining is None
        async with get_sessionmaker()() as session:
            event = (
                (
                    await session.execute(
                        select(UsageEvent).where(UsageEvent.org_id == org_id)
                    )
                )
                .scalars()
                .one()
            )
            assert Decimal(event.credits) == cost  # visible cost, no charge
            assert (
                await session.execute(
                    select(CreditLedger).where(CreditLedger.org_id == org_id)
                )
            ).first() is None

    async def test_grant_credits(self, hosted_db):
        from northwind_copilot.metering.credits import grant_credits
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import CreditLedger, Org

        org_id = await _make_org(plan="starter", balance=0)
        async with get_sessionmaker()() as session:
            balance = await grant_credits(session, org_id=org_id, amount=Decimal("300"))
            await session.commit()
        assert balance == Decimal("300")
        async with get_sessionmaker()() as session:
            org = await session.get(Org, org_id)
            assert Decimal(org.credit_balance) == Decimal("300")
            row = (
                (
                    await session.execute(
                        select(CreditLedger).where(CreditLedger.org_id == org_id)
                    )
                )
                .scalars()
                .one()
            )
            assert row.reason == "grant"
            assert Decimal(row.balance_after) == Decimal("300")
