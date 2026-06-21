"""Playlist output adapter — build a discovery-weighted plan, then write it.

`build()` is the dry-run: it selects discovery-ranked artists, picks
representative tracks (Last.fm), resolves each to a Spotify URI, persists every
resolution decision (candidates + choice), and returns an inspectable
PlaylistPlan — *without writing any playlist*. `write()` then hands the plan's
URIs to a swappable PlaylistWriter (Spotify or export file).

Track selection stays on Last.fm; Spotify is only the URI resolver + target.
Both the top-track provider and the resolver are injected, so the dry-run and
all tests run offline against fixtures.
"""
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from showcat.adapters.spotify.client import Resolution
from showcat.ingest.history.models import Artist, Scrobble
from showcat.outputs.base import BaseOutputAdapter
from showcat.outputs.playlist.models import TrackResolution
from showcat.outputs.playlist.track_selection import (
    DEFAULT_PLAYLIST_LIMIT,
    CandidateArtist,
    min_discovery_pct,
    select_artists,
)
from showcat.resolve.models import EventMatch
from showcat.score.models import EventScore


class TopTrackProvider(Protocol):
    """Anything that yields an artist's representative track names (Last.fm)."""

    def get_top_tracks(
        self, artist: str, mbid: str | None = ..., limit: int = ...
    ) -> list[str]: ...


class TrackResolver(Protocol):
    """Anything that resolves (artist, track) to a Spotify URI (SpotifyClient)."""

    def resolve(self, artist: str, track: str, limit: int = ...) -> Resolution: ...


@dataclass(frozen=True)
class PlaylistEntry:
    """One resolved track in the plan."""

    artist_name: str
    track_name: str
    uri: str | None
    under_explored: bool
    discovery_score: float
    candidate_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class PlaylistPlan:
    """The inspectable dry-run artifact: the playlist before it is written."""

    scoring_version: str
    name: str
    public: bool
    entries: list[PlaylistEntry] = field(default_factory=list)

    @property
    def resolved_uris(self) -> list[str]:
        return [e.uri for e in self.entries if e.uri]

    @property
    def under_explored_pct(self) -> float:
        artists = {e.artist_name: e.under_explored for e in self.entries}
        if not artists:
            return 0.0
        return sum(1 for v in artists.values() if v) / len(artists)

    def to_dict(self) -> dict[str, object]:
        return {
            "scoring_version": self.scoring_version,
            "name": self.name,
            "public": self.public,
            "under_explored_pct": round(self.under_explored_pct, 6),
            "track_count": len(self.entries),
            "resolved_count": len(self.resolved_uris),
            "entries": [e.to_dict() for e in self.entries],
        }


class PlaylistOutputAdapter(BaseOutputAdapter):
    """Builds the discovery playlist plan from scored data; writes via a PlaylistWriter."""

    def __init__(
        self,
        name: str = "Opener — Portland Discovery",
        public: bool = False,
        scoring_version: str = "discovery-v1",
        playlist_limit: int = DEFAULT_PLAYLIST_LIMIT,
        tracks_per_artist: int = 1,
    ) -> None:
        self._name = name
        self._public = public
        self._version = scoring_version
        self._limit = playlist_limit
        self._tracks_per_artist = tracks_per_artist

    @property
    def output_name(self) -> str:
        return "playlist"

    # build() requires session for typing parity with BaseOutputAdapter; the
    # provider/resolver are injected so it stays offline-testable.
    def build(  # type: ignore[override]
        self,
        session: Session,
        top_tracks: TopTrackProvider,
        resolver: TrackResolver,
    ) -> PlaylistPlan:
        candidates = self._candidate_artists(session)
        selected = select_artists(candidates, limit=self._limit)

        entries: list[PlaylistEntry] = []
        now = datetime.now(UTC)
        for artist in selected:
            track_names = top_tracks.get_top_tracks(
                artist.artist_name, mbid=artist.mbid, limit=self._tracks_per_artist
            )
            for track_name in track_names[: self._tracks_per_artist]:
                resolution = resolver.resolve(artist.artist_name, track_name)
                self._persist_resolution(session, resolution, now)
                entries.append(
                    PlaylistEntry(
                        artist_name=artist.artist_name,
                        track_name=track_name,
                        uri=resolution.chosen_uri,
                        under_explored=artist.under_explored,
                        discovery_score=artist.discovery_score,
                        candidate_count=len(resolution.candidates),
                    )
                )

        return PlaylistPlan(
            scoring_version=self._version,
            name=self._name,
            public=self._public,
            entries=entries,
        )

    def meets_discovery_floor(self, plan: PlaylistPlan) -> bool:
        """Whether the plan's under-explored share clears the configured floor."""
        return plan.under_explored_pct >= min_discovery_pct()

    def _candidate_artists(self, session: Session) -> list[CandidateArtist]:
        # Best discovery score per matched artist under the chosen version.
        rows = session.execute(
            select(
                Artist.id,
                Artist.raw_name,
                Artist.mbid,
                func.max(EventScore.score_total),
            )
            .join(EventMatch, EventMatch.artist_id == Artist.id)
            .join(EventScore, EventScore.event_id == EventMatch.event_id)
            .where(
                EventMatch.status == "matched",
                EventScore.scoring_version == self._version,
            )
            .group_by(Artist.id, Artist.raw_name, Artist.mbid)
        ).all()

        candidates: list[CandidateArtist] = []
        for artist_id, raw_name, mbid, best_score in rows:
            play_count = session.execute(
                select(func.count())
                .select_from(Scrobble)
                .where(Scrobble.artist_id == artist_id)
            ).scalar_one()
            candidates.append(
                CandidateArtist(
                    artist_id=artist_id,
                    artist_name=raw_name,
                    mbid=mbid,
                    discovery_score=best_score or 0.0,
                    play_count=play_count,
                )
            )
        return candidates

    def _persist_resolution(
        self, session: Session, resolution: Resolution, now: datetime
    ) -> None:
        session.execute(
            pg_insert(TrackResolution)
            .values(
                artist_name=resolution.artist,
                track_name=resolution.track,
                chosen_uri=resolution.chosen_uri,
                candidates=resolution.candidates,
                source="spotify",
                resolved_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_track_resolutions_artist_track",
                set_={
                    "chosen_uri": resolution.chosen_uri,
                    "candidates": resolution.candidates,
                    "resolved_at": now,
                },
            )
        )
