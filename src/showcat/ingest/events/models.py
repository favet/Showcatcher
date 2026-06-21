"""ORM models for Phase 2 event-ingest tables."""
import datetime as dt
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from showcat.core.database import Base


class Event(Base):
    """Normalised upcoming show. Unique per (source, source_id)."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_events_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    headliner: Mapped[str] = mapped_column(String(500), nullable=False)
    openers: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    venue: Mapped[str] = mapped_column(String(255), nullable=False)
    on_sale_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    ticket_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EventSnapshot(Base):
    """Raw captured source response per run — used for change detection."""

    __tablename__ = "event_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    captured_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)


class EventChange(Base):
    """A detected change between two consecutive snapshots."""

    __tablename__ = "event_changes"
    __table_args__ = (
        UniqueConstraint(
            "source", "event_source_id", "change_type", "detected_at",
            name="uq_event_changes_unique"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    event_source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)
    change_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    detected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceHealth(Base):
    """Per-source health tracking: last success, trailing counts, anomaly flag."""

    __tablename__ = "source_health"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    last_success_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_event_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trailing_counts: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)
    anomaly_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    anomaly_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
