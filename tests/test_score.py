"""Phase 3 — Scoring tests.

Gate 3 assertion covered here:
  - Every scored show persists its full term breakdown (no black box).
Plus: the taste term reflects decayed affinity, and scoring is idempotent
and versioned.
"""
import datetime as dt
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opener.ingest.events.models import Event
from opener.ingest.history.models import Artist, Scrobble
from opener.resolve.models import EventMatch
from opener.score.models import EventScore
from opener.score.scorer import SCORING_VERSION, ScoreSignals, compute_score
from opener.score.stage import ScoreStage

REF = datetime(2026, 7, 1, tzinfo=UTC)


def _seed_artist(session: Session, name: str, mbid: str | None = None) -> Artist:
    now = datetime.now(UTC)
    artist = Artist(
        raw_name=name, mbid=mbid, resolved=mbid is not None,
        first_seen_at=now, updated_at=now,
    )
    session.add(artist)
    session.flush()
    return artist


def _seed_scrobbles(session: Session, artist: Artist, when: datetime, count: int) -> None:
    for i in range(count):
        session.add(
            Scrobble(
                scrobbled_at=when - dt.timedelta(hours=i),
                artist_name=artist.raw_name,
                track_name=f"track-{i}",
                artist_id=artist.id,
                created_at=datetime.now(UTC),
            )
        )
    session.flush()


def _seed_matched_event(session: Session, source_id: str, artist: Artist) -> Event:
    now = datetime.now(UTC)
    event = Event(
        source="fixture_source", source_id=source_id, headliner=artist.raw_name,
        openers=[], date=dt.date(2026, 7, 20), venue="Crystal Ballroom",
        on_sale_date=dt.date(2026, 6, 1), ticket_url="https://example.com/" + source_id,
        first_seen=now, last_seen=now,
    )
    session.add(event)
    session.flush()
    session.add(
        EventMatch(
            event_id=event.id, artist_id=artist.id, matched_name=artist.raw_name,
            match_type="exact", confidence=1.0, status="matched", created_at=now,
        )
    )
    session.flush()
    return event


# ---------------------------------------------------------------------------
# Pure scorer
# ---------------------------------------------------------------------------


class TestScorer:
    def test_exact_match_v1_is_taste_only(self) -> None:
        # exact-match-v1 weights: taste 1.0, everything else 0.
        breakdown = compute_score(ScoreSignals(taste=0.5, adjacency=0.1), "exact-match-v1")
        assert breakdown.taste == 0.5
        assert breakdown.adjacency == 0.0
        assert breakdown.total == 0.5

    def test_contributions_sum_to_total(self) -> None:
        breakdown = compute_score(
            ScoreSignals(taste=2.0, adjacency=0.4, discovery=0.3, recency=0.5), "discovery-v1"
        )
        assert breakdown.total == round(
            breakdown.taste
            + breakdown.adjacency
            + breakdown.discovery
            + breakdown.recency
            + breakdown.distance,
            6,
        )

    def test_breakdown_exposes_all_named_terms(self) -> None:
        terms = compute_score(ScoreSignals(taste=0.3), SCORING_VERSION).as_terms()
        assert set(terms) == {"taste", "adjacency", "discovery", "recency", "distance"}


# ---------------------------------------------------------------------------
# ScoreStage
# ---------------------------------------------------------------------------


class TestScoreStage:
    def test_score_persists_full_breakdown(self, db_session: Session) -> None:
        artist = _seed_artist(db_session, "Modest Mouse", mbid="mm-1")
        _seed_scrobbles(db_session, artist, REF - dt.timedelta(days=1), 3)
        event = _seed_matched_event(db_session, "S1", artist)

        ScoreStage(reference_time=REF)._run(db_session)
        db_session.flush()

        score = db_session.execute(
            select(EventScore).where(EventScore.event_id == event.id)
        ).scalar_one()
        assert score.scoring_version == SCORING_VERSION
        assert score.taste_score > 0.0
        # Phase 3 only fills taste; the rest exist and are zero (no black box).
        assert score.adjacency_score == 0.0
        assert score.discovery_score == 0.0
        assert score.recency_score == 0.0
        assert score.distance_score == 0.0
        assert score.score_total == score.taste_score

    def test_more_recent_plays_score_higher(self, db_session: Session) -> None:
        heavy = _seed_artist(db_session, "Heavy Rotation", mbid="h-1")
        light = _seed_artist(db_session, "Light Rotation", mbid="l-1")
        _seed_scrobbles(db_session, heavy, REF - dt.timedelta(days=1), 5)
        _seed_scrobbles(db_session, light, REF - dt.timedelta(days=1), 1)
        e_heavy = _seed_matched_event(db_session, "S2", heavy)
        e_light = _seed_matched_event(db_session, "S3", light)

        ScoreStage(reference_time=REF)._run(db_session)
        db_session.flush()

        s_heavy = db_session.execute(
            select(EventScore).where(EventScore.event_id == e_heavy.id)
        ).scalar_one()
        s_light = db_session.execute(
            select(EventScore).where(EventScore.event_id == e_light.id)
        ).scalar_one()
        assert s_heavy.score_total > s_light.score_total

    def test_score_is_idempotent(self, db_session: Session) -> None:
        artist = _seed_artist(db_session, "Modest Mouse", mbid="mm-1")
        _seed_scrobbles(db_session, artist, REF - dt.timedelta(days=1), 3)
        _seed_matched_event(db_session, "S4", artist)

        ScoreStage(reference_time=REF)._run(db_session)
        db_session.flush()
        first = db_session.execute(select(func.count()).select_from(EventScore)).scalar_one()

        ScoreStage(reference_time=REF)._run(db_session)
        db_session.flush()
        second = db_session.execute(select(func.count()).select_from(EventScore)).scalar_one()
        assert first == second, "Re-running score must not create duplicate score rows"

    def test_review_only_event_is_not_scored(self, db_session: Session) -> None:
        artist = _seed_artist(db_session, "Death Cab for Cutie")
        _seed_scrobbles(db_session, artist, REF - dt.timedelta(days=1), 2)
        now = datetime.now(UTC)
        event = Event(
            source="fixture_source", source_id="S5", headliner="Death Cab", openers=[],
            date=dt.date(2026, 7, 20), venue="Hawthorne", on_sale_date=dt.date(2026, 6, 1),
            ticket_url="https://example.com/S5", first_seen=now, last_seen=now,
        )
        db_session.add(event)
        db_session.flush()
        db_session.add(
            EventMatch(
                event_id=event.id, artist_id=artist.id, matched_name="Death Cab",
                match_type="fuzzy", confidence=0.643, status="review", created_at=now,
            )
        )
        db_session.flush()

        ScoreStage(reference_time=REF)._run(db_session)
        db_session.flush()

        count = db_session.execute(
            select(func.count()).select_from(EventScore).where(EventScore.event_id == event.id)
        ).scalar_one()
        assert count == 0, "Review-only events must not be scored until accepted"
