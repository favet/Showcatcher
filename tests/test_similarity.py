"""Phase 4.2 — Artist similarity tests.

Gate 4 assertion covered here:
  - Similarity returns plausible neighbors for fixture artists (golden test).
"""
from pytest import approx

from showcat.score.similarity import (
    adjacency,
    build_taste_vector,
    cosine,
    nearest_neighbors,
)

# A small fixture tag-world. Two indie-rock artists are close; the metal act
# and the jazz act are far from both and from each other.
ARTIST_VECTORS = {
    "modest-mouse": {"indie rock": 100.0, "indie": 80.0, "lo-fi": 30.0},
    "built-to-spill": {"indie rock": 95.0, "indie": 70.0, "alternative": 40.0},
    "metallica": {"thrash metal": 100.0, "metal": 90.0},
    "miles-davis": {"jazz": 100.0, "bebop": 70.0},
}


class TestCosine:
    def test_identical_vectors_are_one(self) -> None:
        v = {"a": 1.0, "b": 2.0}
        assert cosine(v, v) == approx(1.0)

    def test_disjoint_vectors_are_zero(self) -> None:
        assert cosine({"a": 1.0}, {"b": 1.0}) == 0.0

    def test_empty_vector_is_zero(self) -> None:
        assert cosine({}, {"a": 1.0}) == 0.0


class TestNearestNeighbors:
    def test_golden_neighbors_for_indie_artist(self) -> None:
        """The nearest neighbour of Modest Mouse is the other indie act."""
        target = ARTIST_VECTORS["modest-mouse"]
        candidates = {k: v for k, v in ARTIST_VECTORS.items() if k != "modest-mouse"}
        neighbors = nearest_neighbors(target, candidates)

        keys = [n.key for n in neighbors]
        # Golden ordering: Built to Spill (indie) first; metal/jazz rank below.
        assert keys[0] == "built-to-spill"
        assert keys[0:1] == ["built-to-spill"]
        # The disjoint-genre artists are not plausible neighbours at all.
        assert "metallica" not in keys
        assert "miles-davis" not in keys

    def test_neighbors_are_sorted_descending(self) -> None:
        target = ARTIST_VECTORS["modest-mouse"]
        neighbors = nearest_neighbors(target, ARTIST_VECTORS)
        sims = [n.similarity for n in neighbors]
        assert sims == sorted(sims, reverse=True)


class TestTasteVectorAndAdjacency:
    def test_taste_vector_weights_by_affinity(self) -> None:
        affinity = {"modest-mouse": 10.0, "built-to-spill": 1.0}
        artist_tags = {
            "modest-mouse": ARTIST_VECTORS["modest-mouse"],
            "built-to-spill": ARTIST_VECTORS["built-to-spill"],
        }
        taste = build_taste_vector(artist_tags, affinity)
        # Heavy artist dominates the taste vector's indie-rock weight.
        assert taste["indie rock"] == 10.0 * 100.0 + 1.0 * 95.0

    def test_adjacent_artist_scores_high_unheard_one_low(self) -> None:
        affinity = {"modest-mouse": 10.0}
        taste = build_taste_vector(
            {"modest-mouse": ARTIST_VECTORS["modest-mouse"]}, affinity
        )
        indie_adj = adjacency(ARTIST_VECTORS["built-to-spill"], taste)
        metal_adj = adjacency(ARTIST_VECTORS["metallica"], taste)
        assert indie_adj > 0.8
        assert metal_adj == 0.0
        assert indie_adj > metal_adj
