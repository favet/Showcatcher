"""ResolveStage — link event artists to taste artists with confidence.

For every event, each artist string (headliner + each opener) is matched
against the canonical taste `artists` set. Auto-accepted matches are stored
with status "matched"; ambiguous ones with status "review" (the review
queue). Names that clear nothing are logged, never silently dropped.

Idempotency: matches are unique per (event_id, artist_id); re-running
upserts rather than duplicating.
"""
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CursorResult, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from showcat.core.base import BaseStage
from showcat.ingest.events.models import Event
from showcat.ingest.history.models import Artist
from showcat.resolve.matcher import TasteArtist, match_artist
from showcat.resolve.models import EventMatch

logger = logging.getLogger(__name__)


class ResolveStage(BaseStage):
    """Resolve event-artist strings to taste artists (MBID-first, fuzzy fallback)."""

    @property
    def stage_name(self) -> str:
        return "resolve/event_artists"

    def _run(self, session: Session, *args: Any, **kwargs: Any) -> int:  # noqa: ARG002
        taste_rows = session.execute(select(Artist)).scalars().all()
        taste_artists = [
            TasteArtist(artist_id=a.id, raw_name=a.raw_name, mbid=a.mbid)
            for a in taste_rows
        ]

        events = session.execute(select(Event)).scalars().all()
        now = datetime.now(UTC)
        matches_written = 0

        for event in events:
            # Headliner + openers are all candidate artists for this show.
            for name in [event.headliner, *event.openers]:
                candidate = match_artist(name, taste_artists)
                if candidate is None:
                    logger.info(
                        "No taste match for event artist",
                        extra={
                            "event_id": event.id,
                            "artist_name": name,
                            "decision": "no_link",
                        },
                    )
                    continue

                result = session.execute(
                    pg_insert(EventMatch)
                    .values(
                        event_id=event.id,
                        artist_id=candidate.artist_id,
                        matched_name=name,
                        match_type=candidate.match_type,
                        confidence=candidate.confidence,
                        status=candidate.status,
                        created_at=now,
                    )
                    .on_conflict_do_update(
                        constraint="uq_event_matches_event_artist",
                        set_={
                            "matched_name": name,
                            "match_type": candidate.match_type,
                            "confidence": candidate.confidence,
                            "status": candidate.status,
                        },
                    )
                )
                if isinstance(result, CursorResult) and result.rowcount:
                    matches_written += 1
                logger.info(
                    "Event artist resolved",
                    extra={
                        "event_id": event.id,
                        "artist_name": name,
                        "matched_name": candidate.matched_name,
                        "match_type": candidate.match_type,
                        "confidence": candidate.confidence,
                        "status": candidate.status,
                    },
                )

        return matches_written
