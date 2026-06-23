"""ArtistSpotifyMetadataStage — fetch artist profile and top album cover art from Spotify.

For every resolved taste artist matched to an upcoming show, fetch their Spotify URL,
profile image, and their top track's album name and cover artwork.
"""
import logging
import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from showcat.adapters.spotify.auth import SpotifyAuth, SpotifyToken
from showcat.adapters.spotify.client import SpotifyClient
from showcat.core.base import BaseStage
from showcat.ingest.history.models import Artist
from showcat.resolve.models import EventMatch

logger = logging.getLogger(__name__)


class ArtistSpotifyMetadataStage(BaseStage):
    """Retrieve and store Spotify metadata (images, URLs, top albums) for matched artists."""

    def __init__(
        self, client: SpotifyClient | None = None, matched_only: bool = True
    ) -> None:
        self._client = client
        self._matched_only = matched_only

    @property
    def stage_name(self) -> str:
        return "ingest/history/spotify_metadata"

    def _build_client(self) -> SpotifyClient:
        if self._client is not None:
            return self._client
        refresh_token = os.environ.get("SPOTIFY_REFRESH_TOKEN", "")
        if not refresh_token:
            raise RuntimeError("SPOTIFY_REFRESH_TOKEN must be set")
        auth = SpotifyAuth.from_env()
        token = auth.refresh(SpotifyToken(access_token="", refresh_token=refresh_token, expires_at=0))
        return SpotifyClient(access_token=token.access_token)

    def _run(self, session: Session, *args: Any, **kwargs: Any) -> int:  # noqa: ARG002
        client = self._build_client()
        query = select(Artist)
        
        # Filter: matched upcoming shows
        if self._matched_only:
            query = query.where(
                exists().where(
                    EventMatch.artist_id == Artist.id,
                    EventMatch.status == "matched",
                )
            )
            
        # Filter: only fetch if not already checked (spotify_url is None)
        query = query.where(Artist.spotify_url.is_(None))
        
        artists = session.execute(query).scalars().all()
        now = datetime.now(UTC)
        records_updated = 0

        for artist in artists:
            try:
                artist_data = client.search_artist(artist.raw_name)
                if not artist_data:
                    logger.info(
                        "Artist not found on Spotify",
                        extra={"artist_id": artist.id, "raw_name": artist.raw_name},
                    )
                    artist.spotify_url = "none"
                    artist.updated_at = now
                    session.add(artist)
                    records_updated += 1
                    continue

                spotify_url = artist_data.get("external_urls", {}).get("spotify")
                
                # Artist profile image
                images = artist_data.get("images", [])
                image_url = images[0].get("url") if images else None

                # Top track's album info
                album_name = None
                album_image_url = None
                top_tracks = client.get_artist_top_tracks(artist_data["id"])
                if top_tracks:
                    top_track = top_tracks[0]
                    album = top_track.get("album", {})
                    album_name = album.get("name")
                    album_images = album.get("images", [])
                    album_image_url = album_images[0].get("url") if album_images else None

                # Update DB
                artist.spotify_url = spotify_url or "none"
                artist.image_url = image_url
                artist.album_name = album_name
                artist.album_image_url = album_image_url
                artist.updated_at = now
                
                session.add(artist)
                records_updated += 1

                logger.info(
                    "Spotify metadata retrieved for artist",
                    extra={
                        "artist_id": artist.id,
                        "raw_name": artist.raw_name,
                        "spotify_url": spotify_url,
                        "album_name": album_name,
                    },
                )
            except Exception as e:
                logger.warning(
                    f"Failed to fetch Spotify metadata for artist {artist.raw_name}: {e}"
                )

        session.commit()
        return records_updated
