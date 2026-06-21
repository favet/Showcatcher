"""ScoreStage — compute and persist a decomposed score per matched show.

For each event with auto-accepted ("matched") artists, every matched artist
is scored from its signals (taste affinity, tag adjacency, discovery boost,
recency) and the show takes its best-scoring artist — a show is as good as
its strongest reason to go. The full term breakdown and scoring version are
persisted to event_scores.

`scoring_version` and `reference_time` are injected (constructor) so the same
DB can hold multiple scoring variants for A/B comparison and so the decay
math is deterministic under test.

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
from opener.ingest.history.models import Artist, ArtistTag, Scrobble
from opener.resolve.models import EventMatch
from opener.score.models import EventScore
from opener.score.scorer import (
    SCORING_VERSION,
    ScoreBreakdown,
    ScoreSignals,
    compute_score,
    discovery_signal,
    recency_signal,
)
from opener.score.similarity import TagVector, adjacency, build_taste_vector

logger = logging.getLogger(__name__)


def _artist_key(mbid: str | None, raw_name: str) -> str:
    """Same keying as compute_decayed_affinity: MBID if resolved, else raw name."""
    return mbid if mbid else raw_name


class ScoreStage(BaseStage):
    """Score every matched show with a persisted, decomposed breakdown."""

    def __init__(
        self,
        scoring_version: str = SCORING_VERSION,
        reference_time: datetime | None = None,
    ) -> None:
        self._version = scoring_version
        self._reference_time = reference_time

    @property
    def stage_name(self) -> str:
        return f"score/shows/{self._version}"

    def _run(self, session: Session, *args: Any, **kwargs: Any) -> int:  # noqa: ARG002
        ref = self._reference_time or datetime.now(UTC)
        now = datetime.now(UTC)

        # --- 1. Decayed affinity (weight + play_count) keyed per artist. ---
        rows = session.execute(
            select(Scrobble.artist_name, Artist.mbid, Scrobble.scrobbled_at).join(
                Artist, Scrobble.artist_id == Artist.id, isouter=True
            )
        ).all()
        plays = [(r.artist_name, r.mbid, r.scrobbled_at) for r in rows]
        affinity = compute_decayed_affinity(plays, top_n=10_000, reference_time=ref)
        weight_by_key = {s.key: s.weight for s in affinity}
        playcount_by_key = {s.key: s.play_count for s in affinity}

        # Days since the most recent play, per key (for the recency signal).
        last_play_days: dict[str, float] = {}
        for name, mbid, scrobbled_at in plays:
            if scrobbled_at.tzinfo is None:
                scrobbled_at = scrobbled_at.replace(tzinfo=UTC)
            days = (ref - scrobbled_at).total_seconds() / 86400.0
            key = _artist_key(mbid, name)
            last_play_days[key] = min(last_play_days.get(key, days), days)

        # --- 2. Tag vectors per artist key, and the user taste vector. ---
        tag_rows = session.execute(
            select(Artist.mbid, Artist.raw_name, ArtistTag.tag, ArtistTag.weight).join(
                ArtistTag, ArtistTag.artist_id == Artist.id
            )
        ).all()
        artist_vectors: dict[str, TagVector] = {}
        for mbid, raw_name, tag, weight in tag_rows:
            key = _artist_key(mbid, raw_name)
            artist_vectors.setdefault(key, {})[tag] = weight
        taste_vector = build_taste_vector(artist_vectors, weight_by_key)

        # --- 3. Score each matched artist; the show takes its best. ---
        matched = session.execute(
            select(EventMatch, Artist)
            .join(Artist, EventMatch.artist_id == Artist.id)
            .where(EventMatch.status == "matched")
        ).all()

        best_by_event: dict[int, ScoreBreakdown] = {}
        for match, artist in matched:
            key = _artist_key(artist.mbid, artist.raw_name)
            taste = weight_by_key.get(key, 0.0)
            adj = adjacency(artist_vectors.get(key, {}), taste_vector)
            disc = discovery_signal(adj, playcount_by_key.get(key, 0))
            rec = recency_signal(last_play_days.get(key, 0.0))
            signals = ScoreSignals(taste=taste, adjacency=adj, discovery=disc, recency=rec)
            breakdown = compute_score(signals, self._version)

            current = best_by_event.get(match.event_id)
            if current is None or breakdown.total > current.total:
                best_by_event[match.event_id] = breakdown

        # --- 4. Persist one decomposed score per event. ---
        scored = 0
        for event_id, breakdown in best_by_event.items():
            result = session.execute(
                pg_insert(EventScore)
                .values(
                    event_id=event_id,
                    scoring_version=self._version,
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
                    "scoring_version": self._version,
                    "terms": breakdown.as_terms(),
                    "total": breakdown.total,
                },
            )

        return scored
