"""Tests for plan entitlements and the BYOK key API."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from northwind_copilot.billing.entitlements import (
    PLANS,
    ensure_upload_allowed,
    get_entitlements,
)


class TestTierSheet:
    def test_every_tier_defined(self):
        assert set(PLANS) == {"trial", "starter", "pro", "team"}

    def test_unknown_plan_falls_back_to_trial(self):
        assert get_entitlements("enterprise-nonsense") is PLANS["trial"]

    def test_trial_has_no_byok(self):
        assert not PLANS["trial"].byok
        assert all(PLANS[p].byok for p in ("starter", "pro", "team"))

    def test_upload_quota_by_count(self):
        with pytest.raises(HTTPException) as err:
            ensure_upload_allowed("trial", dataset_count=1, file_bytes=1)
        assert err.value.status_code == 403

    def test_upload_quota_by_size(self):
        too_big = PLANS["trial"].upload_cap_bytes + 1
        with pytest.raises(HTTPException) as err:
            ensure_upload_allowed("trial", dataset_count=0, file_bytes=too_big)
        assert err.value.status_code == 413

    def test_upload_within_quota_passes(self):
        ensure_upload_allowed("pro", dataset_count=9, file_bytes=1024)


async def _signup(client, email):
    resp = await client.post(
        "/api/auth/signup",
        json={"email": email, "password": "password123", "name": "T"},
    )
    assert resp.status_code == 201
    return resp.json()


async def _set_plan(org_id, plan):
    from northwind_copilot.tenancy.db import get_sessionmaker
    from northwind_copilot.tenancy.models import Org

    async with get_sessionmaker()() as session:
        org = await session.get(Org, org_id)
        org.plan = plan
        await session.commit()


class TestKeysApi:
    async def test_trial_cannot_store_a_key(self, hosted_client, hosted_db):
        await _signup(hosted_client, "trial@x.com")
        resp = await hosted_client.put(
            "/api/keys/openrouter", json={"key": "sk-or-testkey-1234"}
        )
        assert resp.status_code == 403

    async def test_put_get_delete_roundtrip(self, hosted_client, hosted_db):
        me = await _signup(hosted_client, "paid@x.com")
        await _set_plan(me["org_id"], "starter")

        put = await hosted_client.put(
            "/api/keys/openrouter", json={"key": "sk-or-testkey-1234"}
        )
        assert put.status_code == 200
        assert put.json()["last4"] == "1234"
        assert "key" not in put.json()  # write-only: plaintext never returned

        listing = (await hosted_client.get("/api/keys")).json()
        assert [k["provider"] for k in listing] == ["openrouter"]
        assert listing[0]["last4"] == "1234"

        assert (await hosted_client.delete("/api/keys/openrouter")).status_code == 204
        assert (await hosted_client.get("/api/keys")).json() == []

    async def test_key_is_encrypted_at_rest_and_resolvable(
        self, hosted_client, hosted_db
    ):
        from northwind_copilot.keys.service import resolve_org_key
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.models import ApiKey

        me = await _signup(hosted_client, "enc@x.com")
        await _set_plan(me["org_id"], "pro")
        secret = "sk-or-supersecret-9876"
        await hosted_client.put("/api/keys/openrouter", json={"key": secret})

        async with get_sessionmaker()() as session:
            row = (await session.execute(select(ApiKey))).scalars().one()
            assert secret not in row.encrypted_key  # Fernet ciphertext only
            assert row.last4 == "9876"
            assert (
                await resolve_org_key(
                    session, org_id=me["org_id"], provider="openrouter"
                )
                == secret
            )

    async def test_other_org_cannot_see_keys(self, hosted_client, hosted_db):
        me = await _signup(hosted_client, "keyowner@x.com")
        await _set_plan(me["org_id"], "starter")
        await hosted_client.put("/api/keys/openai", json={"key": "sk-owner-key-0001"})
        hosted_client.cookies.clear()
        intruder = await _signup(hosted_client, "intruder@x.com")
        await _set_plan(intruder["org_id"], "starter")
        assert (await hosted_client.get("/api/keys")).json() == []
        # Deleting the other org's provider key hits *their own* (empty) slot.
        assert (await hosted_client.delete("/api/keys/openai")).status_code == 404

    async def test_unknown_provider_rejected(self, hosted_client, hosted_db):
        me = await _signup(hosted_client, "prov@x.com")
        await _set_plan(me["org_id"], "starter")
        resp = await hosted_client.put(
            "/api/keys/anthropic", json={"key": "sk-ant-nope-1234"}
        )
        assert resp.status_code == 422


class TestUsageEndpoint:
    async def test_reports_trial_allowance(self, hosted_client, hosted_db):
        await _signup(hosted_client, "meter@x.com")
        usage = (await hosted_client.get("/api/usage")).json()
        assert usage["hosted"] is True
        assert usage["plan"] == "trial"
        assert usage["trial_queries_limit"] == PLANS["trial"].trial_queries
        assert usage["trial_queries_used"] == 0
        assert usage["credits_remaining"] == 0.0
        assert usage["byok_providers"] == []

    async def test_requires_auth(self, hosted_client, hosted_db):
        hosted_client.cookies.clear()
        assert (await hosted_client.get("/api/usage")).status_code == 401


class TestDatasetUploadGate:
    async def test_trial_second_dataset_rejected(self, hosted_client, hosted_db):
        await _signup(hosted_client, "uploader@x.com")
        csv = b"name,amount\na,1\nb,2\n"
        first = await hosted_client.post(
            "/api/datasets",
            files={"file": ("sales.csv", csv, "text/csv")},
            data={"name": "sales"},
        )
        assert first.status_code == 201
        second = await hosted_client.post(
            "/api/datasets",
            files={"file": ("more.csv", csv, "text/csv")},
            data={"name": "more"},
        )
        assert second.status_code == 403

    async def test_pro_can_hold_several_datasets(self, hosted_client, hosted_db):
        me = await _signup(hosted_client, "pro-up@x.com")
        await _set_plan(me["org_id"], "pro")
        csv = b"name,amount\na,1\n"
        for i in range(3):
            resp = await hosted_client.post(
                "/api/datasets",
                files={"file": (f"d{i}.csv", csv, "text/csv")},
                data={"name": f"d{i}"},
            )
            assert resp.status_code == 201
