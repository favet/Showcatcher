"""Shared date-parsing helpers for venue scrapers.

Venue listings give month/day without a year ("Jun 23", "6/21", "June 24").
infer_date() attaches the most sensible year: the upcoming occurrence, rolling
to next year when the month/day has already passed by more than a small grace
window (so a late-December scrape still resolves January dates forward).
"""
from datetime import date

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def month_to_num(month: str) -> int | None:
    """'June' / 'Jun' / 'JUNE' -> 6. None if unrecognised."""
    key = month.strip().lower()[:3]
    return _MONTHS.get(key)


def infer_date(month: int, day: int, today: date | None = None) -> date | None:
    """Build a date for (month, day) choosing the upcoming year.

    If the resulting date is more than ~90 days in the past, assume next year
    (matches the existing scraper convention).
    """
    today = today or date.today()
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if (today - candidate).days <= 90:
            return candidate
    return None


def parse_month_day_text(text: str, today: date | None = None) -> date | None:
    """Parse a month name + day from free text, e.g. 'Tue, Jun 23' or 'June 24'."""
    import re

    m = re.search(
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})",
        text,
        re.IGNORECASE,
    )
    if not m:
        return None
    month = month_to_num(m.group(1))
    if month is None:
        return None
    return infer_date(month, int(m.group(2)), today)


def parse_numeric_md(text: str, today: date | None = None) -> date | None:
    """Parse a numeric M/D from free text, e.g. 'Sun 6/21' -> date."""
    import re

    m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", text)
    if not m:
        return None
    return infer_date(int(m.group(1)), int(m.group(2)), today)
