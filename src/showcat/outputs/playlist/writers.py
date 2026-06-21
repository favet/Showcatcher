"""Playlist writers — swappable write targets behind one interface.

The hero output is written through a `PlaylistWriter`, so the Spotify target
can be swapped for a plain export file without touching the pipeline. The
export writer is the fallback stub that proves the bridge is swappable if the
Spotify API erodes further (DECISIONS D6).
"""
import abc
import json
from pathlib import Path

from showcat.adapters.spotify.client import SpotifyClient


class PlaylistWriter(abc.ABC):
    """Write an ordered list of track URIs somewhere; return a locator."""

    @abc.abstractmethod
    def write(self, name: str, public: bool, track_uris: list[str]) -> str:
        """Persist the playlist; return a locator (URL, id, or file path)."""


class SpotifyPlaylistWriter(PlaylistWriter):
    """Create or refresh a real Spotify playlist.

    If `playlist_id` is provided (from SPOTIFY_PLAYLIST_ID), the playlist is
    refreshed in place (idempotent); otherwise a new one is created and its id
    is returned for the user to record.
    """

    def __init__(self, client: SpotifyClient, playlist_id: str | None = None) -> None:
        self._client = client
        self._playlist_id = playlist_id

    def write(self, name: str, public: bool, track_uris: list[str]) -> str:
        playlist_id = self._playlist_id
        if not playlist_id:
            playlist_id = self._client.create_playlist(name, public=public)
        self._client.replace_items(playlist_id, track_uris)
        return f"spotify:playlist:{playlist_id}"


class ExportFilePlaylistWriter(PlaylistWriter):
    """Fallback: write the playlist to a local JSON file instead of Spotify."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def write(self, name: str, public: bool, track_uris: list[str]) -> str:
        payload = {"name": name, "public": public, "track_uris": track_uris}
        self._path.write_text(json.dumps(payload, indent=2))
        return str(self._path)
