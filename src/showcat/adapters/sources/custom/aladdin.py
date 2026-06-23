"""Aladdin Theater — venue-direct scraper (Phase 8.3).

The Aladdin's own site lists every show as a schema.org Event card whose
"buy tickets" link points at Etix — the venue's real ticketer. Scraping the
venue site (rather than Ticketmaster) gives an event-specific, non-TM ticket
URL, which the de-Ticketmaster link preference will favour over the TM
duplicate.

Card markup (div.event--card-style):
    data-event-id            -> stable source_id
    meta[itemprop=startDate] -> ISO datetime (date + show time)
    a.event-title-link href  -> Etix ticket URL
    h3.event-title           -> headliner
    div.event-venue          -> venue name
"""
import logging
from datetime import datetime
from datetime import time as dt_time

import requests
from bs4 import BeautifulSoup

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.title_parser import is_non_show, normalize_title

logger = logging.getLogger(__name__)


class AladdinAdapter(BaseSourceAdapter):
    """Scrape upcoming Aladdin Theater shows (Etix-ticketed) from the venue site."""

    URL = "https://aladdin-theater.com/"
    DEFAULT_VENUE = "Aladdin Theater"

    @property
    def source_name(self) -> str:
        return "aladdin_theater"

    def fetch(self) -> list[RawEvent]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        try:
            resp = requests.get(self.URL, headers=headers, timeout=20)
            resp.raise_for_status()
            html_content = resp.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch Aladdin Theater events: {e}")
            raise

        return self.parse(html_content)

    def parse(self, html_content: str) -> list[RawEvent]:
        soup = BeautifulSoup(html_content, "html.parser")
        events: list[RawEvent] = []
        seen_ids: set[str] = set()

        for card in soup.select("div.event--card-style"):
            link = card.select_one("a.event-title-link[href]")
            if not link:
                continue
            ticket_url = str(link.get("href", "")).strip()
            if not ticket_url:
                continue

            title_el = card.select_one(".event-title")
            headliner = title_el.get_text(strip=True) if title_el else ""
            if not headliner:
                continue

            # Date + show time from the schema.org startDate meta.
            event_date = None
            show_time: dt_time | None = None
            meta = card.select_one("meta[itemprop=startDate]")
            start_raw = str(meta.get("content", "")).strip() if meta else ""
            if start_raw:
                try:
                    # e.g. "2026-08-29T19:00:00+00:00" — treat as venue-local naive.
                    dt_val = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                    event_date = dt_val.date()
                    if dt_val.hour or dt_val.minute:
                        show_time = dt_val.time().replace(tzinfo=None)
                except ValueError:
                    pass
            if event_date is None:
                continue

            venue_el = card.select_one(".event-venue")
            venue = venue_el.get_text(strip=True) if venue_el else self.DEFAULT_VENUE

            # Stable id: the venue's own event id, else fall back to the Etix path.
            event_id = str(card.get("data-event-id", "")).strip()
            source_id = event_id or ticket_url.rsplit("/", 1)[-1]
            if source_id in seen_ids:
                continue
            seen_ids.add(source_id)

            # Price
            price_el = card.select_one(".event-price, .event-cost, .event-price-range")
            price_str = price_el.get_text(strip=True) if price_el else None

            # Image URL
            image_el = card.select_one(".event-image img, img")
            image_url = image_el.get("src") if image_el else None

            headliner, _, status = normalize_title(headliner)
            events.append(
                RawEvent(
                    source=self.source_name,
                    source_id=source_id,
                    headliner=headliner,
                    openers=[],
                    event_date=event_date,
                    show_time=show_time,
                    venue=venue or self.DEFAULT_VENUE,
                    ticket_url=ticket_url,
                    price=price_str,
                    image_url=image_url,
                    sold_out=(status == "sold_out"),
                )
            )

        logger.info(
            "Aladdin fetch complete",
            extra={"source": self.source_name, "event_count": len(events)},
        )
        return events
