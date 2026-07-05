"""Apply normalized billing events to plan, subscription, and ledger state.

This is the provider-agnostic half of billing: whatever backend delivered the
event (mock today, Paddle later), the lifecycle is the same —

* ``activated``  → set the org's plan, reset the balance, grant the plan's
  monthly credits, upsert an active subscription.
* ``renewed``    → expire whatever is left (credits don't roll over), grant a
  fresh month.
* ``payment_failed`` → mark the subscription ``past_due`` (the org keeps
  working through the grace period; dunning UX is frontend-side).
* ``cancelled``  → mark cancelled and demote the org to an *expired* trial:
  data stays readable, chat answers 402 until they resubscribe.

Every application is idempotent: the provider's event id is recorded in
``webhook_events`` (unique per provider) before anything changes, so retried
deliveries and refreshed mock redirects are no-ops.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northwind_copilot.billing.entitlements import PLANS, get_entitlements
from northwind_copilot.billing.provider import NormalizedEvent
from northwind_copilot.metering.credits import grant_credits
from northwind_copilot.tenancy.models import Org, Subscription, WebhookEvent

_PERIOD = timedelta(days=30)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BillingApplyError(ValueError):
    """Raised when an event references an unknown org or plan."""


async def _record_event(session: AsyncSession, event: NormalizedEvent) -> bool:
    """Record the delivery id; return False when it was already processed."""
    seen = (
        await session.execute(
            select(WebhookEvent.id).where(
                WebhookEvent.provider == event.provider,
                WebhookEvent.external_event_id == event.external_event_id,
            )
        )
    ).first()
    if seen:
        return False
    session.add(
        WebhookEvent(
            provider=event.provider,
            external_event_id=event.external_event_id,
            kind=event.kind,
            org_id=event.org_id,
        )
    )
    try:
        await session.flush()
    except IntegrityError:
        # A concurrent delivery of the same event won the race.
        await session.rollback()
        return False
    return True


async def _get_subscription(session: AsyncSession, org_id: str) -> Subscription | None:
    return (
        await session.execute(select(Subscription).where(Subscription.org_id == org_id))
    ).scalar_one_or_none()


async def _reset_balance(session: AsyncSession, org_id: str) -> None:
    """Zero the org's balance (credits don't roll over between periods)."""
    org = await session.get(Org, org_id)
    balance = Decimal(org.credit_balance)
    if balance != 0:
        await grant_credits(
            session, org_id=org_id, amount=-balance, reason="rollover_expiry"
        )


async def _start_period(session: AsyncSession, org_id: str, plan: str) -> None:
    """Reset the balance and grant the plan's monthly credits."""
    await _reset_balance(session, org_id)
    monthly = get_entitlements(plan).credits_per_month
    if monthly > 0:
        await grant_credits(
            session, org_id=org_id, amount=Decimal(monthly), reason="grant"
        )


async def apply_event(session: AsyncSession, event: NormalizedEvent) -> bool:
    """Apply one billing event; returns False for duplicate deliveries.

    Raises:
        BillingApplyError: Unknown org, unknown plan, or an event that
            requires a subscription the org doesn't have.
    """
    org = await session.get(Org, event.org_id)
    if org is None:
        raise BillingApplyError("Unknown organisation.")
    if not await _record_event(session, event):
        return False

    if event.kind == "activated":
        if event.plan not in PLANS or event.plan == "trial":
            raise BillingApplyError("Unknown plan.")
        org.plan = event.plan
        await _start_period(session, org.id, event.plan)
        sub = await _get_subscription(session, org.id)
        if sub is None:
            sub = Subscription(org_id=org.id)
            session.add(sub)
        sub.provider = event.provider
        sub.external_id = event.external_subscription_id
        sub.plan = event.plan
        sub.status = "active"
        sub.current_period_end = _utcnow() + _PERIOD

    elif event.kind == "renewed":
        sub = await _get_subscription(session, org.id)
        if sub is None:
            raise BillingApplyError("No subscription to renew.")
        plan = event.plan or sub.plan
        org.plan = plan
        sub.plan = plan
        sub.status = "active"
        sub.current_period_end = _utcnow() + _PERIOD
        await _start_period(session, org.id, plan)

    elif event.kind == "payment_failed":
        sub = await _get_subscription(session, org.id)
        if sub is None:
            raise BillingApplyError("No subscription for this org.")
        sub.status = "past_due"

    elif event.kind == "cancelled":
        sub = await _get_subscription(session, org.id)
        if sub is not None:
            sub.status = "cancelled"
        # Demote to an *expired* trial: chat is blocked (402), data stays
        # readable. (Retention/deletion of cancelled orgs is a later cron.)
        org.plan = "trial"
        org.trial_ends_at = _utcnow()
        await _reset_balance(session, org.id)

    await session.flush()
    return True
