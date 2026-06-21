"""HistoryIncrementalStage — sync only new scrobbles since last stored timestamp."""
import logging
import os
from datetime import UTC
from typing import Any

from sqlalchemy import CursorResult, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from opener.adapters.lastfm.client import LastFmClient
from opener.core.base import BaseStage
from opener.ingest.history.backfill import _parse_scrobble, _upsert_artist
from opener.ingest.history.models import Scrobble

logger = logging.getLogger(__name__)


class HistoryIncrementalStage(BaseStage):
    """Fetch only scrobbles newer than the most recently stored timestamp.

    Designed to run after HistoryBackfillStage. Idempotent via the same
    unique constraint as the backfill stage.
    """

    @property
    def stage_name(self) -> str:
        return "ingest/history/incremental"

    def _run(self, session: Session, *args: Any, **kwargs: Any) -> int:  # noqa: ARG002
        api_key = os.environ.get("LASTFM_API_KEY", "")
        user = os.environ.get("LASTFM_USER", "")
        if not api_key or not user:
            raise RuntimeError("LASTFM_API_KEY and LASTFM_USER must be set")

        # Find the newest stored scrobble timestamp
        newest_ts = session.execute(
            select(func.max(Scrobble.scrobbled_at))
        ).scalar_one_or_none()

        from_ts: int | None = None
        if newest_ts:
            # Add 1 second to avoid re-fetching the last known scrobble
            from_ts = int(newest_ts.astimezone(UTC).timestamp()) + 1
            logger.info(
                "Incremental sync starting",
                extra={"from_ts": from_ts, "newest_stored": newest_ts.isoformat()},
            )
        else:
            logger.warning("No stored scrobbles found; consider running backfill first")

        client = LastFmClient(api_key=api_key, user=user)
        inserted = 0
        page = 1

        while True:
            data = client.get_recent_tracks(from_ts=from_ts, page=page)
            tracks = data.get("recenttracks", {}).get("track", [])
            attr = data.get("recenttracks", {}).get("@attr", {})
            total_pages = int(attr.get("totalPages", 1))

            if not tracks:
                break

            for track in tracks:
                parsed = _parse_scrobble(track)
                if not parsed:
                    continue

                artist_id = _upsert_artist(session, parsed["artist_name"])
                stmt = (
                    pg_insert(Scrobble)
                    .values(**parsed, artist_id=artist_id)
                    .on_conflict_do_nothing(constraint="uq_scrobbles_play_event")
                )
                result = session.execute(stmt)
                if isinstance(result, CursorResult) and result.rowcount:
                    inserted += 1

            if page >= total_pages:
                break
            page += 1

        logger.info("Incremental sync complete", extra={"new_scrobbles": inserted})
        return inserted
