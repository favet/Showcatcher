"""ORM model for Phase 3 per-show scores.

Every score decomposes into named terms (taste, adjacency, discovery,
recency, distance) that are persisted alongside the total and the
scoring-config version. This is the "scoring is explainable and versioned"
invariant: any ranking can be reconstructed and diffed after the fact.

In Phase 3 (exact-match slice) only the `taste` term is populated; the
adjacency/discovery/recency/distance terms exist in the schema and default
to 0.0, to be filled in by the Phase 4 discovery engine.
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


class EventScore(Base):
    """Per-show score with full term breakdown. Unique per (event, scoring_version)."""

    __tablename__ = "event_scores"
    __table_args__ = (
        UniqueConstraint(
            "event_id", "scoring_version", name="uq_event_scores_event_version"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    scoring_version: Mapped[str] = mapped_column(String(50), nullable=False)
    score_total: Mapped[float] = mapped_column(Float, nullable=False)
    taste_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    adjacency_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    discovery_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    recency_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    distance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
