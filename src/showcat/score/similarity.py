"""Tag-vector taste model and artist similarity — pure functions, no DB.

A tag vector is a mapping {tag -> weight}. The per-user *taste vector* is the
affinity-weighted sum of each taste artist's tag vector. Artist adjacency is
the cosine similarity between an artist's tag vector and the taste vector —
this is what lets the engine recognise an artist you've barely heard as
"taste-adjacent" and surface it (the discovery tilt).

All functions are deterministic and offline; neighbours are tested against
committed fixtures (golden test).
"""
import math
from dataclasses import dataclass

TagVector = dict[str, float]


def cosine(a: TagVector, b: TagVector) -> float:
    """Cosine similarity of two tag vectors in [0, 1] (weights are non-negative)."""
    if not a or not b:
        return 0.0
    shared = set(a) & set(b)
    dot = sum(a[t] * b[t] for t in shared)
    if dot == 0.0:
        return 0.0
    norm_a = math.sqrt(sum(w * w for w in a.values()))
    norm_b = math.sqrt(sum(w * w for w in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_taste_vector(
    artist_tags: dict[str, TagVector],
    affinity: dict[str, float],
) -> TagVector:
    """Affinity-weighted sum of artist tag vectors, keyed by the same artist key.

    Args:
        artist_tags: artist_key -> {tag -> weight}.
        affinity: artist_key -> decayed affinity weight.

    Returns:
        The taste vector {tag -> weight}. Artists with no affinity entry are
        skipped (they contribute nothing to taste).
    """
    taste: TagVector = {}
    for key, tags in artist_tags.items():
        a = affinity.get(key, 0.0)
        if a <= 0.0:
            continue
        for tag, weight in tags.items():
            taste[tag] = taste.get(tag, 0.0) + a * weight
    return taste


def adjacency(artist_vec: TagVector, taste_vec: TagVector) -> float:
    """How taste-adjacent an artist is — cosine of its tags against the taste vector."""
    return cosine(artist_vec, taste_vec)


@dataclass(frozen=True)
class Neighbor:
    """An artist and its similarity to a target artist."""

    key: str
    similarity: float


def nearest_neighbors(
    target_vec: TagVector,
    candidates: dict[str, TagVector],
    top_n: int = 10,
) -> list[Neighbor]:
    """Rank candidate artists by tag-vector similarity to the target.

    Deterministic ordering: similarity desc, then key asc (stable tie-break).
    The target's own key, if present in candidates, is excluded.
    """
    scored = [
        Neighbor(key=key, similarity=round(cosine(target_vec, vec), 6))
        for key, vec in candidates.items()
    ]
    scored = [n for n in scored if n.similarity > 0.0]
    scored.sort(key=lambda n: (-n.similarity, n.key))
    return scored[:top_n]
