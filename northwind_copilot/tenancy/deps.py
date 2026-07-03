"""Request-scoped tenant context and the FastAPI dependencies that build it.

``current_user`` resolves the session cookie to a ``User`` row; ``current_org``
resolves the user's active org and returns a frozen ``RequestContext`` that the
rest of the request path (chat, datasets, conversations) authorises against.

In the single-user POC (``hosted_mode`` off) these dependencies are not wired
in — the shared-token guard in ``web.security`` stays. They activate only in the
hosted product.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northwind_copilot.auth.service import read_session_token
from northwind_copilot.tenancy.db import get_session
from northwind_copilot.tenancy.models import Org, OrgMember, User


@dataclass(frozen=True)
class RequestContext:
    """The resolved tenant context for one authenticated request.

    Attributes:
        user_id: The authenticated user's id.
        org_id: The active org (tenant) id.
        plan: The org's current plan string (e.g. ``trial``, ``starter``).
        role: The user's role in the org (``owner`` | ``member``).
    """

    user_id: str
    org_id: str
    plan: str
    role: str


_UNAUTH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Authentication required.",
)


async def current_user(
    session: AsyncSession = Depends(get_session),
    nw_session: str | None = Cookie(default=None),
) -> User:
    """Resolve the session cookie to a ``User``.

    Raises:
        HTTPException: 401 when the cookie is missing, invalid, or the user no
            longer exists.
    """
    if not nw_session:
        raise _UNAUTH
    user_id = read_session_token(nw_session)
    if not user_id:
        raise _UNAUTH
    user = await session.get(User, user_id)
    if user is None:
        raise _UNAUTH
    return user


async def load_context(session: AsyncSession, user_id: str) -> RequestContext:
    """Resolve a user's active org into a ``RequestContext``.

    v1 assumes a single (personal) org per user — the first membership. When
    multi-org selection ships, this reads an ``active_org`` claim/header.

    Args:
        session: An open application-database session.
        user_id: The authenticated user's id.

    Returns:
        The resolved tenant context.

    Raises:
        HTTPException: 403 if the user belongs to no org.
    """
    row = (
        await session.execute(
            select(OrgMember, Org)
            .join(Org, Org.id == OrgMember.org_id)
            .where(OrgMember.user_id == user_id)
            .order_by(OrgMember.created_at)
            .limit(1)
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No organisation."
        )
    member, org = row
    return RequestContext(
        user_id=user_id, org_id=org.id, plan=org.plan, role=member.role
    )


async def current_org(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> RequestContext:
    """FastAPI dependency: resolve the signed-in user's active org."""
    return await load_context(session, user.id)
