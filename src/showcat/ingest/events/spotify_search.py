"""EventSpotifySearchStage — direct Spotify artist search for unmatched events.

For every upcoming event without a confirmed Last.fm taste match, search Spotify
by headliner name and store the URL on the event row so the UI can link to it
without falling back to a generic Last.fm URL.

"none" sentinel: only written when Spotify successfully returned results but none
matched (similarity below threshold). Transient errors (rate limits, network) are
NOT stored so the event is re-tried on the next pipeline run.
"""
import logging
import os
import time
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from showcat.adapters.spotify.auth import SpotifyAuth, SpotifyToken
from showcat.adapters.spotify.client import SpotifyClient, SpotifyError
from showcat.core.base import BaseStage
from showcat.ingest.events.models import Event
from showcat.resolve.matcher import similarity
from showcat.resolve.models import EventMatch

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.55

# Spotify rate-limits on a rolling ~30-second window; sustained over-rate triggers
# a *fixed multi-hour cooldown* (observed Retry-After ~10h), not a short backoff —
# and that cooldown blocks the discovery-playlist refresh, which shares the quota.
# So this stage is deliberately gentle:
#   - REQUEST_DELAY_S keeps us to ~2.5 req/s (~75 per 30s window, well under the cap).
#   - MAX_PER_RUN caps the burst so the initial backfill spreads over several runs
#     (results persist per-event, so each run makes progress without redoing work).
REQUEST_DELAY_S = float(os.environ.get("SPOTIFY_SEARCH_DELAY_S", "0.4"))
MAX_PER_RUN = int(os.environ.get("SPOTIFY_SEARCH_MAX_PER_RUN", "100"))


class EventSpotifySearchStage(BaseStage):
    """Search Spotify by headliner name for events not matched through Last.fm taste."""

    def __init__(self, client: SpotifyClient | None = None) -> None:
        self._client = client

    @property
    def stage_name(self) -> str:
        return "ingest/events/spotify_search"

    def _build_client(self) -> SpotifyClient:
        if self._client is not None:
            return self._client
        refresh_token = os.environ.get("SPOTIFY_REFRESH_TOKEN", "")
        if not refresh_token:
            raise RuntimeError("SPOTIFY_REFRESH_TOKEN must be set")
        auth = SpotifyAuth.from_env()
        token = auth.refresh(
            SpotifyToken(access_token="", refresh_token=refresh_token, expires_at=0)
        )
        return SpotifyClient(access_token=token.access_token)

    def _run(self, session: Session, *args: Any, **kwargs: Any) -> int:  # noqa: ARG002
        today = date.today()
        client = self._build_client()

        # Upcoming events without a confirmed taste match and not yet searched.
        # Capped per run so a large initial backlog doesn't blow the Spotify
        # window — results persist, so subsequent runs drain the rest.
        rows = (
            session.execute(
                select(Event)
                .outerjoin(
                    EventMatch,
                    (EventMatch.event_id == Event.id) & (EventMatch.status == "matched"),
                )
                .where(EventMatch.id.is_(None))
                .where(Event.date >= today)
                .where(Event.event_spotify_url.is_(None))
                .order_by(Event.date.asc())
                .limit(MAX_PER_RUN)
            )
            .scalars()
            .all()
        )
        logger.info("Spotify search batch", extra={"batch_size": len(rows), "cap": MAX_PER_RUN})

        records_updated = 0

        for event in rows:
            time.sleep(REQUEST_DELAY_S)
            result = None
            had_error = False

            try:
                result = client.search_artist(event.headliner)
            except SpotifyError as e:
                if e.status_code == 429:
                    # Spotify's 429 is a fixed, often multi-hour cooldown — retrying
                    # now can't succeed and only risks extending it. Stop cleanly and
                    # leave the rest NULL so a later run (after the window) resumes.
                    logger.warning(
                        "Spotify rate limited (429) — stopping stage; %d events left this batch. "
                        "Retry-After=%ss",
                        len(rows) - records_updated,
                        e.retry_after if e.retry_after is not None else "unknown",
                    )
                    session.commit()
                    return records_updated
                had_error = True
                logger.warning("Spotify API error for '%s': %s", event.headliner, e)
            except Exception as e:
                had_error = True
                logger.warning(
                    "Unexpected error searching Spotify for '%s': %s", event.headliner, e
                )

            if result is None:
                # Only write "none" for a clean empty response — not for transient errors.
                # Errors leave event_spotify_url = NULL so the next run retries.
                if not had_error:
                    event.event_spotify_url = "none"
                    session.add(event)
                    records_updated += 1
                continue

            result_name: str = result.get("name", "")
            sim = similarity(event.headliner, result_name)
            if sim >= SIMILARITY_THRESHOLD:
                url = result.get("external_urls", {}).get("spotify") or "none"
                event.event_spotify_url = url
                logger.info(
                    "Event Spotify URL found",
                    extra={"headliner": event.headliner, "spotify_name": result_name,
                           "sim": round(sim, 3), "url": url},
                )
            else:
                event.event_spotify_url = "none"
                logger.debug(
                    "Spotify name mismatch",
                    extra={"headliner": event.headliner, "spotify_name": result_name,
                           "sim": round(sim, 3)},
                )

            session.add(event)
            records_updated += 1

        session.commit()
        return records_updated
