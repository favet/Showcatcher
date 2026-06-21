"""Last.fm API client — rate-limit-aware, offline-testable via fixtures."""
import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

LASTFM_API_BASE = "https://ws.audioscrobbler.com/2.0/"
# Last.fm terms: max 5 requests/second for most endpoints.
# We stay conservative at 4/s (250 ms between calls).
MIN_INTERVAL_SECONDS = 0.25


class LastFmError(Exception):
    """Raised when Last.fm returns a non-success status code or API error."""


class LastFmClient:
    """Thin, rate-limit-aware HTTP client for the Last.fm API.

    All methods return raw parsed JSON. Fixtures are committed as .json
    files in tests/fixtures/lastfm/ — unit tests monkeypatch _get() to
    return those instead of hitting the network.
    """

    def __init__(self, api_key: str, user: str) -> None:
        self.api_key = api_key
        self.user = user
        self._session = requests.Session()
        self._last_call_at: float = 0.0

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a rate-limited GET against the Last.fm API."""
        # Rate limiting — enforce minimum gap between requests
        elapsed = time.monotonic() - self._last_call_at
        if elapsed < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - elapsed)

        full_params = {
            "api_key": self.api_key,
            "format": "json",
            **params,
        }
        self._last_call_at = time.monotonic()
        response = self._session.get(LASTFM_API_BASE, params=full_params, timeout=30)
        response.raise_for_status()
        data: dict[str, Any] = response.json()

        if "error" in data:
            raise LastFmError(
                f"Last.fm API error {data['error']}: {data.get('message', 'unknown')}"
            )
        return data

    def get_user_info(self) -> dict[str, Any]:
        """Return user profile including total scrobble count for reconciliation."""
        data = self._get({"method": "user.getinfo", "user": self.user})
        return dict(data.get("user", {}))

    def get_recent_tracks(
        self,
        from_ts: int | None = None,
        page: int = 1,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Return one page of scrobbles.

        Args:
            from_ts: Unix timestamp — only return scrobbles after this time.
                     None means return all (used during backfill).
            page: 1-indexed page number.
            limit: Results per page (max 200 per Last.fm docs).

        Returns:
            Parsed JSON response dict with 'recenttracks' key.
        """
        params: dict[str, Any] = {
            "method": "user.getrecenttracks",
            "user": self.user,
            "page": page,
            "limit": limit,
            "extended": 0,
        }
        if from_ts is not None:
            params["from"] = from_ts

        data = self._get(params)
        logger.debug(
            "Fetched recent tracks page",
            extra={
                "page": page,
                "from_ts": from_ts,
                "total_pages": data.get("recenttracks", {})
                .get("@attr", {})
                .get("totalPages"),
            },
        )
        return data

    def get_top_tags(
        self, artist: str, mbid: str | None = None
    ) -> list[tuple[str, float]]:
        """Return an artist's top genre/style tags as (name, weight) pairs.

        Uses artist.getTopTags. Last.fm tag `count` is 0–100; it is returned
        verbatim as the weight so the taste vector can normalise downstream.
        Prefers MBID lookup when available (more precise than name).
        """
        params: dict[str, Any] = {"method": "artist.gettoptags", "autocorrect": 1}
        if mbid:
            params["mbid"] = mbid
        else:
            params["artist"] = artist

        data = self._get(params)
        raw_tags = data.get("toptags", {}).get("tag", [])
        tags: list[tuple[str, float]] = []
        for entry in raw_tags:
            name = entry.get("name")
            if not name:
                continue
            try:
                weight = float(entry.get("count", 0))
            except (TypeError, ValueError):
                weight = 0.0
            tags.append((name, weight))
        return tags

    def get_top_tracks(
        self, artist: str, mbid: str | None = None, limit: int = 10
    ) -> list[str]:
        """Return an artist's most popular track names, most-played first.

        Uses artist.getTopTracks. Track *selection* is kept on Last.fm (off the
        eroding Spotify API) — Spotify is only used later to resolve each track
        name to a URI. Names are returned in Last.fm's playcount order.
        """
        params: dict[str, Any] = {
            "method": "artist.gettoptracks",
            "autocorrect": 1,
            "limit": limit,
        }
        if mbid:
            params["mbid"] = mbid
        else:
            params["artist"] = artist

        data = self._get(params)
        raw_tracks = data.get("toptracks", {}).get("track", [])
        names: list[str] = []
        for entry in raw_tracks:
            name = entry.get("name")
            if name:
                names.append(name)
        return names
