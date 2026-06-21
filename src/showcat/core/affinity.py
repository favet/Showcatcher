"""Decayed affinity query — time-decayed per-artist weights.

Pure function: no DB writes. Takes a list of (artist_name, scrobbled_at)
pairs and returns a sorted list of (mbid_or_name, weight) tuples.

Decay formula: weight = sum(2 ^ -(days_since / half_life_days))
  - Each scrobble contributes a weight that halves every `half_life_days`.
  - Config: AFFINITY_HALF_LIFE_DAYS (default: 56, i.e. ~8 weeks).
  - Artists with no MBID use their raw name as the key (still counted).
"""
import os
from dataclasses import dataclass
from datetime import UTC, datetime

DEFAULT_HALF_LIFE_DAYS = 56


@dataclass(frozen=True)
class AffinityScore:
    """Decayed affinity score for one artist."""

    key: str  # MBID if resolved, else raw artist name
    raw_name: str
    weight: float
    play_count: int  # total scrobbles in window (unweighted)


def compute_decayed_affinity(
    plays: list[tuple[str, str | None, datetime]],
    top_n: int = 50,
    half_life_days: int | None = None,
    reference_time: datetime | None = None,
) -> list[AffinityScore]:
    """Compute time-decayed artist affinity scores.

    Args:
        plays: List of (raw_artist_name, mbid_or_None, scrobbled_at) tuples.
               Rows come from a JOIN of scrobbles ⟕ artists.
        top_n: Return only the top-N artists by weight.
        half_life_days: Decay half-life in days. Defaults to env var
                        AFFINITY_HALF_LIFE_DAYS (default 56).
        reference_time: "Now" for decay calculation. Defaults to utcnow().
                        Parameterised to make tests deterministic.

    Returns:
        List of AffinityScore, sorted descending by weight, limited to top_n.
    """
    if half_life_days is None:
        half_life_days = int(os.environ.get("AFFINITY_HALF_LIFE_DAYS", DEFAULT_HALF_LIFE_DAYS))

    ref = reference_time or datetime.now(UTC)

    # Group plays by artist key (MBID preferred, else raw name)
    weights: dict[str, float] = {}
    counts: dict[str, int] = {}
    names: dict[str, str] = {}  # key -> raw_name

    for raw_name, mbid, scrobbled_at in plays:
        key = mbid if mbid else raw_name
        names[key] = raw_name

        if scrobbled_at.tzinfo is None:
            scrobbled_at = scrobbled_at.replace(tzinfo=UTC)
        days_since = (ref - scrobbled_at).total_seconds() / 86400.0
        contribution = 2.0 ** (-days_since / half_life_days)

        weights[key] = weights.get(key, 0.0) + contribution
        counts[key] = counts.get(key, 0) + 1

    scores = [
        AffinityScore(
            key=key,
            raw_name=names[key],
            weight=round(weight, 6),
            play_count=counts[key],
        )
        for key, weight in weights.items()
    ]
    scores.sort(key=lambda s: s.weight, reverse=True)
    return scores[:top_n]
