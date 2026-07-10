"""The tier sheet and the FastAPI gates that enforce it.

Plans are defined in code (provider-agnostic — Paddle in Phase 2 only flips
``orgs.plan``), as one frozen dataclass per tier. Everything a route needs to
enforce lives here: dataset count/size quotas, BYOK availability, seats, and
the trial's day-and-query caps. Credit *balance* checks live in
``metering.credits`` (they need the ledger); this module is pure policy.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status

from northwind_copilot.tenancy.deps import RequestContext, current_org

_MB = 1024 * 1024


@dataclass(frozen=True)
class Entitlements:
    """What one plan tier allows.

    Attributes:
        credits_per_month: Monthly metered-credit grant. 0 for the trial,
            which is capped by ``trial_days``/``trial_queries`` instead.
        max_datasets: How many datasets the org may keep (uploads; the shared
            sample doesn't count).
        upload_cap_bytes: Per-file upload size ceiling.
        byok: Whether the org may store its own provider key.
        seats: Included seats (enforced once org invites ship).
        trial_days: Trial length in days (trial tier only).
        trial_queries: Trial query allowance (trial tier only).
        price_usd: Monthly price, for display.
    """

    credits_per_month: int
    max_datasets: int
    upload_cap_bytes: int
    byok: bool
    seats: int
    trial_days: int = 0
    trial_queries: int = 0
    price_usd: int = 0


PLANS: dict[str, Entitlements] = {
    "trial": Entitlements(
        credits_per_month=0,
        max_datasets=1,
        upload_cap_bytes=10 * _MB,
        byok=False,
        seats=1,
        trial_days=14,
        trial_queries=30,
    ),
    "starter": Entitlements(
        credits_per_month=300,
        max_datasets=3,
        upload_cap_bytes=50 * _MB,
        byok=True,
        seats=1,
        price_usd=15,
    ),
    "pro": Entitlements(
        credits_per_month=1200,
        max_datasets=10,
        upload_cap_bytes=200 * _MB,
        byok=True,
        seats=1,
        price_usd=29,
    ),
    "team": Entitlements(
        credits_per_month=4000,
        max_datasets=25,
        upload_cap_bytes=500 * _MB,
        byok=True,
        seats=5,
        price_usd=69,
    ),
}


def get_entitlements(plan: str) -> Entitlements:
    """Resolve a plan string to its entitlements (unknown plans → trial)."""
    return PLANS.get(plan, PLANS["trial"])


def require_entitlement(feature: str):
    """Build a FastAPI dependency that gates a route on a boolean entitlement.

    Args:
        feature: The `Entitlements` field to require (e.g. ``"byok"``).

    Returns:
        A dependency that resolves the caller's org and raises 403 when the
        org's plan lacks the feature; otherwise returns the request context.
    """

    async def guard(
        ctx: RequestContext = Depends(current_org),
    ) -> RequestContext:
        if not getattr(get_entitlements(ctx.plan), feature, False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This feature isn't included in your plan. "
                "Upgrade to unlock it.",
            )
        return ctx

    return guard


def ensure_upload_allowed(plan: str, *, dataset_count: int, file_bytes: int) -> None:
    """Enforce the plan's dataset-count and upload-size quotas.

    Args:
        plan: The org's plan string.
        dataset_count: How many datasets the org already has.
        file_bytes: The incoming file's size.

    Raises:
        HTTPException: 403 when the dataset quota is reached, 413 when the
            file exceeds the plan's upload cap.
    """
    ent = get_entitlements(plan)
    if dataset_count >= ent.max_datasets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Your plan allows {ent.max_datasets} "
            f"dataset{'s' if ent.max_datasets != 1 else ''}. "
            "Delete one or upgrade to add more.",
        )
    if file_bytes > ent.upload_cap_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds your plan's "
            f"{ent.upload_cap_bytes // _MB}MB upload limit.",
        )
