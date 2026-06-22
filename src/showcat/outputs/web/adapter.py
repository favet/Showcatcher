"""Static HTML generator for showcat.favet.net."""
import datetime as dt
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from showcat.adapters.tickets.providers import best_link, classify_provider, provider_label
from showcat.ingest.events.models import Event
from showcat.ingest.history.models import Artist, ArtistTag
from showcat.outputs.base import BaseOutputAdapter
from showcat.resolve.matcher import normalize
from showcat.resolve.models import EventMatch
from showcat.score.models import EventScore

logger = logging.getLogger(__name__)

SQLITE_DB_PATH = os.environ.get("SQLITE_DB_PATH", r"C:\Users\Justin\Documents\PDX Shows\data\pdx.sqlite")
HOME_CELL_ID = "8828f0003dfffff"

# TM returns slightly different venue name strings; normalize before any logic.
VENUE_CANONICAL: dict[str, str] = {
    "revolution hall - portland": "Revolution Hall",
    "mcmenamins historic edgefield manor": "McMenamins Edgefield",
    "the get down music venue": "The Get Down",
    "mcmenamins edgefield amphitheatre": "Edgefield Amphitheater",
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


def normalize_venue_name(name: str) -> str:
    name = name.lower()
    for word in ["music venue", "theater", "theatre", "- portland",
                 "mcmenamins historic", "manor", "and hotel"]:
        name = name.replace(word, "")
    return name.strip()


def canonical_show_key(venue: str, date_iso: str, headliner: str) -> tuple[str, str, str]:
    return (
        normalize(normalize_venue_name(canonicalize_venue(venue))),
        date_iso,
        normalize(headliner),
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
        merged.append(rep)
    return merged


def get_travel_times() -> dict[str, dict[str, Any]]:
    times: dict[str, dict[str, Any]] = {}
    if not os.path.exists(SQLITE_DB_PATH):
        return times
    try:
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        venues = conn.execute("SELECT venue_id, name FROM venues").fetchall()
        for v in venues:
            bm = conn.execute(
                "SELECT base_seconds, base_meters FROM base_matrix WHERE cell_id = ? AND venue_id = ?",
                (HOME_CELL_ID, v["venue_id"]),
            ).fetchone()
            if bm:
                times[normalize_venue_name(v["name"])] = {
                    "minutes": round(bm["base_seconds"] / 60),
                    "miles": round(bm["base_meters"] / 1609.34, 1),
                }
        conn.close()
    except Exception as e:
        logger.error("Error querying SQLite: %s", e)
    return times


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
                tag for tag, _ in sorted(tags_by_artist[aid], key=lambda x: x[1], reverse=True)[:3]  # type: ignore[index]
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
        seen.add(event.id)

        venue = canonicalize_venue(event.venue)

        norm_v = normalize_venue_name(venue)
        travel_info = None
        for k, v in travel_times.items():
            if norm_v == k or norm_v in k or k in norm_v:
                travel_info = v
                break

        genres = tags_by_artist.get(artist.id, []) if artist else []

        sort_time = event.show_time or event.doors_time or dt.time()
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
            "venue": venue,
            "venue_size": get_venue_size(venue),
            "date": event.date.isoformat(),
            "date_display": date_display,
            "doors_display": fmt_time(event.doors_time) if event.doors_time else None,
            "show_display": fmt_time(event.show_time) if event.show_time else None,
            "ticket_url": event.ticket_url,
            "ticket_provider": ticket_provider,
            "ticket_provider_label": provider_label(ticket_provider),
            "score_total": score_int,
            "matched_artist": artist.raw_name if artist else None,
            "travel_minutes": travel_info["minutes"] if travel_info else None,
            "genres": genres,
            "source": event.source,
            "timestamp": timestamp,
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
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,400;0,500;0,600;0,700;1,400&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
  <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
  <style>
    :root {{
      --bg:           #171410;
      --surface:      #211E18;
      --surface-2:    #2A2620;
      --text:         #EDE5D8;
      --muted:        #7D7060;
      --border:       #302B23;
      --accent:       #E8961A;
      --accent-dim:   rgba(232,150,26,0.13);
      --score-hi:     #E8961A;
      --score-mid:    #8A6830;
      --score-lo:     #3E3830;
      --tonight:      #D95F2B;
      --font:         'Inter', system-ui, sans-serif;
      --mono:         'IBM Plex Mono', 'Courier New', monospace;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }}
    html {{ font-size: 16px; }}
    body {{ background: var(--bg); color: var(--text); font-family: var(--font); line-height: 1.4; -webkit-font-smoothing: antialiased; }}
    a {{ color: inherit; text-decoration: none; }}
    button {{ font-family: var(--font); cursor: pointer; }}

    /* ── Header ─────────────────────────────── */
    .site-header {{
      background: var(--bg);
      border-bottom: 1px solid var(--border);
      padding: 1rem 1rem 0;
      position: sticky; top: 0; z-index: 20;
    }}
    .brand-row {{
      display: flex; align-items: baseline; justify-content: space-between;
      margin-bottom: 0.75rem;
    }}
    .brand {{ font-size: 1.1rem; font-weight: 700; letter-spacing: -0.02em; }}
    .brand em {{ color: var(--accent); font-style: normal; }}
    .brand-meta {{ font-family: var(--mono); font-size: 0.7rem; color: var(--muted); }}
    .brand-meta strong {{ color: var(--text); }}

    /* Filter chips */
    .filter-row {{
      display: flex; align-items: center; gap: 0.4rem;
      overflow-x: auto; padding-bottom: 0.75rem;
      scrollbar-width: none;
    }}
    .filter-row::-webkit-scrollbar {{ display: none; }}
    .chip {{
      flex-shrink: 0;
      font-size: 0.78rem; font-weight: 500;
      padding: 0.3rem 0.65rem;
      border: 1px solid var(--border);
      border-radius: 20px;
      background: transparent; color: var(--muted);
      transition: all 0.12s;
      white-space: nowrap;
    }}
    .chip:hover {{ border-color: var(--muted); color: var(--text); }}
    .chip.active {{
      background: var(--accent); border-color: var(--accent);
      color: var(--bg); font-weight: 600;
    }}
    .chip.tonight-active {{
      background: var(--tonight); border-color: var(--tonight);
      color: #fff;
    }}
    .chip-divider {{ width: 1px; height: 1.1rem; background: var(--border); flex-shrink: 0; margin: 0 0.1rem; }}

    /* Sort row */
    .sort-row {{
      display: flex; align-items: center; justify-content: space-between;
      padding: 0.4rem 0 0.5rem; border-top: 1px solid var(--border);
      font-size: 0.75rem; color: var(--muted);
    }}
    .result-count {{ font-family: var(--mono); }}
    .sort-toggle {{ display: flex; gap: 0; border: 1px solid var(--border); border-radius: 5px; overflow: hidden; }}
    .sort-opt {{
      padding: 0.2rem 0.55rem; font-size: 0.72rem; font-weight: 500;
      background: transparent; color: var(--muted); border: none;
    }}
    .sort-opt.active {{ background: var(--surface-2); color: var(--text); }}

    /* ── Layout ─────────────────────────────── */
    .feed {{ max-width: 720px; margin: 0 auto; padding-bottom: 4rem; }}

    /* ── Date header ─────────────────────────── */
    .day-header {{
      position: sticky; top: var(--header-h, 130px); z-index: 10;
      display: flex; justify-content: space-between; align-items: center;
      padding: 0.45rem 1rem;
      background: rgba(23,20,16,0.97); backdrop-filter: blur(6px);
      border-bottom: 1px solid var(--border);
      font-family: var(--mono); font-size: 0.7rem; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted);
    }}
    .day-header.is-tonight {{ color: var(--tonight); }}
    .day-header.is-tomorrow {{ color: var(--accent); }}
    .day-count {{ opacity: 0.6; }}

    /* ── Show row ────────────────────────────── */
    .show-row {{
      border-bottom: 1px solid var(--border);
      padding: 0.6rem 1rem;
      cursor: pointer;
      transition: background 0.1s;
      user-select: none; -webkit-user-select: none;
    }}
    .show-row:hover {{ background: var(--surface); }}
    .show-row.is-past {{ opacity: 0.35; pointer-events: none; }}

    .row-main {{
      display: flex; align-items: flex-start; gap: 0.75rem;
    }}

    /* Score badge */
    .score-badge {{
      flex-shrink: 0; width: 2.25rem;
      font-family: var(--mono); font-size: 0.95rem; font-weight: 600;
      text-align: right; line-height: 1.35; padding-top: 0.1rem;
    }}
    .score-badge.hi {{ color: var(--score-hi); }}
    .score-badge.md {{ color: var(--score-mid); }}
    .score-badge.lo {{ color: var(--score-lo); }}
    .score-badge.none {{ color: var(--border); }}

    /* Show info */
    .show-info {{ flex: 1; min-width: 0; }}
    .show-headliner {{
      font-size: 0.975rem; font-weight: 600; line-height: 1.25;
      color: var(--text);
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }}
    .show-sub {{
      display: flex; align-items: center; gap: 0.4rem;
      font-size: 0.75rem; color: var(--muted); margin-top: 0.15rem;
      overflow: hidden; white-space: nowrap;
    }}
    .show-venue {{ overflow: hidden; text-overflow: ellipsis; min-width: 0; }}
    .show-time {{
      font-family: var(--mono); font-size: 0.72rem;
      color: var(--text); opacity: 0.55; flex-shrink: 0;
    }}
    .show-time.soon {{ color: var(--tonight); opacity: 1; font-weight: 600; }}
    .sub-dot {{ opacity: 0.35; }}

    /* Right side: ticket link + chevron */
    .row-right {{
      display: flex; align-items: center; gap: 0.4rem;
      flex-shrink: 0; padding-top: 0.1rem;
    }}
    .tix-link {{
      font-size: 1rem; color: var(--accent); opacity: 0.75;
      line-height: 1; display: block; padding: 0.1rem 0.2rem;
      transition: opacity 0.1s;
    }}
    .tix-link:hover {{ opacity: 1; }}
    .tix-link.tm {{ color: var(--muted); opacity: 0.5; }}
    .chevron {{ font-size: 0.8rem; color: var(--muted); opacity: 0.45; width: 1rem; text-align: center; transition: transform 0.15s; }}
    .chevron.open {{ transform: scaleY(-1); opacity: 0.7; }}

    /* ── Expanded drawer ─────────────────────── */
    .drawer {{
      padding: 0.65rem 0 0.2rem 3rem;
      animation: fadeSlide 0.18s ease-out;
    }}
    @keyframes fadeSlide {{
      from {{ opacity: 0; transform: translateY(-4px); }}
      to   {{ opacity: 1; transform: translateY(0); }}
    }}
    .drawer-genres {{ display: flex; flex-wrap: wrap; gap: 0.3rem; margin-bottom: 0.5rem; }}
    .genre-tag {{
      font-size: 0.68rem; padding: 0.18rem 0.45rem;
      border: 1px solid var(--border); border-radius: 3px;
      color: var(--muted); background: var(--surface);
    }}
    .drawer-match {{
      font-size: 0.72rem; color: var(--muted); margin-bottom: 0.55rem;
      font-style: italic;
    }}
    .drawer-footer {{
      display: flex; align-items: center; justify-content: space-between;
    }}
    .travel-label {{
      font-family: var(--mono); font-size: 0.72rem; color: var(--muted);
    }}
    .tix-btn {{
      font-size: 0.78rem; font-weight: 600;
      padding: 0.35rem 0.85rem; border-radius: 4px;
      background: var(--accent); color: var(--bg);
      display: inline-flex; align-items: center; gap: 0.35rem;
      transition: opacity 0.1s;
    }}
    .tix-btn:hover {{ opacity: 0.88; }}
    .tix-btn.tm {{ background: var(--surface-2); color: var(--muted); }}
    .tix-provider {{ font-size: 0.62rem; font-weight: 500; opacity: 0.8; }}

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
<div id="app">

  <header class="site-header">
    <div class="brand-row">
      <div class="brand">Show<em>cat</em></div>
      <div class="brand-meta"><strong>{{{{ filteredShows.length }}}}</strong> shows &middot; Portland &middot; {ts}</div>
    </div>

    <div class="filter-row">
      <button class="chip" :class="dateRange === 'tonight' ? 'active tonight-active' : ''" @click="setDate('tonight')">Tonight</button>
      <button class="chip" :class="{{active: dateRange === 'week'}}" @click="setDate('week')">This Week</button>
      <button class="chip" :class="{{active: dateRange === 'month'}}" @click="setDate('month')">This Month</button>
      <button class="chip" :class="{{active: dateRange === 'all'}}" @click="setDate('all')">All</button>
      <div class="chip-divider"></div>
      <button class="chip" :class="{{active: matchedOnly}}" @click="matchedOnly = !matchedOnly">Known</button>
      <button class="chip" :class="{{active: favoritesOnly}}" @click="favsChipClick">&#9733; Favs</button>
    </div>

    <div class="sort-row">
      <span class="result-count">{{{{ filteredShows.length }}}} results</span>
      <div class="sort-toggle">
        <button class="sort-opt" :class="{{active: sortMode === 'date'}}" @click="sortMode = 'date'">By Date</button>
        <button class="sort-opt" :class="{{active: sortMode === 'score'}}" @click="sortMode = 'score'">By Score</button>
      </div>
    </div>
  </header>

  <div class="feed">
    <div v-if="filteredShows.length === 0" class="empty">
      No shows match your filters.<br>
      <a @click="resetFilters">Clear filters</a>
    </div>

    <template v-for="group in groupedShows" :key="group.date">
      <div class="day-header"
           :class="{{
             'is-tonight': group.date === 'TONIGHT',
             'is-tomorrow': group.date === 'TOMORROW'
           }}">
        <span>{{{{ group.date }}}}</span>
        <span class="day-count">{{{{ group.shows.length }}}}</span>
      </div>

      <div v-for="show in group.shows" :key="show.id"
           class="show-row"
           :class="{{  'is-past': isPast(show.timestamp) }}"
           @click="toggleExpand(show.id)"
           :data-id="show.id">

        <div class="row-main">
          <div class="score-badge" :class="scoreClass(show.score_total)">
            {{{{ show.score_total !== null ? show.score_total : '·' }}}}
          </div>

          <div class="show-info">
            <div class="show-headliner">{{{{ show.headliner }}}}</div>
            <div class="show-sub">
              <span class="show-venue">{{{{ show.venue }}}}</span>
              <span class="sub-dot" v-if="show.show_display || show.doors_display">&middot;</span>
              <span class="show-time" :class="{{soon: isSoon(show.timestamp)}}" v-if="show.show_display">
                {{{{ fmtTime(show.show_display) }}}}
              </span>
              <span class="show-time" :class="{{soon: isSoon(show.timestamp)}}" v-else-if="show.doors_display">
                {{{{ fmtTime(show.doors_display) }}}} <span style="opacity:0.6;font-size:0.65rem">doors</span>
              </span>
            </div>
          </div>

          <div class="row-right">
            <a v-if="show.ticket_url"
               :href="show.ticket_url" target="_blank" rel="noopener"
               class="tix-link" :class="{{tm: show.ticket_provider === 'ticketmaster' || show.ticket_provider === 'ticketweb'}}"
               @click.stop title="Buy tickets">&#8599;</a>
            <span class="chevron" :class="{{open: expandedId === show.id}}">▾</span>
          </div>
        </div>

        <div class="drawer" v-if="expandedId === show.id">
          <div class="drawer-genres" v-if="show.genres && show.genres.length">
            <span class="genre-tag" v-for="g in show.genres.slice(0,4)" :key="g">{{{{ g }}}}</span>
          </div>
          <div class="drawer-match" v-if="show.matched_artist && show.matched_artist !== show.headliner">
            matched via {{{{ show.matched_artist }}}}
          </div>
          <div class="drawer-footer">
            <span class="travel-label" v-if="show.travel_minutes">{{{{ show.travel_minutes }}}}m away</span>
            <span v-else></span>
            <a v-if="show.ticket_url" :href="show.ticket_url" target="_blank" rel="noopener"
               class="tix-btn" :class="{{tm: show.ticket_provider === 'ticketmaster' || show.ticket_provider === 'ticketweb'}}"
               @click.stop>
              Tickets
              <span class="tix-provider" v-if="show.ticket_provider_label && show.ticket_provider_label !== 'Tickets'">via {{{{ show.ticket_provider_label }}}}</span>
              &#8599;
            </a>
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

</div><!-- #app -->

<script>
const rawShows = {shows_json};

const {{ createApp, ref, computed, watch, onMounted, onUnmounted, nextTick }} = Vue;
createApp({{
  setup() {{
    const shows      = ref(rawShows);
    const expandedId = ref(null);
    const favsOpen   = ref(false);
    const playlistOpen = ref(false);
    const dateRange  = ref('all');
    const sortMode   = ref('date');
    const matchedOnly   = ref(false);
    const favoritesOnly = ref(false);
    const favoriteVenues = ref([]);
    const venueSearch = ref('');
    const now = ref(Date.now() / 1000);

    // ── Date helpers ───────────────────────────
    const todayStr = new Date().toISOString().slice(0, 10);
    const inDays = (n) => {{
      const d = new Date(); d.setDate(d.getDate() + n);
      return d.toISOString().slice(0, 10);
    }};

    const setDate = (v) => {{ dateRange.value = v; }};
    const resetFilters = () => {{
      dateRange.value = 'all'; matchedOnly.value = false;
      favoritesOnly.value = false;
    }};
    // Chip toggles filter off if active, opens modal otherwise.
    const favsChipClick = () => {{
      if (favoritesOnly.value) {{ favoritesOnly.value = false; }}
      else {{ favsOpen.value = true; }}
    }};

    // ── Score class ────────────────────────────
    const scoreClass = (s) => ({{
      hi:   s !== null && s >= 70,
      md:   s !== null && s >= 40 && s < 70,
      lo:   s !== null && s < 40,
      none: s === null,
    }});

    // ── Time helpers ───────────────────────────
    const fmtTime = (t) => {{
      if (!t) return '';
      // "8:00 PM" → "8p", "7:30 PM" → "7:30p", "10:00 AM" → "10a"
      return t.replace(/:00(?=\\s)/, '').replace(/\\s+PM/i, 'p').replace(/\\s+AM/i, 'a');
    }};
    const isPast  = (ts) => ts < now.value - 7200;
    const isSoon  = (ts) => ts > now.value && ts < now.value + 7200;

    // ── Filtered / sorted shows ─────────────────
    const filteredShows = computed(() => {{
      const weekEnd  = inDays(7);
      const monthEnd = inDays(30);
      let r = shows.value.filter(s => {{
        if (dateRange.value === 'tonight' && s.date !== todayStr) return false;
        if (dateRange.value === 'week'    && s.date > weekEnd)    return false;
        if (dateRange.value === 'month'   && s.date > monthEnd)   return false;
        if (matchedOnly.value   && s.score_total === null)                    return false;
        if (favoritesOnly.value && !favoriteVenues.value.includes(s.venue))  return false;
        return true;
      }});
      // Always chronological first; score sort is applied within date groups.
      r = [...r].sort((a, b) => a.timestamp - b.timestamp);
      return r;
    }});

    const groupedShows = computed(() => {{
      const map = {{}};
      filteredShows.value.forEach(s => {{
        if (!map[s.date_display]) map[s.date_display] = [];
        map[s.date_display].push(s);
      }});
      return Object.keys(map).map(d => {{
        let list = map[d];
        if (sortMode.value === 'score') {{
          list = [...list].sort((a, b) => {{
            if (a.score_total === null && b.score_total === null) return 0;
            if (a.score_total === null) return 1;
            if (b.score_total === null) return -1;
            return b.score_total - a.score_total;
          }});
        }}
        return {{ date: d, shows: list }};
      }});
    }});

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
        if (p.dateRange)     dateRange.value     = p.dateRange;
        if (p.sortMode)      sortMode.value      = p.sortMode;
      }} catch(e) {{}}
      timer = setInterval(() => {{ now.value = Date.now() / 1000; }}, 60000);
    }});
    onUnmounted(() => clearInterval(timer));

    watch(favoriteVenues, (v) => {{
      localStorage.setItem('sc-favs', JSON.stringify(v));
    }}, {{ deep: true }});

    watch([matchedOnly, favoritesOnly, dateRange, sortMode], () => {{
      localStorage.setItem('sc-prefs', JSON.stringify({{
        matchedOnly:   matchedOnly.value,
        favoritesOnly: favoritesOnly.value,
        dateRange:     dateRange.value,
        sortMode:      sortMode.value,
      }}));
    }});

    return {{
      shows, expandedId, favsOpen, playlistOpen,
      dateRange, sortMode, matchedOnly, favoritesOnly,
      favoriteVenues, venueSearch,
      filteredShows, groupedShows,
      allVenueNames, venueGroups, showCountByVenue,
      setDate, resetFilters, favsChipClick, toggleExpand,
      scoreClass, fmtTime, isPast, isSoon,
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
