"""Phase 3 — End-to-end pipeline (vertical slice) golden test.

Gate 3 assertions covered here:
  - The full pipeline runs end-to-end on fixtures and produces a
    *deterministic* digest (golden test).
  - Every digest entry includes ticket_url and on_sale_date.
  - Every digest entry exposes its score breakdown (no black box).
"""
import datetime as dt
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from showcat.cli.run import run_pipeline
from showcat.ingest.events.models import Event
from showcat.ingest.history.models import Artist, Scrobble

GOLDEN = Path(__file__).parent / "fixtures" / "digest" / "expected_digest.json"
REF = datetime(2026, 7, 1, tzinfo=UTC)


def _round_floats(obj: Any, ndigits: int = 4) -> Any:
    """Recursively round floats so the golden comparison is platform-stable."""
    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, dict):
        return {k: _round_floats(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, ndigits) for v in obj]
    return obj


def _seed_artist(session: Session, name: str, mbid: str) -> Artist:
    now = datetime.now(UTC)
    artist = Artist(
        raw_name=name, mbid=mbid, resolved=True, first_seen_at=now, updated_at=now
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


def _seed_event(
    session: Session,
    source_id: str,
    headliner: str,
    openers: list[str],
    venue: str,
    date: dt.date,
    on_sale: dt.date,
) -> None:
    now = datetime.now(UTC)
    session.add(
        Event(
            source="fixture_source", source_id=source_id, headliner=headliner,
            openers=openers, date=date, venue=venue, on_sale_date=on_sale,
            ticket_url=f"https://example.com/{source_id}", first_seen=now, last_seen=now,
        )
    )
    session.flush()


def _seed_world(session: Session) -> None:
    """Seed a coherent taste + events dataset for the slice."""
    when = REF - dt.timedelta(days=1)
    mm = _seed_artist(session, "Modest Mouse", "mm-1")
    bts = _seed_artist(session, "Built to Spill", "bts-1")
    mj = _seed_artist(session, "Mt. Joy", "mj-1")
    _seed_scrobbles(session, mm, when, 3)       # heavy rotation
    _seed_scrobbles(session, bts, when, 1)
    _seed_scrobbles(session, mj, REF - dt.timedelta(days=2), 1)

    # EV1: exact headliner + exact opener match.
    _seed_event(
        session, "EV1", "Modest Mouse", ["Built to Spill"],
        "Crystal Ballroom", dt.date(2026, 7, 15), dt.date(2026, 6, 1),
    )
    # EV2: fuzzy headliner ("Mount Joy" -> "Mt. Joy") above threshold.
    _seed_event(
        session, "EV2", "Mount Joy", [],
        "Wonder Ballroom", dt.date(2026, 7, 18), dt.date(2026, 6, 5),
    )
    # EV3: no taste artist at all -> must not appear in the digest.
    _seed_event(
        session, "EV3", "Some Band Nobody Played", [],
        "Roseland", dt.date(2026, 7, 20), dt.date(2026, 6, 10),
    )


class TestPipelineGolden:
    def test_pipeline_matches_golden_digest(self, db_session: Session) -> None:
        _seed_world(db_session)

        digest = run_pipeline(reference_time=REF)
        produced = _round_floats(digest.to_dict())
        expected = json.loads(GOLDEN.read_text())

        assert produced == expected

    def test_pipeline_is_deterministic(self, db_session: Session) -> None:
        _seed_world(db_session)

        first = _round_floats(run_pipeline(reference_time=REF).to_dict())
        second = _round_floats(run_pipeline(reference_time=REF).to_dict())
        assert first == second, "Pipeline output must be deterministic across runs"

    def test_unmatched_event_absent_from_digest(self, db_session: Session) -> None:
        _seed_world(db_session)

        digest = run_pipeline(reference_time=REF)
        source_ids = {e.source_id for e in digest.entries}
        assert "EV3" not in source_ids, "An event with no taste match must not be in the digest"

    def test_every_entry_has_ticket_url_and_on_sale_date(self, db_session: Session) -> None:
        _seed_world(db_session)

        digest = run_pipeline(reference_time=REF)
        assert digest.entries
        for entry in digest.entries:
            assert entry.ticket_url is not None, f"{entry.source_id} missing ticket_url"
            assert entry.on_sale_date is not None, f"{entry.source_id} missing on_sale_date"

    def test_every_entry_exposes_score_breakdown(self, db_session: Session) -> None:
        _seed_world(db_session)

        digest = run_pipeline(reference_time=REF)
        for entry in digest.entries:
            assert set(entry.score_terms) == {
                "taste", "adjacency", "discovery", "recency", "distance"
            }
            assert entry.score_total == round(sum(entry.score_terms.values()), 6)

    def test_highest_taste_show_ranks_first(self, db_session: Session) -> None:
        _seed_world(db_session)

        digest = run_pipeline(reference_time=REF)
        assert digest.entries[0].headliner == "Modest Mouse"
