import json
import logging
from datetime import datetime, time
from typing import Any

import requests
from bs4 import BeautifulSoup

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.title_parser import is_non_show, normalize_title

logger = logging.getLogger(__name__)

class LaurelThirstAdapter(BaseSourceAdapter):
    """Adapter for LaurelThirst Public House, parsing EventON JSON-LD from HTML."""

    @property
    def source_name(self) -> str:
        return "laurelthirst"

    def fetch(self) -> list[RawEvent]:
        events: list[RawEvent] = []
        url = "https://laurelthirst.com/"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            html = resp.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch LaurelThirst events: {e}")
            raise
            
        soup = BeautifulSoup(html, "html.parser")
        
        for event_div in soup.find_all("div", class_="eventon_list_event"):
            try:
                # Find the JSON-LD script block
                script_tag = event_div.find("script", type="application/ld+json")
                if not script_tag:
                    continue
                    
                data = json.loads(script_tag.string)
                
                title = data.get("name", "").strip()
                if not title or "CLOSED" in title.upper():
                    continue
                    
                # The start date format is like "2026-6-21T13:00-7:00"
                # We can just extract the YYYY-MM-DD part
                start_str = data.get("startDate", "")
                if not start_str:
                    continue
                    
                date_part = start_str.split("T")[0]
                # Parse time from the T portion (e.g. "13:00-7:00")
                start_time_val: time | None = None
                if "T" in start_str:
                    try:
                        time_portion = start_str.split("T")[1]
                        # Strip timezone offset (e.g. "-7:00")
                        time_clean = time_portion.split("-")[0].split("+")[0]
                        t_parts = time_clean.split(":")
                        start_time_val = time(int(t_parts[0]), int(t_parts[1]))
                    except (ValueError, IndexError):
                        pass
                
                # Sometimes it's 2026-6-21 instead of 2026-06-21
                parts = date_part.split("-")
                if len(parts) == 3:
                    y, m, d = parts
                    date_part = f"{y}-{int(m):02d}-{int(d):02d}"
                
                event_date = datetime.strptime(date_part, "%Y-%m-%d").date()
                source_id = data.get("@id", event_div.get("id", ""))
                event_url = data.get("url", url)
                
                import html as pyhtml
                headliner = pyhtml.unescape(title).strip()
                
                image_url = data.get("image")
                offers = data.get("offers", {})
                price_str = None
                if isinstance(offers, dict):
                    val = offers.get("price") or offers.get("lowPrice")
                    if val is not None:
                        price_str = str(val).strip()
                elif isinstance(offers, list) and len(offers) > 0:
                    val = offers[0].get("price")
                    if val is not None:
                        price_str = str(val).strip()

                headliner, _, status = normalize_title(headliner)
                events.append(
                    RawEvent(
                        source=self.source_name,
                        source_id=source_id,
                        headliner=headliner,
                        event_date=event_date,
                        show_time=start_time_val,
                        venue="LaurelThirst Public House",
                        ticket_url=event_url,
                        price=price_str or None,
                        image_url=image_url or None,
                        sold_out=(status == "sold_out"),
                    )
                )
            except Exception as e:
                logger.warning(f"Error parsing LaurelThirst event: {e}")

        return events
