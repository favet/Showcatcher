"""Spotify Web API client — the narrow surviving surface we depend on.

Only three operations are used: `/search` (resolve a track name to a URI),
create a playlist, and replace a playlist's items. Track *selection* stays on
Last.fm; Spotify is just the URI resolver + write target, so further Spotify
API erosion can't strand the hero output.

Every URI resolution returns its full candidate set and the chosen URI — the
"no black box" record persisted by the playlist adapter. Network is confined
to the `_get`/`_post`/`_put` helpers so unit tests run offline.
"""
import logging
from dataclasses import dataclass, field
from typing import Any

import requests

from showcat.resolve.matcher import similarity

logger = logging.getLogger(__name__)

SPOTIFY_API_BASE = "https://api.spotify.com/v1"
# At/above this combined artist+track match we accept a URI automatically.
RESOLUTION_THRESHOLD = 0.6


@dataclass
class Resolution:
    """The outcome of resolving one (artist, track) to a Spotify URI."""

    artist: str
    track: str
    chosen_uri: str | None
    candidates: list[dict[str, Any]] = field(default_factory=list)


class SpotifyError(Exception):
    """Raised on a non-success Spotify API response."""


class SpotifyClient:
    """Authenticated Spotify client. Pass a current access token."""

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token
        self._session = requests.Session()

    # --- HTTP helpers (the only network edges) ---------------------------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        resp = self._session.get(
            f"{SPOTIFY_API_BASE}{path}", headers=self._headers(), params=params, timeout=30
        )
        if resp.status_code != 200:
            raise SpotifyError(f"GET {path} failed ({resp.status_code}): {resp.text}")
        data: dict[str, Any] = resp.json()
        return data

    def _post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any]:
        resp = self._session.post(
            f"{SPOTIFY_API_BASE}{path}", headers=self._headers(), json=json_body, timeout=30
        )
        if resp.status_code not in (200, 201):
            raise SpotifyError(f"POST {path} failed ({resp.status_code}): {resp.text}")
        data: dict[str, Any] = resp.json()
        return data

    def _put(self, path: str, json_body: dict[str, Any]) -> None:
        resp = self._session.put(
            f"{SPOTIFY_API_BASE}{path}", headers=self._headers(), json=json_body, timeout=30
        )
        if resp.status_code not in (200, 201):
            raise SpotifyError(f"PUT {path} failed ({resp.status_code}): {resp.text}")

    # --- URI resolution ---------------------------------------------------

    def resolve(self, artist: str, track: str, limit: int = 5) -> Resolution:
        """Resolve (artist, track) to a Spotify URI via /search, explainably.

        Returns a Resolution carrying every candidate considered (with its match
        score) and the chosen URI — or None if nothing cleared the threshold.
        """
        data = self._get(
            "/search",
            {"q": f"artist:{artist} track:{track}", "type": "track", "limit": limit},
        )
        items = data.get("tracks", {}).get("items", [])
        candidates: list[dict[str, Any]] = []
        for item in items:
            item_artist = ", ".join(a.get("name", "") for a in item.get("artists", []))
            item_name = item.get("name", "")
            score = round(
                0.5 * similarity(artist, item_artist) + 0.5 * similarity(track, item_name),
                6,
            )
            candidates.append(
                {
                    "uri": item.get("uri"),
                    "name": item.get("name"),
                    "artist": item_artist,
                    "popularity": item.get("popularity"),
                    "match_score": score,
                }
            )

        candidates.sort(key=lambda c: (-c["match_score"], c.get("uri") or ""))
        chosen_uri: str | None = None
        if candidates and candidates[0]["match_score"] >= RESOLUTION_THRESHOLD:
            chosen_uri = candidates[0]["uri"]

        logger.info(
            "Track resolution",
            extra={
                "artist": artist,
                "track": track,
                "chosen_uri": chosen_uri,
                "candidate_count": len(candidates),
            },
        )
        return Resolution(artist=artist, track=track, chosen_uri=chosen_uri, candidates=candidates)

    # --- Playlist write ---------------------------------------------------

    def current_user_id(self) -> str:
        return str(self._get("/me", {}).get("id", ""))

    def create_playlist(self, name: str, public: bool, description: str = "") -> str:
        """Create a playlist for the current user; return its id.

        Uses POST /me/playlists (the Feb-2026 endpoint; the older
        /users/{id}/playlists form is gone).
        """
        data = self._post(
            "/me/playlists",
            {"name": name, "public": public, "description": description},
        )
        return str(data["id"])

    def replace_items(self, playlist_id: str, uris: list[str]) -> None:
        """Replace all items in a playlist (idempotent refresh).

        Uses PUT /playlists/{id}/items (Feb-2026 rename; the older
        /playlists/{id}/tracks endpoint is gone).
        """
        self._put(f"/playlists/{playlist_id}/items", {"uris": uris})

    def search_artist(self, artist_name: str) -> dict[str, Any] | None:
        """Search for an artist by name. Returns the first matching artist object or None."""
        try:
            data = self._get(
                "/search",
                {"q": f"artist:\"{artist_name}\"", "type": "artist", "limit": 1},
            )
            items = data.get("artists", {}).get("items", [])
            if items:
                return items[0]
        except Exception as e:
            logger.warning(f"Failed to search Spotify artist '{artist_name}': {e}")
        return None

    def get_artist_top_tracks(self, artist_id: str, market: str = "US") -> list[dict[str, Any]]:
        """Get top tracks for an artist. Returns list of track objects."""
        try:
            data = self._get(
                f"/artists/{artist_id}/top-tracks",
                {"market": market},
            )
            return data.get("tracks", [])
        except Exception as e:
            logger.warning(f"Failed to get Spotify top tracks for artist ID '{artist_id}': {e}")
        return []
