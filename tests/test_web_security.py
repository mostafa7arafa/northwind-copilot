"""Loopback, origin, DNS-rebinding, and rate-limit guards."""

from __future__ import annotations

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from northwind_copilot.web import security
from northwind_copilot.web.app import app


def _request(peer="127.0.0.1", host="localhost:8000", origin=None, extra=()):
    headers = [(b"host", host.encode()), *extra]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    return Request(
        {
            "type": "http",
            "scheme": "http",
            "path": "/api/chat",
            "headers": headers,
            "client": (peer, 12345),
            "server": ("localhost", 8000),
            "query_string": b"",
        }
    )


class TestRequireAccess:
    @pytest.mark.parametrize(
        "peer,host",
        [
            ("127.0.0.1", "localhost:8000"),
            ("::1", "[::1]:8000"),
            ("127.0.0.1", "127.0.0.1:8000"),
        ],
    )
    async def test_local_cli_allowed(self, peer, host):
        await security.require_access(_request(peer, host))

    async def test_local_browser_allowed(self):
        await security.require_access(_request(origin="http://localhost:3000"))

    @pytest.mark.parametrize(
        "incoming",
        [
            _request(peer="192.168.1.3"),
            _request(host="attacker.example"),
            _request(origin="https://attacker.example"),
            _request(origin="null"),
            _request(origin="http://localhost:9999"),
            _request(extra=[(b"sec-fetch-site", b"cross-site")]),
            _request(peer="192.168.1.3", extra=[(b"x-forwarded-for", b"127.0.0.1")]),
        ],
    )
    async def test_untrusted_requests_denied(self, incoming):
        with pytest.raises(HTTPException) as exc:
            await security.require_access(incoming)
        assert exc.value.status_code == 403

    @pytest.mark.parametrize(
        "forwarded",
        [
            "192.168.1.3",
            "203.0.113.1",
            "127.0.0.1, 192.168.1.3",
            "unknown",
            "",
            "localhost",
        ],
    )
    async def test_remote_or_invalid_forwarded_address_denied(self, forwarded):
        incoming = _request(extra=[(b"x-forwarded-for", forwarded.encode())])
        with pytest.raises(HTTPException) as exc:
            await security.require_access(incoming)
        assert exc.value.status_code == 403

    @pytest.mark.parametrize("forwarded", ["127.0.0.1", "::1", " 127.0.0.1 "])
    async def test_loopback_forwarded_address_allowed(self, forwarded):
        await security.require_access(
            _request(extra=[(b"x-forwarded-for", forwarded.encode())])
        )

    async def test_any_remote_forwarded_header_denied(self):
        incoming = _request(
            extra=[
                (b"x-forwarded-for", b"127.0.0.1"),
                (b"x-forwarded-for", b"192.168.1.3"),
            ]
        )
        with pytest.raises(HTTPException) as exc:
            await security.require_access(incoming)
        assert exc.value.status_code == 403

    def test_guard_covers_product_endpoints_without_spending(self, monkeypatch):
        def unexpected():
            pytest.fail("guard must run before cloud fallback or persistence")

        from northwind_copilot.web import app as app_module

        monkeypatch.setattr(app_module, "_build_fallback", unexpected)
        client = TestClient(app, base_url="http://localhost", client=("192.168.1.3", 1))
        for method, path, body in [
            ("GET", "/api/models", None),
            ("GET", "/api/preferences", None),
            ("GET", "/api/datasets", None),
            ("GET", "/api/conversations", None),
            ("POST", "/api/chat", {"messages": [{"role": "user", "content": "hi"}]}),
        ]:
            assert client.request(method, path, json=body).status_code == 403
        assert client.get("/api/health").status_code == 200


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
