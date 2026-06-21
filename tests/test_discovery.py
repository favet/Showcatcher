"""Phase 4.3–4.5 — Discovery tilt, A/B harness, and explainability.

Gate 4 assertions covered here:
  - The discovery tilt works: holding venue and date constant, a taste-adjacent
    artist with low play-count scores HIGHER than a heavy-rotation artist.
  - Scoring config is versioned; two versions on the same input can be diffed.
  - Every scored show persists its term breakdown; `explain <show>` prints it.
"""
import datetime as dt
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from opener.cli.explain import explain_show
from opener.ingest.events.models import Event
from opener.ingest.history.models import Artist, ArtistTag, Scrobble
from opener.resolve.models import EventMatch
from opener.score.models import EventScore
from opener.score.scorer import ScoreSignals, ab_diff
from opener.score.stage import ScoreStage

REF = datetime(2026, 7, 1, tzinfo=UTC)


def _seed_artist(session: Session, name: str, mbid: str) -> Artist:
    now = datetime.now(UTC)
    artist = Artist(
        raw_name=name, mbid=mbid, resolved=True, first_seen_at=now, updated_at=now
    )
    session.add(artist)
    session.flush()
    return artist


def _seed_scrobbles(session: Session, artist: Artist, count: int) -> None:
    when = REF - dt.timedelta(days=1)
    for i in range(count):
        session.add(
            Scrobble(
                scrobbled_at=when - dt.timedelta(hours=i),
                artist_name=artist.raw_name,
                track_name=f"{artist.raw_name}-track-{i}",
                artist_id=artist.id,
                created_at=datetime.now(UTC),
            )
        )
    session.flush()


def _seed_tags(session: Session, artist: Artist, tags: dict[str, float]) -> None:
    now = datetime.now(UTC)
    for tag, weight in tags.items():
        session.add(ArtistTag(artist_id=artist.id, tag=tag, weight=weight, fetched_at=now))
    session.flush()


def _seed_matched_event(session: Session, source_id: str, artist: Artist) -> Event:
    now = datetime.now(UTC)
    event = Event(
        source="fixture_source", source_id=source_id, headliner=artist.raw_name,
        openers=[], date=dt.date(2026, 7, 15), venue="Crystal Ballroom",
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


def _seed_heavy_and_light(session: Session) -> tuple[Event, Event]:
    """Heavy-rotation indie artist + barely-played, equally-adjacent indie artist.

    Both share the same tag profile (so both are taste-adjacent); they differ
    only in play-count. Same venue + date so distance/date are held constant.
    """
    heavy = _seed_artist(session, "Heavy Indie", "heavy-1")
    light = _seed_artist(session, "Barely Heard Indie", "light-1")
    _seed_scrobbles(session, heavy, 50)
    _seed_scrobbles(session, light, 1)
    _seed_tags(session, heavy, {"indie rock": 100.0, "indie": 80.0})
    _seed_tags(session, light, {"indie rock": 100.0, "indie": 80.0})
    e_heavy = _seed_matched_event(session, "HEAVY", heavy)
    e_light = _seed_matched_event(session, "LIGHT", light)
    return e_heavy, e_light


class TestDiscoveryTilt:
    def test_low_playcount_adjacent_artist_outranks_heavy_rotation(
        self, db_session: Session
    ) -> None:
        e_heavy, e_light = _seed_heavy_and_light(db_session)

        ScoreStage(scoring_version="discovery-v1", reference_time=REF)._run(db_session)
        db_session.flush()

        s_heavy = db_session.execute(
            select(EventScore).where(EventScore.event_id == e_heavy.id)
        ).scalar_one()
        s_light = db_session.execute(
            select(EventScore).where(EventScore.event_id == e_light.id)
        ).scalar_one()

        assert s_light.score_total > s_heavy.score_total, (
            "Discovery tilt failed: the barely-played adjacent artist must outrank "
            "the heavy-rotation artist under discovery-v1"
        )
        # The tilt is driven by the discovery term, not by taste.
        assert s_light.discovery_score > s_heavy.discovery_score

    def test_exact_match_v1_does_not_tilt(self, db_session: Session) -> None:
        """Under the precision version, the heavy artist still wins (taste only)."""
        e_heavy, e_light = _seed_heavy_and_light(db_session)

        ScoreStage(scoring_version="exact-match-v1", reference_time=REF)._run(db_session)
        db_session.flush()

        s_heavy = db_session.execute(
            select(EventScore).where(EventScore.event_id == e_heavy.id)
        ).scalar_one()
        s_light = db_session.execute(
            select(EventScore).where(EventScore.event_id == e_light.id)
        ).scalar_one()
        assert s_heavy.score_total > s_light.score_total


class TestABHarness:
    def test_versions_diff_on_same_signals(self) -> None:
        signals = ScoreSignals(taste=10.0, adjacency=0.9, discovery=0.45, recency=0.95)
        diff = ab_diff(signals, "exact-match-v1", "discovery-v1")

        assert diff.total_a != diff.total_b
        assert diff.total_delta == round(diff.total_b - diff.total_a, 6)
        # exact-match-v1 has no discovery term; discovery-v1 does -> a real delta.
        assert diff.term_deltas["discovery"] != 0.0

    def test_two_versions_coexist_in_db(self, db_session: Session) -> None:
        e_heavy, _ = _seed_heavy_and_light(db_session)

        ScoreStage(scoring_version="exact-match-v1", reference_time=REF)._run(db_session)
        ScoreStage(scoring_version="discovery-v1", reference_time=REF)._run(db_session)
        db_session.flush()

        versions = (
            db_session.execute(
                select(EventScore.scoring_version).where(EventScore.event_id == e_heavy.id)
            )
            .scalars()
            .all()
        )
        assert set(versions) == {"exact-match-v1", "discovery-v1"}


class TestExplain:
    def test_explain_prints_breakdown(self, db_session: Session) -> None:
        e_heavy, _ = _seed_heavy_and_light(db_session)
        ScoreStage(scoring_version="discovery-v1", reference_time=REF)._run(db_session)
        db_session.flush()

        text = explain_show(db_session, e_heavy.id)
        assert "Heavy Indie" in text
        assert "discovery-v1" in text
        for term in ("taste", "adjacency", "discovery", "recency", "distance"):
            assert term in text
        assert "TOTAL" in text

    def test_explain_unknown_event(self, db_session: Session) -> None:
        assert "No event" in explain_show(db_session, 999999)
