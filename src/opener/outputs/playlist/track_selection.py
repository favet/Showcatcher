"""Playlist track selection — pure discovery weighting, no DB or network.

Chooses which artists make the playlist and in what order. The whole point of
the hero output is the discovery tilt, so artists are ranked by their
discovery-version score and the set is weighted toward *under-explored*
artists (low personal play-count). Composition is measured over artists, and
the under-explored share is asserted against a configurable floor.
"""
import os
from dataclasses import dataclass

DEFAULT_UNDEREXPLORED_MAX_PLAYS = 25
DEFAULT_MIN_DISCOVERY_PCT = 0.5
DEFAULT_PLAYLIST_LIMIT = 30


@dataclass(frozen=True)
class CandidateArtist:
    """A scored artist eligible for the playlist."""

    artist_id: int
    artist_name: str
    mbid: str | None
    discovery_score: float
    play_count: int

    def is_under_explored(self, max_plays: int) -> bool:
        return self.play_count <= max_plays


@dataclass(frozen=True)
class SelectedArtist:
    """A chosen playlist artist with its under-explored flag."""

    artist_id: int
    artist_name: str
    mbid: str | None
    discovery_score: float
    play_count: int
    under_explored: bool


def under_explored_max_plays() -> int:
    return int(
        os.environ.get("PLAYLIST_UNDEREXPLORED_MAX_PLAYS", DEFAULT_UNDEREXPLORED_MAX_PLAYS)
    )


def min_discovery_pct() -> float:
    return float(os.environ.get("PLAYLIST_MIN_DISCOVERY_PCT", DEFAULT_MIN_DISCOVERY_PCT))


def select_artists(
    candidates: list[CandidateArtist],
    limit: int = DEFAULT_PLAYLIST_LIMIT,
    max_plays: int | None = None,
) -> list[SelectedArtist]:
    """Rank by discovery score (desc), then fewer plays, then name — take top `limit`.

    Deterministic ordering so the playlist plan is a stable artifact.
    """
    if max_plays is None:
        max_plays = under_explored_max_plays()

    ordered = sorted(
        candidates,
        key=lambda c: (-c.discovery_score, c.play_count, c.artist_name),
    )
    return [
        SelectedArtist(
            artist_id=c.artist_id,
            artist_name=c.artist_name,
            mbid=c.mbid,
            discovery_score=c.discovery_score,
            play_count=c.play_count,
            under_explored=c.is_under_explored(max_plays),
        )
        for c in ordered[:limit]
    ]


def under_explored_fraction(selected: list[SelectedArtist]) -> float:
    """Share of selected artists that are under-explored, in [0, 1]."""
    if not selected:
        return 0.0
    return sum(1 for s in selected if s.under_explored) / len(selected)
