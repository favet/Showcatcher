import logging
from datetime import datetime, date
from typing import Any

import requests

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent

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
                    
                # We only need the date part
                event_date = datetime.strptime(start_str.split(" ")[0], "%Y-%m-%d").date()
                
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
                
                events.append(
                    RawEvent(
                        source=self.source_name,
                        source_id=source_id,
                        headliner=headliner,
                        event_date=event_date,
                        venue="Blue Diamond",
                        ticket_url=url,
                    )
                )
            except Exception as e:
                logger.warning(f"Error parsing Blue Diamond event: {e}")

        return events
