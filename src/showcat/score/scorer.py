"""Scoring — pure, versioned, decomposable.

A show's score is a weighted sum of named term *signals*:
    taste      — decayed affinity for the matched artist (raw, unbounded)
    adjacency  — cosine similarity of the artist's tags to the taste vector
    discovery  — taste-adjacent AND low personal play-count (the hero tilt)
    recency    — freshness of the underlying listening signal
    distance   — venue close/near/far band (Phase 6; 0 for now)

The persisted breakdown stores each term's *contribution* (weight × signal)
so the terms always sum to the total — any ranking is explainable after the
fact. The weight set is selected by `scoring_version`, so two versions can be
run on identical signals and diffed (A/B). Weights are config, not policy —
they get tuned in Phase 6.

Versions:
    exact-match-v1  — taste only (Phase 3 high-precision digest). Raw taste.
    discovery-v1    — the discovery engine. Taste is saturated to [0, 1) so a
                      barely-played adjacent artist can out-rank a heavy-rotation
                      one; discovery is the dominant term.
"""
from collections.abc import Mapping
from dataclasses import asdict, dataclass

SCORING_VERSION = "exact-match-v1"  # current production pointer

TERMS = ("taste", "adjacency", "discovery", "recency", "distance")


@dataclass(frozen=True)
class ScoringConfig:
    """A named, versioned scoring strategy."""

    version: str
    weights: Mapping[str, float]
    # If set, the taste signal is saturated: taste / (taste + k) -> [0, 1).
    # Keeps an unbounded affinity from dominating the discovery tilt.
    taste_saturation_k: float | None = None


SCORING_CONFIGS: dict[str, ScoringConfig] = {
    "exact-match-v1": ScoringConfig(
        version="exact-match-v1",
        weights={"taste": 1.0, "adjacency": 0.0, "discovery": 0.0, "recency": 0.0,
                 "distance": 0.0},
        taste_saturation_k=None,
    ),
    "discovery-v1": ScoringConfig(
        version="discovery-v1",
        weights={"taste": 0.5, "adjacency": 0.5, "discovery": 2.0, "recency": 0.3,
                 "distance": 0.15},
        taste_saturation_k=5.0,
    ),
}


def get_config(version: str) -> ScoringConfig:
    if version not in SCORING_CONFIGS:
        raise KeyError(f"Unknown scoring version: {version!r}")
    return SCORING_CONFIGS[version]


@dataclass(frozen=True)
class ScoreSignals:
    """Raw, version-independent signals for one show/artist."""

    taste: float = 0.0
    adjacency: float = 0.0
    discovery: float = 0.0
    recency: float = 0.0
    distance: float = 0.0


@dataclass(frozen=True)
class ScoreBreakdown:
    """The weighted contribution of each term; the terms sum to `total`."""

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
        """Term name -> contribution, for logging / explain affordances."""
        return asdict(self)


def discovery_signal(adjacency_value: float, play_count: int) -> float:
    """High when an artist is taste-adjacent AND barely played.

    discovery = adjacency / (1 + play_count): the play-count penalty shrinks
    the boost as you listen more, so heavy-rotation artists get ~no discovery
    credit while an adjacent artist you've barely heard gets the full benefit.
    """
    return adjacency_value / (1.0 + play_count)


def recency_signal(days_since_last_play: float, half_life_days: float = 56.0) -> float:
    """Freshness of the listening signal in [0, 1] — decays from a recent play."""
    if days_since_last_play < 0:
        days_since_last_play = 0.0
    return float(2.0 ** (-days_since_last_play / half_life_days))


def compute_score(signals: ScoreSignals, version: str = SCORING_VERSION) -> ScoreBreakdown:
    """Combine raw signals into a weighted, decomposable breakdown for `version`."""
    cfg = get_config(version)

    taste = signals.taste
    if cfg.taste_saturation_k is not None:
        taste = taste / (taste + cfg.taste_saturation_k) if taste > 0 else 0.0

    return ScoreBreakdown(
        taste=round(cfg.weights["taste"] * taste, 6),
        adjacency=round(cfg.weights["adjacency"] * signals.adjacency, 6),
        discovery=round(cfg.weights["discovery"] * signals.discovery, 6),
        recency=round(cfg.weights["recency"] * signals.recency, 6),
        distance=round(cfg.weights["distance"] * signals.distance, 6),
    )


@dataclass(frozen=True)
class ScoreDiff:
    """Per-term and total delta between two scoring versions on the same signals."""

    version_a: str
    version_b: str
    total_a: float
    total_b: float
    term_deltas: dict[str, float]

    @property
    def total_delta(self) -> float:
        return round(self.total_b - self.total_a, 6)


def ab_diff(signals: ScoreSignals, version_a: str, version_b: str) -> ScoreDiff:
    """Run two scoring versions on identical signals and return their diff.

    The A/B harness the project expects to use repeatedly: same input, two
    configs, a decomposed delta so a ranking change is explainable.
    """
    a = compute_score(signals, version_a)
    b = compute_score(signals, version_b)
    a_terms = a.as_terms()
    b_terms = b.as_terms()
    return ScoreDiff(
        version_a=version_a,
        version_b=version_b,
        total_a=a.total,
        total_b=b.total,
        term_deltas={t: round(b_terms[t] - a_terms[t], 6) for t in TERMS},
    )
