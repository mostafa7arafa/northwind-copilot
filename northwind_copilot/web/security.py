"""Request-level guards for the web service: auth and rate limiting.

Both are deliberately lightweight and dependency-free so a self-hosted operator
can stand the service up on a single box without extra infrastructure:

* **Auth** is an optional shared bearer token. When ``APP_AUTH_TOKEN`` is set,
  every request must present it; when unset, the API stays open (the original
  single-user local POC behaviour). This is a deployment boundary, not a full
  multi-user identity system — that arrives with the tenant model.
* **Rate limiting** is an in-memory sliding window keyed by client. It is
  per-process, so it bounds abuse on a single-worker self-host; a multi-worker
  or multi-node deployment should move this to a shared store (e.g. Redis).
"""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request, status

from northwind_copilot.core.config import settings


async def require_auth(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency enforcing the optional shared bearer token.

    Args:
        authorization: The incoming ``Authorization`` header, if any.

    Raises:
        HTTPException: 401 when a token is configured and the header is missing
            or does not match.
    """
    expected = settings.auth_token
    if not expected:
        return  # Open mode: no token configured.

    prefix = "Bearer "
    provided = (
        authorization[len(prefix) :]
        if authorization and authorization.startswith(prefix)
        else ""
    )
    # Constant-time compare so a wrong token can't be recovered by timing.
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )


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
