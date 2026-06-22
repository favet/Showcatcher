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

Precision guards (applied to the fuzzy path only):

  1. Single-distinctive-token guard: when both names reduce to exactly one
     meaningful token after stripping articles ("the", "a", "an"), short band
     names like "The Strike" / "The Strokes" share a high char-similarity
     purely from the shared prefix. We require 0.90 to auto-accept — routes
     the ambiguous pair to review instead of matched.

  2. Token-subset guard: when the shorter name's full token set is a strict
     subset of the longer name's (e.g. "the verve" ⊂ "the verve pipe"),
     the char similarity is inflated by the prefix. We require 0.92 to
     auto-accept — routes the false prefix-match to review.

Both guards only raise the auto-accept bar; they never lower it or alter
what goes to review vs. dropped.
"""
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

DEFAULT_MATCH_THRESHOLD = 0.75
DEFAULT_REVIEW_FLOOR = 0.55

_ARTICLES = frozenset({"the", "a", "an"})

# Parenthetical context to strip before fuzzy matching:
#   "(of La Femme)" — the artist is in a side project
#   "(formerly X)" — old band name context
#   "(DJ Set)" / "(live)" / "(acoustic)" — performance format
_OF_CONTEXT = re.compile(r"\s*\((?:of|formerly|ex-)\s+.+?\)\s*$", re.IGNORECASE)
_ROLE_CONTEXT = re.compile(r"\s*\((?:DJ\s+[Ss]et|live|acoustic|solo\s+set)\)\s*$", re.IGNORECASE)


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


def strip_artist_context(name: str) -> str:
    """Remove parenthetical context from an artist name before matching.

    Handles:
    - ``"Marlon Magnée (of La Femme)"`` → ``"Marlon Magnée"``
    - ``"Matthew Dear (DJ set)"`` → ``"Matthew Dear"``
    - ``"X (formerly Y)"`` → ``"X"``
    """
    name = _OF_CONTEXT.sub("", name)
    name = _ROLE_CONTEXT.sub("", name)
    return name.strip()


def similarity(a: str, b: str) -> float:
    """Normalised string similarity in [0, 1]. Reproducible (difflib ratio)."""
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def _distinctive_tokens(name: str) -> list[str]:
    """Tokens remaining after stripping common English articles."""
    return [t for t in normalize(name).split() if t not in _ARTICLES]


def _adjusted_match_threshold(event_name: str, taste_name: str, base: float) -> float:
    """Return a stricter auto-accept threshold when structural guards fire.

    Only raises the bar; never lowers it below `base`.
    """
    ev_tokens = set(normalize(event_name).split())
    ta_tokens = set(normalize(taste_name).split())
    shorter, longer = (
        (ev_tokens, ta_tokens)
        if len(ev_tokens) <= len(ta_tokens)
        else (ta_tokens, ev_tokens)
    )

    # Guard 2 — token subset: "the verve" ⊂ "the verve pipe" inflates char sim.
    if shorter and shorter.issubset(longer) and shorter != longer:
        return max(base, 0.92)

    # Guard 1 — single distinctive token: "The Strike" / "The Strokes" share
    # a prefix that yields high char similarity but are unrelated bands.
    if len(_distinctive_tokens(event_name)) == 1 and len(_distinctive_tokens(taste_name)) == 1:
        return max(base, 0.90)

    return base


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

    # 3b. If the event name has parenthetical context ("(of Band)", "(DJ Set)"),
    #     try again with the stripped version; keep whichever yields a better score.
    stripped_name = strip_artist_context(event_artist_name)
    if stripped_name != event_artist_name:
        for ta in taste_artists:
            score = similarity(stripped_name, ta.raw_name)
            if score > best_score:
                best_score = score
                best = ta

    if best is None or best_score < review_floor:
        return None

    confidence = round(best_score, 6)
    effective_threshold = _adjusted_match_threshold(
        event_artist_name, best.raw_name, match_threshold
    )
    status = "matched" if confidence >= effective_threshold else "review"
    return MatchCandidate(
        artist_id=best.artist_id,
        matched_name=best.raw_name,
        match_type="fuzzy",
        confidence=confidence,
        status=status,
    )
