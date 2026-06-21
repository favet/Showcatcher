"""Scoring — pure, versioned, decomposable.

A show's score is the sum of named terms. In the Phase 3 exact-match slice
only `taste` (decayed affinity for the matched artist) is populated; the
adjacency/discovery/recency/distance terms are reserved for the Phase 4
discovery engine and default to 0.0. The breakdown is always persisted so
any ranking is explainable after the fact ("why did show X score Y?").

`SCORING_VERSION` tags every persisted score so two scoring variants can be
run on identical input and diffed (the A/B expectation in DECISIONS D5).
"""
from dataclasses import asdict, dataclass

SCORING_VERSION = "exact-match-v1"


@dataclass(frozen=True)
class ScoreBreakdown:
    """The full set of named score terms plus their total."""

    taste: float = 0.0
    adjacency: float = 0.0
    discovery: float = 0.0
    recency: float = 0.0
    distance: float = 0.0

    @property
    def total(self) -> float:
        return round(
            self.taste + self.adjacency + self.discovery + self.recency + self.distance, 6
        )

    def as_terms(self) -> dict[str, float]:
        """Term name -> value, for logging / explain affordances."""
        return asdict(self)


def compute_score(
    taste: float,
    adjacency: float = 0.0,
    discovery: float = 0.0,
    recency: float = 0.0,
    distance: float = 0.0,
) -> ScoreBreakdown:
    """Combine named terms into an explainable breakdown.

    The combination is a plain sum in this version — deliberately simple and
    inspectable. The terms (not the formula) carry the meaning; the formula
    is what gets tuned/versioned in Phase 6.
    """
    return ScoreBreakdown(
        taste=round(taste, 6),
        adjacency=round(adjacency, 6),
        discovery=round(discovery, 6),
        recency=round(recency, 6),
        distance=round(distance, 6),
    )
