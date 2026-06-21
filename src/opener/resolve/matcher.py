"""Entity-resolution matcher — pure functions, no DB.

Matches a dirty event-artist string (e.g. "Mount Joy", free-text openers)
to a clean taste artist. MBID-first, with a fuzzy fallback that emits an
explainable confidence score.

The confidence is `difflib.SequenceMatcher.ratio()` over normalised names
— a documented, reproducible measure, deliberately chosen over a black-box
similarity. Calibration (normalised ratios):
    "Mt. Joy"  vs "Mount Joy"          -> 0.80   (real fuzzy match)
    "The War on Drugs" vs "War on Drugs" -> 0.86 (real fuzzy match)
    "Modest Mouse" vs "Modern Baseball" -> 0.52  (ambiguous)

Decision bands (both thresholds are config, not hardcoded policy):
    confidence >= MATCH_CONFIDENCE_THRESHOLD  -> "matched"
    REVIEW_FLOOR <= confidence < threshold    -> "review"  (review queue)
    confidence < REVIEW_FLOOR                  -> no link (logged, not stored)
"""
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

DEFAULT_MATCH_THRESHOLD = 0.75
DEFAULT_REVIEW_FLOOR = 0.55


@dataclass(frozen=True)
class MatchCandidate:
    """The outcome of matching one event-artist string against the taste set."""

    artist_id: int
    matched_name: str  # the taste artist's raw_name that was matched against
    match_type: str  # "mbid" | "exact" | "fuzzy"
    confidence: float
    status: str  # "matched" | "review"


@dataclass(frozen=True)
class TasteArtist:
    """Minimal projection of a taste Artist row for matching."""

    artist_id: int
    raw_name: str
    mbid: str | None


def normalize(name: str) -> str:
    """Lowercase, strip punctuation to spaces, collapse whitespace."""
    lowered = re.sub(r"[^a-z0-9]+", " ", name.lower())
    return re.sub(r"\s+", " ", lowered).strip()


def similarity(a: str, b: str) -> float:
    """Normalised string similarity in [0, 1]. Reproducible (difflib ratio)."""
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def match_artist(
    event_artist_name: str,
    taste_artists: list[TasteArtist],
    event_mbid: str | None = None,
    match_threshold: float | None = None,
    review_floor: float | None = None,
) -> MatchCandidate | None:
    """Resolve one event-artist string to the best taste artist.

    Args:
        event_artist_name: the dirty string from the event listing.
        taste_artists: candidate taste artists to match against.
        event_mbid: an MBID for the event artist, if the source provided one
            (enables an exact MBID link — the highest-confidence path).
        match_threshold: confidence at/above which a match is auto-accepted.
        review_floor: confidence at/above which a match goes to the review
            queue (below it, no link is stored — only logged by the caller).

    Returns:
        The best MatchCandidate, or None if nothing cleared the review floor.
        A returned candidate may have status "matched" or "review"; the caller
        persists both and routes "review" rows to the queue.
    """
    if match_threshold is None:
        match_threshold = float(
            os.environ.get("MATCH_CONFIDENCE_THRESHOLD", DEFAULT_MATCH_THRESHOLD)
        )
    if review_floor is None:
        review_floor = float(os.environ.get("MATCH_REVIEW_FLOOR", DEFAULT_REVIEW_FLOOR))

    if not taste_artists:
        return None

    # 1. MBID-first: an exact MBID hit is unambiguous, confidence 1.0.
    if event_mbid:
        for ta in taste_artists:
            if ta.mbid and ta.mbid == event_mbid:
                return MatchCandidate(
                    artist_id=ta.artist_id,
                    matched_name=ta.raw_name,
                    match_type="mbid",
                    confidence=1.0,
                    status="matched",
                )

    # 2. Name-based: exact normalised match wins outright.
    norm_event = normalize(event_artist_name)
    for ta in taste_artists:
        if normalize(ta.raw_name) == norm_event:
            return MatchCandidate(
                artist_id=ta.artist_id,
                matched_name=ta.raw_name,
                match_type="exact",
                confidence=1.0,
                status="matched",
            )

    # 3. Fuzzy fallback: best similarity over the taste set.
    best: TasteArtist | None = None
    best_score = 0.0
    for ta in taste_artists:
        score = similarity(event_artist_name, ta.raw_name)
        if score > best_score:
            best_score = score
            best = ta

    if best is None or best_score < review_floor:
        return None

    confidence = round(best_score, 6)
    status = "matched" if confidence >= match_threshold else "review"
    return MatchCandidate(
        artist_id=best.artist_id,
        matched_name=best.raw_name,
        match_type="fuzzy",
        confidence=confidence,
        status=status,
    )
