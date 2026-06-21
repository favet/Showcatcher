"""Ticketmaster Discovery API source adapter.

Fetches upcoming music events at configured Portland venues using the
Ticketmaster Discovery API v2 (/events.json with venueId filter).

Configuration (env vars):
    TICKETMASTER_API_KEY  — required
    TICKETMASTER_VENUE_IDS — comma-separated venue IDs (e.g. KovZ917A9v!,...)

Venue IDs for key Portland venues (look up via /venues.json?city=Portland&stateCode=OR):
    Crystal Ballroom  : KovZ917A9v!
    Hawthorne Theatre : KovZpZAEdkaA
    Wonder Ballroom   : KovZpZAEd1aA
    Roseland Theater  : KovZpZAEkdaA
    McMenamins (Crystal) same as Crystal Ballroom above

These are stored in config, NOT hardcoded in logic.
"""
import contextlib
import logging
import os
from datetime import date
from typing import Any

import requests

from opener.adapters.sources.base import BaseSourceAdapter, RawEvent

logger = logging.getLogger(__name__)

TM_BASE_URL = "https://app.ticketmaster.com/discovery/v2"

# Default Portland music venue IDs — configurable via env
DEFAULT_VENUE_IDS = ",".join([
    "KovZ917A9v!",   # Crystal Ballroom
    "KovZpZAEdkaA",  # Hawthorne Theatre
    "KovZpZAEd1aA",  # Wonder Ballroom
    "KovZpZAEkdaA",  # Roseland Theater
])


class TicketmasterAdapter(BaseSourceAdapter):
    """Fetch upcoming Portland shows from Ticketmaster Discovery API."""

    @property
    def source_name(self) -> str:
        return "ticketmaster"

    def fetch(self) -> list[RawEvent]:
        api_key = os.environ.get("TICKETMASTER_API_KEY", "")
        if not api_key:
            raise RuntimeError("TICKETMASTER_API_KEY must be set")

        venue_ids = os.environ.get("TICKETMASTER_VENUE_IDS", DEFAULT_VENUE_IDS)
        events: list[RawEvent] = []

        # Ticketmaster paginates — fetch all pages
        page = 0
        while True:
            params: dict[str, Any] = {
                "apikey": api_key,
                "venueId": venue_ids,
                "classificationName": "music",
                "size": 50,
                "page": page,
                "sort": "date,asc",
            }
            response = requests.get(
                f"{TM_BASE_URL}/events.json",
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            embedded = data.get("_embedded", {})
            raw_events = embedded.get("events", [])

            for raw in raw_events:
                parsed = self._parse_event(raw)
                if parsed:
                    events.append(parsed)

            page_info = data.get("page", {})
            total_pages = page_info.get("totalPages", 1)
            if page >= total_pages - 1:
                break
            page += 1

        logger.info(
            "Ticketmaster fetch complete",
            extra={"source": self.source_name, "event_count": len(events)},
        )
        return events

    def _parse_event(self, raw: dict[str, Any]) -> RawEvent | None:
        """Parse one Ticketmaster event JSON object into a RawEvent."""
        try:
            event_id = raw.get("id", "")
            name = raw.get("name", "").strip()
            ticket_url = raw.get("url")

            # Date
            dates = raw.get("dates", {})
            start_str = dates.get("start", {}).get("localDate")
            if not start_str or not name or not event_id:
                return None
            event_date = date.fromisoformat(start_str)

            # On-sale date
            on_sale_str = (
                dates.get("sales", {}).get("public", {}).get("startDateTime", "")[:10]
            )
            on_sale: date | None = None
            with contextlib.suppress(ValueError):
                on_sale = date.fromisoformat(on_sale_str)

            # Venue name
            venues = raw.get("_embedded", {}).get("venues", [])
            venue_name = venues[0].get("name", "Unknown Venue") if venues else "Unknown Venue"

            # Headliner + openers via attractions
            attractions = raw.get("_embedded", {}).get("attractions", [])
            artist_names = [a.get("name", "").strip() for a in attractions if a.get("name")]
            headliner = artist_names[0] if artist_names else name
            openers = artist_names[1:] if len(artist_names) > 1 else []

            return RawEvent(
                source=self.source_name,
                source_id=event_id,
                headliner=headliner,
                event_date=event_date,
                venue=venue_name,
                openers=openers,
                on_sale_date=on_sale,
                ticket_url=ticket_url,
            )
        except Exception as exc:
            logger.warning(
                "Failed to parse Ticketmaster event",
                extra={"raw_id": raw.get("id"), "error": str(exc)},
            )
            return None
