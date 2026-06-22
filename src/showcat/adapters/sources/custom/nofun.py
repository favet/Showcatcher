import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.custom.time_utils import extract_doors_show_times
from showcat.adapters.sources.title_parser import is_non_show, normalize_title

logger = logging.getLogger(__name__)

class NoFunBarAdapter(BaseSourceAdapter):
    """Adapter for No Fun Bar, parsing Squarespace DOM."""

    @property
    def source_name(self) -> str:
        return "nofunbar"

    def fetch(self) -> list[RawEvent]:
        events: list[RawEvent] = []
        base_url = "https://www.nofunportland.com"
        url = f"{base_url}/"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            html_content = resp.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch No Fun Bar events: {e}")
            raise

        soup = BeautifulSoup(html_content, "html.parser")

        for event_item in soup.select('.eventlist-event'):
            try:
                title_link = event_item.select_one('.eventlist-title a')
                if not title_link:
                    continue

                title = title_link.get_text(strip=True)
                if not title or "CLOSED" in title.upper():
                    continue

                path = title_link.get('href', '')
                event_url = f"{base_url}{path}" if path.startswith('/') else path

                source_id = path.strip("/")
                if not source_id:
                    continue

                date_tag = event_item.select_one('time.event-date')
                if not date_tag:
                    continue

                date_str = date_tag.get('datetime')
                if not date_str:
                    continue

                event_date = datetime.strptime(date_str, "%Y-%m-%d").date()

                # Parse doors/show times from the event text block.
                # Squarespace may include "Doors: 7PM / Show: 8PM" in meta.
                event_text = event_item.get_text(" ", strip=True)
                doors_time_val, show_time_val = extract_doors_show_times(event_text)
                # If no keyword context, fall back to the structured time element.
                if not show_time_val and not doors_time_val:
                    time_tag = event_item.select_one(
                        'time.event-time-12hr, time.event-time-24hr, .eventlist-meta-time'
                    )
                    if time_tag:
                        _, show_time_val = extract_doors_show_times(time_tag.get_text(strip=True))

                # Split openers from headliner if they use common separators
                # "The Warped Lines • Sunny Bear Forrest • Speaker Typhoon"
                parts = [p.strip() for p in title.replace("•", "|").split("|")]
                headliner = parts[0]
                raw_openers = parts[1:] if len(parts) > 1 else []

                # ── Title normalization ─────────────────────────────────
                if is_non_show(headliner):
                    continue
                headliner, openers, status = normalize_title(headliner, existing_openers=raw_openers)
                if status in ("moved", "cancelled"):
                    continue

                # Image URL
                image_el = event_item.select_one('.eventlist-thumbnail img, img')
                image_url = image_el.get('data-src') or image_el.get('src') if image_el else None

                # Price
                import re
                price_match = re.search(r'\$\d+(?:\.\d{2})?', event_text)
                price_str = price_match.group(0) if price_match else None

                events.append(
                    RawEvent(
                        source=self.source_name,
                        source_id=source_id,
                        headliner=headliner,
                        openers=openers,
                        event_date=event_date,
                        doors_time=doors_time_val,
                        show_time=show_time_val,
                        venue="No Fun Bar",
                        ticket_url=event_url,
                        price=price_str,
                        image_url=image_url,
                    )
                )
            except Exception as e:
                logger.warning(f"Error parsing No Fun Bar event: {e}")

        return events
