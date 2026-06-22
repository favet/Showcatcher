"""McMenamins venue scraper (Phase 8.3).

McMenamins venues (Crystal Ballroom, Lola's Room, …) render a
`.wm-tour-schedule-wrap` whose children alternate: an event `<a>` (title +
month/day) followed by a `.ticket-buttons` block containing the Etix
"Tickets" link. Pairing the two yields an event-specific Etix URL instead of
sending visitors to Ticketmaster.
"""
import logging

import requests
from bs4 import BeautifulSoup, Tag

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.custom.date_utils import infer_date, month_to_num

logger = logging.getLogger(__name__)


class McMenaminsVenueAdapter(BaseSourceAdapter):
    """Base scraper for McMenamins wm-tour-schedule venue sites."""

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

        for wrap in soup.select(".wm-tour-schedule-wrap"):
            children = [c for c in wrap.find_all(recursive=False) if isinstance(c, Tag)]
            for i, node in enumerate(children):
                # An event is an <a> with a .title; its Etix link is in the
                # following .ticket-buttons sibling.
                if node.name != "a":
                    continue
                title_el = node.select_one(".title")
                if not title_el:
                    continue
                headliner = title_el.get_text(strip=True)
                if not headliner:
                    continue

                # Date: month name + day inside .event-list-date.
                event_date = None
                time_el = node.select_one(".event-list-date time")
                if time_el:
                    month_el = time_el.find("strong")
                    day_el = time_el.find("span")
                    if month_el and day_el:
                        month = month_to_num(month_el.get_text(strip=True))
                        day_txt = day_el.get_text(strip=True)
                        if month and day_txt.isdigit():
                            event_date = infer_date(month, int(day_txt))
                if event_date is None:
                    continue

                # Etix link from the following ticket-buttons sibling.
                ticket_url = ""
                for sib in children[i + 1 : i + 3]:
                    buy = sib.select_one('a[href*="etix.com/ticket/p/"]') or sib.select_one(
                        "a.buy-button[href]"
                    )
                    if buy:
                        ticket_url = str(buy.get("href", "")).strip()
                        break
                if not ticket_url:
                    continue

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
                        venue=self.DEFAULT_VENUE,
                        ticket_url=ticket_url,
                    )
                )

        logger.info(
            f"{self.SOURCE} fetch complete",
            extra={"source": self.source_name, "event_count": len(events)},
        )
        return events


class CrystalBallroomAdapter(McMenaminsVenueAdapter):
    URL = "https://www.crystalballroompdx.com/events"
    SOURCE = "crystal_ballroom"
    DEFAULT_VENUE = "Crystal Ballroom"
