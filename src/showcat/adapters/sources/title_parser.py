"""title_parser.py — Shared event title normalization.

Applied by all source adapters before constructing a RawEvent.
Produces a clean (headliner, openers, status) triple.

status values:
  None         — normal show
  'sold_out'   — "SOLD OUT:" prefix detected (keep; show indicator in UI)
  'cancelled'  — cancelled (adapter should skip/exclude)
  'moved'      — moved to a different venue (adapter should exclude;
                 the new venue's scraper will pick it up)

Design principles:
  - Pure functions only — no IO, no DB, deterministic.
  - Conservative: when in doubt, don't strip. A false-positive strip
    (e.g. stripping " & The Boys" thinking it's a tour suffix) is worse
    than leaving a dirty string — the matcher can still recover via
    fuzzy comparison.
  - All regexes compiled at module load for performance.
  - All examples drawn from real Portland venue data audited 2026-06-21.
"""
import html
import re

# ── Status prefixes ──────────────────────────────────────────────────────────
# Matches leading: "SOLD OUT:", "*CANCELLED*", "MOVED TO THE CRYSTAL BALLROOM:"
# Greedy enough to consume multi-word venue names like "MOVED TO THE CRYSTAL BALLROOM"
# but stops before the colon/asterisk separator.
_STATUS_PREFIX = re.compile(
    r"^\*?\s*"
    r"(SOLD[\s_]?OUT"                          # "SOLD OUT" / "SOLD_OUT"
    r"|CANCEL+ED?"                             # "CANCELLED" / "CANCELED"
    r"|MOVED\s+TO\s+(?:THE\s+)?[\w\s]{1,40}?" # "MOVED TO THE CRYSTAL BALLROOM"
    r")"
    r"\s*[:\*]\s*",                            # separator: colon or asterisk
    re.IGNORECASE,
)

# ── Tour / subtitle suffix ────────────────────────────────────────────────────
# Strips the part after a dash/em-dash that looks like marketing copy:
#   "Artist – Tour Name Tour"
#   "Artist - 20th Anniversary Tour"
#   "Artist – Deep End World Tour"
#   "Artist – Celebrating 'Album' 20th Anniversary"
#   "Artist – World Tour Part 1"
#
# Conservative guards — we do NOT strip if:
#   - The dash is followed by a short word that looks like a band name modifier
#     (e.g. "& The Boys", "and the Angry Inch")
#   - The body before "tour" contains an ampersand (likely co-headliner)
_TOUR_SUFFIX = re.compile(
    r"\s*[-–—]\s+"                             # separator (requires space after)
    r"(?!&|and\s)"                             # NOT "&" or "and " — co-headliner guard
    r"(?:the\s+)?"                             # optional "the"
    r"[^&\n]{4,70}"                            # tour name body (no ampersand)
    r"(?:"
        r"tour(?:\s+\d{4})?"                   # "…Tour" / "…Tour 2026"
        r"|world\s+tour"                       # "…World Tour"
        r"|anniversary(?:\s+tour)?"            # "…Anniversary" / "…Anniversary Tour"
        r"|celebrating\b"                      # "…Celebrating …"
        r"|part\s+\d"                          # "…Part 1"
    r")"
    r"[^&\n]*$",                               # remainder to end of string
    re.IGNORECASE,
)

# ── Parenthetical night/show/set suffix ──────────────────────────────────────
# "Artist (Night 1)", "Artist (Show 2)", "Artist (Part 3)"
_PAREN_NIGHT = re.compile(
    r"\s*\(\s*(?:Night|Show|Set|Part)\s*\d+\s*\)\s*$",
    re.IGNORECASE,
)

# ── Age / admission suffix ────────────────────────────────────────────────────
# "Artist – 21+", "Artist – 18+ event", "Artist – All Ages!", "Artist – EARLY SHOW!"
_AGE_SUFFIX = re.compile(
    r"\s*[-–—]\s*"
    r"(?:"
        r"(?:18|21)\+(?:\s*event)?"
        r"|all[\s\-]ages?!?"
        r"|early\s+show!?"
        r"|ages?\s+\d+"
    r")\s*$",
    re.IGNORECASE,
)

# ── "w/" opener embedded in title ────────────────────────────────────────────
# "Artist – w/ Opener Name"
# "Artist w/ Opener Name – All Ages"
# "Artist (DJ set) w/ Opener"
# Captures: group 1 = headliner part, group 2 = opener part
# Stop capture before any trailing age/admission suffix.
_W_OPENER = re.compile(
    r"^(.+?)"                                  # headliner (non-greedy)
    r"\s*(?:[-–—]\s*)?"                        # optional preceding dash
    r"[Ww]/"                                   # literal "w/"
    r"\s*"
    r"(.+?)"                                   # opener (non-greedy)
    r"(?:\s*[-–—]\s*(?:18|21|all\s+ages?).*)?" # optional trailing age suffix
    r"$",
    re.IGNORECASE,
)

# ── Non-show event patterns ───────────────────────────────────────────────────
# These titles are never real shows and should be skipped by scrapers.
_NON_SHOW = re.compile(
    r"^(?:"
    # Recurring venue events
    r"bridgetown\s+trivia"
    r"|no\s+fun\s+karaoke"
    r"|rip\s+city\s+(?:bingo|music\s+bingo|bingo-?oke)"
    r"|trivia\s+with\s+\w+"
    r"|karaoke\s+from\s+hell"            # TM entry
    r"|two[\s\-]step\s+tuesday"
    r"|two[\s\-]step\s+lesson"
    r"|whiskey\s+wednesday"
    r"|dance\s+lesson"
    # Venue-operational noise
    r"|closed\s+all\s+day"
    r"|private\s+event"
    r"|outdoor\s+early"
    r"|indoor\s+evening"
    r"|easyfolk\s+presents\s*$"          # White Eagle recurring promo (no artist)
    # Kenton Club address / email strings
    r"|\d{3,5}\s+[nsew]\s+\w+\s+st"
    r"|\S*\s*@\s*\w+\.(com|org|net)"              # email addresses (any form)
    r")",
    re.IGNORECASE,
)

# ── "Presenter Presents:" strip ───────────────────────────────────────────────
# "Blisspop Presents: Hot In Herre" → "Hot In Herre"
# Heuristic: only strip when the presents-clause is ≤ 30 chars (so we don't
# accidentally strip "PJCE presents Rebecca Sanborn's Shadow Work w/ ...")
_PRESENTS = re.compile(
    r"^(.{1,30}?)\bpresents?\b[:\s]+",
    re.IGNORECASE,
)

# ── Trailing punctuation / whitespace cleanup ─────────────────────────────────
_TRAIL_PUNCT = re.compile(r"[\s,;:–—-]+$")


# ─────────────────────────────────────────────────────────────────────────────
# Public helpers
# ─────────────────────────────────────────────────────────────────────────────

def is_non_show(title: str) -> bool:
    """Return True if *title* is a recurring/junk/non-show event.

    Applied by every scraper before constructing a RawEvent; matching events
    are silently skipped so they never enter the DB.
    """
    return bool(_NON_SHOW.match(title.strip()))


def decode_html(s: str) -> str:
    """Unescape HTML entities: ``&amp;`` → ``&``, ``&#39;`` → ``'``, etc."""
    return html.unescape(s)


def clean_whitespace(s: str) -> str:
    """Collapse non-breaking spaces, zero-width spaces, and double spaces."""
    s = s.replace("\xa0", " ").replace("\u200b", "").replace("\u2009", " ")
    return re.sub(r" {2,}", " ", s).strip()


def extract_status(title: str) -> tuple[str, str | None]:
    """Strip a status prefix (SOLD OUT / CANCELLED / MOVED) from *title*.

    Returns:
        (clean_title, status) where status is one of:
        ``None`` | ``'sold_out'`` | ``'cancelled'`` | ``'moved'``
    """
    m = _STATUS_PREFIX.match(title)
    if not m:
        return title, None
    keyword = m.group(1).upper()
    remainder = title[m.end():].strip()
    if "SOLD" in keyword:
        return remainder, "sold_out"
    if "CANCEL" in keyword:
        return remainder, "cancelled"
    if "MOVED" in keyword:
        return remainder, "moved"
    return remainder, None


def strip_age_suffix(title: str) -> str:
    """Remove trailing admission annotations (``– 21+``, ``– All Ages!``, etc.)."""
    return _AGE_SUFFIX.sub("", title).strip()


def strip_tour_suffix(title: str) -> str:
    """Remove tour / anniversary / subtitle marketing copy after a dash.

    Conservative: only strips when the suffix contains a tour-marker keyword
    (``tour``, ``world tour``, ``anniversary``, ``celebrating``, ``part N``).
    Does not strip co-headliner patterns like ``& The Boys``.
    """
    return _TOUR_SUFFIX.sub("", title).strip()


def strip_paren_night(title: str) -> str:
    """Remove ``(Night 1)``, ``(Show 2)``, ``(Part 3)`` parentheticals."""
    return _PAREN_NIGHT.sub("", title).strip()


def extract_w_opener(title: str) -> tuple[str, str | None]:
    """Split ``"Artist – w/ Opener"`` into ``(headliner, opener_name)``.

    Returns ``(original_title, None)`` when the pattern is not found.
    The returned headliner has trailing dashes and whitespace cleaned.
    The returned opener has age-restriction suffixes removed.
    TBA / TBD openers are returned as None.
    """
    m = _W_OPENER.match(title)
    if not m:
        return title, None

    headliner = _TRAIL_PUNCT.sub("", m.group(1)).strip()
    opener = strip_age_suffix(m.group(2).strip()).strip()

    if not opener or opener.upper() in ("TBA", "TBD", "MORE"):
        return headliner, None
    return headliner, opener


def normalize_title(
    raw_title: str,
    existing_openers: list[str] | None = None,
) -> tuple[str, list[str], str | None]:
    """Full normalization pipeline for a raw event title.

    Steps (in order):
      1. HTML-decode + whitespace collapse
      2. Extract & strip status prefix (SOLD OUT / CANCELLED / MOVED)
      3. Strip age-restriction suffix
      4. Extract embedded ``w/`` opener, extend openers list
      5. Strip tour / anniversary suffix
      6. Strip ``(Night N)`` parenthetical
      7. Final whitespace cleanup

    Args:
        raw_title: The dirty string from the scraper.
        existing_openers: Openers already known (e.g. from a separate field);
            any opener extracted from the title is appended if not already present.

    Returns:
        ``(headliner, openers, status)``
        - *headliner*: cleaned artist string
        - *openers*: list of opener names (may be longer than existing_openers)
        - *status*: ``None`` | ``'sold_out'`` | ``'cancelled'`` | ``'moved'``
    """
    openers: list[str] = list(existing_openers or [])

    # 1. Decode + whitespace
    title = decode_html(raw_title)
    title = clean_whitespace(title)

    # 2. Status prefix
    title, status = extract_status(title)

    # 3. Age suffix (strip before tour suffix so the end-anchor fires correctly)
    title = strip_age_suffix(title)

    # 4. Embedded w/ opener
    title, w_opener = extract_w_opener(title)
    if w_opener and w_opener not in openers:
        openers.append(w_opener)

    # 5. Tour suffix (dash-separated)
    title = strip_tour_suffix(title)

    # 5b. Colon-separated subtitle that contains a tour keyword
    #     e.g. "Otha: Club 20 Tour 2026" → "Otha"
    #     Guard: only strip if the colon-suffix matches a tour keyword AND the
    #     part before the colon is 1–3 words (an artist name, not an event name).
    _colon_tour = re.search(
        r"^(.{1,30}?):\s+.{3,60}?"
        r"(?:tour(?:\s+\d{4})?|world\s+tour|anniversary)",
        title,
        re.IGNORECASE,
    )
    if _colon_tour:
        before_colon = _colon_tour.group(1).strip()
        if 1 <= len(before_colon.split()) <= 3:
            title = before_colon

    # 6. Night/Show parenthetical
    title = strip_paren_night(title)

    # 7. Final cleanup
    title = _TRAIL_PUNCT.sub("", title).strip()
    title = clean_whitespace(title)

    return title, openers, status


def split_multi_artist_plus(
    title: str,
    existing_openers: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Split ``"Band A + Band B + TBA"`` into ``(headliner, openers)``.

    Used by Starday (and similar sources) where the title field packs the
    full bill as a plus- or slash-separated list.  TBA/TBD entries are
    dropped.  Returns the title unchanged if there is only one real act.
    """
    openers: list[str] = list(existing_openers or [])

    # Try ' + ' first, then '/' (without 'http' to guard URLs)
    if " + " in title:
        parts = [p.strip() for p in title.split(" + ")]
    elif "/" in title and "http" not in title:
        parts = [p.strip() for p in title.split("/")]
    else:
        return title, openers

    real = [p for p in parts if p and p.upper() not in ("TBA", "TBD", "MORE", "")]
    if len(real) == 0:
        return title, openers
    if len(real) == 1:
        # Only one real act after filtering TBA — return the cleaned name
        return real[0], openers

    headliner = real[0]
    for act in real[1:]:
        if act not in openers:
            openers.append(act)
    return headliner, openers


def split_multi_artist_comma(
    title: str,
    existing_openers: list[str] | None = None,
    min_parts: int = 3,
) -> tuple[str, list[str]]:
    """Split ``"Band A, Band B, Band C"`` into ``(headliner, openers)``.

    Only splits when there are at least *min_parts* comma-separated tokens
    and every token looks like a short artist name (1–5 words).  This avoids
    false splits on titles like ``"Casket Cassette, Stare Away"`` (2 parts —
    could be one long band name or two; left ambiguous).

    Used by Holocene and similar venues that pack multi-band bills into the
    title field.
    """
    openers: list[str] = list(existing_openers or [])

    if "," not in title:
        return title, openers

    parts = [p.strip() for p in title.split(",")]
    # Filter blanks and TBA
    real = [p for p in parts if p and p.upper() not in ("TBA", "TBD", "")]
    if len(real) < min_parts:
        return title, openers

    # All parts must look like short band names (1–5 words)
    if not all(1 <= len(p.split()) <= 5 for p in real):
        return title, openers

    headliner = real[0]
    for act in real[1:]:
        if act not in openers:
            openers.append(act)
    return headliner, openers
