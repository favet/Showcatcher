"""Phase 4.1 — Artist tag ingest tests.

Verifies the Last.fm top-tags adapter method parses the committed fixture and
that ArtistTagStage stores tag vectors idempotently.
"""
import datetime as dt
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opener.adapters.lastfm.client import LastFmClient
from opener.ingest.events.models import Event
from opener.ingest.history.models import Artist, ArtistTag
from opener.ingest.history.tag_ingest import ArtistTagStage
from opener.resolve.models import EventMatch

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "lastfm"


def load_fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES_DIR / name).read_text())
    return data


def _seed_artist(session: Session, name: str, mbid: str | None = None) -> Artist:
    now = datetime.now(UTC)
    artist = Artist(
        raw_name=name, mbid=mbid, resolved=mbid is not None,
        first_seen_at=now, updated_at=now,
    )
    session.add(artist)
    session.flush()
    return artist


class TestGetTopTags:
    def test_parses_fixture_tags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = LastFmClient(api_key="fake", user="testuser")
        fixture = load_fixture("artist_top_tags_modest_mouse.json")
        monkeypatch.setattr(client, "_get", lambda _p: fixture)

        tags = client.get_top_tags("Modest Mouse")
        assert ("indie rock", 100.0) in tags
        assert len(tags) == 4
        # Weights are returned verbatim (0-100) for downstream normalisation.
        assert all(isinstance(w, float) for _, w in tags)


class TestArtistTagStage:
    def _client_returning(
        self, fixture: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> LastFmClient:
        client = LastFmClient(api_key="fake", user="testuser")
        monkeypatch.setattr(client, "_get", lambda _params: fixture)
        return client

    def test_tags_are_stored(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        artist = _seed_artist(db_session, "Modest Mouse", mbid="mm-1")
        client = self._client_returning(
            load_fixture("artist_top_tags_modest_mouse.json"), monkeypatch
        )

        ArtistTagStage(client=client)._run(db_session)
        db_session.flush()

        count = db_session.execute(
            select(func.count()).select_from(ArtistTag).where(ArtistTag.artist_id == artist.id)
        ).scalar_one()
        assert count == 4

    def test_tag_ingest_is_idempotent(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_artist(db_session, "Modest Mouse", mbid="mm-1")
        client = self._client_returning(
            load_fixture("artist_top_tags_modest_mouse.json"), monkeypatch
        )

        ArtistTagStage(client=client)._run(db_session)
        db_session.flush()
        first = db_session.execute(select(func.count()).select_from(ArtistTag)).scalar_one()

        ArtistTagStage(client=client)._run(db_session)
        db_session.flush()
        second = db_session.execute(select(func.count()).select_from(ArtistTag)).scalar_one()
        assert first == second, "Re-running tag ingest must not duplicate tag rows"

    def test_matched_only_skips_unmatched_artists(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """matched_only=True fetches tags only for artists with a matched event."""
        matched = _seed_artist(db_session, "Matched Artist", mbid="m-1")
        unmatched = _seed_artist(db_session, "Unmatched Artist", mbid="u-1")

        now = datetime.now(UTC)
        event = Event(
            source="fixture_source", source_id="E1", headliner="Matched Artist", openers=[],
            date=dt.date(2026, 7, 15), venue="Crystal Ballroom", on_sale_date=dt.date(2026, 6, 1),
            ticket_url="https://example.com/E1", first_seen=now, last_seen=now,
        )
        db_session.add(event)
        db_session.flush()
        db_session.add(
            EventMatch(
                event_id=event.id, artist_id=matched.id, matched_name="Matched Artist",
                match_type="exact", confidence=1.0, status="matched", created_at=now,
            )
        )
        db_session.flush()

        client = self._client_returning(
            load_fixture("artist_top_tags_modest_mouse.json"), monkeypatch
        )
        ArtistTagStage(client=client, matched_only=True)._run(db_session)
        db_session.flush()

        matched_tags = db_session.execute(
            select(func.count()).select_from(ArtistTag).where(ArtistTag.artist_id == matched.id)
        ).scalar_one()
        unmatched_tags = db_session.execute(
            select(func.count()).select_from(ArtistTag).where(ArtistTag.artist_id == unmatched.id)
        ).scalar_one()
        assert matched_tags > 0
        assert unmatched_tags == 0, "matched_only must skip artists with no matched event"
