"""Phase 1 — Listening-History Ingest tests.

Gate 1 assertions:
  - Backfill loads scrobble count from fixture; reconciles with reported count.
  - Re-running backfill produces zero duplicate scrobbles.
  - Incremental only picks up scrobbles newer than the last stored timestamp.
  - MBID resolver resolves a known artist; unknown artist lands in unresolved queue.
  - Affinity query returns sensible top-N; changing half_life changes weights.
"""
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opener.adapters.lastfm.client import LastFmClient
from opener.core.affinity import compute_decayed_affinity
from opener.ingest.history.backfill import HistoryBackfillStage, _parse_scrobble
from opener.ingest.history.incremental import HistoryIncrementalStage
from opener.ingest.history.mbid_resolve import MbidResolveStage
from opener.ingest.history.models import Artist, ArtistUnresolvedQueue, Scrobble

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "lastfm"


def load_fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES_DIR / name).read_text())
    return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client_from_fixture(fixture_name: str, monkeypatch: pytest.MonkeyPatch) -> LastFmClient:
    """Return a LastFmClient whose _get() is patched to return fixture data."""
    client = LastFmClient(api_key="fake", user="testuser")
    fixture_data = load_fixture(fixture_name)
    monkeypatch.setattr(client, "_get", lambda _params: fixture_data)
    return client


# ---------------------------------------------------------------------------
# _parse_scrobble unit tests
# ---------------------------------------------------------------------------


class TestClientRetry:
    def test_retries_transient_5xx_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 500 then a 200 should succeed after one retry (no backoff sleep in test)."""
        import requests

        from opener.adapters.lastfm import client as client_mod

        monkeypatch.setattr(client_mod.time, "sleep", lambda _s: None)
        client = LastFmClient(api_key="fake", user="testuser")

        calls = {"n": 0}

        class Resp:
            def __init__(self, status: int) -> None:
                self.status_code = status

            def raise_for_status(self) -> None:
                if self.status_code >= 500:
                    err = requests.exceptions.HTTPError("500 Server Error")
                    err.response = self  # type: ignore[assignment]
                    raise err

            def json(self) -> dict[str, Any]:
                return {"ok": True}

        def fake_get(*_a: Any, **_k: Any) -> Resp:
            calls["n"] += 1
            return Resp(500 if calls["n"] == 1 else 200)

        monkeypatch.setattr(client._session, "get", fake_get)
        assert client._get({"method": "x"}) == {"ok": True}
        assert calls["n"] == 2  # first failed, second succeeded

    def test_does_not_retry_4xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import requests

        client = LastFmClient(api_key="fake", user="testuser")

        class Resp:
            status_code = 403

            def raise_for_status(self) -> None:
                err = requests.exceptions.HTTPError("403")
                err.response = self  # type: ignore[assignment]
                raise err

            def json(self) -> dict[str, Any]:
                return {}

        calls = {"n": 0}

        def fake_get(*_a: Any, **_k: Any) -> Resp:
            calls["n"] += 1
            return Resp()

        monkeypatch.setattr(client._session, "get", fake_get)
        with pytest.raises(requests.exceptions.HTTPError):
            client._get({"method": "x"})
        assert calls["n"] == 1  # 4xx is not retried


class TestParseScrobble:
    def test_parses_normal_track(self) -> None:
        fixture = load_fixture("recent_tracks_page1.json")
        track = fixture["recenttracks"]["track"][0]
        result = _parse_scrobble(track)
        assert result is not None
        assert result["artist_name"] == "Modest Mouse"
        assert result["track_name"] == "Float On"

    def test_skips_now_playing(self) -> None:
        track = {
            "artist": {"#text": "Someone"},
            "name": "A Song",
            "@attr": {"nowplaying": "true"},
        }
        assert _parse_scrobble(track) is None

    def test_skips_missing_timestamp(self) -> None:
        track = {"artist": {"#text": "Someone"}, "name": "A Song", "@attr": {}}
        assert _parse_scrobble(track) is None


# ---------------------------------------------------------------------------
# Backfill Stage
# ---------------------------------------------------------------------------


class TestHistoryBackfillStage:
    def test_backfill_loads_all_fixture_scrobbles(
        self,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Backfill should insert all scrobbles from the fixture page."""
        fixture = load_fixture("recent_tracks_page1.json")
        expected_total = int(fixture["recenttracks"]["@attr"]["total"])

        # Patch env and client
        monkeypatch.setenv("LASTFM_API_KEY", "fake")
        monkeypatch.setenv("LASTFM_USER", "testuser")

        def fake_get(_self: object, params: dict[str, Any]) -> dict[str, Any]:
            if params.get("method") == "user.getinfo":
                return load_fixture("user_info.json")
            return fixture

        with patch.object(LastFmClient, "_get", fake_get):
            stage = HistoryBackfillStage()
            stage._run(db_session)
            db_session.flush()

        count = db_session.execute(select(func.count()).select_from(Scrobble)).scalar_one()
        assert count == expected_total, (
            f"Expected {expected_total} scrobbles (as reported by Last.fm fixture), got {count}"
        )

    def test_backfill_is_idempotent(
        self,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Re-running backfill with the same data produces zero additional scrobbles."""
        fixture = load_fixture("recent_tracks_page1.json")
        monkeypatch.setenv("LASTFM_API_KEY", "fake")
        monkeypatch.setenv("LASTFM_USER", "testuser")

        def fake_get(_self: object, _params: dict[str, Any]) -> dict[str, Any]:
            return fixture

        with patch.object(LastFmClient, "_get", fake_get):
            stage = HistoryBackfillStage()
            stage._run(db_session)
            db_session.flush()
            count_after_first = db_session.execute(
                select(func.count()).select_from(Scrobble)
            ).scalar_one()

            # Run again — should produce zero new rows
            stage._run(db_session)
            db_session.flush()
            count_after_second = db_session.execute(
                select(func.count()).select_from(Scrobble)
            ).scalar_one()

        assert count_after_first == count_after_second, (
            "Re-running backfill produced duplicate scrobbles — idempotency broken"
        )

    def test_since_ts_bounds_the_backfill(
        self,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Passing since_ts pushes the `from` floor to the Last.fm request."""
        monkeypatch.setenv("LASTFM_API_KEY", "fake")
        monkeypatch.setenv("LASTFM_USER", "testuser")
        captured: dict[str, Any] = {}

        def fake_get(_self: object, params: dict[str, Any]) -> dict[str, Any]:
            captured["from"] = params.get("from")
            return {
                "recenttracks": {
                    "track": [],
                    "@attr": {"page": "1", "totalPages": "1", "total": "0"},
                }
            }

        with patch.object(LastFmClient, "_get", fake_get):
            HistoryBackfillStage()._run(db_session, since_ts=1_700_000_000)

        assert captured["from"] == 1_700_000_000


# ---------------------------------------------------------------------------
# Incremental Stage
# ---------------------------------------------------------------------------


class TestHistoryIncrementalStage:
    def test_incremental_skips_already_stored(
        self,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Incremental stage with empty API response after seeding produces 0 new rows."""
        # Seed one scrobble
        now_ts = 1718755200
        scrobble = Scrobble(
            scrobbled_at=datetime.fromtimestamp(now_ts, tz=UTC),
            artist_name="Modest Mouse",
            track_name="Float On",
            created_at=datetime.now(UTC),
        )
        db_session.add(scrobble)
        db_session.flush()

        monkeypatch.setenv("LASTFM_API_KEY", "fake")
        monkeypatch.setenv("LASTFM_USER", "testuser")

        # API returns empty page (no new scrobbles since stored timestamp)
        empty_response = {
            "recenttracks": {
                "track": [],
                "@attr": {"user": "testuser", "page": "1", "totalPages": "1", "total": "0"},
            }
        }

        with patch.object(LastFmClient, "_get", lambda _s, _p: empty_response):
            stage = HistoryIncrementalStage()
            inserted = stage._run(db_session)

        assert inserted == 0


# ---------------------------------------------------------------------------
# MBID Resolution Stage
# ---------------------------------------------------------------------------


class TestMbidResolveStage:
    def _seed_artist(self, session: Session, name: str) -> Artist:
        artist = Artist(
            raw_name=name,
            resolved=False,
            first_seen_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(artist)
        session.flush()
        return artist

    def test_resolves_known_artist(
        self,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Artist with matching search result gets MBID and resolved=True."""
        self._seed_artist(db_session, "Mt. Joy")
        monkeypatch.setenv("LASTFM_API_KEY", "fake")
        monkeypatch.setenv("LASTFM_USER", "testuser")

        fixture_data = load_fixture("artist_search_mt_joy.json")

        with patch.object(LastFmClient, "_get", lambda _s, _p: fixture_data):
            stage = MbidResolveStage()
            resolved = stage._run(db_session)
            db_session.flush()

        assert resolved == 1
        artist = db_session.execute(
            select(Artist).where(Artist.raw_name == "Mt. Joy")
        ).scalar_one()
        assert artist.resolved is True
        assert artist.mbid == "b5f5caf4-7e2f-4638-8a74-0c6d64b47ff8"

    def test_unknown_artist_lands_in_unresolved_queue(
        self,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Artist with no matching search result goes to unresolved queue, not silently dropped."""
        self._seed_artist(db_session, "Unknown Band XYZ")
        monkeypatch.setenv("LASTFM_API_KEY", "fake")
        monkeypatch.setenv("LASTFM_USER", "testuser")

        no_match: dict[str, Any] = {"results": {"artistmatches": {"artist": []}}}

        with patch.object(LastFmClient, "_get", lambda _s, _p: no_match):
            stage = MbidResolveStage()
            resolved = stage._run(db_session)
            db_session.flush()

        assert resolved == 0

        queue_count = db_session.execute(
            select(func.count()).select_from(ArtistUnresolvedQueue)
        ).scalar_one()
        assert queue_count == 1, "Unknown artist must appear in unresolved queue"

        queue_entry = db_session.execute(
            select(ArtistUnresolvedQueue).where(
                ArtistUnresolvedQueue.raw_name == "Unknown Band XYZ"
            )
        ).scalar_one()
        assert queue_entry.failure_reason == "no_match"


# ---------------------------------------------------------------------------
# Affinity Query
# ---------------------------------------------------------------------------

REF_TIME = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)


def _make_plays() -> list[tuple[str, str | None, datetime]]:
    """Fixture plays: Modest Mouse x3, Mt. Joy x1, all recent."""
    return [
        ("Modest Mouse", "d517b1f5-4ea9-4e00-bfbb-aaa6c91b1d5d", datetime(2026, 6, 30, tzinfo=UTC)),
        ("Modest Mouse", "d517b1f5-4ea9-4e00-bfbb-aaa6c91b1d5d", datetime(2026, 6, 20, tzinfo=UTC)),
        ("Modest Mouse", "d517b1f5-4ea9-4e00-bfbb-aaa6c91b1d5d", datetime(2026, 6, 1, tzinfo=UTC)),
        ("Mt. Joy", "b5f5caf4-7e2f-4638-8a74-0c6d64b47ff8", datetime(2026, 6, 29, tzinfo=UTC)),
    ]


class TestDecayedAffinity:
    def test_top_artist_is_most_played_recent(self) -> None:
        """Modest Mouse (3 recent plays) should rank above Mt. Joy (1 play)."""
        scores = compute_decayed_affinity(_make_plays(), top_n=10, reference_time=REF_TIME)
        assert len(scores) >= 2
        assert scores[0].raw_name == "Modest Mouse"

    def test_returns_correct_key_for_resolved_artist(self) -> None:
        """Resolved artist uses MBID as key, not raw name."""
        scores = compute_decayed_affinity(_make_plays(), top_n=10, reference_time=REF_TIME)
        keys = [s.key for s in scores]
        assert "d517b1f5-4ea9-4e00-bfbb-aaa6c91b1d5d" in keys

    def test_changing_half_life_changes_weights(self) -> None:
        """Longer half-life gives more weight to older plays — scores must differ."""
        scores_short = compute_decayed_affinity(
            _make_plays(), half_life_days=14, reference_time=REF_TIME
        )
        scores_long = compute_decayed_affinity(
            _make_plays(), half_life_days=180, reference_time=REF_TIME
        )
        # Find Modest Mouse in both
        short_weight = next(s.weight for s in scores_short if s.raw_name == "Modest Mouse")
        long_weight = next(s.weight for s in scores_long if s.raw_name == "Modest Mouse")
        assert short_weight != long_weight, (
            "Changing half_life_days must produce different affinity weights"
        )

    def test_unresolved_artist_uses_name_as_key(self) -> None:
        """Artist without MBID uses raw name as key — still counted."""
        plays: list[tuple[str, str | None, datetime]] = [
            ("No MBID Artist", None, datetime(2026, 6, 28, tzinfo=UTC)),
        ]
        scores = compute_decayed_affinity(plays, reference_time=REF_TIME)
        assert scores[0].key == "No MBID Artist"
