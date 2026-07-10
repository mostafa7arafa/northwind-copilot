"""Credit accounting: pre-flight checks, settlement, and grants.

The ledger (``credit_ledger``) is the auditable source of truth; the cached
``orgs.credit_balance`` column is updated in the same transaction under
``SELECT ... FOR UPDATE`` (a real row lock on Postgres; a no-op on the SQLite
dev/test backend) so concurrent turns can't double-spend.

Three settlement modes, decided per turn:

* **Metered** (paid plan, our provider key): usage event + ledger debit.
* **BYOK** (org's own stored key): usage event with ``byok=True, credits=0``,
  no ledger write — recorded for fair-use analytics only.
* **Trial** (no credit grant yet): usage event with the real credit cost for
  visibility, no ledger write — the trial is capped by days and query count,
  not by balance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northwind_copilot.billing.entitlements import get_entitlements
from northwind_copilot.metering.pricing import credits_for
from northwind_copilot.metering.usage import UsageAccumulator
from northwind_copilot.tenancy.models import CreditLedger, Org, UsageEvent

_PAYMENT_REQUIRED = status.HTTP_402_PAYMENT_REQUIRED


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def trial_queries_used(session: AsyncSession, org_id: str) -> int:
    """Count the org's metered (non-BYOK) turns — the trial query counter."""
    return (
        await session.execute(
            select(func.count())
            .select_from(UsageEvent)
            .where(UsageEvent.org_id == org_id, UsageEvent.byok.is_(False))
        )
    ).scalar_one()


async def check_and_reserve(
    session: AsyncSession, *, org_id: str, plan: str, byok: bool
) -> None:
    """Pre-flight allowance check before running a chat turn.

    BYOK turns bypass every credit check (the org spends its own provider
    account). Trial turns are capped by trial expiry and query count; paid
    turns require a positive credit balance.

    Args:
        session: An open application-database session.
        org_id: The caller's org.
        plan: The org's plan string.
        byok: Whether this turn runs on the org's own stored key.

    Raises:
        HTTPException: 402 when the allowance is exhausted.
    """
    if byok:
        return
    ent = get_entitlements(plan)
    org = await session.get(Org, org_id)
    if org is None:  # pragma: no cover - ctx already proved the org exists
        raise HTTPException(status_code=_PAYMENT_REQUIRED, detail="No organisation.")

    if ent.credits_per_month == 0:  # trial: days + query cap, not balance
        ends = org.trial_ends_at
        if ends is not None and ends.tzinfo is None:
            ends = ends.replace(tzinfo=timezone.utc)
        if ends is not None and ends < _utcnow():
            raise HTTPException(
                status_code=_PAYMENT_REQUIRED,
                detail="Your trial has ended. Upgrade to keep asking questions.",
            )
        used = await trial_queries_used(session, org_id)
        if used >= ent.trial_queries:
            raise HTTPException(
                status_code=_PAYMENT_REQUIRED,
                detail="Your trial's query allowance is used up. "
                "Upgrade to keep asking questions.",
            )
        return

    if Decimal(org.credit_balance) <= 0:
        raise HTTPException(
            status_code=_PAYMENT_REQUIRED,
            detail="You're out of credits for this billing period. "
            "Upgrade your plan or add your own API key.",
        )


async def settle(
    session: AsyncSession,
    *,
    org_id: str,
    plan: str,
    turn_id: str | None,
    provider: str,
    model: str,
    usage: UsageAccumulator,
    byok: bool,
) -> tuple[Decimal, Decimal | None]:
    """Record one turn's usage and debit the ledger when metered.

    Called from the chat endpoint's ``finally`` path (the same path that
    persists the turn), so usage is settled even when the client disconnects
    or the turn times out mid-stream.

    Args:
        session: An open application-database session.
        org_id: The org that ran the turn.
        plan: The org's plan string.
        turn_id: The persisted turn's id, when available.
        provider: The inference provider that served the turn.
        model: The model id that served the turn.
        usage: The turn's accumulated token counts.
        byok: Whether the turn ran on the org's own stored key.

    Returns:
        ``(credits_used, credits_remaining)``. ``credits_remaining`` is the
        updated balance for metered turns and ``None`` otherwise (BYOK/trial
        turns don't touch the ledger).
    """
    cost = credits_for(model, usage.input_tokens, usage.output_tokens)
    metered = not byok and get_entitlements(plan).credits_per_month > 0

    session.add(
        UsageEvent(
            org_id=org_id,
            turn_id=turn_id,
            provider=provider,
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            credits=Decimal("0") if byok else cost,
            byok=byok,
        )
    )
    if byok:
        return Decimal("0"), None
    if not metered:
        return cost, None

    # Lock the org row so concurrent turns serialise their balance updates.
    org = (
        await session.execute(select(Org).where(Org.id == org_id).with_for_update())
    ).scalar_one()
    balance = Decimal(org.credit_balance) - cost
    session.add(
        CreditLedger(org_id=org_id, delta=-cost, reason="usage", balance_after=balance)
    )
    org.credit_balance = balance
    return cost, balance


async def grant_credits(
    session: AsyncSession,
    *,
    org_id: str,
    amount: Decimal,
    reason: str = "grant",
) -> Decimal:
    """Add credits to an org (plan activation, renewal, manual adjustment).

    Args:
        session: An open application-database session.
        org_id: The org to credit.
        amount: The credit delta (positive to grant, negative to claw back).
        reason: Ledger reason: ``grant`` | ``adjustment`` | ``rollover_expiry``.

    Returns:
        The updated balance.
    """
    org = (
        await session.execute(select(Org).where(Org.id == org_id).with_for_update())
    ).scalar_one()
    balance = Decimal(org.credit_balance) + amount
    session.add(
        CreditLedger(org_id=org_id, delta=amount, reason=reason, balance_after=balance)
    )
    org.credit_balance = balance
    return balance
