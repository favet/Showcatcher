"""Phase 3 — Entity resolution tests.

Gate 3 assertions covered here:
  - Resolver maps a known fixture artist correctly (exact match).
  - The fuzzy case ("Mt. Joy" / "Mount Joy") resolves with confidence >= threshold.
  - Low-confidence/ambiguous matches go to a review queue — never silently
    matched or dropped.
  - Resolve is idempotent (re-running produces no duplicate matches).
"""
import datetime as dt
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from showcat.ingest.events.models import Event
from showcat.ingest.history.models import Artist
from showcat.resolve.matcher import match_artist
from showcat.resolve.models import EventMatch
from showcat.resolve.stage import ResolveStage


def _seed_artist(session: Session, name: str, mbid: str | None = None) -> Artist:
    existing = session.execute(select(Artist).where(Artist.raw_name == name)).scalar_one_or_none()
    if existing is not None:
        return existing
    now = datetime.now(UTC)
    artist = Artist(
        raw_name=name,
        mbid=mbid,
        resolved=mbid is not None,
        first_seen_at=now,
        updated_at=now,
    )
    session.add(artist)
    session.flush()
    return artist


def _seed_event(session: Session, source_id: str, headliner: str, openers: list[str]) -> Event:
    now = datetime.now(UTC)
    event = Event(
        source="fixture_source",
        source_id=source_id,
        headliner=headliner,
        openers=openers,
        date=dt.date(2026, 7, 15),
        venue="Crystal Ballroom",
        on_sale_date=dt.date(2026, 6, 1),
        ticket_url="https://example.com/" + source_id,
        first_seen=now,
        last_seen=now,
    )
    session.add(event)
    session.flush()
    return event


# ---------------------------------------------------------------------------
# Pure matcher unit tests
# ---------------------------------------------------------------------------


class TestMatcher:
    def test_exact_normalised_match_is_confident(self) -> None:
        from showcat.resolve.matcher import TasteArtist

        taste = [TasteArtist(artist_id=1, raw_name="Modest Mouse", mbid="m-1")]
        result = match_artist("modest mouse", taste)
        assert result is not None
        assert result.match_type == "exact"
        assert result.confidence == 1.0
        assert result.status == "matched"

    def test_mbid_match_wins_outright(self) -> None:
        from showcat.resolve.matcher import TasteArtist

        taste = [TasteArtist(artist_id=7, raw_name="Whatever Name", mbid="abc-123")]
        result = match_artist("Totally Different String", taste, event_mbid="abc-123")
        assert result is not None
        assert result.match_type == "mbid"
        assert result.confidence == 1.0

    def test_fuzzy_mt_joy_clears_threshold(self) -> None:
        from showcat.resolve.matcher import TasteArtist

        taste = [TasteArtist(artist_id=2, raw_name="Mt. Joy", mbid="mj-1")]
        result = match_artist("Mount Joy", taste)
        assert result is not None
        assert result.match_type == "fuzzy"
        assert result.confidence >= 0.75, "Mt. Joy/Mount Joy must clear the match threshold"
        assert result.status == "matched"

    def test_ambiguous_lands_in_review_band(self) -> None:
        from showcat.resolve.matcher import TasteArtist

        taste = [TasteArtist(artist_id=3, raw_name="Death Cab for Cutie", mbid=None)]
        result = match_artist("Death Cab", taste)
        assert result is not None
        assert result.status == "review", "Ambiguous match must be flagged for review"
        assert 0.55 <= result.confidence < 0.75

    def test_no_plausible_candidate_returns_none(self) -> None:
        from showcat.resolve.matcher import TasteArtist

        taste = [TasteArtist(artist_id=4, raw_name="Modest Mouse", mbid=None)]
        assert match_artist("Completely Unrelated XYZ", taste) is None

    def test_single_token_guard_routes_to_review_not_matched(self) -> None:
        """'The Strike' must not auto-match 'The Strokes' — single-token guard."""
        from showcat.resolve.matcher import TasteArtist

        taste = [TasteArtist(artist_id=10, raw_name="The Strokes", mbid=None)]
        result = match_artist("The Strike", taste)
        # High char similarity (0.857) but must not be "matched" — routes to review.
        assert result is not None
        assert result.status == "review", "Single-token guard must route 'The Strike' to review"

    def test_token_subset_guard_routes_to_review_not_matched(self) -> None:
        """'The Verve Pipe' must not auto-match 'The Verve' — token-subset guard."""
        from showcat.resolve.matcher import TasteArtist

        taste = [TasteArtist(artist_id=11, raw_name="The Verve", mbid=None)]
        result = match_artist("The Verve Pipe", taste)
        # "the verve" tokens ⊂ "the verve pipe" tokens — must route to review.
        assert result is not None
        assert result.status == "review", "Token-subset guard must route 'The Verve Pipe' to review"

    def test_no_shared_token_guard_routes_to_review(self) -> None:
        """Multi-token names with high char-sim but no shared word must not match.

        'Like Mang' vs 'louke man' scores ~0.78 (above the 0.75 threshold) purely
        on character overlap, but the two names share no distinctive token — a
        coincidental match. Guard 3 routes it to review.
        """
        from showcat.resolve.matcher import TasteArtist

        taste = [TasteArtist(artist_id=20, raw_name="louke man", mbid=None)]
        result = match_artist("Like Mang", taste)
        assert result is not None
        assert result.status == "review", "No-shared-token pair must route to review"

    def test_no_shared_token_guard_heather_christie(self) -> None:
        """'Heather Christie' vs 'The Charities' — no shared distinctive token."""
        from showcat.resolve.matcher import TasteArtist

        taste = [TasteArtist(artist_id=21, raw_name="The Charities", mbid=None)]
        result = match_artist("Heather Christie", taste)
        assert result is not None
        assert result.status == "review"

    def test_shared_token_multiword_still_matches(self) -> None:
        """A real multi-word fuzzy match (shared distinctive token) is unaffected.

        'Bright Eyes' / 'Bright Eyez' share 'bright' (sim 0.909, not a subset) —
        Guard 3 must NOT route this to review.
        """
        from showcat.resolve.matcher import TasteArtist

        taste = [TasteArtist(artist_id=22, raw_name="Bright Eyez", mbid=None)]
        result = match_artist("Bright Eyes", taste)
        assert result is not None
        assert result.status == "matched", "Shared-token multiword match must stay matched"


# ---------------------------------------------------------------------------
# ResolveStage integration tests
# ---------------------------------------------------------------------------


class TestResolveStage:
    def test_exact_match_persisted_as_matched(self, db_session: Session) -> None:
        _seed_artist(db_session, "Modest Mouse", mbid="mm-1")
        event = _seed_event(db_session, "E1", "Modest Mouse", [])
        ResolveStage()._run(db_session)
        db_session.flush()

        match = db_session.execute(
            select(EventMatch).where(EventMatch.event_id == event.id)
        ).scalar_one()
        assert match.status == "matched"
        assert match.match_type == "exact"
        assert match.confidence == 1.0

    def test_fuzzy_match_persisted_with_confidence(self, db_session: Session) -> None:
        _seed_artist(db_session, "Mt. Joy", mbid="mj-1")
        event = _seed_event(db_session, "E2", "Mount Joy", [])
        ResolveStage()._run(db_session)
        db_session.flush()

        match = db_session.execute(
            select(EventMatch).where(EventMatch.event_id == event.id)
        ).scalar_one()
        assert match.match_type == "fuzzy"
        assert match.status == "matched"
        assert match.confidence >= 0.75

    def test_ambiguous_goes_to_review_queue_not_dropped(self, db_session: Session) -> None:
        _seed_artist(db_session, "Death Cab for Cutie")
        event = _seed_event(db_session, "E3", "Death Cab", [])
        ResolveStage()._run(db_session)
        db_session.flush()

        review = db_session.execute(
            select(EventMatch).where(
                EventMatch.event_id == event.id, EventMatch.status == "review"
            )
        ).scalar_one()
        assert review.confidence < 0.75

    def test_unrelated_artist_is_not_matched(self, db_session: Session) -> None:
        _seed_artist(db_session, "Modest Mouse", mbid="mm-1")
        event = _seed_event(db_session, "E4", "Completely Unrelated XYZ", [])
        ResolveStage()._run(db_session)
        db_session.flush()

        count = db_session.execute(
            select(func.count()).select_from(EventMatch).where(EventMatch.event_id == event.id)
        ).scalar_one()
        assert count == 0

    def test_opener_is_resolved_too(self, db_session: Session) -> None:
        _seed_artist(db_session, "Built to Spill", mbid="bts-1")
        event = _seed_event(db_session, "E5", "Some Headliner", ["Built to Spill"])
        ResolveStage()._run(db_session)
        db_session.flush()

        match = db_session.execute(
            select(EventMatch).where(EventMatch.event_id == event.id)
        ).scalar_one()
        assert match.matched_name == "Built to Spill"
        assert match.status == "matched"

    def test_resolve_is_idempotent(self, db_session: Session) -> None:
        _seed_artist(db_session, "Modest Mouse", mbid="mm-1")
        _seed_event(db_session, "E6", "Modest Mouse", ["Built to Spill"])
        _seed_artist(db_session, "Built to Spill", mbid="bts-1")

        ResolveStage()._run(db_session)
        db_session.flush()
        first = db_session.execute(select(func.count()).select_from(EventMatch)).scalar_one()

        ResolveStage()._run(db_session)
        db_session.flush()
        second = db_session.execute(select(func.count()).select_from(EventMatch)).scalar_one()

        assert first == second, "Re-running resolve must not create duplicate matches"
