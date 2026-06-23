"""Kelly's Olympian adapter — Tribe Events REST API."""
import html
import json
import logging
import re
from datetime import datetime, time

import requests

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.title_parser import is_non_show, normalize_title

logger = logging.getLogger(__name__)

_API_URL = "https://www.kellysolympian.com/wp-json/tribe/events/v1/events"
_VENUE = "Kelly's Olympian"


class KellysOlympianAdapter(BaseSourceAdapter):
    """Scrape Kelly's Olympian via the Tribe Events REST API."""

    @property
    def source_name(self) -> str:
        return "kellys_olympian"

    def parse(self, content: str) -> list[RawEvent]:
        """Parse a Tribe Events API JSON response string into RawEvents."""
        data = json.loads(content)
        events: list[RawEvent] = []
        for item in data.get("events", []):
            try:
                start_str = item.get("start_date", "")
                if not start_str:
                    continue

                parts = start_str.split(" ")
                event_date = datetime.strptime(parts[0], "%Y-%m-%d").date()

                show_time: time | None = None
                if len(parts) > 1:
                    try:
                        t = parts[1].split(":")
                        show_time = time(int(t[0]), int(t[1]))
                    except (ValueError, IndexError):
                        pass

                title = html.unescape(item.get("title", "")).strip()
                if not title:
                    continue

                headliner, openers, status = normalize_title(title)
                if is_non_show(headliner) or status in ("moved", "cancelled"):
                    continue

                source_id = str(item.get("id", ""))
                if not source_id:
                    continue

                ticket_url = item.get("url", "")

                # Cost from the cost field; fall back to scanning description HTML.
                cost = item.get("cost") or ""
                if not cost:
                    desc_html = item.get("description", "")
                    desc_text = re.sub(r"<[^>]+>", " ", desc_html)
                    m = re.search(r"(\$\d+(?:\.\d{2})?|free)", desc_text, re.IGNORECASE)
                    if m:
                        cost = m.group(0)

                image_info = item.get("image")
                image_url: str | None = None
                if isinstance(image_info, dict):
                    image_url = image_info.get("url")
                elif isinstance(image_info, str):
                    image_url = image_info

                events.append(
                    RawEvent(
                        source=self.source_name,
                        source_id=source_id,
                        headliner=headliner,
                        openers=openers,
                        event_date=event_date,
                        venue=_VENUE,
                        ticket_url=ticket_url or None,
                        price=str(cost) if cost else None,
                        image_url=image_url,
                        show_time=show_time,
                        sold_out=(status == "sold_out"),
                    )
                )
            except Exception as e:
                logger.warning("Error parsing Kelly's Olympian event: %s", e)

        logger.info(
            "Kelly's Olympian fetch complete",
            extra={"source": self.source_name, "event_count": len(events)},
        )
        return events

    def fetch(self) -> list[RawEvent]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        try:
            resp = requests.get(_API_URL, headers=headers, timeout=15, params={"per_page": 50})
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("Failed to fetch Kelly's Olympian events: %s", e)
            raise
        return self.parse(resp.text)
