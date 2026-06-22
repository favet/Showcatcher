"""Revolution Hall scraper (Phase 8 follow-on).

revolutionhall.com is server-rendered via the same True West / Etix CMS used by
Mississippi Studios.  Events live in `.events-feed .event-wrapper` blocks;
each block carries title, date, door/show times, and a direct Etix ticket link.

The feed is paginated (30 events per page).  We fetch pages until one returns
zero new events or we hit the page cap.
"""
import logging

import requests
from bs4 import BeautifulSoup

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.custom.date_utils import parse_full_date
from showcat.adapters.sources.custom.time_utils import extract_doors_show_times

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.revolutionhall.com"
_MAX_PAGES = 5


class RevolutionHallAdapter(BaseSourceAdapter):
    SOURCE = "revolution_hall"

    @property
    def source_name(self) -> str:
        return self.SOURCE

    def fetch(self) -> list[RawEvent]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        events: list[RawEvent] = []
        seen: set[str] = set()

        for page in range(1, _MAX_PAGES + 1):
            url = _BASE_URL if page == 1 else f"{_BASE_URL}/page/{page}"
            try:
                resp = requests.get(url, headers=headers, timeout=20)
                resp.raise_for_status()
            except requests.RequestException as e:
                logger.error("Failed to fetch Revolution Hall page %d: %s", page, e)
                break

            new_events = self.parse(resp.text, seen)
            if not new_events:
                break
            events.extend(new_events)

        logger.info(
            "revolution_hall fetch complete",
            extra={"source": self.SOURCE, "event_count": len(events)},
        )
        return events

    def parse(self, html_content: str, seen: set[str] | None = None) -> list[RawEvent]:
        if seen is None:
            seen = set()
        soup = BeautifulSoup(html_content, "html.parser")
        events: list[RawEvent] = []

        for wrapper in soup.select(".event-wrapper"):
            event_div = wrapper.select_one("div.event[data-event-id]")
            if not event_div:
                continue

            source_id = str(event_div.get("data-event-id", "")).strip()
            if not source_id or source_id in seen:
                continue

            # Title
            title_a = event_div.select_one("h3[itemprop='name'] a")
            if not title_a:
                continue
            headliner = title_a.get_text(strip=True)
            if not headliner:
                continue

            # Ticket URL (event-action link to Etix)
            ticket_a = event_div.select_one("a.event-action[href*='etix.com/ticket/p/']")
            if not ticket_a:
                continue
            ticket_url = str(ticket_a.get("href", "")).strip()

            # Date: "Tue, June 23rd, 2026"
            date_el = event_div.select_one(".event-date--full")
            event_date = parse_full_date(date_el.get_text(strip=True)) if date_el else None
            if event_date is None:
                continue

            # Doors / show time: "Doors: 6PM / Show: 7PM"
            time_el = event_div.select_one(".event-doors-showtime")
            doors_time = show_time = None
            if time_el:
                doors_time, show_time = extract_doors_show_times(
                    time_el.get_text(strip=True)
                )

            # Venue: distinguish Revolution Hall vs Show Bar from wrapper class
            wrapper_classes = wrapper.get("class", [])
            if "show-bar-at-revolution-hall" in wrapper_classes:
                venue = "Show Bar"
            else:
                venue = "Revolution Hall"

            seen.add(source_id)
            events.append(
                RawEvent(
                    source=self.SOURCE,
                    source_id=source_id,
                    headliner=headliner,
                    openers=[],
                    event_date=event_date,
                    doors_time=doors_time,
                    show_time=show_time,
                    venue=venue,
                    ticket_url=ticket_url,
                )
            )

        return events
