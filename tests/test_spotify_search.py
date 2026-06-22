"""EventSpotifySearchStage — per-run cap + rate-limit (429) handling.

These guard the Spotify quota: the stage must cap its burst (so a large backlog
doesn't blow the rolling window) and must STOP on a 429 (a fixed multi-hour
cooldown) rather than hammer it or mis-store transient failures as "not found".
"""
import datetime as dt
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from showcat.adapters.spotify.client import SpotifyError
from showcat.ingest.events import spotify_search as ss
from showcat.ingest.events.models import Event


def _seed_event(session: Session, source_id: str, headliner: str) -> Event:
    now = datetime.now(UTC)
    event = Event(
        source="fixture_source",
        source_id=source_id,
        headliner=headliner,
        openers=[],
        date=dt.date.today() + dt.timedelta(days=10),
        venue="Crystal Ballroom",
        ticket_url="https://example.com/" + source_id,
        first_seen=now,
        last_seen=now,
    )
    session.add(event)
    session.flush()
    return event


class _FakeClient:
    """Stand-in SpotifyClient; records calls and returns/raises as scripted."""

    def __init__(self, result=None, raise_on_call: int | None = None,
                 error: Exception | None = None) -> None:
        self._result = result
        self._raise_on_call = raise_on_call
        self._error = error
        self.calls = 0

    def search_artist(self, name: str):  # noqa: ARG002 — mirrors the real signature
        self.calls += 1
        if self._raise_on_call is not None and self.calls >= self._raise_on_call:
            raise self._error  # type: ignore[misc]
        return self._result


def test_clean_miss_is_stored_as_none(db_session: Session) -> None:
    """An empty (but successful) search stores the 'none' sentinel."""
    _seed_event(db_session, "E1", "Nonexistent Band XYZ")
    db_session.flush()

    stage = ss.EventSpotifySearchStage(client=_FakeClient(result=None))
    updated = stage._run(db_session)

    assert updated == 1
    ev = db_session.execute(select(Event).where(Event.source_id == "E1")).scalar_one()
    assert ev.event_spotify_url == "none"


def test_per_run_cap_limits_batch(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """No more than MAX_PER_RUN events are searched in one run."""
    monkeypatch.setattr(ss, "MAX_PER_RUN", 2)
    monkeypatch.setattr(ss, "REQUEST_DELAY_S", 0.0)
    for i in range(5):
        _seed_event(db_session, f"C{i}", f"Band {i}")
    db_session.flush()

    client = _FakeClient(result=None)
    updated = ss.EventSpotifySearchStage(client=client)._run(db_session)

    assert client.calls == 2, "must stop at the per-run cap"
    assert updated == 2

    # The remaining 3 are untouched (NULL) so a later run resumes them.
    remaining = db_session.execute(
        select(Event).where(Event.event_spotify_url.is_(None))
    ).scalars().all()
    assert len(remaining) == 3


def test_429_stops_stage_and_leaves_rest_null(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 429 stops the stage immediately; unsearched events stay NULL (not 'none')."""
    monkeypatch.setattr(ss, "REQUEST_DELAY_S", 0.0)
    for i in range(4):
        _seed_event(db_session, f"R{i}", f"Rate Band {i}")
    db_session.flush()

    err = SpotifyError("GET /search failed (429)", status_code=429, retry_after=3600)
    client = _FakeClient(result=None, raise_on_call=2, error=err)
    updated = ss.EventSpotifySearchStage(client=client)._run(db_session)

    # First call stored "none"; second call 429'd and stopped the stage.
    assert updated == 1
    nulls = db_session.execute(
        select(Event).where(Event.event_spotify_url.is_(None))
    ).scalars().all()
    assert len(nulls) == 3, "events after the 429 must remain NULL for a later retry"


def test_non_429_error_does_not_store_none(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient non-429 error leaves the event NULL (not a permanent 'none')."""
    monkeypatch.setattr(ss, "REQUEST_DELAY_S", 0.0)
    _seed_event(db_session, "X1", "Some Band")
    db_session.flush()

    err = SpotifyError("GET /search failed (500)", status_code=500)
    client = _FakeClient(result=None, raise_on_call=1, error=err)
    updated = ss.EventSpotifySearchStage(client=client)._run(db_session)

    assert updated == 0
    ev = db_session.execute(select(Event).where(Event.source_id == "X1")).scalar_one()
    assert ev.event_spotify_url is None
