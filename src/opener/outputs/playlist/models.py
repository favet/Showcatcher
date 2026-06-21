"""ORM model for Phase 5 track-resolution decisions.

Each row records one artist->track->Spotify-URI resolution: the candidates
considered and the URI chosen. This is the "never a black box" record for
track selection, parallel to event_scores for show scoring — it makes
"why was track T chosen for artist A?" answerable from persisted data.

A null chosen_uri means the track could not be resolved on the source and is
visible (not silently dropped) for review.
"""
import datetime as dt
from typing import Any

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from opener.core.database import Base


class TrackResolution(Base):
    """One artist->track->URI decision with its candidate set. Unique per (artist, track)."""

    __tablename__ = "track_resolutions"
    __table_args__ = (
        UniqueConstraint(
            "artist_name", "track_name", name="uq_track_resolutions_artist_track"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    artist_name: Mapped[str] = mapped_column(String(500), nullable=False)
    track_name: Mapped[str] = mapped_column(String(500), nullable=False)
    chosen_uri: Mapped[str | None] = mapped_column(String(255), nullable=True)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="spotify")
    resolved_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
