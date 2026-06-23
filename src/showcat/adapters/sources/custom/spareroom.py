import logging
import re
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.custom.time_utils import extract_doors_show_times
from showcat.adapters.sources.title_parser import is_non_show, normalize_title

logger = logging.getLogger(__name__)

class SpareRoomAdapter(BaseSourceAdapter):
    """Adapter for The Spare Room, parsing Weebly div.paragraph events."""

    @property
    def source_name(self) -> str:
        return "spare_room"

    def fetch(self) -> list[RawEvent]:
        events: list[RawEvent] = []
        url = "https://spareroomrestaurantandlounge.com/music-calendar.html"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            html_content = resp.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch Spare Room events: {e}")
            raise

        soup = BeautifulSoup(html_content, "html.parser")

        date_pat = re.compile(
            r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s*'
            r'(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*'
            r'(\d{1,2})(?:st|nd|rd|th)?',
            re.IGNORECASE
        )

        # Weebly text can have random zero-width spaces (\u200b)
        for el in soup.find_all("div", class_="paragraph"):
            text = el.get_text('\n', strip=True).replace('\u200b', '')
            if not text:
                continue

            lines = text.split('\n')

            # Find the date line
            event_date = None
            year = date.today().year

            for line in lines:
                match = date_pat.search(line)
                if match:
                    # Parse the matched date
                    date_str = match.group(0).replace('st','').replace('nd','').replace('rd','').replace('th','')
                    # "Fri June 19", "Sat June 20"
                    # clean up spacing: 'Fri June19' -> 'Fri June 19'
                    # Actually just extract the month and day using another simple regex
                    md_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*(\d{1,2})', date_str, re.IGNORECASE)
                    if md_match:
                        month = md_match.group(1)[:3]
                        day = md_match.group(2)
                        try:
                            dt = datetime.strptime(f"{year} {month} {day}", "%Y %b %d").date()
                            if (date.today() - dt).days > 90:
                                dt = datetime.strptime(f"{year+1} {month} {day}", "%Y %b %d").date()
                            event_date = dt
                        except ValueError:
                            pass
                    break

            if not event_date:
                continue

            # Filter recurring that aren't specific shows
            lower_text = text.lower()
            if "every thursday" in lower_text or "every monday" in lower_text or "jam session" in lower_text:
                continue

            headliner = lines[0].strip()

            if "KARAOKE" in headliner.upper() or "BINGO" in headliner.upper():
                continue

            # Parse doors and show times from the full text block.
            doors_time_val, show_time_val = extract_doors_show_times(text)

            openers = []
            for line in lines[1:]:
                if line.lower().startswith('w/') or line.lower().startswith('with '):
                    # split openers by &
                    opener_str = line[2:].strip()
                    if opener_str:
                        openers = [o.strip() for o in opener_str.split('&') if o.strip()]

            # Try to find a price in the text block (e.g., "$10" or "Cover: $10")
            price_match = re.search(r'\$\d+(?:\.\d{2})?', text)
            price_str = price_match.group(0) if price_match else None

            if headliner:
                source_id = f"{event_date.strftime('%Y-%m-%d')}-{headliner[:10].replace(' ', '').lower()}"

                headliner, _, status = normalize_title(headliner)
                events.append(
                    RawEvent(
                        source=self.source_name,
                        source_id=source_id,
                        headliner=headliner,
                        openers=openers,
                        event_date=event_date,
                        doors_time=doors_time_val,
                        show_time=show_time_val,
                        venue="The Spare Room",
                        ticket_url=url,
                        price=price_str,
                        sold_out=(status == "sold_out"),
                    )
                )

        return events
