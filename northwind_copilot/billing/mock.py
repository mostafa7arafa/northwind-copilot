"""A payment backend that mimics the full transaction flow with no money.

The mock walks the exact path a real processor would: checkout returns a URL,
opening it "completes payment", and completion is delivered as a signed
webhook through the same parse → verify → idempotent-apply pipeline Paddle
will use. The only thing missing is the card form.

Tokens are short-lived JWTs signed with ``JWT_SECRET``: the signature plays
the role of Paddle's webhook signature (a tampered payload is rejected), the
``jti`` plays the role of the provider event id (replays are idempotent), and
the expiry bounds how long a checkout link stays usable.
"""

from __future__ import annotations

import json
import uuid
from typing import Mapping

import jwt

from northwind_copilot.billing.provider import NormalizedEvent, WebhookError
from northwind_copilot.core.config import settings

_ALG = "HS256"
_CHECKOUT_TTL_SECONDS = 60 * 60  # a checkout link is valid for one hour
_KINDS = {"activated", "renewed", "payment_failed", "cancelled"}


def _sign(claims: dict) -> str:
    import time

    payload = {
        **claims,
        "jti": uuid.uuid4().hex,
        "exp": int(time.time()) + _CHECKOUT_TTL_SECONDS,
        "iss": "northwind-mock-billing",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALG)


class MockBillingProvider:
    """Instant, signed, idempotent — everything but the money."""

    name = "mock"

    def create_checkout_url(self, *, org_id: str, plan: str) -> str:
        """A same-origin URL that completes the "purchase" when opened.

        The browser navigates here exactly like it would to a Paddle-hosted
        checkout; the endpoint behind it feeds the token through the webhook
        pipeline and redirects back to the app.
        """
        token = _sign({"kind": "activated", "org_id": org_id, "plan": plan})
        return f"/api/billing/mock/complete?token={token}"

    def create_portal_url(self, *, org_id: str) -> str | None:
        """No self-serve portal in the mock — the frontend hides the link."""
        return None

    def sign_event(self, *, kind: str, org_id: str, plan: str) -> str:
        """Sign a lifecycle event token (used to simulate renewals etc.)."""
        return _sign({"kind": kind, "org_id": org_id, "plan": plan})

    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> NormalizedEvent:
        """Verify a mock delivery: ``{"token": <signed jwt>}``."""
        try:
            token = json.loads(body.decode("utf-8"))["token"]
        except (ValueError, KeyError, UnicodeDecodeError) as exc:
            raise WebhookError("Malformed webhook body.") from exc
        try:
            claims = jwt.decode(token, settings.jwt_secret, algorithms=[_ALG])
        except jwt.PyJWTError as exc:
            raise WebhookError("Invalid webhook signature.") from exc
        kind = claims.get("kind", "")
        if kind not in _KINDS or not claims.get("org_id"):
            raise WebhookError("Malformed webhook payload.")
        return NormalizedEvent(
            kind=kind,
            org_id=claims["org_id"],
            plan=claims.get("plan", ""),
            external_event_id=claims["jti"],
            provider=self.name,
            external_subscription_id=f"mock-sub-{claims['org_id'][:8]}",
        )
