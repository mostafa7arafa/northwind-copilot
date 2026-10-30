"""Loopback-only access and in-memory rate limiting for the personal app."""

from __future__ import annotations

import ipaddress
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

from northwind_copilot.core.config import settings


def _loopback(host: str | None) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


async def require_access(request: Request) -> None:
    """Reject remote peers, DNS rebinding, and foreign browser origins.

    Forwarded headers cannot grant access, and non-loopback forwarded addresses
    are rejected even behind a local proxy. Origin-less local CLI requests remain
    supported; this is not a LAN/public service.
    """
    forwarded = request.headers.getlist("x-forwarded-for")
    try:
        allowed_forwarded = len(forwarded) <= 1 and all(
            ipaddress.ip_address(value.strip()).is_loopback for value in forwarded
        )
    except ValueError:
        allowed_forwarded = False
    origin = request.headers.get("origin")
    allowed_origin = not origin or (
        origin in settings.cors_origins_list and _loopback(urlsplit(origin).hostname)
    )
    if (
        not request.client
        or not _loopback(request.client.host)
        or not _loopback(request.url.hostname)
        or not allowed_origin
        or not allowed_forwarded
        or request.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise HTTPException(status_code=403, detail="Local access only.")


class RateLimiter:
    """A per-client sliding-window request limiter (in-memory)."""

    def __init__(self, max_per_minute: int) -> None:
        """Initialise the limiter.

        Args:
            max_per_minute: Maximum requests allowed per client per 60 seconds.
        """
        self._max = max_per_minute
        self._window = 60.0
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, client_id: str) -> None:
        """Record a hit for ``client_id`` and enforce the window.

        Args:
            client_id: A stable identifier for the caller (e.g. remote IP).

        Raises:
            HTTPException: 429 when the client exceeds the configured rate.
        """
        if self._max <= 0:
            return  # Disabled.
        now = time.monotonic()
        hits = self._hits[client_id]
        cutoff = now - self._window
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= self._max:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Try again shortly.",
                headers={"Retry-After": "60"},
            )
        hits.append(now)


_limiter = RateLimiter(settings.rate_limit_per_minute)


async def rate_limit(request: Request) -> None:
    """FastAPI dependency enforcing the per-client chat rate limit.

    Args:
        request: The incoming request (used for the client host).

    Raises:
        HTTPException: 429 when the caller exceeds the configured rate.
    """
    client_id = request.client.host if request.client else "unknown"
    _limiter.check(client_id)
