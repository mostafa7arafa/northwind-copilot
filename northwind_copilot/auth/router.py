"""Authentication routes: signup, login, logout, and the current-user probe.

Signup atomically provisions a personal org and an owner membership, so every
user has a tenant from the first request. Sessions are delivered as an httpOnly
cookie; the response bodies never contain the token.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northwind_copilot.auth.service import (
    COOKIE_NAME,
    hash_password,
    mint_session_token,
    verify_password,
)
from northwind_copilot.core.config import settings
from northwind_copilot.tenancy.db import get_session
from northwind_copilot.tenancy.deps import current_user
from northwind_copilot.tenancy.models import Org, OrgMember, User

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Trial length granted at signup.
_TRIAL_DAYS = 14


class SignupRequest(BaseModel):
    """A new-account request."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=200)


class LoginRequest(BaseModel):
    """A sign-in request."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    """Public view of the signed-in user and their org."""

    id: str
    email: str
    name: str
    org_id: str
    plan: str


def _set_session_cookie(response: Response, user_id: str) -> None:
    """Attach the httpOnly session cookie for ``user_id`` to ``response``."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=mint_session_token(user_id),
        max_age=settings.jwt_expiry_minutes * 60,
        httponly=True,
        # Secure in the hosted product (always HTTPS behind Caddy); relaxed in
        # local dev so the cookie works over plain http://localhost.
        secure=settings.hosted_mode,
        samesite="lax",
        path="/",
    )


async def _provision_user(session: AsyncSession, req: SignupRequest) -> User:
    """Create a user, a personal org, and an owner membership."""
    from northwind_copilot.tenancy.models import _utcnow  # local: avoid cycle

    user = User(
        email=req.email.lower(),
        password_hash=hash_password(req.password),
        name=req.name,
    )
    session.add(user)
    await session.flush()  # assign user.id

    org = Org(
        name=req.name or req.email.split("@")[0],
        owner_user_id=user.id,
        plan="trial",
        trial_ends_at=_utcnow() + timedelta(days=_TRIAL_DAYS),
    )
    session.add(org)
    await session.flush()  # assign org.id

    session.add(OrgMember(org_id=org.id, user_id=user.id, role="owner"))
    return user


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def signup(
    req: SignupRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    """Create an account (+ personal org) and start a session."""
    existing = (
        await session.execute(select(User).where(User.email == req.email.lower()))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )
    user = await _provision_user(session, req)
    await session.flush()
    org_id = (
        await session.execute(
            select(OrgMember.org_id).where(OrgMember.user_id == user.id)
        )
    ).scalar_one()
    _set_session_cookie(response, user.id)
    return UserOut(
        id=user.id, email=user.email, name=user.name, org_id=org_id, plan="trial"
    )


@router.post("/login", response_model=UserOut)
async def login(
    req: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    """Verify credentials and start a session."""
    user = (
        await session.execute(select(User).where(User.email == req.email.lower()))
    ).scalar_one_or_none()
    if (
        user is None
        or not user.password_hash
        or not verify_password(req.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    row = (
        await session.execute(
            select(OrgMember.org_id, Org.plan)
            .join(Org, Org.id == OrgMember.org_id)
            .where(OrgMember.user_id == user.id)
            .order_by(OrgMember.created_at)
            .limit(1)
        )
    ).first()
    org_id, plan = (row[0], row[1]) if row else ("", "trial")
    _set_session_cookie(response, user.id)
    return UserOut(
        id=user.id, email=user.email, name=user.name, org_id=org_id, plan=plan
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    """Clear the session cookie."""
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut)
async def me(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    """Return the signed-in user and their active org."""
    row = (
        await session.execute(
            select(OrgMember.org_id, Org.plan)
            .join(Org, Org.id == OrgMember.org_id)
            .where(OrgMember.user_id == user.id)
            .order_by(OrgMember.created_at)
            .limit(1)
        )
    ).first()
    org_id, plan = (row[0], row[1]) if row else ("", "trial")
    return UserOut(
        id=user.id, email=user.email, name=user.name, org_id=org_id, plan=plan
    )
