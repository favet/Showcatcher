"""Ticket-link provider classification and link preference.

Phase 8 goal: prefer venue-direct / non-Ticketmaster ticket links. Ticketmaster
is kept as a discovery source, but its purchase URL is only shown when nothing
better exists. This module is the single source of truth for:

  - classify_provider(url): which ticketing platform a URL points at.
  - PROVIDER_RANK: preference ordering (higher = preferred).
  - best_link(urls): pick the most-preferred URL among candidates.
  - provider_label(provider): human label for the UI badge.

Pure and offline — unit-tested without network or DB.
"""
from urllib.parse import urlparse

# Domain fragments → provider key. Checked as substrings of the host.
_DOMAIN_PROVIDERS: list[tuple[str, str]] = [
    ("ticketmaster.", "ticketmaster"),
    ("livenation.", "ticketmaster"),
    ("etix.com", "etix"),
    ("dice.fm", "dice"),
    ("eventbrite.", "eventbrite"),
    ("ticketweb.", "ticketweb"),
    ("tixr.com", "tixr"),
    ("seetickets.", "seetickets"),
    ("axs.com", "axs"),
    ("ticketleap.", "ticketleap"),
    ("eventbrite.ca", "eventbrite"),
    ("songkick.", "songkick"),
    ("bandsintown.", "bandsintown"),
    ("seated.com", "seated"),
    ("showclix.", "showclix"),
    ("ticketfairy.", "ticketfairy"),
    ("simpletix.", "simpletix"),
    ("eventcreate.", "eventcreate"),
    ("withfriends.", "withfriends"),
    ("audienceview.", "audienceview"),
    ("portland5.org", "portland5"),
]

# Platforms that are non-TM, event-specific ticketers. All share the top tier.
_TICKETER_PROVIDERS = {
    "etix", "dice", "eventbrite", "ticketweb", "tixr", "seetickets", "axs",
    "ticketleap", "showclix", "ticketfairy", "simpletix", "seated",
    "audienceview", "portland5",
}

# Preference ranking — higher is preferred. Named non-TM ticketers win; a
# venue's own site beats Ticketmaster (an "internal site" per project policy);
# Ticketmaster is last-resort; unknown/none lowest.
_TICKETER_RANK = 100
PROVIDER_RANK: dict[str, int] = {
    **dict.fromkeys(_TICKETER_PROVIDERS, _TICKETER_RANK),
    "venue": 60,
    "ticketmaster": 20,
    "unknown": 10,
    "none": 0,
}

_LABELS: dict[str, str] = {
    "etix": "Etix",
    "dice": "Dice",
    "eventbrite": "Eventbrite",
    "ticketweb": "TicketWeb",
    "tixr": "Tixr",
    "seetickets": "See Tickets",
    "axs": "AXS",
    "ticketleap": "TicketLeap",
    "showclix": "ShowClix",
    "ticketfairy": "Ticket Fairy",
    "simpletix": "SimpleTix",
    "seated": "Seated",
    "audienceview": "AudienceView",
    "portland5": "Portland'5",
    "songkick": "Songkick",
    "bandsintown": "Bandsintown",
    "venue": "Venue",
    "ticketmaster": "Ticketmaster",
    "unknown": "Tickets",
    "none": "Tickets",
}


def classify_provider(url: str | None) -> str:
    """Return the provider key for a ticket URL.

    Known ticketers map to their key; any other resolvable host is "venue"
    (the venue's own site — still an internal, non-TM link); empty/garbage is
    "none".
    """
    if not url:
        return "none"
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return "none"
    for fragment, provider in _DOMAIN_PROVIDERS:
        if fragment in host:
            return provider
    # A real host we don't recognise = the venue's own ticketing/listing site.
    return "venue"


def rank_of(provider: str) -> int:
    """Preference rank for a provider key (higher = preferred)."""
    return PROVIDER_RANK.get(provider, PROVIDER_RANK["unknown"])


def provider_label(provider: str | None) -> str:
    """Human label for the UI ticket badge."""
    if not provider:
        return _LABELS["none"]
    return _LABELS.get(provider, "Tickets")


def best_link(urls: list[str | None]) -> tuple[str | None, str]:
    """Pick the most-preferred ticket URL among candidates.

    Returns (url, provider). Ties keep the first candidate (stable). If no
    candidate has a usable URL, returns (None, "none").
    """
    best_url: str | None = None
    best_provider = "none"
    best_rank = -1
    for url in urls:
        provider = classify_provider(url)
        if provider == "none":
            continue
        r = rank_of(provider)
        if r > best_rank:
            best_rank = r
            best_url = url
            best_provider = provider
    return best_url, best_provider
