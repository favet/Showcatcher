"""HistoryBackfillStage — full scrobble backfill from Last.fm.

Resumable: checkpoints last-processed timestamp into run_ledger metadata.
Idempotent: scrobbles table has a unique constraint on (scrobbled_at, artist_name, track_name).
"""
import logging
import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CursorResult, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from opener.adapters.lastfm.client import LastFmClient
from opener.core.base import BaseStage
from opener.core.database import RunLedger, get_db_session
from opener.ingest.history.models import Artist, Scrobble

logger = logging.getLogger(__name__)


def _parse_scrobble(track: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a raw Last.fm track dict into a normalised scrobble dict.

    Returns None for 'now playing' entries (they have no timestamp).
    """
    attr = track.get("@attr", {})
    if attr.get("nowplaying"):
        return None

    date_info = track.get("date")
    if not date_info:
        return None

    scrobbled_at = datetime.fromtimestamp(int(date_info["uts"]), tz=UTC)
    artist_name = track.get("artist", {}).get("#text", "").strip()
    track_name = (track.get("name") or "").strip()
    album_name = track.get("album", {}).get("#text", "").strip() or None

    if not artist_name or not track_name:
        return None

    return {
        "scrobbled_at": scrobbled_at,
        "artist_name": artist_name,
        "track_name": track_name,
        "album_name": album_name,
        "created_at": datetime.now(UTC),
    }


def _upsert_artist(session: Session, artist_name: str) -> int | None:
    """Ensure artist row exists; return its id."""
    now = datetime.now(UTC)
    stmt = (
        pg_insert(Artist)
        .values(raw_name=artist_name, resolved=False, first_seen_at=now, updated_at=now)
        .on_conflict_do_nothing(index_elements=["raw_name"])
    )
    session.execute(stmt)
    result = session.execute(
        select(Artist.id).where(Artist.raw_name == artist_name)
    ).scalar_one_or_none()
    return result


class HistoryBackfillStage(BaseStage):
    """Full scrobble backfill from Last.fm.

    Resumes from last checkpoint stored in run_ledger.run_metadata.
    On re-run after completion, adds only new scrobbles (idempotent).
    """

    @property
    def stage_name(self) -> str:
        return "ingest/history/backfill"

    def _run(self, session: Session, *args: Any, **kwargs: Any) -> int:  # noqa: ARG002
        api_key = os.environ.get("LASTFM_API_KEY", "")
        user = os.environ.get("LASTFM_USER", "")
        if not api_key or not user:
            raise RuntimeError("LASTFM_API_KEY and LASTFM_USER must be set")

        client = LastFmClient(api_key=api_key, user=user)

        # Resume from checkpoint if available (stored in previous run's metadata)
        from_ts: int | None = None
        with get_db_session() as check_session:
            last_run = (
                check_session.query(RunLedger)
                .filter(
                    RunLedger.stage_name == self.stage_name,
                    RunLedger.status == "completed",
                )
                .order_by(RunLedger.started_at.desc())
                .first()
            )
            if last_run and last_run.run_metadata:
                from_ts = last_run.run_metadata.get("last_scrobble_ts")

        # Optional bounded backfill: only pull scrobbles at/after `since_ts`.
        # Lets a first run cover recent history (where decayed affinity weight
        # lives) instead of a full multi-year pull. Takes the later of the two.
        since_ts = kwargs.get("since_ts")
        if since_ts is not None and (from_ts is None or int(since_ts) > from_ts):
            from_ts = int(since_ts)

        inserted = 0
        latest_ts: int | None = None
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

                # INSERT ... ON CONFLICT DO NOTHING for idempotency
                stmt = (
                    pg_insert(Scrobble)
                    .values(**parsed, artist_id=artist_id)
                    .on_conflict_do_nothing(constraint="uq_scrobbles_play_event")
                )
                result = session.execute(stmt)
                if isinstance(result, CursorResult) and result.rowcount:
                    inserted += 1
                    ts = int(parsed["scrobbled_at"].timestamp())
                    if latest_ts is None or ts > latest_ts:
                        latest_ts = ts

            logger.info(
                "Backfill page processed",
                extra={"page": page, "total_pages": total_pages, "inserted_so_far": inserted},
            )

            if page >= total_pages:
                break
            page += 1

        # Store checkpoint in kwargs so BaseStage writes it to run_ledger.run_metadata
        if latest_ts:
            kwargs["last_scrobble_ts"] = latest_ts

        return inserted
