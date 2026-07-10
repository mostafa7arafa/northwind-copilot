"""Billing API: plans, checkout, portal, and the webhook receiver.

The routes are provider-agnostic — they call whatever ``get_provider()``
resolves. The two ``/mock/*`` endpoints exist only while ``BILLING_PROVIDER``
is ``mock`` (they 404 otherwise): ``complete`` is where the mock's "hosted
checkout" lands, and ``simulate`` lets you drive renewals, payment failures,
and cancellations through the same webhook pipeline for validation.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from northwind_copilot.billing.entitlements import PLANS
from northwind_copilot.billing.provider import WebhookError, get_provider
from northwind_copilot.billing.service import BillingApplyError, apply_event
from northwind_copilot.core.config import settings
from northwind_copilot.tenancy.db import get_session
from northwind_copilot.tenancy.deps import RequestContext, current_org

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])

_MB = 1024 * 1024


class CheckoutRequest(BaseModel):
    """Which plan the caller wants to buy."""

    plan: Literal["starter", "pro", "team"]


class SimulateRequest(BaseModel):
    """A lifecycle event to simulate against the caller's own org (mock only)."""

    kind: Literal["renewed", "payment_failed", "cancelled"]


@router.get("/plans")
async def list_plans() -> list[dict]:
    """The public tier sheet (drives the pricing/upgrade UI)."""
    return [
        {
            "id": plan_id,
            "price_usd": ent.price_usd,
            "credits_per_month": ent.credits_per_month,
            "max_datasets": ent.max_datasets,
            "upload_cap_mb": ent.upload_cap_bytes // _MB,
            "byok": ent.byok,
            "seats": ent.seats,
            "trial_days": ent.trial_days,
            "trial_queries": ent.trial_queries,
        }
        for plan_id, ent in PLANS.items()
    ]


@router.post("/checkout")
async def checkout(
    body: CheckoutRequest,
    ctx: RequestContext = Depends(current_org),
) -> dict:
    """Return the URL the browser should open to buy the plan.

    With the mock provider this is a same-origin URL that completes
    instantly; with a real provider it is the hosted checkout page. The
    frontend treats both identically.
    """
    url = get_provider().create_checkout_url(org_id=ctx.org_id, plan=body.plan)
    return {"checkout_url": url}


@router.get("/portal")
async def portal(ctx: RequestContext = Depends(current_org)) -> dict:
    """The provider's self-serve billing portal URL (null for the mock)."""
    return {"portal_url": get_provider().create_portal_url(org_id=ctx.org_id)}


@router.post("/webhook")
async def webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Receive one provider delivery: verify, normalize, apply idempotently.

    Unauthenticated by design — the provider signs the payload and
    ``parse_webhook`` verifies it. Replays answer 200 without reapplying.
    """
    body = await request.body()
    try:
        event = get_provider().parse_webhook(body, dict(request.headers))
        applied = await apply_event(session, event)
    except (WebhookError, BillingApplyError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not applied:
        logger.info("billing webhook replay ignored: %s", event.external_event_id)
    return {"received": True, "applied": applied}


def _require_mock() -> None:
    """The /mock/* endpoints exist only under the mock provider."""
    if settings.billing_provider != "mock":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


@router.get("/mock/complete")
async def mock_complete(
    token: str,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Where the mock's "hosted checkout" lands: apply and bounce back.

    Feeds the signed token through the exact webhook pipeline a real
    provider delivery would take, then redirects into the app. Refreshing
    the page replays the event id and changes nothing.
    """
    _require_mock()
    body = json.dumps({"token": token}).encode("utf-8")
    try:
        event = get_provider().parse_webhook(body, {})
        await apply_event(session, event)
    except (WebhookError, BillingApplyError):
        return RedirectResponse("/?billing=error", status_code=303)
    return RedirectResponse("/?billing=success", status_code=303)


@router.post("/mock/simulate")
async def mock_simulate(
    body: SimulateRequest,
    ctx: RequestContext = Depends(current_org),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Simulate a lifecycle event for the caller's org (validation drills).

    Runs renewal / payment-failure / cancellation through the same signed
    webhook path, so what you validate here is what Paddle will trigger.
    """
    _require_mock()
    from northwind_copilot.billing.mock import MockBillingProvider

    provider = get_provider()
    assert isinstance(provider, MockBillingProvider)
    token = provider.sign_event(kind=body.kind, org_id=ctx.org_id, plan="")
    payload = json.dumps({"token": token}).encode("utf-8")
    try:
        event = provider.parse_webhook(payload, {})
        applied = await apply_event(session, event)
    except BillingApplyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"applied": applied, "kind": body.kind}
