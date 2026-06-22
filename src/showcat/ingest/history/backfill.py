"""HistoryBackfillStage — full scrobble backfill from Last.fm.

Resumable: checkpoints last-processed timestamp into run_ledger metadata.
Idempotent: scrobbles table has a unique constraint on (scrobbled_at, artist_name, track_name).
"""
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import CursorResult, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from showcat.adapters.lastfm.client import LastFmClient
from showcat.core.base import BaseStage
from showcat.core.database import RunLedger, get_db_session
from showcat.ingest.history.models import Artist, Scrobble

logger = logging.getLogger(__name__)

# Concurrent workers for page fetching. Each spawns its own LastFmClient.
# Last.fm read-only pagination is tolerant of this many parallel requests.
MAX_CONCURRENT_PAGES = 15


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


def _fetch_page(api_key: str, user: str, from_ts: int | None, page: int) -> tuple[int, list[dict]]:
    """Worker: create a fresh client, fetch one page, return (page_num, tracks)."""
    client = LastFmClient(api_key=api_key, user=user)
    data = client.get_recent_tracks(from_ts=from_ts, page=page)
    tracks = data.get("recenttracks", {}).get("track", [])
    return page, tracks


class HistoryBackfillStage(BaseStage):
    """Full scrobble backfill from Last.fm.

    Resumes from last checkpoint stored in run_ledger.run_metadata.
    On re-run after completion, adds only new scrobbles (idempotent).

    progress_path: if set, a JSON file written after each page so a browser
    polling it can display live status.
    """

    def __init__(self, progress_path: str | None = None) -> None:
        self._progress_path = progress_path
        self._started_at: datetime | None = None

    def _write_progress(
        self,
        status: str,
        page: int,
        total_pages: int,
        inserted: int,
        phase: str = "fetch",
        scrobbles_total: int = 0,
    ) -> None:
        if not self._progress_path:
            return
        now = datetime.now(UTC)
        elapsed = (now - self._started_at).total_seconds() if self._started_at else 0
        if phase == "insert" and scrobbles_total > 0:
            pct = round(inserted / scrobbles_total * 100)
            eta_s = round(elapsed / max(inserted, 1) * (scrobbles_total - inserted)) if inserted > 0 and inserted < scrobbles_total else None
        else:
            pct = round(page / total_pages * 100) if total_pages else 0
            eta_s = round(elapsed / page * (total_pages - page)) if page > 0 and total_pages > page else None
        try:
            Path(self._progress_path).write_text(
                json.dumps({
                    "status": status,
                    "phase": phase,
                    "page": page,
                    "total_pages": total_pages,
                    "pct": pct,
                    "scrobbles_inserted": inserted,
                    "scrobbles_total": scrobbles_total,
                    "started_at": self._started_at.isoformat() if self._started_at else None,
                    "updated_at": now.isoformat(),
                    "elapsed_s": round(elapsed),
                    "eta_s": eta_s,
                }),
                encoding="utf-8",
            )
        except OSError:
            pass

    @property
    def stage_name(self) -> str:
        return "ingest/history/backfill"

    def _run(self, session: Session, *args: Any, **kwargs: Any) -> int:  # noqa: ARG002
        api_key = os.environ.get("LASTFM_API_KEY", "")
        user = os.environ.get("LASTFM_USER", "")
        if not api_key or not user:
            raise RuntimeError("LASTFM_API_KEY and LASTFM_USER must be set")

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
        since_ts = kwargs.get("since_ts")
        if since_ts is not None and (from_ts is None or int(since_ts) > from_ts):
            from_ts = int(since_ts)

        self._started_at = datetime.now(UTC)

        # ── Phase 1: get page count from page 1 ──────────────────────────────
        client = LastFmClient(api_key=api_key, user=user)
        first_data = client.get_recent_tracks(from_ts=from_ts, page=1)
        attr = first_data.get("recenttracks", {}).get("@attr", {})
        total_pages = int(attr.get("totalPages", 1))
        first_tracks = first_data.get("recenttracks", {}).get("track", [])

        self._write_progress("running", 1, total_pages, 0)
        logger.info("Backfill started", extra={"total_pages": total_pages})

        # ── Phase 2: fetch remaining pages concurrently ───────────────────────
        # page_tracks[n] = list of raw track dicts for page n
        page_tracks: dict[int, list[dict]] = {1: first_tracks}
        pages_fetched = 1

        if total_pages > 1:
            with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_PAGES) as executor:
                futures = {
                    executor.submit(_fetch_page, api_key, user, from_ts, p): p
                    for p in range(2, total_pages + 1)
                }
                for future in as_completed(futures):
                    page_num, tracks = future.result()
                    page_tracks[page_num] = tracks
                    pages_fetched += 1
                    self._write_progress("running", pages_fetched, total_pages, 0)

        logger.info("All pages fetched", extra={"total_pages": total_pages})

        # ── Phase 3: insert scrobbles in page order (DB writes, main thread) ──
        # Parse everything first so we know the total for a meaningful ETA.
        all_parsed: list[dict] = []
        for page_num in range(1, total_pages + 1):
            for track in page_tracks.get(page_num, []):
                parsed = _parse_scrobble(track)
                if parsed:
                    all_parsed.append(parsed)

        scrobbles_total = len(all_parsed)
        inserted = 0
        latest_ts: int | None = None
        PROGRESS_INTERVAL = 5000

        self._write_progress("running", total_pages, total_pages, 0,
                             phase="insert", scrobbles_total=scrobbles_total)

        for i, parsed in enumerate(all_parsed):
            artist_id = _upsert_artist(session, parsed["artist_name"])

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

            if (i + 1) % PROGRESS_INTERVAL == 0:
                self._write_progress("running", total_pages, total_pages, inserted,
                                     phase="insert", scrobbles_total=scrobbles_total)

        self._write_progress("completed", total_pages, total_pages, inserted,
                             phase="insert", scrobbles_total=scrobbles_total)
        logger.info("Backfill complete", extra={"inserted": inserted})

        if latest_ts:
            kwargs["last_scrobble_ts"] = latest_ts

        return inserted
