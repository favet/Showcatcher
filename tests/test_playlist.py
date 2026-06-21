"""Phase 5.2–5.5 — Discovery playlist tests (offline).

Gate 5 assertions covered here:
  - Dry-run produces a complete, inspectable plan without touching Spotify.
  - Every artist->track resolution is logged with candidates + choice (no black box).
  - Playlist composition reflects discovery weighting: >= N% under-explored artists.
  - An export-file bridge stub exists, proving the Spotify target is swappable.
"""
import datetime as dt
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from showcat.adapters.lastfm.client import LastFmClient
from showcat.adapters.spotify.client import Resolution
from showcat.ingest.events.models import Event
from showcat.ingest.history.models import Artist, ArtistTag, Scrobble
from showcat.outputs.playlist.adapter import PlaylistOutputAdapter
from showcat.outputs.playlist.models import TrackResolution
from showcat.outputs.playlist.writers import (
    ExportFilePlaylistWriter,
    SpotifyPlaylistWriter,
)
from showcat.resolve.models import EventMatch
from showcat.score.stage import ScoreStage

REF = datetime(2026, 7, 1, tzinfo=UTC)
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "lastfm"


# ---------------------------------------------------------------------------
# Test doubles for the injected Last.fm + Spotify edges
# ---------------------------------------------------------------------------


class FakeTopTracks:
    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self._mapping = mapping

    def get_top_tracks(
        self, artist: str, mbid: str | None = None, limit: int = 10  # noqa: ARG002
    ) -> list[str]:
        return self._mapping.get(artist, [])


class FakeResolver:
    """Returns a fixed URI per (artist, track); None marks an unresolvable track."""

    def __init__(self, uri_map: dict[tuple[str, str], str | None]) -> None:
        self._uri_map = uri_map

    def resolve(self, artist: str, track: str, limit: int = 5) -> Resolution:  # noqa: ARG002
        uri = self._uri_map.get((artist, track), f"spotify:track:{artist}-{track}")
        candidates = [
            {"uri": uri or "spotify:track:rejected", "name": track,
             "artist": artist, "match_score": 0.9 if uri else 0.2}
        ]
        return Resolution(artist=artist, track=track, chosen_uri=uri, candidates=candidates)


class FakeSpotifyClient:
    def __init__(self) -> None:
        self.created: list[tuple[str, bool]] = []
        self.replaced: list[tuple[str, list[str]]] = []

    def create_playlist(
        self, name: str, public: bool, description: str = ""  # noqa: ARG002
    ) -> str:
        self.created.append((name, public))
        return "new-playlist-id"

    def replace_items(self, playlist_id: str, uris: list[str]) -> None:
        self.replaced.append((playlist_id, uris))


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def _seed_artist(session: Session, name: str, mbid: str) -> Artist:
    now = datetime.now(UTC)
    artist = Artist(
        raw_name=name, mbid=mbid, resolved=True, first_seen_at=now, updated_at=now
    )
    session.add(artist)
    session.flush()
    return artist


def _seed(session: Session, artist: Artist, plays: int) -> None:
    when = REF - dt.timedelta(days=1)
    for i in range(plays):
        session.add(
            Scrobble(
                scrobbled_at=when - dt.timedelta(hours=i),
                artist_name=artist.raw_name, track_name=f"{artist.raw_name}-t{i}",
                artist_id=artist.id, created_at=datetime.now(UTC),
            )
        )
    session.add(ArtistTag(artist_id=artist.id, tag="indie rock", weight=100.0, fetched_at=when))
    session.flush()


def _seed_event(session: Session, source_id: str, artist: Artist) -> Event:
    now = datetime.now(UTC)
    event = Event(
        source="fixture_source", source_id=source_id, headliner=artist.raw_name, openers=[],
        date=dt.date(2026, 7, 15), venue="Crystal Ballroom", on_sale_date=dt.date(2026, 6, 1),
        ticket_url="https://example.com/" + source_id, first_seen=now, last_seen=now,
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


def _seed_scored_world(session: Session) -> None:
    """One heavy-rotation artist + two barely-heard, equally-adjacent artists."""
    heavy = _seed_artist(session, "Heavy Indie", "heavy-1")
    light_a = _seed_artist(session, "Barely A", "light-a")
    light_b = _seed_artist(session, "Barely B", "light-b")
    _seed(session, heavy, 50)
    _seed(session, light_a, 1)
    _seed(session, light_b, 2)
    for sid, artist in [("EH", heavy), ("EA", light_a), ("EB", light_b)]:
        _seed_event(session, sid, artist)
    ScoreStage(scoring_version="discovery-v1", reference_time=REF)._run(session)
    session.flush()


_TRACKS = FakeTopTracks(
    {"Heavy Indie": ["Heavy Hit"], "Barely A": ["A Song"], "Barely B": ["B Song"]}
)
_RESOLVER = FakeResolver(
    {
        ("Heavy Indie", "Heavy Hit"): "spotify:track:heavy",
        ("Barely A", "A Song"): "spotify:track:a",
        ("Barely B", "B Song"): None,  # unresolvable — must be recorded, not dropped
    }
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDryRunPlan:
    def test_plan_built_without_writing(self, db_session: Session) -> None:
        _seed_scored_world(db_session)
        plan = PlaylistOutputAdapter().build(db_session, _TRACKS, _RESOLVER)
        db_session.flush()

        assert len(plan.entries) == 3
        # The two resolvable tracks make the URI list; the unresolved one does not.
        assert set(plan.resolved_uris) == {"spotify:track:heavy", "spotify:track:a"}
        d = plan.to_dict()
        assert d["track_count"] == 3
        assert d["resolved_count"] == 2

    def test_discovery_ranks_under_explored_first(self, db_session: Session) -> None:
        _seed_scored_world(db_session)
        plan = PlaylistOutputAdapter().build(db_session, _TRACKS, _RESOLVER)
        # Heavy-rotation artist is last under discovery weighting.
        assert plan.entries[-1].artist_name == "Heavy Indie"


class TestResolutionLogging:
    def test_every_resolution_persisted_with_candidates_and_choice(
        self, db_session: Session
    ) -> None:
        _seed_scored_world(db_session)
        PlaylistOutputAdapter().build(db_session, _TRACKS, _RESOLVER)
        db_session.flush()

        rows = db_session.execute(select(TrackResolution)).scalars().all()
        assert len(rows) == 3
        for row in rows:
            assert row.candidates, "every resolution records its candidate set"
        chosen = {(r.artist_name, r.track_name): r.chosen_uri for r in rows}
        assert chosen[("Barely A", "A Song")] == "spotify:track:a"
        # Unresolvable track is recorded with a null URI, not dropped.
        assert chosen[("Barely B", "B Song")] is None

    def test_resolution_is_idempotent(self, db_session: Session) -> None:
        _seed_scored_world(db_session)
        adapter = PlaylistOutputAdapter()
        adapter.build(db_session, _TRACKS, _RESOLVER)
        db_session.flush()
        first = db_session.execute(
            select(func.count()).select_from(TrackResolution)
        ).scalar_one()
        adapter.build(db_session, _TRACKS, _RESOLVER)
        db_session.flush()
        second = db_session.execute(
            select(func.count()).select_from(TrackResolution)
        ).scalar_one()
        assert first == second


class TestDiscoveryComposition:
    def test_under_explored_share_meets_floor(self, db_session: Session) -> None:
        _seed_scored_world(db_session)
        adapter = PlaylistOutputAdapter()
        plan = adapter.build(db_session, _TRACKS, _RESOLVER)
        # 2 of 3 artists are under-explored (<= 25 plays) => 66.7% >= 50% floor.
        assert plan.under_explored_pct >= 0.5
        assert adapter.meets_discovery_floor(plan) is True


class TestSwappableWriters:
    def test_export_file_stub_writes_plan(self, db_session: Session, tmp_path: Path) -> None:
        _seed_scored_world(db_session)
        plan = PlaylistOutputAdapter().build(db_session, _TRACKS, _RESOLVER)

        out = tmp_path / "playlist.json"
        locator = ExportFilePlaylistWriter(out).write(plan.name, plan.public, plan.resolved_uris)
        assert Path(locator).exists()
        payload = json.loads(out.read_text())
        assert payload["track_uris"] == plan.resolved_uris
        assert payload["name"] == plan.name

    def test_spotify_writer_creates_then_replaces(self, db_session: Session) -> None:
        _seed_scored_world(db_session)
        plan = PlaylistOutputAdapter().build(db_session, _TRACKS, _RESOLVER)

        fake = FakeSpotifyClient()
        writer = SpotifyPlaylistWriter(fake, playlist_id=None)  # type: ignore[arg-type]
        locator = writer.write(plan.name, plan.public, plan.resolved_uris)

        assert locator == "spotify:playlist:new-playlist-id"
        assert fake.created == [(plan.name, False)]
        assert fake.replaced == [("new-playlist-id", plan.resolved_uris)]

    def test_spotify_writer_refreshes_existing(self, db_session: Session) -> None:
        _seed_scored_world(db_session)
        plan = PlaylistOutputAdapter().build(db_session, _TRACKS, _RESOLVER)

        fake = FakeSpotifyClient()
        writer = SpotifyPlaylistWriter(fake, playlist_id="existing-id")  # type: ignore[arg-type]
        locator = writer.write(plan.name, plan.public, plan.resolved_uris)
        assert locator == "spotify:playlist:existing-id"
        assert fake.created == []  # refreshed, not created
        assert fake.replaced == [("existing-id", plan.resolved_uris)]


class TestLastFmTopTracks:
    def test_get_top_tracks_parses_fixture(
        self, monkeypatch: "Any"
    ) -> None:
        client = LastFmClient(api_key="fake", user="testuser")
        fixture = json.loads(
            (FIXTURES_DIR / "artist_top_tracks_built_to_spill.json").read_text()
        )
        monkeypatch.setattr(client, "_get", lambda _p: fixture)
        tracks = client.get_top_tracks("Built to Spill")
        assert tracks[0] == "Carry the Zero"
        assert len(tracks) == 3
