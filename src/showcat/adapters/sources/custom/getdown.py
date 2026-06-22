"""The Get Down scraper (Phase 9 — venue expansion).

Events are rendered as Webflow CMS list items (.ca-info.w-dyn-item), each with
an embedded JSON-LD <script type="application/ld+json"> block carrying the name,
startDate ("Jun 26, 2026"), and Tixr ticket URL in offers.url.
"""
import json
import logging
import re

import requests
from bs4 import BeautifulSoup

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.custom.date_utils import parse_full_date
from showcat.adapters.sources.custom.time_utils import extract_doors_show_times
from showcat.adapters.sources.title_parser import is_non_show, normalize_title

logger = logging.getLogger(__name__)


class GetDownAdapter(BaseSourceAdapter):
    URL = "https://thegetdownpdx.com/calendar"
    SOURCE = "the_get_down"

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

        for item in soup.select(".ca-info.w-dyn-item"):
            script = item.find("script", type="application/ld+json")
            if not script:
                continue
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, ValueError):
                continue
            if data.get("@type") != "Event":
                continue

            name = data.get("name", "").strip()
            if not name:
                continue

            event_date = parse_full_date(data.get("startDate", ""))
            if event_date is None:
                continue

            offers = data.get("offers", {})
            ticket_url = offers.get("url", "").strip() if isinstance(offers, dict) else ""
            # Reject group-level URLs (no event slug after /events/).
            if not re.search(r"/events/.+-.+", ticket_url):
                ticket_url = ""
            if not ticket_url:
                continue

            # source_id: full event slug from the Tixr URL path.
            source_id = ticket_url.rstrip("/").split("/events/")[-1]
            if source_id in seen:
                continue
            seen.add(source_id)

            # Doors time from "DOORS: 8:00 pm" in item text.
            text = item.get_text(" ", strip=True)
            doors_time, show_time = extract_doors_show_times(text)

            image_url = data.get("image")
            price_str = None
            if isinstance(offers, dict):
                val = offers.get("price") or offers.get("lowPrice")
                if val is not None:
                    price_str = str(val).strip()
            if not price_str:
                price_match = re.search(r'\$\d+(?:\.\d{2})?', text)
                price_str = price_match.group(0) if price_match else None

            name, _, status = normalize_title(name)
            events.append(
                RawEvent(
                    source=self.source_name,
                    source_id=source_id,
                    headliner=name,
                    openers=[],
                    event_date=event_date,
                    doors_time=doors_time,
                    show_time=show_time,
                    venue="The Get Down",
                    ticket_url=ticket_url,
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
