"""Static HTML generator for showcat.favet.net."""
import datetime as dt
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from showcat.adapters.sources.title_parser import is_non_show
from showcat.adapters.tickets.providers import _TM_FAMILY, best_link, classify_provider, provider_label
from showcat.core.travel import (
    departure_bucket,
    get_eta_travel_times,
    get_travel_times,
    lookup_travel,
    normalize_venue_name,
)
from showcat.ingest.events.models import Event
from showcat.ingest.history.models import Artist, ArtistTag
from showcat.outputs.base import BaseOutputAdapter
from showcat.resolve.matcher import normalize
from showcat.resolve.models import EventMatch
from showcat.score.models import EventScore

logger = logging.getLogger(__name__)

# Catcat mascot — favicon + default show-image fallback. Shipped as a package
# asset (base64 of Media/catcat.png) so it deploys with the web output.
_CATCAT_B64 = (Path(__file__).parent / "catcat_b64.txt").read_text(encoding="utf-8").strip()
CATCAT_DATA_URI = f"data:image/png;base64,{_CATCAT_B64}"

# TM returns slightly different venue name strings; normalize before any logic.
VENUE_CANONICAL: dict[str, str] = {
    "revolution hall - portland": "Revolution Hall",
    # Edgefield's amphitheater shows come from Ticketmaster as "…Manor" and from
    # the venue scraper as "Edgefield Amphitheater" — same place. Unify both so
    # the cross-source merge collapses the duplicate (TM + venue-direct) rows.
    "mcmenamins historic edgefield manor": "Edgefield Amphitheater",
    "mcmenamins edgefield amphitheatre": "Edgefield Amphitheater",
    "the get down music venue": "The Get Down",
}

# Capacity tier for modal grouping: lower-cased partial match.
VENUE_SIZE: dict[str, str] = {
    "moda center": "large",
    "veterans memorial coliseum": "large",
    "arlene schnitzer": "large",
    "keller auditorium": "large",
    "edgefield amphitheater": "large",
    "mcmenamins edgefield": "large",
    "roseland theater": "large",
    "crystal ballroom": "large",
    "newmark theatre": "large",
    "revolution hall": "mid",
    "wonder ballroom": "mid",
    "hawthorne theatre": "mid",
    "aladdin theater": "mid",
    "star theater": "mid",
    "lola's room": "mid",
    "dante's": "mid",
    "polaris hall": "mid",
    "bossanova": "mid",
    "alberta rose": "mid",
    "mississippi studios": "small",
    "holocene": "small",
    "white eagle": "small",
    "al's den": "small",
    "show bar": "small",
    "jack london": "small",
    "the get down": "small",
    "blue diamond": "small",
    "laurelthirst": "small",
    "kenton club": "small",
    "starday tavern": "small",
    "no fun bar": "small",
    "spare room": "small",
    "blackberry hall": "small",
    "kelly's olympian": "small",
}


def canonicalize_venue(name: str) -> str:
    return VENUE_CANONICAL.get(name.lower().strip(), name)


def get_venue_size(name: str) -> str:
    n = name.lower()
    for key, size in VENUE_SIZE.items():
        if key in n:
            return size
    return "mid"


_EVENING_PREFIX_RE = re.compile(
    r"^an?\s+(?:intimate\s+|acoustic\s+|enchanted\s+|special\s+)?evening\s+with\s+", re.I
)


def core_headliner(headliner: str) -> str:
    """Reduce a headliner to its core artist for duplicate detection.

    Collapses the title decorations that make the same show look different across
    sources: an "An Evening with X" framing, a co-bill/support act after "&", and
    a ": Tour Name" subtitle. Used only for the merge key, never for display.
    Per the domain rule that a music act never plays the same venue twice in one
    day, this errs toward merging.
    """
    h = _EVENING_PREFIX_RE.sub("", headliner)
    h = re.split(r"\s*[:&]\s*", h, maxsplit=1)[0]
    return normalize(h)


def canonical_show_key(venue: str, date_iso: str, headliner: str) -> tuple[str, str, str]:
    return (
        normalize(normalize_venue_name(canonicalize_venue(venue))),
        date_iso,
        core_headliner(headliner),
    )


def merge_shows_by_identity(raw_shows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    order: list[tuple[str, str, str]] = []
    for show in raw_shows:
        key = canonical_show_key(show["venue"], show["date"], show["headliner"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(show)

    merged: list[dict[str, Any]] = []
    for key in order:
        members = groups[key]
        rep = max(members, key=lambda s: (s.get("score_total") is not None, s.get("score_total") or -1))
        url, provider = best_link([m.get("ticket_url") for m in members])
        rep = dict(rep)
        rep["ticket_url"] = url
        rep["ticket_provider"] = provider
        rep["ticket_provider_label"] = provider_label(provider)

        # Price precedence: select custom scraper price (source != 'ticketmaster') first, fallback to TM
        price = None
        for m in members:
            if m.get("source") != "ticketmaster" and m.get("price"):
                price = m["price"]
                break
        if not price:
            for m in members:
                if m.get("source") == "ticketmaster" and m.get("price"):
                    price = m["price"]
                    break
        rep["price"] = price

        # All TM-family links are placeholders: they go to an aggregator page,
        # not direct purchase. Style them muted so venue-direct (Etix) wins visually.
        rep["is_placeholder_link"] = provider in _TM_FAMILY

        # Merge event image
        event_image_url = None
        for m in members:
            if m.get("event_image_url"):
                event_image_url = m["event_image_url"]
                break
        rep["event_image_url"] = event_image_url

        # Merge openers
        openers = []
        for m in members:
            if m.get("openers"):
                openers = m["openers"]
                break
        rep["openers"] = openers

        # Merge event_spotify_url (prefer any member that has one)
        event_spotify_url = None
        for m in members:
            if m.get("event_spotify_url"):
                event_spotify_url = m["event_spotify_url"]
                break
        rep["event_spotify_url"] = event_spotify_url

        merged.append(rep)
    return merged




def _query_shows(session: Session, scoring_version: str, limit: int = 2000) -> list[dict[str, Any]]:
    today = dt.date.today()
    rows = (
        session.execute(
            select(Event, EventScore, EventMatch, Artist)
            .outerjoin(EventScore, (EventScore.event_id == Event.id) & (EventScore.scoring_version == scoring_version))
            .outerjoin(EventMatch, (EventMatch.event_id == Event.id) & (EventMatch.status == "matched"))
            .outerjoin(Artist, Artist.id == EventMatch.artist_id)
            .where(Event.date >= today)
            .order_by(EventScore.score_total.desc().nulls_last(), Event.date.asc())
        )
        .unique()
        .all()
    )

    travel_times = get_travel_times()
    # Time-of-day drive times (one map per traffic bucket); falls back to base.
    eta_by_bucket = get_eta_travel_times()

    artist_ids = [row[3].id for row in rows if row[3] is not None]
    tags_by_artist: dict[int, list[str]] = {}
    if artist_ids:
        tags_rows = session.execute(
            select(ArtistTag).where(ArtistTag.artist_id.in_(artist_ids))
        ).scalars().all()
        for t in tags_rows:
            tags_by_artist.setdefault(t.artist_id, []).append((t.tag, t.weight))  # type: ignore[arg-type]
        for aid in tags_by_artist:
            tags_by_artist[aid] = [
                tag for tag, _ in sorted(tags_by_artist[aid], key=lambda x: x[1], reverse=True)[:6]  # type: ignore[index]
            ]

    def fmt_time(t: dt.time) -> str:
        h, m = t.hour, t.minute
        ampm = "AM" if h < 12 else "PM"
        h12 = h if h <= 12 else h - 12
        if h12 == 0:
            h12 = 12
        return f"{h12}:{m:02d} {ampm}"

    seen: set[int] = set()
    shows: list[dict[str, Any]] = []

    for event, score, _match, artist in rows:
        if event.id in seen:
            continue
        if is_non_show(event.headliner):
            continue
        seen.add(event.id)

        venue = canonicalize_venue(event.venue)

        genres = tags_by_artist.get(artist.id, []) if artist else []

        # Time fallback logic:
        # If doors_time is missing, default to show_time - 1h.
        # If show_time is missing, default to doors_time + 1h.
        doors_time = event.doors_time
        show_time = event.show_time
        if doors_time is None and show_time is not None:
            dt_show = dt.datetime.combine(event.date, show_time)
            dt_doors = dt_show - dt.timedelta(hours=1)
            doors_time = dt_doors.time()
        elif show_time is None and doors_time is not None:
            dt_doors = dt.datetime.combine(event.date, doors_time)
            dt_show = dt_doors + dt.timedelta(hours=1)
            show_time = dt_show.time()

        doors_display = fmt_time(doors_time) if doors_time else None
        show_display = fmt_time(show_time) if show_time else None

        # Drive time for THIS show's traffic bucket (time-of-day), from eta_matrix
        # with a base-time fallback baked into each bucket map.
        bucket = departure_bucket(event.date, show_time)
        travel_info = lookup_travel(venue, eta_by_bucket.get(bucket, travel_times))

        # Untimed shows default to 8pm (a typical showtime), NOT midnight — a
        # midnight default made today's untimed shows compute a "past" timestamp,
        # greying them and sorting them to the top of the feed.
        time_known = show_time is not None or doors_time is not None
        sort_time = show_time or doors_time or dt.time(20, 0)
        timestamp = int(dt.datetime.combine(event.date, sort_time).timestamp())

        if event.date == today:
            date_display = "TONIGHT"
        elif event.date == today + dt.timedelta(days=1):
            date_display = "TOMORROW"
        else:
            date_display = f"{event.date.strftime('%a %b')} {event.date.day}"

        # Score: normalize to 0-100 integer, null when no score.
        score_int: int | None = None
        if score is not None:
            score_int = min(100, round(score.score_total * 100))

        ticket_provider = event.ticket_provider or classify_provider(event.ticket_url)

        shows.append({
            "id": event.id,
            "headliner": event.headliner,
            "openers": event.openers or [],
            "venue": venue,
            "venue_size": get_venue_size(venue),
            "date": event.date.isoformat(),
            "date_display": date_display,
            "doors_display": doors_display,
            "show_display": show_display,
            "ticket_url": event.ticket_url,
            "ticket_provider": ticket_provider,
            "ticket_provider_label": provider_label(ticket_provider),
            "is_placeholder_link": False,
            "price": event.price,
            "event_image_url": event.image_url,
            "spotify_artist_image_url": artist.image_url if artist else None,
            "spotify_album_image_url": artist.album_image_url if artist else None,
            "spotify_url": artist.spotify_url if artist else None,
            "event_spotify_url": (
                event.event_spotify_url
                if event.event_spotify_url and event.event_spotify_url != "none"
                else None
            ),
            "album_name": artist.album_name if artist else None,
            "score_total": score_int,
            "matched_artist": artist.raw_name if artist else None,
            "travel_minutes": travel_info["minutes"] if travel_info else None,
            "genres": genres,
            "description": event.description,
            "source": event.source,
            "timestamp": timestamp,
            "time_known": time_known,
            "bucket": bucket,
        })

    merged = merge_shows_by_identity(shows)
    return merged[:limit]


def render_html(shows: list[dict[str, Any]], generated_at: dt.datetime) -> str:
    shows_json = json.dumps(shows, ensure_ascii=False)
    ts = generated_at.strftime("%b %d, %Y")
    spotify_id = os.environ.get("SPOTIFY_PLAYLIST_ID", "")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0">
  <title>Showcat — Portland Shows</title>
  <meta name="description" content="Every upcoming Portland show, ranked by your taste.">
  <meta http-equiv="Content-Security-Policy" content="upgrade-insecure-requests">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <link rel="icon" type="image/png" href="{CATCAT_DATA_URI}">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,400;0,500;0,600;0,700;1,400&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
  <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
  <style>
    :root {{
      --bg:           #0c0b15;
      --surface:      #141220;
      --surface-2:    #1e1b2e;
      --text:         #ede8f4;
      --muted:        #a195c1;
      --border:       #2a2445;
      --accent:       #a78bfa;
      --accent-dim:   rgba(167,139,250,0.12);
      --score-hi:     #a78bfa;
      --score-mid:    #7c6cc0;
      --score-lo:     #3d3660;
      --tonight:      #f472b6;
      --font:         'Inter', system-ui, sans-serif;
      --mono:         'IBM Plex Mono', 'Courier New', monospace;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }}
    html {{ font-size: 16px; scroll-behavior: smooth; }}
    body {{ background: var(--bg); color: var(--text); font-family: var(--font); line-height: 1.4; -webkit-font-smoothing: antialiased; }}
    a {{ color: inherit; text-decoration: none; }}
    button {{ font-family: var(--font); cursor: pointer; border: none; background: none; }}

    /* ── Header ─────────────────────────────── */
    .site-header {{
      background: rgba(14, 12, 10, 0.95);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--border);
      position: sticky; top: 0; z-index: 20;
      width: 100%;
    }}
    .header-inner {{
      max-width: 720px;
      margin: 0 auto;
      padding: 1rem 1.25rem 0.5rem;
      /* No height transition: the collapse is instant so the header's real
         height always equals the measured --header-h (an animated height would
         drift from --header-h mid-transition and open a variable gap). */
    }}
    /* Collapsed (scrolled) header keeps the tools you actually use while
       browsing — search + filters — and drops only the brand/stats and the
       sort row. A slim, complete toolbar rather than a half-measure. */
    .site-header.compact .brand-row,
    .site-header.compact .health-stats,
    .site-header.compact .sort-row {{ display: none; }}
    .site-header.compact .header-inner {{ padding-top: 0.55rem; padding-bottom: 0.2rem; }}
    .site-header.compact .search-row {{ margin-bottom: 0.5rem; }}
    .site-header.compact .filter-row {{ padding-bottom: 0.35rem; }}
    .brand-row {{
      display: flex; align-items: baseline; justify-content: space-between;
      margin-bottom: 0.6rem;
    }}
    .brand {{ font-size: 1.4rem; font-weight: 800; letter-spacing: -0.03em; }}
    .brand-logo {{
      background: linear-gradient(90deg, #a78bfa 0%, #e879f9 55%, #f472b6 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }}
    .brand-meta {{ font-family: var(--mono); font-size: 0.7rem; color: var(--muted); }}
    .brand-meta strong {{ color: var(--text); }}
    
    .header-tools {{
      display: flex; align-items: center; gap: 0.8rem;
      position: relative; margin-left: auto;
    }}
    .tool-btn {{
      font-family: var(--mono); font-size: 0.66rem; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.04em;
      padding: 0.3rem 0.6rem; border-radius: 6px; cursor: pointer;
      background: transparent; border: 1px solid var(--border); color: var(--muted);
      transition: color 0.15s, border-color 0.15s;
    }}
    .tool-btn:hover, .tool-btn.active {{ color: var(--text); border-color: var(--muted); }}
    .vial-btn.active {{ color: var(--accent); border-color: var(--accent); }}
    
    .vial-popover {{
      position: absolute; top: 100%; right: 0; margin-top: 0.65rem;
      background: var(--surface); border: 1px solid var(--border);
      padding: 1.25rem; border-radius: 12px;
      box-shadow: 0 8px 30px rgba(0,0,0,0.6), 0 0 20px rgba(167, 139, 250, 0.1);
      z-index: 100; min-width: 320px; cursor: default;
    }}
    .vial-popover::before {{
      content: ''; position: absolute; top: -6px; right: 2rem;
      width: 10px; height: 10px; background: var(--surface);
      border-top: 1px solid var(--border); border-left: 1px solid var(--border);
      transform: rotate(45deg);
    }}
    .vial-popover .health-stats {{
      margin-bottom: 0; flex-direction: column; gap: 0.8rem;
    }}
    
    /* Health metrics — progress bars */
    .health-stats {{
      display: flex; gap: 0.75rem; margin-bottom: 0.85rem;
      font-family: var(--mono); font-size: 0.6rem; text-transform: uppercase;
      letter-spacing: 0.05em; color: var(--muted);
    }}
    .hs-col {{ flex: 1; display: flex; flex-direction: column; gap: 0.3rem; }}
    .hs-label {{ display: flex; justify-content: space-between; align-items: baseline; }}
    .hs-v {{ font-size: 0.7rem; font-weight: 700; font-feature-settings: 'tnum'; }}
    .hs-bar-bg {{ width: 100%; height: 4px; background: rgba(255,255,255,0.06); border-radius: 2px; overflow: hidden; }}
    .hs-bar-fill {{ height: 100%; border-radius: 2px; transition: width 0.5s ease-out; }}
    .hs-taste .hs-bar-fill {{ background: var(--accent); }}
    .hs-linked .hs-bar-fill {{ background: #34d399; }}
    .hs-priced .hs-bar-fill {{ background: #fbbf24; }}
    .hs-pictured .hs-bar-fill {{ background: #f472b6; }}
    .hs-located .hs-bar-fill {{ background: #60a5fa; }}

    /* Search bar */
    .search-row {{
      position: relative;
      margin-bottom: 0.75rem;
    }}
    .search-input {{
      width: 100%;
      padding: 0.6rem 2.2rem 0.6rem 1rem;
      font-size: 0.85rem;
      font-family: var(--font);
      background: rgba(255, 255, 255, 0.04);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 7px;
      outline: none;
      transition: border-color 0.15s ease;
    }}
    .search-input:focus {{
      background: rgba(255, 255, 255, 0.05);
      border-color: rgba(167, 139, 250, 0.4);
    }}
    .clear-search {{
      position: absolute;
      right: 0.75rem;
      top: 50%;
      transform: translateY(-50%);
      background: none;
      border: none;
      color: var(--muted);
      font-size: 1.1rem;
      cursor: pointer;
      line-height: 1;
      padding: 0.2rem;
    }}
    .clear-search:hover {{
      color: var(--text);
    }}

    /* Search autocomplete dropdown */
    .search-suggest {{
      position: absolute; top: calc(100% + 4px); left: 0; right: 0; z-index: 30;
      background: var(--surface-2); border: 1px solid var(--border); border-radius: 9px;
      overflow: hidden; box-shadow: 0 16px 40px rgba(0,0,0,0.45);
    }}
    .suggest-item {{
      display: flex; align-items: center; gap: 0.55rem; width: 100%;
      padding: 0.55rem 0.8rem; text-align: left; background: transparent;
      border: none; border-bottom: 1px solid var(--border); color: var(--text);
      font-size: 0.85rem; cursor: pointer;
    }}
    .suggest-item:last-child {{ border-bottom: none; }}
    .suggest-item:hover {{ background: var(--accent-dim); }}
    .suggest-kind {{
      font-family: var(--mono); font-size: 0.58rem; text-transform: uppercase;
      letter-spacing: 0.05em; padding: 0.12rem 0.4rem; border-radius: 4px; flex-shrink: 0;
      border: 1px solid var(--border); color: var(--muted);
    }}
    .suggest-kind.venue {{ color: #60a5fa; border-color: rgba(96,165,250,0.4); }}
    .suggest-kind.artist {{ color: var(--accent); border-color: rgba(167,139,250,0.4); }}
    .suggest-label {{ flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .suggest-count {{ font-family: var(--mono); font-size: 0.65rem; color: var(--muted); }}

    /* Card date (shown when ranked by Last.fm, where there are no day headers) */
    .card-date {{ font-family: var(--mono); font-size: 0.66rem; font-weight: 600; color: var(--accent); }}
    .price-chip {{ font-family: var(--mono); font-size: 0.68rem; color: #fbbf24; opacity: 0.9; }}
    .travel-custom {{ color: #f472b6 !important; }}

    /* Custom-location settings + banner */
    .settings-eta-actions {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem; }}
    .settings-ghost-btn {{
      padding: 0.5rem 0.8rem; border-radius: 7px; font-size: 0.8rem; cursor: pointer;
      background: transparent; border: 1px solid var(--border); color: var(--text);
    }}
    .settings-ghost-btn:hover {{ border-color: var(--muted); }}
    .settings-status {{ margin-top: 0.5rem; font-size: 0.78rem; color: var(--muted); }}
    .settings-status strong {{ color: var(--text); }}
    .loc-banner {{
      display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;
      background: rgba(244,114,182,0.1); border: 1px solid rgba(244,114,182,0.3);
      border-radius: 8px; padding: 0.5rem 0.8rem; margin-bottom: 0.8rem;
      font-size: 0.78rem; color: #f472b6;
    }}
    .loc-banner strong {{ color: var(--text); }}
    .loc-banner button {{
      background: transparent; border: 1px solid rgba(244,114,182,0.4); color: #f472b6;
      border-radius: 6px; padding: 0.2rem 0.55rem; font-size: 0.7rem; cursor: pointer;
    }}

    /* Command Strip */
    .command-strip {{ display: flex; flex-direction: column; gap: 0.8rem; padding-bottom: 0.8rem; }}
    .cs-top {{ display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }}
    .cs-slider-group {{ flex: 1; min-width: 150px; display: flex; flex-direction: column; gap: 0.3rem; }}
    .cs-label {{ font-size: 0.7rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }}
    .score-dial {{
      -webkit-appearance: none; width: 100%; height: 6px; border-radius: 3px;
      background: rgba(255,255,255,0.1); outline: none; transition: background 0.2s;
    }}
    .score-dial::-webkit-slider-thumb {{
      -webkit-appearance: none; width: 16px; height: 16px; border-radius: 50%;
      background: var(--accent); cursor: pointer; box-shadow: 0 0 10px rgba(167, 139, 250, 0.5);
    }}
    .score-dial:focus::-webkit-slider-thumb {{ box-shadow: 0 0 15px rgba(167, 139, 250, 0.8); }}
    .cs-toggles {{ display: flex; gap: 0.4rem; flex-wrap: wrap; }}
    .cs-pill {{
      font-size: 0.75rem; font-weight: 600; padding: 0.35rem 0.75rem; border-radius: 20px;
      background: rgba(255,255,255,0.05); color: var(--muted); border: 1px solid rgba(255,255,255,0.1);
      transition: all 0.2s; cursor: pointer; user-select: none;
    }}
    .cs-pill:hover {{ background: rgba(255,255,255,0.1); color: var(--text); }}
    .cs-pill.active {{ background: var(--accent); color: var(--bg); border-color: var(--accent); }}
    .cs-genres {{ display: flex; gap: 0.4rem; overflow-x: auto; padding-bottom: 0.2rem; scrollbar-width: none; }}
    .cs-genres::-webkit-scrollbar {{ display: none; }}
    .cs-genre-pill {{
      flex-shrink: 0; font-size: 0.65rem; padding: 0.25rem 0.6rem; border-radius: 6px;
      background: transparent; color: var(--muted); border: 1px solid var(--border);
      cursor: pointer; transition: all 0.2s; text-transform: lowercase; user-select: none;
    }}
    .cs-genre-pill:hover {{ border-color: var(--muted); color: var(--text); }}
    .cs-genre-pill.active {{ border-color: var(--accent); color: var(--accent); background: rgba(167, 139, 250, 0.1); }}

    /* Sort row */
    .sort-row {{
      display: flex; align-items: center; justify-content: space-between;
      padding: 0.4rem 0 0.5rem; border-top: 1px solid var(--border);
      font-size: 0.75rem; color: var(--muted);
    }}
    .result-count {{ font-family: var(--mono); }}
    .sort-toggle {{ display: flex; gap: 0; border: 1px solid var(--border); border-radius: 5px; overflow: hidden; }}
    .sort-opt {{
      padding: 0.25rem 0.6rem; font-size: 0.72rem; font-weight: 500;
      background: transparent; color: var(--muted); border: none;
    }}
    .sort-opt.active {{ background: var(--surface-2); color: var(--text); }}

    /* ── Layout ─────────────────────────────── */
    .feed {{ max-width: 720px; margin: 0 auto; padding: 0.75rem 1.25rem 4rem; }}

    /* ── Date header ─────────────────────────── */
    .day-header {{
      /* Tuck 1px up under the header (z-index 20 > 10, so the overlap is hidden)
         to defeat sub-pixel rounding that otherwise leaves a 1px gap. */
      position: sticky; top: calc(var(--header-h, 130px) - 1px); z-index: 10;
      display: flex; justify-content: space-between; align-items: center;
      padding: 0.5rem 0.75rem;
      background: rgba(14, 12, 10, 0.95); backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--border);
      font-family: var(--mono); font-size: 0.7rem; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted);
      margin-top: 1rem;
      margin-bottom: 0.5rem;
      border-radius: 4px;
    }}
    .day-header.is-tonight {{ color: var(--tonight); border-bottom-color: rgba(226, 88, 34, 0.3); }}
    .day-header.is-tomorrow {{ color: var(--accent); border-bottom-color: rgba(232, 150, 26, 0.3); }}
    .day-count {{ opacity: 0.6; }}

    /* ── Card design ──────────────── */
    .show-card {{
      background: var(--surface);
      border-radius: 10px;
      margin-bottom: 0.4rem;
      padding: 0.7rem 0.9rem;
      cursor: pointer;
      transition: background 0.12s;
      user-select: none; -webkit-user-select: none;
      border: 1px solid transparent;
    }}
    .show-card:hover {{ background: var(--surface-2); border-color: var(--border); }}
    .show-card.is-past {{ opacity: 0.3; pointer-events: none; }}

    .row-main {{ display: flex; align-items: center; gap: 0.7rem; }}

    /* Thumbnail — 56px, square with rounded corners */
    .show-thumb-container {{
      position: relative; width: 3.5rem; height: 3.5rem;
      border-radius: 8px; overflow: hidden; flex-shrink: 0;
    }}
    .show-thumb {{
      width: 100%; height: 100%; object-fit: cover;
      border: 1px solid rgba(255,255,255,0.08); border-radius: 8px;
    }}
    .show-thumb-fallback {{
      width: 100%; height: 100%;
      background: linear-gradient(135deg, #1e1a2e 0%, #12101c 100%);
      border: 1px solid rgba(167,139,250,0.1); border-radius: 8px;
      display: flex; align-items: center; justify-content: center;
      font-size: 1.3rem;
    }}

    /* Info column */
    .show-info {{ flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 0.1rem; }}
    .show-headliner-row {{ display: flex; align-items: baseline; }}
    .show-headliner {{
      font-size: 1rem; font-weight: 650; line-height: 1.2;
      color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      text-decoration: none;
    }}
    .show-headliner:hover {{
      text-decoration: underline; text-decoration-color: rgba(167,139,250,0.5);
    }}
    .show-headliner.is-matched {{ color: var(--accent); }}

    .show-sub {{
      display: flex; align-items: center; gap: 0.35rem;
      font-size: 0.73rem; color: var(--muted);
      overflow: hidden; white-space: nowrap;
    }}
    .show-venue {{ overflow: hidden; text-overflow: ellipsis; min-width: 0; }}
    .show-time {{
      font-family: var(--mono); font-size: 0.7rem;
      color: var(--text); opacity: 0.5; flex-shrink: 0;
    }}
    .show-time.soon {{ color: var(--tonight); opacity: 1; font-weight: 700; }}
    .sub-dot {{ opacity: 0.3; flex-shrink: 0; }}
    .travel-chip {{
      font-family: var(--mono); font-size: 0.64rem; color: #60a5fa;
      opacity: 0.9; flex-shrink: 0;
    }}
    .leave-by {{ color: var(--muted); margin-left: 0.25rem; }}

    /* Openers preview in collapsed card */
    .show-openers-preview {{
      font-size: 0.68rem; color: #7b6da0; opacity: 0.85;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }}

    /* Genre tags — compact, inline */
    .row-genres {{
      display: flex; flex-wrap: wrap; gap: 0.2rem; margin-top: 0.15rem;
    }}
    .micro-genre {{
      font-size: 0.6rem; font-weight: 500; padding: 0.06rem 0.35rem;
      border-radius: 4px;
      background: transparent; border: 1px solid rgba(255,255,255,0.12);
      color: var(--muted); text-transform: lowercase; letter-spacing: 0.01em;
    }}

    /* Score badge — only shown when scored; unscored shows just have the chevron */
    .score-badge-circle {{
      display: flex; align-items: center; justify-content: center;
      width: 2.1rem; height: 2.1rem; border-radius: 50%;
      font-family: var(--mono); font-size: 0.78rem; font-weight: 700;
      flex-shrink: 0; align-self: center;
      margin-right: 0.5rem;
      position: relative;
    }}
    .score-badge-circle::before {{
      content: '';
      position: absolute;
      inset: 0;
      border-radius: 50%;
      padding: 2px; /* ring thickness */
      background: conic-gradient(currentColor calc(var(--score, 0) * 1%), rgba(255,255,255,0.05) 0);
      -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
      -webkit-mask-composite: xor;
      mask-composite: exclude;
      pointer-events: none;
    }}
    .score-badge-circle.hi {{ color: var(--accent); }}
    .score-badge-circle.md {{ color: var(--score-mid); }}
    .score-badge-circle.lo {{ color: #5a5080; }}
    .score-badge-circle.zero {{ color: rgba(255,255,255,0.2); font-weight: 400; }}
    .score-badge-circle.none {{ display: none; }}

    .row-chevron {{
      display: flex; align-items: center; justify-content: center;
      width: 1.1rem; flex-shrink: 0;
    }}
    .chevron-arrow {{
      font-size: 0.85rem; color: var(--muted); opacity: 0.45;
      transition: transform 0.18s ease, opacity 0.18s ease;
    }}
    .chevron-arrow.open {{ transform: rotate(180deg); color: var(--accent); opacity: 0.9; }}

    /* ── Expanded drawer & ticket stub ─────────── */
    .drawer {{
      padding-top: 0.5rem;
      animation: fadeSlide 0.18s ease-out;
    }}
    @keyframes fadeSlide {{
      from {{ opacity: 0; transform: translateY(-4px); }}
      to   {{ opacity: 1; transform: translateY(0); }}
    }}

    .ticket-container {{
      position: relative;
      background: #1e1a14;
      border: 1px solid rgba(255, 255, 255, 0.04);
      border-radius: 12px;
      padding: 1rem;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.03), 0 8px 24px rgba(0,0,0,0.3);
    }}

    .ticket-body {{
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }}
    @media (min-width: 480px) {{
      .ticket-body {{
        flex-direction: row;
        gap: 1rem;
      }}
    }}

    .ticket-art-wrap {{
      flex-shrink: 0;
      position: relative;
      width: 76px;
      height: 76px;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 0 10px rgba(232, 150, 26, 0.15);
      border: 1px solid rgba(232, 150, 26, 0.25);
      align-self: flex-start;
    }}

    .ticket-art {{
      width: 100%;
      height: 100%;
      object-fit: cover;
    }}
    .ticket-art-fallback {{
      width: 100%;
      height: 100%;
      background: linear-gradient(135deg, #2b251d 0%, #15120e 100%);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.5rem;
    }}

    .ticket-details {{
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
      min-width: 0;
    }}

    .ticket-openers {{
      font-size: 0.8rem;
      color: #c7bdae;
      line-height: 1.35;
    }}
    .ticket-openers strong {{
      color: var(--muted);
      font-size: 0.65rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      display: block;
      margin-bottom: 0.1rem;
    }}

    .ticket-description {{
      font-size: 0.78rem;
      color: #c7bdae;
      line-height: 1.45;
      margin-top: 0.25rem;
    }}
    .ticket-description p {{
      margin-bottom: 0.6rem;
    }}
    .ticket-description p:last-child {{
      margin-bottom: 0;
    }}
    .desc-clamp {{
      max-height: 120px;
      overflow: hidden;
      -webkit-mask-image: linear-gradient(to bottom, black 60%, transparent 100%);
      mask-image: linear-gradient(to bottom, black 60%, transparent 100%);
    }}
    .desc-toggle-btn {{
      color: var(--accent);
      font-size: 0.75rem;
      font-weight: 600;
      cursor: pointer;
      align-self: flex-start;
      margin-top: -0.2rem;
    }}
    .desc-toggle-btn:hover {{ text-decoration: underline; }}

    .ticket-times-row {{
      display: flex;
      gap: 1.25rem;
      margin: 0.2rem 0;
      border-top: 1px solid var(--border);
      border-bottom: 1px solid var(--border);
      padding: 0.4rem 0;
    }}

    .time-slot {{
      display: flex;
      flex-direction: column;
    }}
    .time-slot .label {{
      font-family: var(--mono);
      font-size: 0.6rem;
      color: var(--muted);
      letter-spacing: 0.08em;
    }}
    .time-slot .val {{
      font-family: var(--mono);
      font-size: 0.8rem;
      color: var(--text);
      font-weight: 600;
    }}

    .ticket-spotify-link {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      font-size: 0.78rem;
      color: #1DB954;
      font-weight: 600;
      transition: color 0.15s;
      align-self: flex-start;
    }}
    .ticket-spotify-link:hover {{
      color: #1ed760;
      text-decoration: underline;
    }}
    .ticket-lastfm-link {{
      display: inline-flex;
      align-items: center;
      gap: 0.25rem;
      font-size: 0.78rem;
      color: var(--muted);
      font-weight: 500;
      transition: color 0.15s;
      align-self: flex-start;
    }}
    .ticket-lastfm-link:hover {{ color: var(--text); text-decoration: underline; }}

    .ticket-divider-line {{
      border-top: 1px dashed var(--border);
      margin: 0.25rem 0;
      position: relative;
    }}
    .ticket-divider-line::before, .ticket-divider-line::after {{
      content: '';
      position: absolute;
      width: 12px; height: 12px;
      background: var(--bg);
      border-radius: 50%;
      top: -6px;
    }}
    .ticket-divider-line::before {{
      left: -17px;
      border-right: 1px solid rgba(255,255,255,0.03);
    }}
    .ticket-divider-line::after {{
      right: -17px;
      border-left: 1px solid rgba(255,255,255,0.03);
    }}

    .ticket-action-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 0.5rem;
    }}

    .price-tag {{
      display: flex;
      flex-direction: column;
    }}
    .price-tag .label {{
      font-size: 0.6rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .price-tag .val {{
      font-family: var(--mono);
      font-size: 1rem;
      font-weight: 700;
      color: var(--text);
      opacity: 0.85;
    }}

    .ticket-btn-link {{
      background: var(--accent);
      color: var(--bg);
      font-weight: 700;
      font-size: 0.8rem;
      padding: 0.45rem 1rem;
      border-radius: 7px;
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      transition: opacity 0.15s ease;
    }}
    .ticket-btn-link:hover {{ opacity: 0.88; }}
    .ticket-btn-link.placeholder-link {{
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--border);
      color: var(--muted);
    }}
    .ticket-btn-link.placeholder-link:hover {{
      background: rgba(255, 255, 255, 0.07);
      color: var(--text);
    }}


    /* ── Empty state ─────────────────────────── */
    .empty {{
      text-align: center; padding: 4rem 1rem;
      color: var(--muted); font-size: 0.875rem; line-height: 1.6;
    }}
    .empty a {{ color: var(--accent); text-decoration: underline; cursor: pointer; }}

    /* ── Modals ──────────────────────────────── */
    .overlay {{
      position: fixed; inset: 0; background: rgba(0,0,0,0.75);
      z-index: 50; display: flex; align-items: flex-end; justify-content: center;
      opacity: 0; pointer-events: none; transition: opacity 0.2s;
    }}
    .overlay.open {{ opacity: 1; pointer-events: all; }}
    .sheet {{
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 14px 14px 0 0; width: 100%; max-width: 640px;
      max-height: 85vh; overflow-y: auto;
      padding: 1.25rem 1.25rem 2rem;
      transform: translateY(8px); transition: transform 0.2s;
    }}
    .overlay.open .sheet {{ transform: translateY(0); }}
    .sheet-handle {{
      width: 2.5rem; height: 3px; background: var(--border);
      border-radius: 2px; margin: 0 auto 1rem;
    }}
    .sheet-header {{
      display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 1rem; padding-bottom: 0.75rem;
      border-bottom: 1px solid var(--border);
      position: sticky; top: -1.25rem; background: var(--surface); padding-top: 0.5rem;
      margin-top: -0.5rem;
    }}
    .sheet-title {{ font-size: 0.95rem; font-weight: 600; }}
    .sheet-close {{
      background: none; border: none; color: var(--muted);
      font-size: 1.25rem; line-height: 1; padding: 0.15rem;
    }}
    .sheet-search {{
      width: 100%; padding: 0.5rem 0.65rem;
      font-size: 0.85rem; font-family: var(--font);
      background: var(--bg); color: var(--text);
      border: 1px solid var(--border); border-radius: 6px;
      outline: none; margin-bottom: 0.75rem;
    }}
    .sheet-search:focus {{ border-color: var(--muted); }}
    .sheet-actions {{ display: flex; gap: 0.4rem; margin-bottom: 0.75rem; }}
    .sheet-act-btn {{
      flex: 1; padding: 0.3rem 0; font-size: 0.73rem;
      background: var(--bg); color: var(--muted);
      border: 1px solid var(--border); border-radius: 4px;
    }}
    .size-label {{
      font-size: 0.67rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.07em; color: var(--muted);
      padding: 0.65rem 0 0.3rem; opacity: 0.7;
    }}
    
    /* ── Settings Form ───────────────────────── */
    .settings-form {{ display: flex; flex-direction: column; gap: 1.25rem; padding-top: 0.5rem; }}
    .settings-group {{ display: flex; flex-direction: column; gap: 0.4rem; }}
    .settings-group label {{ font-size: 0.8rem; font-weight: 600; color: var(--muted); }}
    .settings-group input {{
      padding: 0.65rem; font-size: 0.9rem; font-family: var(--font);
      background: var(--bg); color: var(--text);
      border: 1px solid var(--border); border-radius: 6px; outline: none;
      transition: border-color 0.2s;
    }}
    .settings-group input:focus {{ border-color: var(--accent); }}
    .settings-save-btn {{
      background: var(--accent); color: var(--bg); font-weight: 700; font-size: 0.9rem;
      padding: 0.75rem; border-radius: 6px; border: none; cursor: pointer;
      margin-top: 0.5rem; transition: opacity 0.2s;
    }}
    .settings-save-btn:hover {{ opacity: 0.9; }}

    /* ── Scraping Toast ──────────────────────── */
    .scraping-toast {{
      position: fixed; bottom: 2rem; right: 2rem;
      background: rgba(20,20,20,0.95); backdrop-filter: blur(10px);
      border: 1px solid rgba(167, 139, 250, 0.4); border-radius: 10px;
      padding: 1.25rem 1.5rem; z-index: 1000;
      box-shadow: 0 10px 40px rgba(0,0,0,0.8), 0 0 20px rgba(167, 139, 250, 0.15);
      display: flex; flex-direction: column; gap: 0.6rem; min-width: 320px;
      transform: translateY(150%); opacity: 0; transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    }}
    .scraping-toast.visible {{
      transform: translateY(0); opacity: 1;
    }}
    .scraping-toast .toast-title {{
      font-size: 0.9rem; font-weight: 600; color: var(--text);
      display: flex; align-items: center; gap: 0.5rem;
    }}
    .scraping-toast .toast-bar-bg {{
      height: 6px; background: rgba(255,255,255,0.08); border-radius: 3px; overflow: hidden;
      position: relative;
    }}
    .scraping-toast .toast-bar-fill {{
      height: 100%; background: var(--accent);
      box-shadow: 0 0 10px var(--accent);
      transition: width 0.2s ease-out;
    }}
    .scraping-toast .toast-status {{
      font-size: 0.75rem; color: var(--muted); font-family: var(--mono);
      display: flex; justify-content: space-between;
    }}
    
    .venue-item {{
      display: flex; align-items: center; gap: 0.65rem;
      padding: 0.35rem 0; cursor: pointer; font-size: 0.875rem;
    }}
    .venue-item input {{ accent-color: var(--accent); width: 15px; height: 15px; flex-shrink: 0; }}
    .venue-count {{ font-family: var(--mono); font-size: 0.68rem; color: var(--muted); margin-left: auto; }}

    /* Centered modal for playlist */
    .overlay.centered {{ align-items: center; }}
    .overlay.centered .sheet {{ border-radius: 12px; max-height: 80vh; }}
  </style>
</head>
<body>
<div id="app" @click="vialOpen = false">

  <header class="site-header" :class="{{ compact: headerCompact }}">
    <div class="header-inner">
      <div class="brand-row">
        <div class="brand"><span class="brand-logo">showcat</span></div>
        <div class="brand-meta">
          <strong>{{{{ filteredShows.length }}}}</strong> shows &middot; {ts}
        </div>
        <div class="header-tools">
          <button class="tool-btn vial-btn" @click="vialOpen = !vialOpen" :class="{{active: vialOpen}}" aria-label="Data coverage stats" title="Data coverage">Stats</button>
          <button class="tool-btn settings-btn" @click="settingsOpen = true" aria-label="Settings" title="Settings">Settings</button>

                    <div class="vial-popover" v-if="vialOpen" @click.stop>
            <div class="health-stats">
        <div class="hs-col hs-taste" title="Matched to your Last.fm taste">
          <div class="hs-label"><span>Taste</span><span class="hs-v">{{{{ matchPct }}}}%</span></div>
          <div class="hs-bar-bg"><div class="hs-bar-fill" :style="{{width: matchPct + '%'}}"></div></div>
        </div>
        <div class="hs-col hs-linked" title="Linked to a Spotify artist">
          <div class="hs-label"><span>Linked</span><span class="hs-v">{{{{ linkedPct }}}}%</span></div>
          <div class="hs-bar-bg"><div class="hs-bar-fill" :style="{{width: linkedPct + '%'}}"></div></div>
        </div>
        <div class="hs-col hs-priced" title="Has a ticket price">
          <div class="hs-label"><span>Priced</span><span class="hs-v">{{{{ pricedPct }}}}%</span></div>
          <div class="hs-bar-bg"><div class="hs-bar-fill" :style="{{width: pricedPct + '%'}}"></div></div>
        </div>
        <div class="hs-col hs-pictured" title="Has artist artwork">
          <div class="hs-label"><span>Pictured</span><span class="hs-v">{{{{ picturedPct }}}}%</span></div>
          <div class="hs-bar-bg"><div class="hs-bar-fill" :style="{{width: picturedPct + '%'}}"></div></div>
        </div>
              <div class="hs-col hs-located" title="Has a drive-time ETA">
                <div class="hs-label"><span>Located</span><span class="hs-v">{{{{ locatedPct }}}}%</span></div>
                <div class="hs-bar-bg"><div class="hs-bar-fill" :style="{{width: locatedPct + '%'}}"></div></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="search-row">
        <input type="text" v-model="searchQuery" placeholder="Search venues, artists, genres…" class="search-input"
               @focus="searchFocused = true" @blur="searchFocused = false" />
        <button v-if="searchQuery" class="clear-search" @click="searchQuery = ''">&times;</button>
        <div class="search-suggest" v-if="searchFocused && searchSuggestions.length">
          <button v-for="sug in searchSuggestions" :key="sug.type + sug.label" class="suggest-item"
                  @mousedown.prevent="pickSuggestion(sug)">
            <span class="suggest-kind" :class="sug.type">{{{{ sug.type === 'venue' ? 'Venue' : 'Artist' }}}}</span>
            <span class="suggest-label">{{{{ sug.label }}}}</span>
            <span class="suggest-count" v-if="sug.count">{{{{ sug.count }}}}</span>
          </button>
        </div>
      </div>

      <div class="command-strip">
        <div class="cs-toggles">
          <button class="cs-pill" :class="{{active: matchedOnly}}" @click="matchedOnly = !matchedOnly"
                  title="Only shows by artists from your Last.fm history">My Taste</button>
          <button class="cs-pill" :class="{{active: favoritesOnly}}" @click="favsChipClick"
                  title="Only your favorite venues">Favorite venues</button>
          <button class="cs-pill" :class="{{active: maxCost <= 20}}" @click="maxCost = maxCost === 20 ? 1000 : 20"
                  title="Tickets $20 or less">Under $20</button>
          <button class="cs-pill" :class="{{active: maxDrive <= 15}}" @click="maxDrive = maxDrive === 15 ? 1000 : 15"
                  title="15 minutes or less from home">Nearby</button>
        </div>
        <div class="cs-genres" v-if="topGenres.length > 0">
          <button v-for="g in topGenres" :key="g" class="cs-genre-pill" :class="{{active: selectedGenres.includes(g)}}" @click="toggleGenre(g)">{{{{ g }}}}</button>
        </div>
      </div>

      <div class="sort-row">
        <span class="result-count">{{{{ filteredShows.length }}}} results</span>
        <div class="sort-toggle">
          <button class="sort-opt" :class="{{active: sortMode === 'date'}}" @click="sortMode = 'date'">By Date</button>
          <button class="sort-opt" :class="{{active: sortMode === 'lastfm'}}" @click="sortMode = 'lastfm'" title="Rank every show by Last.fm match, ignoring date">By Last.fm</button>
        </div>
      </div>
    </div>
  </header>

  <div class="feed">
    <div v-if="userLoc" class="loc-banner">
      <span>Drive times from <strong>{{{{ userLoc }}}}</strong></span>
      <button @click="clearLocation">reset</button>
    </div>
    <div v-if="filteredShows.length === 0" class="empty">
      No shows match your filters.<br>
      <a @click="resetFilters">Clear filters</a>
    </div>

    <template v-for="group in groupedShows" :key="group.date">
      <div class="day-header" v-if="group.date"
           :class="{{
             'is-tonight': group.date === 'TONIGHT',
             'is-tomorrow': group.date === 'TOMORROW'
           }}">
        <span>{{{{ group.date }}}}</span>
        <span class="day-count">{{{{ group.shows.length }}}}</span>
      </div>

      <div v-for="show in group.shows" :key="show.id"
           class="show-card"
           :class="{{  'is-past': isPast(show.timestamp, show.time_known) }}"
           @click="toggleExpand(show.id)"
           :data-id="show.id">

        <div class="row-main">
          <!-- Thumbnail Image -->
          <div class="show-thumb-container">
            <img v-if="getShowImage(show)" :src="getShowImage(show)" class="show-thumb" loading="lazy" @error="onImgError($event, show.id)" />
            <img v-else :src="DEFAULT_SHOW_IMG" class="show-thumb show-thumb-default" loading="lazy" alt="" />
          </div>

          <!-- Show Information -->
          <div class="show-info">
            <div class="show-headliner-row">
              <a v-if="artistUrl(show)" class="show-headliner" :class="{{'is-matched': show.matched_artist}}"
                 :href="artistUrl(show)" target="_blank" rel="noopener" @click.stop>{{{{ show.headliner }}}}</a>
              <span v-else class="show-headliner" :class="{{'is-matched': show.matched_artist}}">{{{{ show.headliner }}}}</span>
            </div>

            <!-- (date when ranked) · venue · time · drive · price -->
            <div class="show-sub">
              <template v-if="sortMode === 'lastfm'">
                <span class="card-date">{{{{ show.date_display }}}}</span>
                <span class="sub-dot">&middot;</span>
              </template>
              <span class="show-venue">{{{{ show.venue }}}}</span>
              <template v-if="show.show_display || show.doors_display">
                <span class="sub-dot">&middot;</span>
                <span class="show-time" :class="{{soon: isSoon(show.timestamp)}}" v-if="show.show_display">{{{{ fmtTime(show.show_display) }}}}</span>
                <span class="show-time" :class="{{soon: isSoon(show.timestamp)}}" v-else-if="show.doors_display">{{{{ fmtTime(show.doors_display) }}}} <span style="opacity:0.55;font-size:0.62rem">doors</span></span>
              </template>
              <template v-if="travelMin(show)">
                <span class="sub-dot">&middot;</span>
                <span class="travel-chip" :class="{{'travel-custom': userEta}}">{{{{ travelMin(show) }}}} min</span>
              </template>
              <template v-if="show.price">
                <span class="sub-dot">&middot;</span>
                <span class="price-chip">{{{{ show.price }}}}</span>
              </template>
            </div>

            <!-- Openers preview (collapsed) -->
            <div class="show-openers-preview" v-if="show.openers && show.openers.length">
              w/ {{{{ show.openers.slice(0,3).join(' · ') }}}}
            </div>

            <!-- Genre tags -->
            <div class="row-genres" v-if="show.genres && show.genres.length">
              <span class="micro-genre" v-for="g in show.genres.slice(0, 3)" :key="g">{{{{ g }}}}</span>
            </div>
          </div>

          <!-- Score badge — hidden when not scored -->
          <div class="score-badge-circle" :class="scoreClass(displayScore(show.score_total))" :style="{{'--score': displayScore(show.score_total) || 0}}" v-if="show.score_total !== null"
               title="Last.fm match — how closely this lines up with your listening (0–100)">
            <span>{{{{ displayScore(show.score_total) === 0 ? '-' : displayScore(show.score_total) }}}}</span>
          </div>

          <!-- Chevron -->
          <div class="row-chevron">
            <span class="chevron-arrow" :class="{{open: expandedId === show.id}}">▾</span>
          </div>
        </div>

        <!-- Expanded Drawer -->
        <div class="drawer" v-if="expandedId === show.id" @click.stop>
          <div class="ticket-container">
            <div class="ticket-body">
              <!-- Details column -->
              <div class="ticket-details">
                <!-- Supporting artists -->
                <div class="ticket-openers" v-if="show.openers && show.openers.length">
                  <strong>Support</strong>
                  {{{{ show.openers.join(', ') }}}}
                </div>

                <!-- Times -->
                <div class="ticket-times-row">
                  <div class="time-slot">
                    <span class="label">DOORS</span>
                    <span class="val">{{{{ show.doors_display || '—' }}}}</span>
                  </div>
                  <div class="time-slot">
                    <span class="label">SHOW</span>
                    <span class="val">{{{{ show.show_display || '—' }}}}</span>
                  </div>
                  <div class="time-slot" v-if="show.score_total !== null">
                    <span class="label">SCORE</span>
                    <span class="val" style="color:var(--accent)">{{{{ show.score_total }}}}</span>
                  </div>
                </div>

                <!-- Genre tags in drawer -->
                <div class="row-genres" v-if="show.genres && show.genres.length">
                  <span class="micro-genre" v-for="g in show.genres" :key="g">{{{{ g }}}}</span>
                </div>

                <!-- Show description -->
                <div v-if="show.description" style="display:flex;flex-direction:column;gap:0.35rem;">
                  <div class="ticket-description" :class="{{'desc-clamp': !expandedText[show.id]}}" v-html="formatDescription(show.description)"></div>
                  <div class="desc-toggle-btn" @click="expandedText[show.id] = !expandedText[show.id]">
                    {{{{ expandedText[show.id] ? 'Show Less' : 'Read More' }}}}
                  </div>
                </div>

                <!-- External links -->
                <div style="display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap;margin-top:0.15rem;">
                  <a v-if="show.spotify_url || show.event_spotify_url"
                     :href="show.spotify_url || show.event_spotify_url" target="_blank" rel="noopener" class="ticket-spotify-link" @click.stop>
                    <svg style="width:13px;height:13px;fill:currentColor;vertical-align:middle;margin-right:2px;" viewBox="0 0 24 24"><path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2zm4.586 14.424c-.18.295-.565.387-.86.207-2.377-1.454-5.37-1.783-8.893-.982-.336.076-.67-.135-.747-.472-.076-.336.136-.67.472-.747 3.856-.88 7.15-.509 9.821 1.13.295.18.387.563.207.864zm1.225-2.72c-.226.367-.707.487-1.074.26-2.72-1.672-6.87-2.157-10.08-1.182-.413.125-.847-.107-.972-.52-.125-.413.108-.847.52-.972 3.668-1.114 8.237-.575 11.35 1.343.366.226.486.706.26 1.073zm.107-2.846C14.538 8.71 8.86 8.52 5.58 9.516c-.523.158-1.08-.143-1.24-.667-.158-.524.143-1.08.667-1.24 3.763-1.14 10.016-.92 13.93 1.403.472.28.623.893.342 1.365-.28.472-.893.622-1.366.342z"/></svg>
                    Spotify
                  </a>
                  <a v-if="show.matched_artist" class="ticket-lastfm-link" :href="lastfmUrl(show)" target="_blank" rel="noopener" @click.stop>Last.fm &rarr;</a>
                </div>
              </div>
            </div>

            <div class="ticket-divider-line"></div>

            <div class="ticket-action-row">
              <div class="price-tag">
                <span class="label">Admission</span>
                <span class="val">{{{{ show.price || 'Door / TBA' }}}}</span>
              </div>
              <a v-if="show.ticket_url" :href="show.ticket_url" target="_blank" rel="noopener"
                 class="tix-pill ticket-btn-link" :class="{{ 'placeholder-link': show.is_placeholder_link }}"
                 @click.stop>
                <span v-if="show.is_placeholder_link">View on Ticketmaster &rarr;</span>
                <span v-else>Buy via {{{{ show.ticket_provider_label }}}} &rarr;</span>
              </a>
            </div>
          </div>
        </div>

      </div>
    </template>
  </div>

  <!-- Venue Favorites sheet -->
  <div class="overlay" :class="{{open: favsOpen}}" @click.self="favsOpen = false">
    <div class="sheet">
      <div class="sheet-handle"></div>
      <div class="sheet-header">
        <span class="sheet-title">Venue Favorites</span>
        <button class="sheet-close" @click="favsOpen = false">&times;</button>
      </div>
      <label style="display:flex;align-items:center;gap:0.65rem;font-size:0.85rem;font-weight:500;margin-bottom:0.85rem;cursor:pointer;">
        <input type="checkbox" v-model="favoritesOnly" style="accent-color:var(--accent);width:15px;height:15px;">
        Show only my favorites
      </label>
      <input class="sheet-search" type="text" v-model="venueSearch" placeholder="Search venues&#x2026;" autocomplete="off">
      <div class="sheet-actions">
        <button class="sheet-act-btn" @click="favoriteVenues = allVenueNames.slice()">Select all</button>
        <button class="sheet-act-btn" @click="favoriteVenues = []">Clear</button>
      </div>
      <template v-for="group in venueGroups" :key="group.label">
        <div class="size-label" v-if="group.venues.length">{{{{ group.label }}}}</div>
        <label class="venue-item" v-for="v in group.venues" :key="v.name">
          <input type="checkbox" :value="v.name" v-model="favoriteVenues">
          <span>{{{{ v.name }}}}</span>
          <span class="venue-count">{{{{ v.count }}}}</span>
        </label>
      </template>
      <div v-if="venueGroups.every(g => g.venues.length === 0)" style="font-size:0.82rem;color:var(--muted);padding:0.5rem 0;">
        No venues match.
      </div>
    </div>
  </div>

  <!-- Playlist sheet -->
  <div class="overlay centered" :class="{{open: playlistOpen}}" @click.self="playlistOpen = false">
    <div class="sheet" style="border-radius:12px;max-width:420px;">
      <div class="sheet-header">
        <span class="sheet-title">Discovery Playlist</span>
        <button class="sheet-close" @click="playlistOpen = false">&times;</button>
      </div>
      <iframe style="border-radius:8px;" src="https://open.spotify.com/embed/playlist/{spotify_id}?utm_source=generator&theme=0" width="100%" height="352" frameBorder="0" allowfullscreen allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture" loading="lazy" v-if="playlistOpen"></iframe>
    </div>
  </div>


  <!-- Settings sheet -->
  <div class="overlay centered" :class="{{open: settingsOpen}}" @click.self="settingsOpen = false">
    <div class="sheet" style="border-radius:12px;max-width:480px;">
      <div class="sheet-header">
        <span class="sheet-title">Settings</span>
        <button class="sheet-close" @click="settingsOpen = false">&times;</button>
      </div>
      <div class="settings-form">
        <div class="settings-group">
          <label>Your address — drive times will be measured from here</label>
          <input type="text" v-model="settingsAddress" placeholder="e.g. 123 SE Main St" @keyup.enter="geocodeAddress" />
          <div class="settings-eta-actions">
            <button class="settings-save-btn" @click="geocodeAddress">Use this address</button>
            <button class="settings-ghost-btn" @click="useMyLocation">Use my location</button>
            <button class="settings-ghost-btn" v-if="userLoc" @click="clearLocation">Reset to default</button>
          </div>
          <div class="settings-status" v-if="etaStatus">{{{{ etaStatus }}}}</div>
          <div class="settings-status" v-else-if="userLoc">Currently: drive times from <strong>{{{{ userLoc }}}}</strong></div>
        </div>
        <div class="settings-group">
          <label>Last.fm username (match shows to your listening)</label>
          <input type="text" v-model="settingsLastfm" placeholder="e.g. your_username" />
          <button class="settings-save-btn" @click="saveSettings">Save</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Scraping Progress Toast -->
  <div class="scraping-toast" :class="{{visible: scrapingActive}}">
    <div class="toast-title">
      <span v-if="scrapingProgress < 100">Updating your taste matches…</span>
      <span v-else>Taste matches updated</span>
    </div>
    <div class="toast-bar-bg">
      <div class="toast-bar-fill" :style="{{width: scrapingProgress + '%'}}"></div>
    </div>
    <div class="toast-status">
      <span>{{{{ scrapingStatusText }}}}</span>
      <span>{{{{ Math.round(scrapingProgress) }}}}%</span>
    </div>
  </div>

</div><!-- #app -->

<script>
const rawShows = {shows_json};

const {{ createApp, ref, computed, watch, onMounted, onUnmounted, nextTick }} = Vue;
createApp({{
  setup() {{
    const shows      = ref(rawShows);
    const expandedId = ref(null);
    const expandedText = ref({{}});
    const favsOpen   = ref(false);
    const playlistOpen = ref(false);
    const sortMode   = ref('date');
    const matchedOnly   = ref(false);
    const favoritesOnly = ref(false);
    const favoriteVenues = ref([]);
    const venueSearch = ref('');
    const searchQuery = ref('');
    const spotifyPlaylistId = ref('{spotify_id}');
    const now = ref(Date.now() / 1000);
    
    // Command Strip State
    const minScore = ref(0);
    const maxCost = ref(1000);
    const maxDrive = ref(1000);
    const selectedGenres = ref([]);

    const toggleGenre = (g) => {{
      if (selectedGenres.value.includes(g)) {{
        selectedGenres.value = selectedGenres.value.filter(x => x !== g);
      }} else {{
        selectedGenres.value.push(g);
      }}
    }};

    const topGenres = computed(() => {{
      const counts = {{}};
      shows.value.forEach(s => {{
        if (s.genres) {{
          s.genres.forEach(g => {{
            counts[g] = (counts[g] || 0) + 1;
          }});
        }}
      }});
      return Object.entries(counts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 8)
        .map(x => x[0]);
    }});

    const todayStr = new Date().toISOString().slice(0, 10);

    const resetFilters = () => {{
      minScore.value = 0; maxCost.value = 1000; maxDrive.value = 1000;
      selectedGenres.value = []; matchedOnly.value = false;
      favoritesOnly.value = false; searchQuery.value = '';
    }};
    // Chip toggles filter off if active, opens modal otherwise.
    const favsChipClick = () => {{
      if (favoritesOnly.value) {{ favoritesOnly.value = false; }}
      else {{ favsOpen.value = true; }}
    }};

    // ── Settings & Scraping State ──────────────
    const vialOpen = ref(false);
    const settingsOpen = ref(false);
    const settingsLastfm = ref('');
    const settingsAddress = ref('');
    const scrapingActive = ref(false);
    const scrapingProgress = ref(0);
    const scrapingStatusText = ref('');

    const saveSettings = () => {{
      settingsOpen.value = false;
      if (settingsLastfm.value) {{
        startScraping();
      }}
    }};

    const startScraping = () => {{
      scrapingActive.value = true;
      scrapingProgress.value = 0;
      scrapingStatusText.value = 'Connecting to Last.fm...';
      let progress = 0;
      const interval = setInterval(() => {{
        progress += Math.random() * 8;
        if (progress > 30 && progress < 40) scrapingStatusText.value = 'Fetching listening history...';
        if (progress > 60 && progress < 70) scrapingStatusText.value = 'Matching artists to venues...';
        if (progress >= 100) {{
          progress = 100;
          scrapingStatusText.value = 'Complete!';
          clearInterval(interval);
          setTimeout(() => {{ scrapingActive.value = false; }}, 2500);
        }}
        scrapingProgress.value = progress;
      }}, 150);
    }};

    // ── Score class ────────────────────────────
    const displayScore = (raw) => {{
      if (raw === null) return null;
      if (raw === 0) return 0;
      if (raw < 30) return Math.round(raw * (70 / 30));
      return Math.round(70 + (raw - 30) * (30 / 70));
    }};
    // ── Score class ────────────────────────────
    const scoreClass = (s) => ({{
      hi:   s !== null && s >= 70,
      md:   s !== null && s >= 40 && s < 70,
      lo:   s !== null && s > 0 && s < 40,
      zero: s === 0,
      none: s === null,
    }});

    // ── Description formatting ─────────────────
    const formatDescription = (text) => {{
      if (!text) return '';
      let formatted = text.replace(/Instructions: For Table Reservations/gi, '\\n\\nInstructions: For Table Reservations');
      let paras = formatted.split(/\\n\\s*\\n/);
      let newParas = [];
      for (let p of paras) {{
        let sentences = p.match(/[^.!?]+[.!?]+/g);
        if (sentences && sentences.length > 3 && p.length > 200) {{
          let chunk = '';
          for (let i = 0; i < sentences.length; i++) {{
            chunk += sentences[i] + ' ';
            if ((i + 1) % 3 === 0 || i === sentences.length - 1) {{
              newParas.push(chunk.trim());
              chunk = '';
            }}
          }}
        }} else {{
          newParas.push(p.trim());
        }}
      }}
      return newParas.filter(Boolean).map(p => "<p>" + p + "</p>").join('');
    }};

    // ── Time helpers ───────────────────────────
    const fmtTime = (t) => {{
      if (!t) return '';
      // "8:00 PM" → "8p", "7:30 PM" → "7:30p", "10:00 AM" → "10a"
      return t.replace(/:00(?=\\s)/, '').replace(/\\s+PM/i, 'p').replace(/\\s+AM/i, 'a');
    }};
    // A show counts as "past" only if we know its time and it started >2h ago.
    // Untimed shows (guessed 8pm) are never treated as past, so today's untimed
    // shows stay visible rather than greying out.
    const isPast  = (ts, timeKnown) => timeKnown !== false && ts < now.value - 7200;
    const isSoon  = (ts) => ts > now.value && ts < now.value + 7200;

    // "Leave by" is anchored to the SHOW time (not when the page was built):
    // depart so you arrive ~30 min before the show, given the venue's drive time.
    // Only shown for shows whose time we actually know.
    const ARRIVE_BUFFER_MIN = 30;
    const fmtClock = (ts) => {{
      const d = new Date(ts * 1000);
      let h = d.getHours(); const m = d.getMinutes();
      const ap = h < 12 ? 'a' : 'p'; h = h % 12; if (h === 0) h = 12;
      return m === 0 ? `${{h}}${{ap}}` : `${{h}}:${{String(m).padStart(2,'0')}}${{ap}}`;
    }};
    const leaveBy = (show) => {{
      if (show.travel_minutes == null || show.time_known === false) return null;
      return fmtClock(show.timestamp - (show.travel_minutes + ARRIVE_BUFFER_MIN) * 60);
    }};

    // ── Custom-address ETA (static per-cell files; no backend) ──
    // Geocode/locate in the browser → snap to the nearest res-9 cell via
    // cells.json → fetch that cell's shard → override drive times. The shard
    // hash mirrors scripts/export_eta_cells.py exactly.
    const etaManifest = ref(null);
    const etaCells = ref(null);
    const userEta = ref(null);   // venueName -> [minutes per bucket], for the chosen cell
    const userLoc = ref('');
    const etaStatus = ref('');
    try {{
      const c = localStorage.getItem('sc-eta'); const l = localStorage.getItem('sc-loc');
      if (c && l) {{ userEta.value = JSON.parse(c); userLoc.value = l; }}
    }} catch (e) {{}}

    const _etaShard = (cellId) => {{
      let h = 0;
      for (let i = 0; i < cellId.length; i++) h = (Math.imul(h, 31) + cellId.charCodeAt(i)) >>> 0;
      return h % (etaManifest.value ? etaManifest.value.shards : 128);
    }};
    const _haversine = (la, lo, lb, lc) => {{
      const R = 6371, p = Math.PI / 180;
      const dla = (lb - la) * p, dlo = (lc - lo) * p;
      const a = Math.sin(dla/2)**2 + Math.cos(la*p)*Math.cos(lb*p)*Math.sin(dlo/2)**2;
      return 2 * R * Math.asin(Math.sqrt(a));
    }};
    const _loadEtaMeta = async () => {{
      if (etaCells.value) return true;
      try {{
        etaManifest.value = await (await fetch('eta/manifest.json')).json();
        etaCells.value = await (await fetch('eta/cells.json')).json();
        return true;
      }} catch (e) {{ return false; }}
    }};
    const applyLocation = async (lat, lon, label) => {{
      etaStatus.value = 'Looking up drive times…';
      if (!(await _loadEtaMeta())) {{ etaStatus.value = 'ETA data unavailable.'; return; }}
      let best = null, bd = 1e9;
      for (const row of etaCells.value) {{
        const d = _haversine(lat, lon, row[1], row[2]);
        if (d < bd) {{ bd = d; best = row[0]; }}
      }}
      if (!best || bd > 8) {{ etaStatus.value = 'That address looks outside the Portland metro coverage.'; return; }}
      try {{
        const shard = await (await fetch('eta/s' + _etaShard(best) + '.json')).json();
        const cell = shard[best];
        if (!cell) {{ etaStatus.value = 'No drive times for that spot.'; return; }}
        userEta.value = cell; userLoc.value = label;
        localStorage.setItem('sc-eta', JSON.stringify(cell));
        localStorage.setItem('sc-loc', label);
        etaStatus.value = 'Drive times now from: ' + label;
        settingsOpen.value = false;
      }} catch (e) {{ etaStatus.value = 'Lookup failed.'; }}
    }};
    const geocodeAddress = async () => {{
      const q = settingsAddress.value.trim();
      if (!q) {{ etaStatus.value = 'Enter an address first.'; return; }}
      etaStatus.value = 'Finding address…';
      try {{
        const url = 'https://nominatim.openstreetmap.org/search?format=json&limit=1&q=' + encodeURIComponent(q + ', Portland, Oregon');
        const j = await (await fetch(url, {{ headers: {{ 'Accept': 'application/json' }} }})).json();
        if (!j.length) {{ etaStatus.value = 'Address not found — try adding the street + city.'; return; }}
        await applyLocation(parseFloat(j[0].lat), parseFloat(j[0].lon), q);
      }} catch (e) {{ etaStatus.value = 'Geocoding failed (network?).'; }}
    }};
    const useMyLocation = () => {{
      if (!navigator.geolocation) {{ etaStatus.value = 'Geolocation not supported.'; return; }}
      etaStatus.value = 'Getting your location…';
      navigator.geolocation.getCurrentPosition(
        (pos) => applyLocation(pos.coords.latitude, pos.coords.longitude, 'My location'),
        () => {{ etaStatus.value = 'Location permission denied.'; }}
      );
    }};
    const clearLocation = () => {{
      userEta.value = null; userLoc.value = '';
      localStorage.removeItem('sc-eta'); localStorage.removeItem('sc-loc');
      etaStatus.value = 'Reset to default home (N Portland).';
    }};
    const _normVenue = (n) => {{
      n = (n || '').toLowerCase();
      for (const w of ['music venue','theater','theatre','- portland','mcmenamins historic','manor','and hotel','at the crystal','saloon']) n = n.split(w).join('');
      return n.replace(/'/g, '').trim();
    }};
    // Effective drive time for a show: the user's address if set, else home.
    const travelMin = (show) => {{
      if (userEta.value) {{
        const ev = _normVenue(show.venue);
        for (const k in userEta.value) {{
          const nk = _normVenue(k);
          if (nk === ev || nk.includes(ev) || ev.includes(nk)) {{
            const buckets = etaManifest.value ? etaManifest.value.buckets
                          : ['pm_peak','evening','late_night','weekend_day','off_peak'];
            const bi = buckets.indexOf(show.bucket);
            const m = userEta.value[k][bi >= 0 ? bi : 0];
            if (m != null) return m;
            break;
          }}
        }}
      }}
      return show.travel_minutes;
    }};

    const DEFAULT_SHOW_IMG = "{CATCAT_DATA_URI}";
    const getShowImage = (show) => {{
      if (failedImages.value.has(show.id)) return null;
      return show.spotify_album_image_url || show.spotify_artist_image_url || show.event_image_url || null;
    }};

    // Track shows whose images have errored so getShowImage returns null → fallback renders.
    const failedImages = ref(new Set());
    const onImgError = (e, showId) => {{
      failedImages.value = new Set([...failedImages.value, showId]);
      e.target.style.display = 'none';
    }};
    const _getShowImageRaw = (show) => show.spotify_album_image_url || show.spotify_artist_image_url || show.event_image_url || null;

    const lastfmUrl = (show) => {{
      const name = show.matched_artist || show.headliner;
      return `https://www.last.fm/music/${{encodeURIComponent(name)}}`;
    }};
    const artistUrl = (show) => show.spotify_url || show.event_spotify_url || null;

    const matchedCount = computed(() => shows.value.filter(s => s.matched_artist !== null).length);
    const matchPct    = computed(() => shows.value.length ? Math.round(matchedCount.value / shows.value.length * 100) : 0);
    const linkedCount = computed(() => shows.value.filter(s => s.spotify_url || s.event_spotify_url).length);
    const linkedPct   = computed(() => shows.value.length ? Math.round(linkedCount.value / shows.value.length * 100) : 0);
    const pricedCount = computed(() => shows.value.filter(s => s.price).length);
    const pricedPct   = computed(() => shows.value.length ? Math.round(pricedCount.value / shows.value.length * 100) : 0);
    const picturedCount = computed(() => shows.value.filter(s => s.spotify_album_image_url || s.spotify_artist_image_url || s.event_image_url).length);
    const picturedPct   = computed(() => shows.value.length ? Math.round(picturedCount.value / shows.value.length * 100) : 0);
    const locatedCount  = computed(() => shows.value.filter(s => s.travel_minutes != null).length);
    const locatedPct    = computed(() => shows.value.length ? Math.round(locatedCount.value / shows.value.length * 100) : 0);

    // Parse the lowest dollar amount out of a price string ("$25", "$25 - $40",
    // "Free", "$15.00") → a number; "free" → 0; nothing parseable → null.
    const priceNum = (p) => {{
      if (p == null) return null;
      if (/free/i.test(p)) return 0;
      const m = String(p).match(/\\d+(?:\\.\\d+)?/);
      return m ? parseFloat(m[0]) : null;
    }};

    // ── Filtered / sorted shows ─────────────────
    const filteredShows = computed(() => {{
      const q = searchQuery.value.toLowerCase().trim();
      let r = shows.value.filter(s => {{
        if (isPast(s.timestamp, s.time_known)) return false;  // drop shows already over

        // Quick filters
        if (maxCost.value < 1000) {{ const pn = priceNum(s.price); if (pn === null || pn > maxCost.value) return false; }}
        if (maxDrive.value < 1000) {{ const tm = travelMin(s); if (tm == null || tm > maxDrive.value) return false; }}
        if (selectedGenres.value.length > 0 && (!s.genres || !selectedGenres.value.some(g => s.genres.includes(g)))) return false;
        
        if (matchedOnly.value   && s.score_total === null)                    return false;
        if (favoritesOnly.value && !favoriteVenues.value.includes(s.venue))  return false;
        
        if (q) {{
          const inHeadliner = s.headliner.toLowerCase().includes(q);
          const inVenue = s.venue.toLowerCase().includes(q);
          const inOpeners = s.openers && s.openers.some(o => o.toLowerCase().includes(q));
          const inGenres = s.genres && s.genres.some(g => g.toLowerCase().includes(q));
          if (!inHeadliner && !inVenue && !inOpeners && !inGenres) return false;
        }}
        return true;
      }});
      r = [...r].sort((a, b) => a.timestamp - b.timestamp);
      return r;
    }});

    const groupedShows = computed(() => {{
      // "By Last.fm" ignores date entirely: one flat list, every show ranked by
      // its Last.fm match score (highest first; unscored shows fall to the end,
      // ordered by date). Cards carry their own date in this mode.
      if (sortMode.value === 'lastfm') {{
        const all = [...filteredShows.value].sort((a, b) => {{
          if (a.score_total === null && b.score_total === null) return a.timestamp - b.timestamp;
          if (a.score_total === null) return 1;
          if (b.score_total === null) return -1;
          return b.score_total - a.score_total;
        }});
        return [{{ date: '', shows: all }}];
      }}
      const map = {{}};
      filteredShows.value.forEach(s => {{
        if (!map[s.date_display]) map[s.date_display] = [];
        map[s.date_display].push(s);
      }});
      return Object.keys(map).map(d => ({{ date: d, shows: map[d] }}));
    }});

    // ── Search autocomplete (venues + artists) ──
    const searchFocused = ref(false);
    const searchSuggestions = computed(() => {{
      const q = searchQuery.value.toLowerCase().trim();
      if (q.length < 1) return [];
      const venues = new Map(), arts = new Set();
      for (const s of shows.value) {{
        if (s.venue && s.venue.toLowerCase().includes(q)) venues.set(s.venue, (venues.get(s.venue) || 0) + 1);
        if (s.headliner && s.headliner.toLowerCase().includes(q)) arts.add(s.headliner);
      }}
      // Don't bother suggesting when the query already equals the only match.
      const vs = [...venues.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5)
                   .map(([name, n]) => ({{ type: 'venue', label: name, count: n }}));
      const as = [...arts].slice(0, 4).map(name => ({{ type: 'artist', label: name }}));
      const all = [...vs, ...as];
      if (all.length === 1 && all[0].label.toLowerCase() === q) return [];
      return all.slice(0, 8);
    }});
    const pickSuggestion = (sug) => {{ searchQuery.value = sug.label; searchFocused.value = false; }};

    // ── Venue modal data ───────────────────────
    const showCountByVenue = computed(() => {{
      const c = {{}};
      shows.value.forEach(s => {{ c[s.venue] = (c[s.venue] || 0) + 1; }});
      return c;
    }});

    const allVenueNames = computed(() => Object.keys(showCountByVenue.value).sort());

    const venueGroups = computed(() => {{
      const q = venueSearch.value.toLowerCase().trim();
      const sizeOrder = ['large', 'mid', 'small'];
      const labels = {{ large: 'Large Venues', mid: 'Mid-Size Venues', small: 'Bars & Small Rooms' }};
      const buckets = {{ large: [], mid: [], small: [] }};

      allVenueNames.value.forEach(name => {{
        if (q && !name.toLowerCase().includes(q)) return;
        const size = shows.value.find(s => s.venue === name)?.venue_size || 'mid';
        (buckets[size] = buckets[size] || []).push({{
          name,
          count: showCountByVenue.value[name] || 0,
        }});
      }});

      return sizeOrder.map(s => ({{ label: labels[s], venues: buckets[s] || [] }}));
    }});

    // ── Expand ─────────────────────────────────
    const toggleExpand = async (id) => {{
      if (expandedId.value === id) {{ expandedId.value = null; return; }}
      expandedId.value = id;
      await nextTick();
      const drawer = document.querySelector(`[data-id="${{id}}"] .drawer`);
      if (drawer) {{
        const rect = drawer.getBoundingClientRect();
        if (rect.bottom > window.innerHeight - 12) {{
          drawer.scrollIntoView({{ block: 'nearest', behavior: 'smooth' }});
        }}
      }}
    }};

    // ── Sticky Header Height Calculation ───────
    const updateHeaderHeight = () => {{
      const header = document.querySelector('.site-header');
      if (header) {{
        // floor() so --header-h is never larger than the real height — the
        // day-header then tucks under the header (gap-free) rather than dropping
        // below it (which would show a sub-pixel gap).
        const height = Math.floor(header.getBoundingClientRect().height);
        document.documentElement.style.setProperty('--header-h', `${{height}}px`);
      }}
    }};

    // ── Collapse the sticky header on scroll ───
    // Full header at the top; once scrolled it shrinks to just the filter chips
    // so it stops dominating the viewport (esp. on mobile).
    const headerCompact = ref(false);
    const onScroll = () => {{
      headerCompact.value = window.scrollY > 60;
      // Re-measure every scroll so --header-h always equals the live header
      // height — no reliance on a single stale measurement.
      updateHeaderHeight();
    }};
    watch(headerCompact, () => nextTick(updateHeaderHeight));

    // ── Persistence ────────────────────────────
    let timer;
    onMounted(() => {{
      const s = localStorage.getItem('sc-favs');
      if (s) try {{ favoriteVenues.value = JSON.parse(s); }} catch(e) {{}}
      const prefs = localStorage.getItem('sc-prefs');
      if (prefs) try {{
        const p = JSON.parse(prefs);
        if (p.matchedOnly)   matchedOnly.value   = p.matchedOnly;
        if (p.favoritesOnly) favoritesOnly.value = p.favoritesOnly;
        if (p.sortMode === 'date' || p.sortMode === 'lastfm') sortMode.value = p.sortMode;
      }} catch(e) {{}}
      timer = setInterval(() => {{ now.value = Date.now() / 1000; }}, 60000);
      
      updateHeaderHeight();
      window.addEventListener('resize', updateHeaderHeight);
      window.addEventListener('scroll', onScroll, {{ passive: true }});
      // Fonts load async and reflow the header — re-measure once they're ready
      // so the initial --header-h isn't stale.
      if (document.fonts && document.fonts.ready) {{
        document.fonts.ready.then(updateHeaderHeight);
      }}
    }});
    onUnmounted(() => {{
      clearInterval(timer);
      window.removeEventListener('resize', updateHeaderHeight);
      window.removeEventListener('scroll', onScroll);
    }});

    watch(favoriteVenues, (v) => {{
      localStorage.setItem('sc-favs', JSON.stringify(v));
    }}, {{ deep: true }});

    watch([matchedOnly, favoritesOnly, sortMode, minScore, maxCost, maxDrive], () => {{
      localStorage.setItem('sc-prefs', JSON.stringify({{
        matchedOnly:   matchedOnly.value,
        favoritesOnly: favoritesOnly.value,
        
        sortMode:      sortMode.value,
      }}));
    }});

    return {{
      shows, expandedId, favsOpen, playlistOpen,
      sortMode, matchedOnly, favoritesOnly,
      favoriteVenues, venueSearch, searchQuery, spotifyPlaylistId,
      searchFocused, searchSuggestions, pickSuggestion,
      filteredShows, groupedShows,
      allVenueNames, venueGroups, showCountByVenue,
      minScore, maxCost, maxDrive, selectedGenres, topGenres, toggleGenre, resetFilters, favsChipClick, toggleExpand,
      scoreClass, displayScore, formatDescription, expandedText, fmtTime, isPast, isSoon, getShowImage, DEFAULT_SHOW_IMG, leaveBy,
      travelMin, userEta, userLoc, etaStatus, geocodeAddress, useMyLocation, clearLocation,
      artistUrl, lastfmUrl, onImgError, failedImages, matchedCount, matchPct,
      linkedCount, linkedPct, pricedCount, pricedPct, picturedCount, picturedPct,
        locatedCount, locatedPct, headerCompact,
        vialOpen, settingsOpen, settingsLastfm, settingsAddress, saveSettings,
        scrapingActive, scrapingProgress, scrapingStatusText,
    }};
  }}
}}).mount('#app');
</script>
</body>
</html>"""


class WebOutputAdapter(BaseOutputAdapter):
    def __init__(self, output_dir: str | None = None, scoring_version: str | None = None) -> None:
        self._output_dir = Path(output_dir or os.environ.get("WEB_OUTPUT_DIR", "public"))
        self._scoring_version = scoring_version or os.environ.get("SCORING_VERSION", "discovery-v1")

    @property
    def output_name(self) -> str:
        return "web"

    def build(self, session: Session) -> str:
        shows = _query_shows(session, self._scoring_version)
        return render_html(shows, dt.datetime.now(dt.UTC))

    def write(self, session: Session) -> Path:
        html_content = self.build(session)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._output_dir / "index.html"
        out_path.write_text(html_content, encoding="utf-8")
        logger.info("Web output written", extra={"path": str(out_path)})
        return out_path
