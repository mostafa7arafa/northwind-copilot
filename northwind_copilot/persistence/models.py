"""Local workspace metadata, separate from uploaded analyst databases."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all application-database models."""


class Dataset(Base):
    """An uploaded dataset: one read-only SQLite file the agent queries.

    ``business_context`` is the per-dataset, user-editable home for the domain
    rules the Northwind POC hardcodes (revenue formula, margin rate, etc.); it
    is injected into the system prompt. ``schema_summary`` holds the generated
    description of the tables/columns, shown at onboarding and prompted with.
    """

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
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


class Conversation(Base):
    """A saved chat thread over an uploaded dataset or the Northwind sample."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), default="New analysis")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        onupdate=_utcnow,
    )

    turns: Mapped[list["Turn"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Turn.created_at",
    )


class Turn(Base):
    """One question/answer exchange, with its artifacts.

    The JSON columns mirror the SSE artifact the frontend already renders:
    ``queries`` is a list of ``{sql, table}``, ``charts`` a list of ECharts
    options, ``insights`` a ``{text, bullets}`` object. Storing them means the
    server owns conversation history, including SQL and chart artifacts.
    """

    __tablename__ = "turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(String, default="")
    answer: Mapped[str] = mapped_column(String, default="")
    queries: Mapped[list] = mapped_column(JSON, default=list)
    charts: Mapped[list] = mapped_column(JSON, default=list)
    insights: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model: Mapped[str] = mapped_column(String(200), default="")
    provider: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="turns")


class TurnFeedback(Base):
    """A thumbs-up/down on one analyst turn.

    One row per turn (re-voting updates it). ``vote`` is +1 or -1. Feedback is
    the raw signal; a thumbs-up on a dataset-backed turn also materialises a
    :class:`GoldenExample` for that dataset.
    """

    __tablename__ = "turn_feedback"

    turn_id: Mapped[str] = mapped_column(
        ForeignKey("turns.id", ondelete="CASCADE"), primary_key=True
    )
    vote: Mapped[int] = mapped_column(Integer)  # +1 | -1
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )


class GoldenExample(Base):
    """A confirmed (question → SQL) pair for one dataset.

    Thumbs-up turns become golden examples; the top-k most similar are
    injected into future prompts for that dataset, so the product gets better
    the more a customer corrects it. Selection is plain keyword overlap +
    recency (deliberately no embeddings in v1).
    """

    __tablename__ = "golden_examples"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    # The turn the example came from; a later thumbs-down retracts it.
    source_turn_id: Mapped[str | None] = mapped_column(
        ForeignKey("turns.id", ondelete="SET NULL"), nullable=True
    )
    question: Mapped[str] = mapped_column(String)
    sql: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
