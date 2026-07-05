"""The provider-agnostic billing interface.

Everything the app knows about payments goes through ``BillingProvider``:
build a checkout URL, build a portal URL, and turn a webhook delivery into a
``NormalizedEvent``. The lifecycle logic (``billing.service``) only ever sees
normalized events, so adding a real processor (Paddle in Phase 2, Paymob
later) is one new module implementing this protocol plus a branch in
:func:`get_provider` — no changes to routes, service, or frontend.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, Mapping, Protocol

EventKind = Literal["activated", "renewed", "payment_failed", "cancelled"]


class WebhookError(ValueError):
    """Raised when a webhook delivery fails verification or parsing."""


@dataclass(frozen=True)
class NormalizedEvent:
    """One billing lifecycle event, normalized across providers.

    Attributes:
        kind: What happened: ``activated`` (new subscription or plan change),
            ``renewed`` (billing period rolled over), ``payment_failed``,
            or ``cancelled``.
        org_id: The org the subscription belongs to (carried through checkout
            as provider metadata/custom_data).
        plan: The plan the event refers to.
        external_event_id: The provider's unique id for this delivery — the
            idempotency key.
        provider: Which backend delivered the event (``mock`` / ``paddle``).
        external_subscription_id: The provider's subscription id, when known.
    """

    kind: EventKind
    org_id: str
    plan: str
    external_event_id: str
    provider: str = "mock"
    external_subscription_id: str = ""


class BillingProvider(Protocol):
    """What a payment backend must implement."""

    name: str

    def create_checkout_url(self, *, org_id: str, plan: str) -> str:
        """Return the URL the browser should open to buy ``plan``."""
        ...

    def create_portal_url(self, *, org_id: str) -> str | None:
        """Return the provider's self-serve portal URL, or ``None``."""
        ...

    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> NormalizedEvent:
        """Verify and normalize one webhook delivery.

        Raises:
            WebhookError: When the signature is invalid or the payload is
                malformed — the route answers 400 and the provider retries.
        """
        ...


@lru_cache(maxsize=1)
def get_provider() -> BillingProvider:
    """Resolve the configured billing backend (``BILLING_PROVIDER``)."""
    from northwind_copilot.core.config import settings

    if settings.billing_provider == "mock":
        from northwind_copilot.billing.mock import MockBillingProvider

        return MockBillingProvider()
    raise ValueError(f"Unknown billing provider: {settings.billing_provider!r}")
