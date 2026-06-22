import json
import logging
from datetime import datetime, time as dt_time
from typing import Any

import requests
from bs4 import BeautifulSoup

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.title_parser import (
    is_non_show,
    normalize_title,
    split_multi_artist_plus,
)

logger = logging.getLogger(__name__)

class StardayTavernAdapter(BaseSourceAdapter):
    """Adapter for Starday Tavern, parsing Elementor Event Calendar JSON payload."""

    @property
    def source_name(self) -> str:
        return "starday"

    def fetch(self) -> list[RawEvent]:
        events: list[RawEvent] = []
        url = "https://www.stardaytavern.com/"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            html_content = resp.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch Starday Tavern events: {e}")
            raise
            
        soup = BeautifulSoup(html_content, "html.parser")
        cal_el = soup.select_one(".eael-event-calendar-cls")
        
        if not cal_el:
            logger.warning("Could not find Elementor calendar element on Starday Tavern")
            return []
            
        events_data_str = cal_el.get("data-events")
        if not events_data_str:
            return []
            
        try:
            events_data = json.loads(events_data_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Starday Tavern events JSON: {e}")
            return []
            
        for item in events_data:
            try:
                title = item.get("title", "").strip()
                if not title or "CLOSED" in title.upper():
                    continue
                    
                start_str = item.get("start", "")
                if not start_str:
                    continue
                    
                date_part = start_str.split("T")[0]
                event_date = datetime.strptime(date_part, "%Y-%m-%d").date()
                
                # Parse time from ISO datetime (e.g. "T18:00:00-08:00")
                start_time_val: dt_time | None = None
                if "T" in start_str:
                    try:
                        time_portion = start_str.split("T")[1]
                        # Strip timezone offset
                        time_clean = time_portion.split("-")[0].split("+")[0]
                        t_parts = time_clean.split(":")
                        start_time_val = dt_time(int(t_parts[0]), int(t_parts[1]))
                    except (ValueError, IndexError):
                        pass
                
                # Filter out past events early? We can just pass them, snapshot stage handles it
                
                source_id = str(item.get("id", ""))
                raw_url = item.get("url", "")
                # Elementor calendar embeds Google Calendar event URLs — not useful as ticket links
                event_url = url if (not raw_url or "google.com/calendar" in raw_url) else raw_url
                
                price = item.get("price") or item.get("cost")
                if not price and item.get("description"):
                    import re
                    match = re.search(r'\$\d+(?:\.\d{2})?', item["description"])
                    if match:
                        price = match.group(0)

                image_url = item.get("image") or item.get("thumbnail")

                # ── Title normalization + multi-band split ────────────────────
                if is_non_show(title):
                    continue
                title, openers_from_title, status = normalize_title(title)
                if status in ("moved", "cancelled"):
                    continue
                # Starday packs full bill in the title: "Band A + Band B + TBA"
                title, openers = split_multi_artist_plus(title, existing_openers=openers_from_title)

                events.append(
                    RawEvent(
                        source=self.source_name,
                        source_id=source_id,
                        headliner=title,
                        openers=openers,
                        event_date=event_date,
                        show_time=start_time_val,
                        venue="Starday Tavern",
                        ticket_url=event_url,
                        price=str(price) if price else "At the door",
                        image_url=image_url,
                        sold_out=(status == "sold_out"),
                    )
                )
            except Exception as e:
                logger.warning(f"Error parsing Starday Tavern event: {e}")

        return events
