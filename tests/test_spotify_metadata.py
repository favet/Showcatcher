"""Spotify metadata ingest stage tests.

Verifies that ArtistSpotifyMetadataStage resolves artist and top track information
from Spotify and updates the Artist table in the database.
"""
import datetime as dt
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from showcat.adapters.spotify.client import SpotifyClient
from showcat.ingest.events.models import Event
from showcat.ingest.history.models import Artist
from showcat.ingest.history.spotify_metadata import ArtistSpotifyMetadataStage
from showcat.resolve.models import EventMatch


def _seed_artist(session: Session, name: str, mbid: str | None = None) -> Artist:
    existing = session.execute(select(Artist).where(Artist.raw_name == name)).scalar_one_or_none()
    if existing is not None:
        return existing
    now = datetime.now(UTC)
    artist = Artist(
        raw_name=name, mbid=mbid, resolved=mbid is not None,
        first_seen_at=now, updated_at=now,
    )
    session.add(artist)
    session.flush()
    return artist


class DummySpotifyClient(SpotifyClient):
    """Mock Spotify client that returns predefined artist and track search payloads."""

    def __init__(self, artist_payload: dict[str, Any] | None = None, top_tracks_payload: list[dict[str, Any]] | None = None) -> None:
        self.artist_payload = artist_payload
        self.top_tracks_payload = top_tracks_payload if top_tracks_payload is not None else []
        super().__init__(access_token="dummy_token")

    def search_artist(self, artist_name: str) -> dict[str, Any] | None:
        return self.artist_payload

    def get_artist_top_tracks(self, artist_id: str, market: str = "US") -> list[dict[str, Any]]:
        return self.top_tracks_payload


class TestArtistSpotifyMetadataStage:
    def test_spotify_metadata_is_stored(self, db_session: Session) -> None:
        artist = _seed_artist(db_session, "Gia Margaret", mbid="gia-1")

        # Mock API responses
        artist_data = {
            "id": "gia_id",
            "external_urls": {"spotify": "https://open.spotify.com/artist/gia_id"},
            "images": [{"url": "https://example.com/gia.jpg", "height": 600, "width": 600}],
        }
        top_tracks = [
            {
                "id": "track_id",
                "name": "Solidago",
                "album": {
                    "name": "Romantic Images",
                    "images": [{"url": "https://example.com/album.jpg", "height": 600, "width": 600}],
                },
            }
        ]
        
        client = DummySpotifyClient(artist_payload=artist_data, top_tracks_payload=top_tracks)
        
        # Run with matched_only=False so we fetch for our seeded artist without matches
        stage = ArtistSpotifyMetadataStage(client=client, matched_only=False)
        stage._run(db_session)
        db_session.flush()

        # Query updated artist from DB
        db_session.expire_all()
        artist_db = db_session.execute(select(Artist).where(Artist.id == artist.id)).scalar_one()

        assert artist_db.spotify_url == "https://open.spotify.com/artist/gia_id"
        assert artist_db.image_url == "https://example.com/gia.jpg"
        assert artist_db.album_name == "Romantic Images"
        assert artist_db.album_image_url == "https://example.com/album.jpg"

    def test_matched_only_skips_unmatched_artists(self, db_session: Session) -> None:
        matched = _seed_artist(db_session, "Matched Artist", mbid="m-1")
        unmatched = _seed_artist(db_session, "Unmatched Artist", mbid="u-1")

        # Create a matched event for 'Matched Artist'
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

        artist_data = {
            "id": "matched_id",
            "external_urls": {"spotify": "https://open.spotify.com/artist/matched_id"},
            "images": [{"url": "https://example.com/matched.jpg"}],
        }
        client = DummySpotifyClient(artist_payload=artist_data)
        
        stage = ArtistSpotifyMetadataStage(client=client, matched_only=True)
        stage._run(db_session)
        db_session.flush()

        db_session.expire_all()
        matched_db = db_session.execute(select(Artist).where(Artist.id == matched.id)).scalar_one()
        unmatched_db = db_session.execute(select(Artist).where(Artist.id == unmatched.id)).scalar_one()

        assert matched_db.spotify_url == "https://open.spotify.com/artist/matched_id"
        assert unmatched_db.spotify_url is None
