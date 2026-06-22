"""True West venue scraper (Phase 8.3).

The Mississippi Studios site renders a combined calendar feed (`.events-feed`)
covering both Mississippi Studios and its sister room Polaris Hall. Each
`.weekday-event` carries the show title, an Etix link, a venue logo (which
identifies Mississippi vs Polaris), and sits under a `.day-header` ("Sun 6/21").
"""
import logging

import requests
from bs4 import BeautifulSoup

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.custom.date_utils import parse_numeric_md
from showcat.adapters.sources.title_parser import is_non_show, normalize_title

logger = logging.getLogger(__name__)


class TrueWestAdapter(BaseSourceAdapter):
    """Scrape the Mississippi Studios / Polaris Hall combined Etix calendar."""

    URL = "https://www.mississippistudios.com/"
    DEFAULT_VENUE = "Mississippi Studios"

    @property
    def source_name(self) -> str:
        return "truewest_pdx"

    def fetch(self) -> list[RawEvent]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        try:
            resp = requests.get(self.URL, headers=headers, timeout=20)
            resp.raise_for_status()
            html_content = resp.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch True West events: {e}")
            raise
        return self.parse(html_content)

    def parse(self, html_content: str) -> list[RawEvent]:
        soup = BeautifulSoup(html_content, "html.parser")
        events: list[RawEvent] = []
        seen: set[str] = set()

        for ev in soup.select(".events-feed .weekday-event"):
            link = ev.select_one('a[href*="etix.com/ticket/p/"]') or ev.select_one(
                "a.event-action[href]"
            )
            if not link:
                continue
            ticket_url = str(link.get("href", "")).strip()
            if not ticket_url:
                continue

            title_el = ev.select_one(".event-title")
            headliner = (title_el or link).get_text(strip=True)
            if not headliner:
                continue

            # Date from the enclosing day cell's header ("Sun 6/21").
            day_inner = ev.find_parent("div", class_="weekday-inner")
            hdr = day_inner.select_one(".day-header") if day_inner else None
            event_date = parse_numeric_md(hdr.get_text(" ", strip=True)) if hdr else None
            if event_date is None:
                continue

            # Venue from the logo (Mississippi Studios vs Polaris Hall).
            logo = ev.select_one("img.venue-logo")
            venue = self.DEFAULT_VENUE
            if logo and logo.get("alt"):
                venue = str(logo.get("alt")).replace("Logo", "").strip() or self.DEFAULT_VENUE

            source_id = ticket_url.rstrip("/").split("/p/", 1)[-1].split("/")[0] or ticket_url
            if source_id in seen:
                continue
            seen.add(source_id)

            # Image URL: find img excluding venue-logo
            image_el = ev.select_one("img:not(.venue-logo)")
            image_url = image_el.get("src") if image_el else None

            # Price
            price_el = ev.select_one(".event-price, .event-cost, .event-price-range")
            price_str = price_el.get_text(strip=True) if price_el else None

            # ── Title normalization ───────────────────────────────────────
            if is_non_show(headliner):
                continue
            headliner, openers, status = normalize_title(headliner)
            if status in ("moved", "cancelled"):
                continue

            events.append(
                RawEvent(
                    source=self.source_name,
                    source_id=source_id,
                    headliner=headliner,
                    openers=openers,
                    event_date=event_date,
                    venue=venue,
                    ticket_url=ticket_url,
                    price=price_str,
                    image_url=image_url,
                    sold_out=(status == "sold_out"),
                )
            )

        logger.info(
            "True West fetch complete",
            extra={"source": self.source_name, "event_count": len(events)},
        )
        return events
