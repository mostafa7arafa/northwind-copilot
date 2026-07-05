"""Integration tests for hosted-mode auth and tenant isolation."""

from __future__ import annotations

import pytest


async def _signup(client, email, password="password123", name="Test"):
    return await client.post(
        "/api/auth/signup",
        json={"email": email, "password": password, "name": name},
    )


class TestSignupLogin:
    async def test_signup_creates_account_org_and_session(self, hosted_client):
        resp = await _signup(hosted_client, "a@example.com")
        assert resp.status_code == 201
        body = resp.json()
        assert body["email"] == "a@example.com"
        assert body["org_id"]
        assert body["plan"] == "trial"
        # A session cookie is set (httpOnly, so only visible on the response).
        assert "nw_session" in resp.cookies

    async def test_duplicate_email_rejected(self, hosted_client):
        await _signup(hosted_client, "dup@example.com")
        resp = await _signup(hosted_client, "dup@example.com")
        assert resp.status_code == 409

    async def test_login_with_correct_password(self, hosted_client):
        await _signup(hosted_client, "b@example.com", password="secretpass")
        # Drop the signup cookie so we exercise a fresh login.
        hosted_client.cookies.clear()
        resp = await hosted_client.post(
            "/api/auth/login",
            json={"email": "b@example.com", "password": "secretpass"},
        )
        assert resp.status_code == 200
        assert "nw_session" in resp.cookies

    async def test_login_with_wrong_password_rejected(self, hosted_client):
        await _signup(hosted_client, "c@example.com", password="rightpass")
        hosted_client.cookies.clear()
        resp = await hosted_client.post(
            "/api/auth/login",
            json={"email": "c@example.com", "password": "wrongpass"},
        )
        assert resp.status_code == 401

    async def test_me_requires_session(self, hosted_client):
        resp = await hosted_client.get("/api/auth/me")
        assert resp.status_code == 401

    async def test_me_returns_current_user(self, hosted_client):
        await _signup(hosted_client, "d@example.com")
        resp = await hosted_client.get("/api/auth/me")
        assert resp.status_code == 200
        assert resp.json()["email"] == "d@example.com"

    async def test_logout_clears_session(self, hosted_client):
        await _signup(hosted_client, "e@example.com")
        await hosted_client.post("/api/auth/logout")
        hosted_client.cookies.clear()
        resp = await hosted_client.get("/api/auth/me")
        assert resp.status_code == 401


class TestProtectedRoutes:
    async def test_models_requires_auth_in_hosted_mode(self, hosted_client):
        resp = await hosted_client.get("/api/models")
        assert resp.status_code == 401

    async def test_models_allowed_with_session(self, hosted_client, monkeypatch):
        async def _fake_registry():
            return {"local": {"available": False, "models": []}, "cloud": []}

        from northwind_copilot.web import app as app_module

        monkeypatch.setattr(app_module, "list_all_providers", _fake_registry)
        await _signup(hosted_client, "f@example.com")
        resp = await hosted_client.get("/api/models")
        assert resp.status_code == 200


class TestTenancyIsolation:
    async def test_context_resolves_to_own_org(self, hosted_db):
        # The most important guarantee: a user's resolved context is their own
        # org, never another tenant's. Build two orgs and verify separation at
        # the context-resolution layer (the seam every data route authorises on).
        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.deps import load_context
        from northwind_copilot.tenancy.models import Org, OrgMember, User

        async with get_sessionmaker()() as session:
            u1, u2 = User(email="one@x.com"), User(email="two@x.com")
            session.add_all([u1, u2])
            await session.flush()
            o1 = Org(name="One", owner_user_id=u1.id)
            o2 = Org(name="Two", owner_user_id=u2.id)
            session.add_all([o1, o2])
            await session.flush()
            session.add_all(
                [
                    OrgMember(org_id=o1.id, user_id=u1.id, role="owner"),
                    OrgMember(org_id=o2.id, user_id=u2.id, role="owner"),
                ]
            )
            await session.commit()

            ctx1 = await load_context(session, u1.id)
            ctx2 = await load_context(session, u2.id)

        assert ctx1.org_id == o1.id
        assert ctx2.org_id == o2.id
        assert ctx1.org_id != ctx2.org_id

    async def test_user_without_org_is_forbidden(self, hosted_db):
        from fastapi import HTTPException

        from northwind_copilot.tenancy.db import get_sessionmaker
        from northwind_copilot.tenancy.deps import load_context
        from northwind_copilot.tenancy.models import User

        async with get_sessionmaker()() as session:
            u = User(email="orphan@x.com")
            session.add(u)
            await session.commit()
            with pytest.raises(HTTPException) as exc:
                await load_context(session, u.id)
            assert exc.value.status_code == 403
