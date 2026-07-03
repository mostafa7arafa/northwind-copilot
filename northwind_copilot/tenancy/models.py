"""SQLAlchemy models for the application (control-plane) database.

This database holds identity, tenancy, datasets, conversations, and billing —
everything *about* the product. It is separate from the per-tenant SQLite files
that hold each customer's uploaded *data*, which the agent queries read-only.

``org`` is the tenant unit from day one: signup creates a personal org, so
adding team seats later is a row change, not a migration. Portability across
Postgres (production) and SQLite (dev/tests) is kept by using string UUIDs and
timezone-aware timestamps rather than backend-specific column types.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    """Generate a new string UUID primary key."""
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    """Timezone-aware current time (portable default across backends)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all application-database models."""


class User(Base):
    """A person who can sign in. May belong to several orgs via memberships."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    # Null for users who only sign in via an OAuth provider.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class OAuthAccount(Base):
    """A link between a local user and an external identity provider."""

    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id", name="uq_oauth_identity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40))  # e.g. "google"
    provider_account_id: Mapped[str] = mapped_column(String(255))

    user: Mapped[User] = relationship(back_populates="oauth_accounts")


class Org(Base):
    """A tenant. Owns datasets, conversations, a plan, and a credit balance."""

    __tablename__ = "orgs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    # Plan is a string so tier definitions live in code (billing.entitlements),
    # not in an enum migration. "trial" is the signup default.
    plan: Mapped[str] = mapped_column(String(40), default="trial")
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Cached ledger balance (source of truth is the future credit_ledger table);
    # kept here so entitlement checks are a single-row read.
    credit_balance: Mapped[float] = mapped_column(Numeric(12, 4), default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    members: Mapped[list["OrgMember"]] = relationship(
        back_populates="org", cascade="all, delete-orphan"
    )


class OrgMember(Base):
    """Membership of a user in an org, with a role."""

    __tablename__ = "org_members"

    org_id: Mapped[str] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20), default="owner")  # owner | member
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    org: Mapped[Org] = relationship(back_populates="members")


class Dataset(Base):
    """An uploaded dataset: one read-only SQLite file the agent queries.

    ``business_context`` is the per-dataset, user-editable home for the domain
    rules the Northwind POC hardcodes (revenue formula, margin rate, etc.); it
    is injected into the system prompt. ``schema_summary`` holds the generated
    description of the tables/columns, shown at onboarding and prompted with.
    """

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(10))  # csv | xlsx | sqlite
    file_path: Mapped[str] = mapped_column(String(500), default="")
    size_bytes: Mapped[int] = mapped_column(default=0)
    row_count: Mapped[int] = mapped_column(default=0)
    table_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(
        String(12), default="processing"
    )  # processing | ready | failed
    schema_summary: Mapped[str] = mapped_column(String, default="")
    business_context: Mapped[str] = mapped_column(String, default="")
    error: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
