"""The Showdown PDX scraper (Phase 9 — venue expansion).

The Showdown uses the TicketWeb WordPress plugin, which renders events as
.tw-section rows inside .tw-plugin-upcoming-event-list. Each row carries
a date (.tw-day-of-week + .tw-event-date), title (.tw-name a), show/doors
times (.tw-event-time / .tw-event-door-time), and a TicketWeb buy link.

TicketWeb is Ticketmaster-owned (rank 20, last-resort), per D17 — but The
Showdown is not currently in TM's API feed, so this scraper is the only way
to get its events.
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


class ShowdownAdapter(BaseSourceAdapter):
    URL = "https://www.showdownpdx.com"
    SOURCE = "showdown"

    @property
    def source_name(self) -> str:
        return self.SOURCE

    def fetch(self) -> list[RawEvent]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        try:
            resp = requests.get(self.URL, headers=headers, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch {self.SOURCE} events: {e}")
            raise
        return self.parse(resp.text)

    def parse(self, html: str) -> list[RawEvent]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[RawEvent] = []
        seen: set[str] = set()

        for section in soup.select(".tw-plugin-upcoming-event-list .tw-section"):
            title_el = section.select_one(".tw-name a")
            if not title_el:
                continue
            headliner = title_el.get_text(strip=True)

            # Date: "Sun" + "Jun 21" → "Sun Jun 21" → parse_month_day_text.
            dow_el = section.select_one(".tw-day-of-week")
            date_el = section.select_one(".tw-event-date")
            date_text = " ".join(
                el.get_text(strip=True) for el in [dow_el, date_el] if el
            )
            event_date = parse_month_day_text(date_text)
            if event_date is None:
                continue

            # Times: combine ".tw-event-time" ("Show: 8:00 pm") and
            # ".tw-event-door-time" ("7:00 pm") so extract_doors_show_times
            # sees both keywords and assigns each to the right field.
            show_el = section.select_one(".tw-event-time")
            door_el = section.select_one(".tw-event-door-time")
            time_text = ""
            if show_el:
                time_text += show_el.get_text(strip=True)
            if door_el:
                time_text += f" Doors: {door_el.get_text(strip=True)}"
            doors_time, show_time = extract_doors_show_times(time_text)

            tix_el = section.select_one("a.tw-buy-tix-btn[href]")
            ticket_url = str(tix_el["href"]).strip() if tix_el else ""

            # source_id: TicketWeb numeric event ID from the URL path.
            m = re.search(r"/(\d{6,})(?:\?|$)", ticket_url)
            source_id = m.group(1) if m else f"{event_date}-{headliner[:30]}"

            if source_id in seen:
                continue
            seen.add(source_id)

            # Price: check standard TicketWeb section price elements
            price_el = section.select_one(".tw-price, .tw-event-price, .tw-price-range")
            price_str = price_el.get_text(strip=True) if price_el else None
            if not price_str:
                sec_text = section.get_text(" ", strip=True)
                price_match = re.search(r'\$\d+(?:\.\d{2})?', sec_text)
                price_str = price_match.group(0) if price_match else None

            # Image
            image_el = section.select_one(".tw-image img, img")
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
                    venue="The Showdown",
                    ticket_url=ticket_url or None,
                    price=price_str,
                    image_url=image_url,
                    sold_out=(status == "sold_out"),
                )
            )

        logger.info(
            f"{self.SOURCE} fetch complete",
            extra={"source": self.source_name, "event_count": len(events)},
        )
        return events
