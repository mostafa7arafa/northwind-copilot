"""BYOK key management API: write-only storage of org provider keys.

``PUT`` stores (requires the plan's BYOK entitlement), ``GET`` returns
metadata only (``provider``, ``last4``, ``set_at``), ``DELETE`` clears. The
plaintext key is never returned by any endpoint after write.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from northwind_copilot.billing.entitlements import require_entitlement
from northwind_copilot.keys import service
from northwind_copilot.tenancy.db import get_session
from northwind_copilot.tenancy.deps import RequestContext, current_org

router = APIRouter(prefix="/api/keys", tags=["keys"])

KeyProvider = Literal["openai", "openrouter"]


class KeyOut(BaseModel):
    """Public view of a stored key: metadata only, never the key itself."""

    provider: str
    last4: str
    set_at: datetime


class KeyIn(BaseModel):
    """A key to store. Accepted once, then only ever surfaced as last4."""

    key: str = Field(min_length=8, max_length=512)


@router.get("", response_model=list[KeyOut])
async def get_keys(
    ctx: RequestContext = Depends(current_org),
    session: AsyncSession = Depends(get_session),
) -> list[KeyOut]:
    """List which providers the org has stored keys for."""
    rows = await service.list_keys(session, ctx.org_id)
    return [KeyOut(provider=r.provider, last4=r.last4, set_at=r.set_at) for r in rows]


@router.put("/{provider}", response_model=KeyOut)
async def put_key(
    provider: KeyProvider,
    body: KeyIn,
    ctx: RequestContext = Depends(require_entitlement("byok")),
    session: AsyncSession = Depends(get_session),
) -> KeyOut:
    """Store (or replace) the org's key for a provider. Write-only."""
    try:
        row = await service.store_key(
            session, org_id=ctx.org_id, provider=provider, plaintext=body.key.strip()
        )
    except service.KeyEncryptionUnavailable:
        # Configuration problem, not a user error — and never echo the key.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Key storage is not configured on this server.",
        )
    return KeyOut(provider=row.provider, last4=row.last4, set_at=row.set_at)


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_key(
    provider: KeyProvider,
    ctx: RequestContext = Depends(current_org),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete the org's stored key for a provider."""
    if not await service.delete_key(session, org_id=ctx.org_id, provider=provider):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
