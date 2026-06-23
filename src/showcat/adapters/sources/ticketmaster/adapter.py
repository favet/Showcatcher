"""Ticketmaster Discovery API source adapter.

Fetches upcoming music events at configured Portland venues using the
Ticketmaster Discovery API v2 (/events.json with venueId filter).

Configuration (env vars):
    TICKETMASTER_API_KEY  — required
    TICKETMASTER_VENUE_IDS — comma-separated venue IDs (e.g. KovZ917A9v!,...)

Venue IDs for key Portland venues (verified via /venues.json?keyword=...&stateCode=OR):
    Crystal Ballroom            : rZ7HnEZaeyv
    Wonder Ballroom             : KovZpa9hBe
    Roseland Theater            : KovZpap9re
    Hawthorne Theatre           : KovZpZAkn7IA
    Aladdin Theater             : KovZpa3qfe
    Revolution Hall             : KovZpZAEkdIA
    Doug Fir Lounge             : KovZpZA1k1EA
    Arlene Schnitzer Concert Hall: KovZpZAEkkJA

These are stored in config, NOT hardcoded in logic.
"""
import contextlib
import logging
import os
from datetime import date, time
from typing import Any

import requests

from showcat.adapters.sources.base import BaseSourceAdapter, RawEvent
from showcat.adapters.sources.title_parser import decode_html, normalize_title

logger = logging.getLogger(__name__)

TM_BASE_URL = "https://app.ticketmaster.com/discovery/v2"

# Default Portland music venue IDs (verified) — configurable via env
DEFAULT_VENUE_IDS = ",".join([
    "rZ7HnEZaeyv",   # Crystal Ballroom
    "KovZpa9hBe",    # Wonder Ballroom
    "KovZpap9re",    # Roseland Theater
    "KovZpZAkn7IA",  # Hawthorne Theatre
    "KovZpa3qfe",    # Aladdin Theater
    "KovZpZAEkdIA",  # Revolution Hall
    "KovZpZA1k1EA",  # Doug Fir Lounge
    "KovZpZAEkkJA",  # Arlene Schnitzer Concert Hall
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

            # Time (e.g. "19:30:00")
            start_time_val: time | None = None
            time_str = dates.get("start", {}).get("localTime")
            if time_str:
                try:
                    parts = time_str.split(":")
                    start_time_val = time(int(parts[0]), int(parts[1]))
                except (ValueError, IndexError):
                    pass

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
            if artist_names:
                headliner = artist_names[0]
                openers = artist_names[1:]
            else:
                # Fallback: use the event name, decode HTML entities and normalize
                clean_name = decode_html(name)
                headliner, _norm_openers, _status = normalize_title(clean_name)
                openers = []

            # Pricing information
            price_ranges = raw.get("priceRanges", [])
            price_str = None
            if price_ranges:
                pr = price_ranges[0]
                min_val = pr.get("min")
                max_val = pr.get("max")
                curr = pr.get("currency", "USD")
                symbol = "$" if curr == "USD" else (curr + " ")
                if min_val is not None and max_val is not None:
                    if min_val == max_val:
                        price_str = f"{symbol}{min_val:.2f}"
                    else:
                        price_str = f"{symbol}{min_val:.2f} - {symbol}{max_val:.2f}"
                elif min_val is not None:
                    price_str = f"{symbol}{min_val:.2f}"

            # High-res event image URL
            images = raw.get("images", [])
            image_url = None
            if images:
                sorted_images = sorted(images, key=lambda img: img.get("width") or 0, reverse=True)
                image_url = sorted_images[0].get("url")

            # Description: TM exposes free-text "info" (the show blurb) and
            # "pleaseNote" (logistics). Prefer info; fall back to pleaseNote.
            description = None
            raw_desc = raw.get("info") or raw.get("pleaseNote")
            if raw_desc:
                cleaned = decode_html(raw_desc).strip()
                description = cleaned or None

            return RawEvent(
                source=self.source_name,
                source_id=event_id,
                headliner=headliner,
                event_date=event_date,
                show_time=start_time_val,
                venue=venue_name,
                openers=openers,
                on_sale_date=on_sale,
                ticket_url=ticket_url,
                price=price_str,
                image_url=image_url,
                description=description,
            )
        except Exception as exc:
            logger.warning(
                "Failed to parse Ticketmaster event",
                extra={"raw_id": raw.get("id"), "error": str(exc)},
            )
            return None
