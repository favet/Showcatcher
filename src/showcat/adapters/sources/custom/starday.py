import json
import logging
from datetime import datetime
from typing import Any

import requests
from bs4 import BeautifulSoup

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent

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
                    
                # Format: 2024-01-16T18:00:00-08:00
                date_part = start_str.split("T")[0]
                event_date = datetime.strptime(date_part, "%Y-%m-%d").date()
                
                # Filter out past events early? We can just pass them, snapshot stage handles it
                
                source_id = str(item.get("id", ""))
                event_url = item.get("url", url)
                
                events.append(
                    RawEvent(
                        source=self.source_name,
                        source_id=source_id,
                        headliner=title,
                        event_date=event_date,
                        venue="Starday Tavern",
                        ticket_url=event_url,
                    )
                )
            except Exception as e:
                logger.warning(f"Error parsing Starday Tavern event: {e}")

        return events
