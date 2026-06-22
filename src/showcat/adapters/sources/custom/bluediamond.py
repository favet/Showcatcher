import logging
from datetime import datetime, date, time
from typing import Any

import requests

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.title_parser import is_non_show, normalize_title

logger = logging.getLogger(__name__)

class BlueDiamondAdapter(BaseSourceAdapter):
    """Adapter for Blue Diamond, using the Tribe Events REST API."""

    @property
    def source_name(self) -> str:
        return "blue_diamond"

    def fetch(self) -> list[RawEvent]:
        events: list[RawEvent] = []
        url = "https://bluediamondpdx.net/wp-json/tribe/events/v1/events"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch Blue Diamond events: {e}")
            raise
            
        for item in data.get("events", []):
            try:
                # E.g. 2026-06-20 20:00:00
                start_str = item.get("start_date", "")
                if not start_str:
                    continue
                    
                # Parse date and time
                date_time_parts = start_str.split(" ")
                event_date = datetime.strptime(date_time_parts[0], "%Y-%m-%d").date()
                
                start_time_val: time | None = None
                if len(date_time_parts) > 1:
                    try:
                        t_parts = date_time_parts[1].split(":")
                        start_time_val = time(int(t_parts[0]), int(t_parts[1]))
                    except (ValueError, IndexError):
                        pass
                
                title = item.get("title", "")
                if not title:
                    continue
                    
                # Handle HTML entities in title like &#8217;
                import html
                headliner = html.unescape(title).strip()
                
                # Check if it's cancelled
                if "cancel" in headliner.lower():
                    continue

                source_id = str(item.get("id", ""))
                if not source_id:
                    continue

                url = item.get("url", "")
                
                cost = item.get("cost") or item.get("price")
                image_info = item.get("image")
                image_url = None
                if isinstance(image_info, dict):
                    image_url = image_info.get("url")
                elif isinstance(image_info, str):
                    image_url = image_info

                events.append(
                    RawEvent(
                        source=self.source_name,
                        source_id=source_id,
                        headliner=headliner,
                        event_date=event_date,
                        show_time=start_time_val,
                        venue="Blue Diamond",
                        ticket_url=url,
                        price=str(cost) if cost else None,
                        image_url=image_url,
                    )
                )
            except Exception as e:
                logger.warning(f"Error parsing Blue Diamond event: {e}")

        return events
