import re
import logging
from datetime import datetime, date
from typing import Any

import requests
from bs4 import BeautifulSoup

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent

logger = logging.getLogger(__name__)

class KentonClubAdapter(BaseSourceAdapter):
    """Adapter for Kenton Club, parsing plain text DOM."""

    @property
    def source_name(self) -> str:
        return "kenton_club"

    def fetch(self) -> list[RawEvent]:
        events: list[RawEvent] = []
        url = "https://www.kentonclub.com/"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            html_content = resp.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch Kenton Club events: {e}")
            raise
            
        soup = BeautifulSoup(html_content, "html.parser")
        lines = soup.get_text('\n', strip=True).splitlines()
        
        # Matches e.g. "Friday May 15", "Sunday May 17 (3PM)", "Friday June 5"
        date_pat = re.compile(r'^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:\s*\(.*?\))?$', re.IGNORECASE)
        
        current_date = None
        current_bands = []
        
        def save_event():
            if current_date and current_bands:
                # Bands might be joined by hyphen or just listed
                # e.g. Naked Mole Rats-DJ Dentside Honky Tonk-Just Clark
                for band_line in current_bands:
                    if band_line.lower() == "sold out":
                        continue
                        
                    parts = [p.strip() for p in band_line.replace("-", "|").split("|")]
                    headliner = parts[0]
                    openers = parts[1:] if len(parts) > 1 else []
                    
                    if headliner:
                        # Construct source_id
                        source_id = f"{current_date.strftime('%Y-%m-%d')}-{headliner[:10].replace(' ', '').lower()}"
                        
                        events.append(
                            RawEvent(
                                source=self.source_name,
                                source_id=source_id,
                                headliner=headliner,
                                openers=openers,
                                event_date=current_date,
                                venue="World Famous Kenton Club",
                                ticket_url=url,
                            )
                        )
        
        year = date.today().year
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            match = date_pat.match(line)
            if match:
                # Save previous
                save_event()
                
                month_str = match.group(1)
                day_str = match.group(2)
                
                # Try to parse date
                try:
                    dt = datetime.strptime(f"{year} {month_str} {day_str}", "%Y %B %d").date()
                    # If the parsed date is more than 3 months in the past, it's probably next year
                    # (e.g. looking at Jan events in Dec)
                    if (date.today() - dt).days > 90:
                        dt = datetime.strptime(f"{year+1} {month_str} {day_str}", "%Y %B %d").date()
                    current_date = dt
                    current_bands = []
                except ValueError:
                    current_date = None
            elif current_date:
                # If we hit a known stopping point
                if line.lower() in ("home", "contact", "menu"):
                    save_event()
                    current_date = None
                elif not re.match(r'^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)', line, re.IGNORECASE):
                    current_bands.append(line)
                
        # save the last one
        save_event()

        return events
