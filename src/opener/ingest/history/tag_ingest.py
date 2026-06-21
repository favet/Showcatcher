"""ArtistTagStage — fetch per-artist genre/tag vectors from Last.fm.

For every resolved taste artist, fetch top tags and store them as weighted
rows in artist_tags. These vectors feed the per-user taste vector and
artist-to-artist adjacency in the Phase 4 discovery engine.

Idempotency: tags are unique per (artist_id, tag); re-running upserts the
weight rather than duplicating.
"""
import logging
import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CursorResult, exists, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from opener.adapters.lastfm.client import LastFmClient
from opener.core.base import BaseStage
from opener.ingest.history.models import Artist, ArtistTag
from opener.resolve.models import EventMatch

logger = logging.getLogger(__name__)


class ArtistTagStage(BaseStage):
    """Populate artist_tags from Last.fm artist.getTopTags.

    `matched_only` restricts the fetch to artists that have a matched upcoming
    event — the only artists whose adjacency actually affects a playlist — so a
    live run makes a few dozen calls instead of one per taste artist.
    """

    def __init__(
        self, client: LastFmClient | None = None, matched_only: bool = False
    ) -> None:
        self._client = client
        self._matched_only = matched_only

    @property
    def stage_name(self) -> str:
        return "ingest/history/tags"

    def _build_client(self) -> LastFmClient:
        if self._client is not None:
            return self._client
        api_key = os.environ.get("LASTFM_API_KEY", "")
        if not api_key:
            raise RuntimeError("LASTFM_API_KEY must be set")
        user = os.environ.get("LASTFM_USER", "testuser")
        return LastFmClient(api_key=api_key, user=user)

    def _run(self, session: Session, *args: Any, **kwargs: Any) -> int:  # noqa: ARG002
        client = self._build_client()
        query = select(Artist)
        if self._matched_only:
            query = query.where(
                exists().where(
                    EventMatch.artist_id == Artist.id,
                    EventMatch.status == "matched",
                )
            )
        artists = session.execute(query).scalars().all()
        now = datetime.now(UTC)
        rows_written = 0

        for artist in artists:
            tags = client.get_top_tags(artist.raw_name, mbid=artist.mbid)
            if not tags:
                logger.info(
                    "No tags returned for artist",
                    extra={"artist_id": artist.id, "raw_name": artist.raw_name},
                )
                continue
            for tag, weight in tags:
                result = session.execute(
                    pg_insert(ArtistTag)
                    .values(
                        artist_id=artist.id,
                        tag=tag,
                        weight=weight,
                        fetched_at=now,
                    )
                    .on_conflict_do_update(
                        constraint="uq_artist_tags_artist_tag",
                        set_={"weight": weight, "fetched_at": now},
                    )
                )
                if isinstance(result, CursorResult) and result.rowcount:
                    rows_written += 1
            logger.info(
                "Artist tags ingested",
                extra={"artist_id": artist.id, "raw_name": artist.raw_name, "tags": len(tags)},
            )

        return rows_written
