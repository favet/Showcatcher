"""ScoreStage — compute and persist a decomposed score per matched show.

For every event with at least one auto-accepted ("matched") artist, the
taste term is the decayed affinity of the strongest matched artist. The
full term breakdown and the scoring version are persisted to event_scores.

`reference_time` is injected (constructor) so the decay calculation — and
therefore the whole pipeline's output — is deterministic under test.

Idempotency: scores are unique per (event_id, scoring_version); re-running
upserts rather than duplicating.
"""
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CursorResult, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from opener.core.affinity import compute_decayed_affinity
from opener.core.base import BaseStage
from opener.ingest.history.models import Artist, Scrobble
from opener.resolve.models import EventMatch
from opener.score.models import EventScore
from opener.score.scorer import SCORING_VERSION, compute_score

logger = logging.getLogger(__name__)


class ScoreStage(BaseStage):
    """Score every matched show from decayed taste affinity, with a persisted breakdown."""

    def __init__(self, reference_time: datetime | None = None) -> None:
        self._reference_time = reference_time

    @property
    def stage_name(self) -> str:
        return "score/shows"

    def _run(self, session: Session, *args: Any, **kwargs: Any) -> int:  # noqa: ARG002
        ref = self._reference_time
        now = datetime.now(UTC)

        # --- 1. Build the decayed-affinity weight map (key -> weight). ---
        plays = [
            (row.artist_name, row.mbid, row.scrobbled_at)
            for row in session.execute(
                select(
                    Scrobble.artist_name,
                    Artist.mbid,
                    Scrobble.scrobbled_at,
                ).join(Artist, Scrobble.artist_id == Artist.id, isouter=True)
            ).all()
        ]
        affinity = compute_decayed_affinity(plays, top_n=10_000, reference_time=ref)
        weight_by_key = {score.key: score.weight for score in affinity}

        # --- 2. For each auto-accepted match, look up its taste weight. ---
        matched = session.execute(
            select(EventMatch, Artist)
            .join(Artist, EventMatch.artist_id == Artist.id)
            .where(EventMatch.status == "matched")
        ).all()

        # event_id -> best taste weight among its matched artists
        taste_by_event: dict[int, float] = {}
        for match, artist in matched:
            key = artist.mbid if artist.mbid else artist.raw_name
            weight = weight_by_key.get(key, 0.0)
            taste_by_event[match.event_id] = max(
                taste_by_event.get(match.event_id, 0.0), weight
            )

        # --- 3. Persist a decomposed score per event. ---
        scored = 0
        for event_id, taste in taste_by_event.items():
            breakdown = compute_score(taste=taste)
            result = session.execute(
                pg_insert(EventScore)
                .values(
                    event_id=event_id,
                    scoring_version=SCORING_VERSION,
                    score_total=breakdown.total,
                    taste_score=breakdown.taste,
                    adjacency_score=breakdown.adjacency,
                    discovery_score=breakdown.discovery,
                    recency_score=breakdown.recency,
                    distance_score=breakdown.distance,
                    computed_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_event_scores_event_version",
                    set_={
                        "score_total": breakdown.total,
                        "taste_score": breakdown.taste,
                        "adjacency_score": breakdown.adjacency,
                        "discovery_score": breakdown.discovery,
                        "recency_score": breakdown.recency,
                        "distance_score": breakdown.distance,
                        "computed_at": now,
                    },
                )
            )
            if isinstance(result, CursorResult) and result.rowcount:
                scored += 1
            logger.info(
                "Show scored",
                extra={
                    "event_id": event_id,
                    "scoring_version": SCORING_VERSION,
                    "terms": breakdown.as_terms(),
                    "total": breakdown.total,
                },
            )

        return scored
