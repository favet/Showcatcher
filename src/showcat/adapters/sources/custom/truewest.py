"""True West venue scraper (Phase 8.3).

The Mississippi Studios site renders a combined calendar feed (`.events-feed`)
covering both Mississippi Studios and its sister room Polaris Hall. Each
`.weekday-event` carries the show title, an Etix link, a venue logo (which
identifies Mississippi vs Polaris), and sits under a `.day-header` ("Sun 6/21").
"""
import logging
import re
from datetime import time

import requests
from bs4 import BeautifulSoup

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.custom.date_utils import parse_numeric_md
from showcat.adapters.sources.title_parser import is_non_show, normalize_title

logger = logging.getLogger(__name__)

# "Doors: 7PM / Show: 8 PM" or "Doors: 7:30PM / Show: 8:30 PM"
_TIME_RE = re.compile(
    r"Doors[:\s]+(\d{1,2}(?::\d{2})?\s*(?:AM|PM))"
    r".*?Show[:\s]+(\d{1,2}(?::\d{2})?\s*(?:AM|PM))",
    re.IGNORECASE,
)


def _parse_12h(s: str) -> time | None:
    """Parse '7PM', '7:30PM', '8 PM' → datetime.time."""
    s = s.strip().upper().replace(" ", "")
    for fmt in ("%I:%M%p", "%I%p"):
        try:
            import datetime as dt
            return dt.datetime.strptime(s, fmt).time()
        except ValueError:
            pass
    return None


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

            # Doors / show times from "Doors: 7PM / Show: 8 PM" paragraph text.
            doors_time: time | None = None
            show_time: time | None = None
            for p in ev.find_all(string=_TIME_RE):
                m = _TIME_RE.search(p)
                if m:
                    doors_time = _parse_12h(m.group(1))
                    show_time = _parse_12h(m.group(2))
                    break

            # Description: any paragraph text that isn't purely a time/age/price line.
            _skip_re = re.compile(r"^(Doors|Show|All Ages|21\+|18\+|\$|Free)", re.IGNORECASE)
            desc_parts: list[str] = []
            for p in ev.select("p, .event-description, .event-blurb"):
                txt = p.get_text(strip=True)
                if txt and not _skip_re.match(txt) and len(txt) > 20:
                    desc_parts.append(txt)
            description = " ".join(desc_parts) or None

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
                    doors_time=doors_time,
                    show_time=show_time,
                    description=description,
                )
            )

        logger.info(
            "True West fetch complete",
            extra={"source": self.source_name, "event_count": len(events)},
        )
        return events
