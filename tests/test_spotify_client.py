"""Phase 5.3/5.4 — Spotify client tests (offline; HTTP mocked).

Covers URI resolution (with its candidate set + choice) and the playlist
write calls, all without touching the network.
"""
import json
from pathlib import Path
from typing import Any

import pytest

from opener.adapters.spotify.client import SpotifyClient

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "spotify"


def load_fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES_DIR / name).read_text())
    return data


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class TestResolve:
    def test_resolves_best_candidate_and_records_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = SpotifyClient(access_token="tok")
        fixture = load_fixture("search_carry_the_zero.json")
        monkeypatch.setattr(
            client._session, "get", lambda *_a, **_k: FakeResponse(200, fixture)
        )

        resolution = client.resolve("Built to Spill", "Carry the Zero")
        # The exact-title, correct-artist track wins over the live + cover variants.
        assert resolution.chosen_uri == "spotify:track:0CZ1Carry"
        # Every candidate considered is recorded with a match score (no black box).
        assert len(resolution.candidates) == 3
        assert all("match_score" in c for c in resolution.candidates)
        # Candidates are ranked best-first.
        assert resolution.candidates[0]["uri"] == "spotify:track:0CZ1Carry"

    def test_no_match_leaves_uri_unresolved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = SpotifyClient(access_token="tok")
        empty = {"tracks": {"items": []}}
        monkeypatch.setattr(
            client._session, "get", lambda *_a, **_k: FakeResponse(200, empty)
        )
        resolution = client.resolve("Nobody", "Nothing")
        assert resolution.chosen_uri is None
        assert resolution.candidates == []


class TestPlaylistWrite:
    def test_create_and_replace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = SpotifyClient(access_token="tok")
        calls: dict[str, Any] = {}

        def fake_get(_url: str, **_k: Any) -> FakeResponse:
            return FakeResponse(200, {"id": "user-1"})

        def fake_post(url: str, **kwargs: Any) -> FakeResponse:
            calls["post_url"] = url
            calls["post_body"] = kwargs.get("json")
            return FakeResponse(201, {"id": "playlist-9"})

        def fake_put(url: str, **kwargs: Any) -> FakeResponse:
            calls["put_url"] = url
            calls["put_body"] = kwargs.get("json")
            return FakeResponse(200, {})

        monkeypatch.setattr(client._session, "get", fake_get)
        monkeypatch.setattr(client._session, "post", fake_post)
        monkeypatch.setattr(client._session, "put", fake_put)

        playlist_id = client.create_playlist("My Playlist", public=False)
        assert playlist_id == "playlist-9"
        # Feb-2026 endpoints: create via /me/playlists, write items via /items.
        assert calls["post_url"].endswith("/me/playlists")

        client.replace_items(playlist_id, ["spotify:track:a", "spotify:track:b"])
        assert calls["put_url"].endswith("/playlists/playlist-9/items")
        assert calls["put_body"] == {"uris": ["spotify:track:a", "spotify:track:b"]}
