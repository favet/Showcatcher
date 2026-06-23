"""Nova PDX (formerly Bossanova Ballroom) — venue-direct scraper.

Scrapes upcoming shows from the Nova PDX event calendar (https://novapdxevents.com/event-calendar),
extracting schema.org Event JSON-LD blocks.
"""
import json
import logging

import requests
from bs4 import BeautifulSoup

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.custom.date_utils import parse_full_date
from showcat.adapters.sources.title_parser import is_non_show, normalize_title

logger = logging.getLogger(__name__)


class NovaPdxAdapter(BaseSourceAdapter):
    """Scrape upcoming Nova PDX (Bossanova Ballroom) shows from the venue site."""

    URL = "https://novapdxevents.com/event-calendar"
    DEFAULT_VENUE = "Nova PDX"

    @property
    def source_name(self) -> str:
        return "nova_pdx"

    def fetch(self) -> list[RawEvent]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        try:
            resp = requests.get(self.URL, headers=headers, timeout=20)
            resp.raise_for_status()
            html_content = resp.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch Nova PDX events: {e}")
            raise

        return self.parse(html_content)

    def parse(self, html_content: str) -> list[RawEvent]:
        soup = BeautifulSoup(html_content, "html.parser")
        events: list[RawEvent] = []
        seen_ids: set[str] = set()

        for script_tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script_tag.string)
                # Sometimes event calendar pages contain single Event objects or lists of Event objects.
                # In Nova PDX, they are single Event objects.
                if isinstance(data, list):
                    items = data
                else:
                    items = [data]

                for item in items:
                    if not isinstance(item, dict) or item.get("@type") != "Event":
                        continue

                    headliner = item.get("name", "").strip()
                    if not headliner:
                        continue

                    start_str = item.get("startDate", "").strip()
                    if not start_str:
                        continue

                    # Parse date (e.g. "Jun 24, 2026")
                    event_date = parse_full_date(start_str)
                    if event_date is None:
                        continue

                    # Offers/ticket url
                    offers = item.get("offers", {})
                    ticket_url = self.URL
                    price_str = None
                    if isinstance(offers, dict):
                        ticket_url = offers.get("url", self.URL).strip()
                        p = offers.get("price")
                        if p:
                            try:
                                price_str = f"${float(p):.2f}"
                            except ValueError:
                                price_str = str(p)
                    elif isinstance(offers, list) and offers:
                        ticket_url = offers[0].get("url", self.URL).strip()
                        p = offers[0].get("price")
                        if p:
                            try:
                                price_str = f"${float(p):.2f}"
                            except ValueError:
                                price_str = str(p)

                    # Image URL
                    image_url = item.get("image")

                    # Source ID: use the Tixr ID from url (e.g. 189938) or fallback
                    source_id = ""
                    if "tixr.com/e/" in ticket_url:
                        source_id = ticket_url.split("/e/")[-1].split("?")[0]
                    
                    if not source_id:
                        source_id = f"{event_date.isoformat()}-{headliner[:15].lower().replace(' ', '')}"

                    if source_id in seen_ids:
                        continue
                    seen_ids.add(source_id)

                    headliner, _, status = normalize_title(headliner)
                    events.append(
                        RawEvent(
                            source=self.source_name,
                            source_id=source_id,
                            headliner=headliner,
                            openers=[],
                            event_date=event_date,
                            show_time=None,
                            venue=self.DEFAULT_VENUE,
                            ticket_url=ticket_url,
                            price=price_str,
                            image_url=image_url,
                            sold_out=(status == "sold_out"),
                        )
                    )
            except Exception as e:
                logger.warning(f"Error parsing Nova PDX JSON-LD script tag: {e}")

        logger.info(
            "Nova PDX fetch complete",
            extra={"source": self.source_name, "event_count": len(events)},
        )
        return events
