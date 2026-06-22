"""McMenamins main-site venue scrapers (Phase 8 follow-on).

mcmenamins.com venue pages (White Eagle, Al's Den, Lola's Room, Edgefield) use
a shared card CMS that differs from the crystalballroompdx.com wm-tour-schedule
markup.  Each event card is a `div.tm-panel-card.event.detailed`.  Cards that
have a ticket embed carry a `<a class="tm-card-ticketscircle" href="javascript:
void window.open('https://www.etix.com/ticket/p/...')">` — the Etix URL is
extracted from the JS string.

Only cards with Etix ticket embeds are emitted; non-ticketed events (beer fests,
tours, seasonal specials) are silently skipped.
"""
import logging
import re

import requests
from bs4 import BeautifulSoup

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.custom.date_utils import parse_month_day_text
from showcat.adapters.sources.custom.time_utils import extract_doors_show_times
from showcat.adapters.sources.title_parser import is_non_show, normalize_title

logger = logging.getLogger(__name__)

# Extracts the URL from "javascript: void window.open('URL'[, ...])"
_JS_OPEN_RE = re.compile(r"window\.open\('([^']+)'")


def _extract_etix_url(href: str) -> str:
    """Pull the real URL out of a javascript: void window.open(...) href."""
    m = _JS_OPEN_RE.search(href)
    return m.group(1) if m else ""


class McMenaminsMainAdapter(BaseSourceAdapter):
    """Base scraper for mcmenamins.com venue event pages."""

    URL = ""
    SOURCE = ""
    DEFAULT_VENUE = ""
    DEFAULT_PRICE: str | None = None  # "Free" for pub stages; None for ticketed rooms

    @property
    def source_name(self) -> str:
        return self.SOURCE

    def fetch(self) -> list[RawEvent]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        try:
            resp = requests.get(self.URL, headers=headers, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("Failed to fetch %s events: %s", self.SOURCE, e)
            raise
        return self.parse(resp.text)

    def parse(self, html_content: str) -> list[RawEvent]:
        soup = BeautifulSoup(html_content, "html.parser")
        events: list[RawEvent] = []
        seen: set[str] = set()

        for card in soup.select("div.tm-panel-card.event.detailed"):
            etix_a = card.select_one("a.tm-card-ticketscircle[href*='etix.com']")
            if not etix_a:
                continue

            ticket_url = _extract_etix_url(str(etix_a.get("href", "")))
            if not ticket_url:
                continue

            # Title: first non-empty direct text node in .tm-panel-titlebg h3
            title_el = card.select_one(".tm-panel-titlebg h3.uk-panel-title")
            if not title_el:
                continue
            headliner = next(
                (s.strip() for s in title_el.strings if s.strip()), ""
            )
            if not headliner:
                continue

            # Date: "Tuesday, June 23" from .tm-card-content h3.uk-panel-title
            date_h3 = card.select_one(".tm-card-content h3.uk-panel-title")
            event_date = (
                parse_month_day_text(date_h3.get_text(strip=True)) if date_h3 else None
            )
            if event_date is None:
                continue

            # Time: "7:30pm doors, 8pm show"
            time_el = card.select_one(".uk-panel-time")
            doors_time = show_time = None
            if time_el:
                doors_time, show_time = extract_doors_show_times(
                    time_el.get_text(strip=True)
                )

            # Venue name from card, fallback to class default
            venue_span = card.select_one(".tm-card-title span")
            venue = (
                venue_span.get_text(strip=True) if venue_span else self.DEFAULT_VENUE
            ) or self.DEFAULT_VENUE

            source_id = (
                ticket_url.rstrip("/").split("/p/", 1)[-1].split("/")[0] or ticket_url
            )
            if source_id in seen:
                continue
            seen.add(source_id)

            card_text = card.get_text(" ", strip=True)
            price_match = re.search(r'\$\d+(?:\.\d{2})?', card_text)
            price_str = price_match.group(0) if price_match else self.DEFAULT_PRICE

            image_el = card.select_one("img")
            image_url = image_el.get("src") if image_el else None

            headliner, _, status = normalize_title(headliner)
            events.append(
                RawEvent(
                    source=self.source_name,
                    source_id=source_id,
                    headliner=headliner,
                    openers=[],
                    event_date=event_date,
                    doors_time=doors_time,
                    show_time=show_time,
                    venue=venue,
                    ticket_url=ticket_url,
                    price=price_str,
                    image_url=image_url,
                    sold_out=(status == "sold_out"),
                )
            )

        logger.info(
            "%s fetch complete",
            self.SOURCE,
            extra={"source": self.source_name, "event_count": len(events)},
        )
        return events


class WhiteEagleAdapter(McMenaminsMainAdapter):
    URL = "https://www.mcmenamins.com/white-eagle-saloon-hotel/white-eagle"
    SOURCE = "white_eagle"
    DEFAULT_VENUE = "White Eagle Saloon"
    DEFAULT_PRICE = "Free"


class AlsDenAdapter(McMenaminsMainAdapter):
    URL = "https://www.mcmenamins.com/crystal-hotel/things-to-do/music-event-calendar"
    SOURCE = "als_den"
    DEFAULT_VENUE = "Al's Den"
    DEFAULT_PRICE = "Free"


class LolasRoomAdapter(McMenaminsMainAdapter):
    URL = "https://www.mcmenamins.com/crystal-ballroom/lolas-room"
    SOURCE = "lolas_room"
    DEFAULT_VENUE = "Lola's Room"


class EdgefieldAdapter(McMenaminsMainAdapter):
    URL = "https://www.mcmenamins.com/edgefield/things-to-do/music-events"
    SOURCE = "edgefield"
    DEFAULT_VENUE = "McMenamins Edgefield"
