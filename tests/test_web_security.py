"""Tests for the web-service request guards: auth token and rate limiting."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from northwind_copilot.web import security


def _with_token(monkeypatch, token: str) -> None:
    """Swap the security module's settings for one with the given auth token.

    ``settings`` is a frozen dataclass, so we replace the module-level name
    rather than mutating the instance.
    """
    monkeypatch.setattr(security, "settings", SimpleNamespace(auth_token=token))


class TestRequireAuth:
    def test_open_when_no_token_configured(self, monkeypatch):
        _with_token(monkeypatch, "")
        # No exception == allowed.
        asyncio.run(security.require_auth(authorization=None))

    def test_rejects_missing_header_when_token_set(self, monkeypatch):
        _with_token(monkeypatch, "secret")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(security.require_auth(authorization=None))
        assert exc.value.status_code == 401

    def test_rejects_wrong_token(self, monkeypatch):
        _with_token(monkeypatch, "secret")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(security.require_auth(authorization="Bearer nope"))
        assert exc.value.status_code == 401

    def test_accepts_correct_token(self, monkeypatch):
        _with_token(monkeypatch, "secret")
        asyncio.run(security.require_auth(authorization="Bearer secret"))


class TestRateLimiter:
    def test_allows_up_to_limit_then_blocks(self):
        limiter = security.RateLimiter(max_per_minute=3)
        for _ in range(3):
            limiter.check("1.2.3.4")
        with pytest.raises(HTTPException) as exc:
            limiter.check("1.2.3.4")
        assert exc.value.status_code == 429

    def test_separate_clients_have_separate_budgets(self):
        limiter = security.RateLimiter(max_per_minute=1)
        limiter.check("a")
        limiter.check("b")  # different client, still allowed
        with pytest.raises(HTTPException):
            limiter.check("a")

    def test_zero_disables_limiting(self):
        limiter = security.RateLimiter(max_per_minute=0)
        for _ in range(100):
            limiter.check("x")  # never raises
