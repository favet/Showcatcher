"""Shared time-parsing helpers for custom venue scrapers.

parse_time_hm() — convert a regex-captured (h, m, ampm) to datetime.time.
extract_doors_show_times() — scan free text for "Doors X / Show Y" patterns
    and return (doors_time, show_time).  Falls back to assigning the first
    time found to show_time only, preserving backwards compatibility.
"""
import re
from datetime import time as dt_time

# Matches "7:30 PM", "8PM", "19:00", etc.
_TIME_PAT = re.compile(r'(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)', re.IGNORECASE)

# "Doors" with optional colon/at/space, then a time.
_DOORS_PAT = re.compile(
    r'door[s]?\s*(?:open[s]?)?\s*(?:at\s*|:\s*)?(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)',
    re.IGNORECASE,
)

# "Show" (or "Music") with optional colon/at/space, then a time.
_SHOW_PAT = re.compile(
    r'(?:show|music|live)\s*(?:start[s]?)?\s*(?:at\s*|:\s*)?(\d{1,2})(?::(\d{2}))?\s*(AM|PM|am|pm)',
    re.IGNORECASE,
)


def parse_time_hm(h: int, m: int, ampm: str | None) -> dt_time:
    """Convert (hour, minute, am/pm string) to datetime.time (24-hour)."""
    if ampm and ampm.upper() == "PM" and h != 12:
        h += 12
    elif ampm and ampm.upper() == "AM" and h == 12:
        h = 0
    return dt_time(h, m)


def extract_doors_show_times(text: str) -> tuple[dt_time | None, dt_time | None]:
    """Parse doors_time and show_time from free text.

    Looks for explicit "Doors X" and "Show X" / "Music X" patterns first.
    If only one generic time is found with no keyword context, assigns it to
    show_time (existing scraper behaviour, preserving idempotency).

    Returns:
        (doors_time, show_time) — either or both may be None.
    """
    doors_time: dt_time | None = None
    show_time: dt_time | None = None

    dm = _DOORS_PAT.search(text)
    if dm:
        doors_time = parse_time_hm(
            int(dm.group(1)), int(dm.group(2) or 0), dm.group(3)
        )

    sm = _SHOW_PAT.search(text)
    if sm:
        show_time = parse_time_hm(
            int(sm.group(1)), int(sm.group(2) or 0), sm.group(3)
        )

    # Fallback: no keyword context — first time found → show_time.
    if not doors_time and not show_time:
        m = _TIME_PAT.search(text)
        if m:
            show_time = parse_time_hm(int(m.group(1)), int(m.group(2) or 0), m.group(3))

    return doors_time, show_time
