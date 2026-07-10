"""Tests for the billing lifecycle through the mock provider.

The mock walks the exact pipeline a real processor will use — checkout URL,
signed webhook, idempotent apply — so these tests validate the lifecycle
logic that stays when Paddle replaces the mock.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from northwind_copilot.billing.entitlements import PLANS


async def _signup(client, email):
    resp = await client.post(
        "/api/auth/signup",
        json={"email": email, "password": "password123", "name": "T"},
    )
    assert resp.status_code == 201
    return resp.json()


async def _buy(client, plan: str) -> str:
    """Run the full mock checkout; returns the redirect target."""
    checkout = await client.post("/api/billing/checkout", json={"plan": plan})
    assert checkout.status_code == 200
    url = checkout.json()["checkout_url"]
    done = await client.get(url)
    assert done.status_code == 303
    return done.headers["location"]


async def _org_state(org_id):
    from northwind_copilot.tenancy.db import get_sessionmaker
    from northwind_copilot.tenancy.models import CreditLedger, Org, Subscription

    async with get_sessionmaker()() as session:
        org = await session.get(Org, org_id)
        sub = (
            await session.execute(
                select(Subscription).where(Subscription.org_id == org_id)
            )
        ).scalar_one_or_none()
        ledger = (
            (
                await session.execute(
                    select(CreditLedger)
                    .where(CreditLedger.org_id == org_id)
                    .order_by(CreditLedger.created_at)
                )
            )
            .scalars()
            .all()
        )
        return org, sub, [(r.reason, Decimal(r.delta)) for r in ledger]


class TestPlansEndpoint:
    async def test_public_tier_sheet(self, hosted_client, hosted_db):
        hosted_client.cookies.clear()
        plans = (await hosted_client.get("/api/billing/plans")).json()
        assert {p["id"] for p in plans} == set(PLANS)
        pro = next(p for p in plans if p["id"] == "pro")
        assert pro["price_usd"] == 29
        assert pro["credits_per_month"] == 1200


class TestCheckout:
    async def test_requires_auth(self, hosted_client, hosted_db):
        hosted_client.cookies.clear()
        resp = await hosted_client.post("/api/billing/checkout", json={"plan": "pro"})
        assert resp.status_code == 401

    async def test_rejects_unknown_plan(self, hosted_client, hosted_db):
        await _signup(hosted_client, "plan@x.com")
        resp = await hosted_client.post(
            "/api/billing/checkout", json={"plan": "enterprise"}
        )
        assert resp.status_code == 422

    async def test_full_purchase_activates_plan_and_grants_credits(
        self, hosted_client, hosted_db
    ):
        me = await _signup(hosted_client, "buyer@x.com")
        location = await _buy(hosted_client, "pro")
        assert location == "/?billing=success"

        org, sub, ledger = await _org_state(me["org_id"])
        assert org.plan == "pro"
        assert Decimal(org.credit_balance) == Decimal(1200)
        assert sub.status == "active"
        assert sub.provider == "mock"
        assert sub.plan == "pro"
        assert sub.current_period_end is not None
        assert ledger == [("grant", Decimal(1200))]

        usage = (await hosted_client.get("/api/usage")).json()
        assert usage["plan"] == "pro"
        assert usage["credits_remaining"] == 1200.0
        assert usage["subscription_status"] == "active"

    async def test_replaying_the_completion_is_idempotent(
        self, hosted_client, hosted_db
    ):
        me = await _signup(hosted_client, "replay@x.com")
        checkout = await hosted_client.post(
            "/api/billing/checkout", json={"plan": "starter"}
        )
        url = checkout.json()["checkout_url"]
        assert (await hosted_client.get(url)).status_code == 303
        # Refreshing the completion page must not grant twice.
        assert (await hosted_client.get(url)).status_code == 303

        org, _, ledger = await _org_state(me["org_id"])
        assert Decimal(org.credit_balance) == Decimal(300)
        assert len(ledger) == 1

    async def test_upgrade_resets_balance_before_new_grant(
        self, hosted_client, hosted_db
    ):
        me = await _signup(hosted_client, "upgrader@x.com")
        await _buy(hosted_client, "starter")
        await _buy(hosted_client, "pro")

        org, sub, ledger = await _org_state(me["org_id"])
        assert org.plan == "pro"
        assert sub.plan == "pro"
        # starter grant, expiry of its remainder, then the pro grant.
        assert [r for r, _ in ledger] == ["grant", "rollover_expiry", "grant"]
        assert Decimal(org.credit_balance) == Decimal(1200)


class TestWebhook:
    async def test_tampered_signature_is_rejected(self, hosted_client, hosted_db):
        hosted_client.cookies.clear()
        import jwt as pyjwt

        forged = pyjwt.encode(
            {"kind": "activated", "org_id": "any", "plan": "team", "jti": "x"},
            "wrong-secret",
            algorithm="HS256",
        )
        resp = await hosted_client.post("/api/billing/webhook", json={"token": forged})
        assert resp.status_code == 400

    async def test_garbage_body_is_rejected(self, hosted_client, hosted_db):
        hosted_client.cookies.clear()
        resp = await hosted_client.post("/api/billing/webhook", content=b"not json")
        assert resp.status_code == 400

    async def test_valid_delivery_applies_once(self, hosted_client, hosted_db):
        from northwind_copilot.billing.provider import get_provider

        me = await _signup(hosted_client, "hook@x.com")
        token = get_provider().sign_event(
            kind="activated", org_id=me["org_id"], plan="team"
        )
        first = await hosted_client.post("/api/billing/webhook", json={"token": token})
        assert first.json() == {"received": True, "applied": True}
        again = await hosted_client.post("/api/billing/webhook", json={"token": token})
        assert again.json() == {"received": True, "applied": False}

        org, _, _ = await _org_state(me["org_id"])
        assert org.plan == "team"
        assert Decimal(org.credit_balance) == Decimal(4000)


class TestLifecycleSimulation:
    async def test_renewal_expires_leftover_and_grants_fresh_month(
        self, hosted_client, hosted_db
    ):
        me = await _signup(hosted_client, "renew@x.com")
        await _buy(hosted_client, "starter")
        resp = await hosted_client.post(
            "/api/billing/mock/simulate", json={"kind": "renewed"}
        )
        assert resp.json()["applied"] is True

        org, sub, ledger = await _org_state(me["org_id"])
        assert sub.status == "active"
        assert [r for r, _ in ledger] == ["grant", "rollover_expiry", "grant"]
        assert Decimal(org.credit_balance) == Decimal(300)

    async def test_payment_failed_marks_past_due_but_keeps_service(
        self, hosted_client, hosted_db
    ):
        await _signup(hosted_client, "dunning@x.com")
        await _buy(hosted_client, "pro")
        await hosted_client.post(
            "/api/billing/mock/simulate", json={"kind": "payment_failed"}
        )
        usage = (await hosted_client.get("/api/usage")).json()
        assert usage["subscription_status"] == "past_due"
        assert usage["plan"] == "pro"  # grace: plan unchanged

    async def test_cancellation_demotes_to_expired_trial_and_blocks_chat(
        self, hosted_client, hosted_db, monkeypatch
    ):
        me = await _signup(hosted_client, "quitter@x.com")
        await _buy(hosted_client, "starter")
        await hosted_client.post(
            "/api/billing/mock/simulate", json={"kind": "cancelled"}
        )

        org, sub, ledger = await _org_state(me["org_id"])
        assert sub.status == "cancelled"
        assert org.plan == "trial"
        assert Decimal(org.credit_balance) == Decimal(0)
        assert ledger[-1][0] == "rollover_expiry"

        # Chat is blocked (402) but data endpoints still work.
        from northwind_copilot.web import app as app_module

        async def never_called(**kwargs):  # pragma: no cover
            yield {"type": "done"}

        monkeypatch.setattr(app_module, "stream_chat", never_called)
        monkeypatch.setattr(app_module, "load_preferences", lambda: "")
        chat = await hosted_client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "provider": "openrouter",
                "model": "openai/gpt-4.1-mini",
            },
        )
        assert chat.status_code == 402
        assert (await hosted_client.get("/api/conversations")).status_code == 200

    async def test_renewal_without_subscription_is_rejected(
        self, hosted_client, hosted_db
    ):
        await _signup(hosted_client, "nosub@x.com")
        resp = await hosted_client.post(
            "/api/billing/mock/simulate", json={"kind": "renewed"}
        )
        assert resp.status_code == 400


class TestMockGating:
    async def test_mock_endpoints_404_under_a_real_provider(
        self, hosted_client, hosted_db, monkeypatch
    ):
        import dataclasses

        from northwind_copilot.billing import router as billing_router

        await _signup(hosted_client, "gated@x.com")
        monkeypatch.setattr(
            billing_router,
            "settings",
            dataclasses.replace(billing_router.settings, billing_provider="paddle"),
        )
        resp = await hosted_client.get("/api/billing/mock/complete?token=x")
        assert resp.status_code == 404
        resp = await hosted_client.post(
            "/api/billing/mock/simulate", json={"kind": "renewed"}
        )
        assert resp.status_code == 404
