"""Phase 4.1 — Artist tag ingest tests.

Verifies the Last.fm top-tags adapter method parses the committed fixture and
that ArtistTagStage stores tag vectors idempotently.
"""
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opener.adapters.lastfm.client import LastFmClient
from opener.ingest.history.models import Artist, ArtistTag
from opener.ingest.history.tag_ingest import ArtistTagStage

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
