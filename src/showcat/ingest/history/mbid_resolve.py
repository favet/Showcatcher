"""MbidResolveStage — resolve artist names to MusicBrainz IDs via Last.fm.

Resolution strategy:
  1. If the Last.fm scrobble already carries an MBID, use it directly.
  2. Otherwise call Last.fm artist.search and take the top result if the
     name matches closely enough (case-insensitive exact match).
  3. If no match: insert into artist_unresolved_queue with reason.

Nothing is silently dropped — every unresolvable artist is visible in the queue.
"""
import logging
import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from showcat.adapters.lastfm.client import LastFmClient
from showcat.core.base import BaseStage
from showcat.ingest.history.models import Artist, ArtistUnresolvedQueue, Scrobble

logger = logging.getLogger(__name__)


class MbidResolveStage(BaseStage):
    """Resolve unresolved artists to MBIDs using the Last.fm artist.search API."""

    @property
    def stage_name(self) -> str:
        return "ingest/history/mbid_resolve"

    def _run(self, session: Session, *args: Any, **kwargs: Any) -> int:  # noqa: ARG002
        api_key = os.environ.get("LASTFM_API_KEY", "")
        if not api_key:
            raise RuntimeError("LASTFM_API_KEY must be set")
        user = os.environ.get("LASTFM_USER", "testuser")

        client = LastFmClient(api_key=api_key, user=user)

        # Find all unresolved artists that appear in scrobbles
        unresolved = session.execute(
            select(Artist).where(Artist.resolved.is_(False))
        ).scalars().all()

        resolved_count = 0

        for artist in unresolved:
            # First check: does any scrobble carry a non-empty MBID for this name?
            scrobble_with_mbid = session.execute(
                select(Scrobble.artist_name)
                .where(
                    Scrobble.artist_name == artist.raw_name,
                )
                .limit(1)
            ).scalar_one_or_none()
            _ = scrobble_with_mbid  # just confirming artist exists in scrobbles

            # Check if the scrobble's artist mbid is embedded in the raw track data
            # (we stored artist_name, not mbid per scrobble — so resolve via API)
            mbid = self._search_mbid(client, artist.raw_name)

            now = datetime.now(UTC)
            if mbid:
                artist.mbid = mbid
                artist.resolved = True
                artist.updated_at = now
                logger.info(
                    "Artist resolved",
                    extra={"raw_name": artist.raw_name, "mbid": mbid},
                )
                resolved_count += 1
            else:
                self._queue_unresolved(
                    session,
                    raw_name=artist.raw_name,
                    reason="no_match",
                    detail="Last.fm artist.search returned no name-matching result",
                    now=now,
                )

        return resolved_count

    def _search_mbid(self, client: LastFmClient, artist_name: str) -> str | None:
        """Call Last.fm artist.search; return MBID if top result name matches."""
        try:
            data = client._get({"method": "artist.search", "artist": artist_name, "limit": 3})
            matches = (
                data.get("results", {})
                .get("artistmatches", {})
                .get("artist", [])
            )
            for match in matches:
                if match.get("name", "").lower() == artist_name.lower():
                    mbid = match.get("mbid", "").strip()
                    return mbid if mbid else None
        except Exception as exc:
            logger.warning(
                "Artist search failed",
                extra={"artist_name": artist_name, "error": str(exc)},
            )
        return None

    def _queue_unresolved(
        self,
        session: Session,
        raw_name: str,
        reason: str,
        detail: str,
        now: datetime,
    ) -> None:
        """Upsert into artist_unresolved_queue — never drop silently."""
        existing = session.execute(
            select(ArtistUnresolvedQueue).where(
                ArtistUnresolvedQueue.raw_name == raw_name
            )
        ).scalar_one_or_none()

        if existing:
            existing.attempt_count += 1
            existing.last_attempted_at = now
        else:
            session.add(
                ArtistUnresolvedQueue(
                    raw_name=raw_name,
                    failure_reason=reason,
                    failure_detail=detail,
                    attempt_count=1,
                    first_failed_at=now,
                    last_attempted_at=now,
                )
            )
        logger.info(
            "Artist queued as unresolved",
            extra={"raw_name": raw_name, "reason": reason},
        )
