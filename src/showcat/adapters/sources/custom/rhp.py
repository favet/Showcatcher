"""RHP-platform venue scrapers (Phase 8.3).

Roseland Theater and Hawthorne Theatre share the "RHP" events CMS: each show is
a `.rhp-event__single-event--list` row carrying title, date, door/show times,
venue, and an Etix "Buy Tickets" link — the venue's real ticketer. Scraping the
venue site gives the event-specific Etix URL instead of a Ticketmaster link.
"""
import logging

import requests
from bs4 import BeautifulSoup

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.custom.date_utils import parse_month_day_text
from showcat.adapters.sources.custom.time_utils import extract_doors_show_times

logger = logging.getLogger(__name__)


class RhpVenueAdapter(BaseSourceAdapter):
    """Base scraper for RHP-platform venue sites (Roseland, Hawthorne)."""

    URL = ""
    SOURCE = ""
    DEFAULT_VENUE = ""

    @property
    def source_name(self) -> str:
        return self.SOURCE

    def fetch(self) -> list[RawEvent]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        try:
            resp = requests.get(self.URL, headers=headers, timeout=20)
            resp.raise_for_status()
            html_content = resp.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch {self.SOURCE} events: {e}")
            raise
        return self.parse(html_content)

    def parse(self, html_content: str) -> list[RawEvent]:
        soup = BeautifulSoup(html_content, "html.parser")
        events: list[RawEvent] = []
        seen: set[str] = set()

        for row in soup.select(".rhp-event__single-event--list"):
            link = row.select_one('a[href*="etix.com/ticket/p/"]') or row.select_one(
                ".rhp-event-cta a[href]"
            )
            if not link:
                continue
            ticket_url = str(link.get("href", "")).strip()
            if not ticket_url:
                continue

            title_el = row.select_one(".rhp-event__title--list")
            headliner = title_el.get_text(strip=True) if title_el else ""
            if not headliner:
                continue

            date_el = row.select_one(".rhp-event__date--list")
            event_date = (
                parse_month_day_text(date_el.get_text(" ", strip=True)) if date_el else None
            )
            if event_date is None:
                continue

            time_el = row.select_one(".rhp-event__time-text--list")
            doors_time = show_time = None
            if time_el:
                doors_time, show_time = extract_doors_show_times(time_el.get_text(" ", strip=True))

            venue_el = row.select_one(".rhp-event__venue-text--list")
            venue = venue_el.get_text(strip=True) if venue_el else self.DEFAULT_VENUE

            source_id = ticket_url.rstrip("/").split("/p/", 1)[-1].split("/")[0] or ticket_url
            if source_id in seen:
                continue
            seen.add(source_id)

            events.append(
                RawEvent(
                    source=self.source_name,
                    source_id=source_id,
                    headliner=headliner,
                    openers=[],
                    event_date=event_date,
                    doors_time=doors_time,
                    show_time=show_time,
                    venue=venue or self.DEFAULT_VENUE,
                    ticket_url=ticket_url,
                )
            )

        logger.info(
            f"{self.SOURCE} fetch complete",
            extra={"source": self.source_name, "event_count": len(events)},
        )
        return events


class RoselandAdapter(RhpVenueAdapter):
    URL = "https://www.roselandpdx.com/"
    SOURCE = "roseland_theater"
    DEFAULT_VENUE = "Roseland Theater"


class HawthorneAdapter(RhpVenueAdapter):
    URL = "https://www.hawthornetheatre.com/"
    SOURCE = "hawthorne_theatre"
    DEFAULT_VENUE = "Hawthorne Theatre"
