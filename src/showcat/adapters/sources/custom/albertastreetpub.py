"""Alberta Street Pub adapter — Squarespace event listing scraper."""
import logging
import re
from datetime import datetime, time

import requests
from bs4 import BeautifulSoup

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.title_parser import is_non_show, normalize_title

logger = logging.getLogger(__name__)

_URL = "https://www.albertastreetpub.com/music"
_VENUE = "Alberta Street Pub"
# Matches slugs like /music/2026/6/21/some-event-name
_SLUG_DATE_RE = re.compile(r"/music/(\d{4})/(\d{1,2})/(\d{1,2})/")
_TIME_RE = re.compile(r"(\d{1,2}(?::\d{2})?)\s*(AM|PM)", re.IGNORECASE)
_PRICE_RE = re.compile(r"(\$\d+(?:\.\d{2})?|free)", re.IGNORECASE)


def _parse_time(s: str) -> time | None:
    m = _TIME_RE.search(s)
    if not m:
        return None
    hm, meridiem = m.group(1), m.group(2).upper()
    parts = hm.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    if meridiem == "PM" and hour != 12:
        hour += 12
    elif meridiem == "AM" and hour == 12:
        hour = 0
    try:
        return time(hour, minute)
    except ValueError:
        return None


class AlbertaStreetPubAdapter(BaseSourceAdapter):
    """Scrape Alberta Street Pub's Squarespace event listing page."""

    @property
    def source_name(self) -> str:
        return "alberta_street_pub"

    def fetch(self) -> list[RawEvent]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        try:
            resp = requests.get(_URL, headers=headers, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("Failed to fetch Alberta Street Pub events: %s", e)
            raise
        return self.parse(resp.text)

    def parse(self, html_content: str) -> list[RawEvent]:
        soup = BeautifulSoup(html_content, "html.parser")
        events: list[RawEvent] = []
        seen: set[str] = set()

        # Squarespace event list: articles or summary items with an href to /music/YYYY/M/D/slug
        for link_el in soup.find_all("a", href=_SLUG_DATE_RE):
            href = str(link_el.get("href", "")).split("?")[0]  # strip ?format=ical etc.
            m = _SLUG_DATE_RE.search(href)
            if not m:
                continue

            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                event_date = datetime(year, month, day).date()
            except ValueError:
                continue

            # source_id from the slug path
            slug = href.rstrip("/").split("/")[-1]
            if not slug or slug in seen:
                continue
            seen.add(slug)

            # Title: look inside the link or its nearest article ancestor
            ancestor = link_el.find_parent("article") or link_el
            title_el = (
                ancestor.select_one(".eventlist-title")
                or ancestor.select_one(".blog-list-item-title")
                or ancestor.select_one("h1, h2, h3")
                or link_el
            )
            title = title_el.get_text(strip=True)
            if not title:
                continue

            headliner, openers, status = normalize_title(title)
            if is_non_show(headliner) or status in ("moved", "cancelled"):
                continue

            # Collect all visible text in the event block for time + price
            block_text = ancestor.get_text(" ", strip=True)

            show_time = _parse_time(block_text)

            price_m = _PRICE_RE.search(block_text)
            price_str: str | None = None
            if price_m:
                raw = price_m.group(1)
                price_str = "Free" if raw.lower() == "free" else raw

            ticket_url = f"https://www.albertastreetpub.com{href}"

            # Image: look for featured image in the ancestor block
            img = ancestor.select_one("img[src]")
            image_url: str | None = None
            if img:
                src = str(img.get("src", ""))
                if src and not src.startswith("data:"):
                    image_url = src

            events.append(
                RawEvent(
                    source=self.source_name,
                    source_id=slug,
                    headliner=headliner,
                    openers=openers,
                    event_date=event_date,
                    venue=_VENUE,
                    ticket_url=ticket_url,
                    price=price_str,
                    image_url=image_url,
                    show_time=show_time,
                    sold_out=(status == "sold_out"),
                )
            )

        logger.info(
            "Alberta Street Pub fetch complete",
            extra={"source": self.source_name, "event_count": len(events)},
        )
        return events
