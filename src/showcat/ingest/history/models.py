"""ORM models for Phase 1 listening-history tables."""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from showcat.core.database import Base


class Artist(Base):
    """Canonical artist identity, keyed by raw name; MBID populated after resolution."""

    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    raw_name: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    mbid: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    scrobbles: Mapped[list["Scrobble"]] = relationship(back_populates="artist")


class Scrobble(Base):
    """One play event from listening history. Unique per (timestamp, artist, track)."""

    __tablename__ = "scrobbles"
    __table_args__ = (
        UniqueConstraint(
            "scrobbled_at", "artist_name", "track_name", name="uq_scrobbles_play_event"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scrobbled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    artist_name: Mapped[str] = mapped_column(String(500), nullable=False)
    track_name: Mapped[str] = mapped_column(String(500), nullable=False)
    album_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    artist_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("artists.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    artist: Mapped["Artist | None"] = relationship(back_populates="scrobbles")


class ArtistTag(Base):
    """One genre/tag weight for an artist (Last.fm top tags). Unique per (artist, tag).

    These per-artist tag vectors are the raw material for the per-user taste
    vector and for artist-to-artist adjacency (Phase 4 discovery engine).
    """

    __tablename__ = "artist_tags"
    __table_args__ = (
        UniqueConstraint("artist_id", "tag", name="uq_artist_tags_artist_tag"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    artist_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("artists.id", ondelete="CASCADE"), nullable=False
    )
    tag: Mapped[str] = mapped_column(String(200), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ArtistUnresolvedQueue(Base):
    """Artists that failed MBID resolution. Nothing is silently dropped."""

    __tablename__ = "artist_unresolved_queue"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    raw_name: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    failure_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
