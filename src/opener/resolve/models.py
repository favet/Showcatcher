"""ORM model for Phase 3 entity-resolution matches.

An EventMatch links an event-artist string (headliner or opener) to a
canonical taste Artist, with an explainable confidence and a status.

status values:
  - "matched": confidence >= the match threshold; accepted automatically.
  - "review":  below the match threshold but above the review floor;
               surfaced in the review queue, never silently accepted.

Nothing ambiguous is silently accepted or dropped — every candidate above
the review floor is persisted here (a "no black box" guarantee).
"""
import datetime as dt

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from opener.core.database import Base


class EventMatch(Base):
    """Event-artist ↔ taste-artist link with confidence. Unique per (event, artist)."""

    __tablename__ = "event_matches"
    __table_args__ = (
        UniqueConstraint("event_id", "artist_id", name="uq_event_matches_event_artist"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    artist_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("artists.id", ondelete="CASCADE"), nullable=False
    )
    matched_name: Mapped[str] = mapped_column(String(255), nullable=False)
    match_type: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
