"""Static HTML generator for showcat.favet.net.

Reads the last scored shows from the database, precomputed travel times from SQLite,
and renders a dynamic, interactive HTML timeline page using Vue.js via CDN.
"""
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

SPOTIFY_PLAYLIST_ID = os.environ.get("SPOTIFY_PLAYLIST_ID", "")
SQLITE_DB_PATH = os.environ.get("SQLITE_DB_PATH", r"C:\Users\Justin\Documents\PDX Shows\data\pdx.sqlite")
HOME_CELL_ID = "8828f0003dfffff"

VENUE_CAPACITIES = {
    "moda center": "large",
    "veterans memorial coliseum": "large",
    "arlene schnitzer concert hall": "large",
    "keller auditorium": "large",
    "mcmenamins historic edgefield manor": "large",
    "roseland theater": "large",
    "crystal ballroom": "large",
    "revolution hall": "mid",
    "revolution hall - portland": "mid",
    "wonder ballroom": "mid",
    "hawthorne theatre": "mid",
    "aladdin theater": "mid",
    "star theater": "mid",
    "dante's": "mid",
    "polaris hall": "small",
    "the get down music venue": "small",
    "mississippi studios": "small",
    "holocene": "small",
    "kelly's olympian": "small",
}

def normalize_venue_name(name: str) -> str:
    name = name.lower()
    for word in ["music venue", "theater", "theatre", "- portland", "mcmenamins historic", "manor", "and hotel"]:
        name = name.replace(word, "")
    return name.strip()

def canonical_show_key(venue: str, date_iso: str, headliner: str) -> tuple[str, str, str]:
    """Cross-source identity for a show: (normalised venue, date, normalised headliner).

    Lets a Ticketmaster-discovered event and a venue-direct (Etix) event for the
    same show collapse into one card so we can prefer the non-TM ticket link.
    """
    return (normalize(normalize_venue_name(venue)), date_iso, normalize(headliner))


def merge_shows_by_identity(raw_shows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate shows across sources, choosing the best ticket link.

    Within each canonical-key group the representative is the highest-scored
    entry (keeps its score/genres/travel), but the ticket link is the
    most-preferred across all siblings — so an Etix link supersedes the
    Ticketmaster duplicate. Order of first appearance (score desc) is kept.
    """
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
        rep = max(members, key=lambda s: (s.get("score_total") is not None, s.get("score_total") or -1.0))
        url, provider = best_link([m.get("ticket_url") for m in members])
        rep = dict(rep)
        rep["ticket_url"] = url
        rep["ticket_provider"] = provider
        rep["ticket_provider_label"] = provider_label(provider)
        merged.append(rep)
    return merged


def get_venue_capacity(venue_name: str) -> str:
    norm = venue_name.lower()
    for k, v in VENUE_CAPACITIES.items():
        if k in norm:
            return v
    return "mid" # default guess

def get_travel_times() -> dict[str, dict[str, Any]]:
    """Fetch travel times from SQLite."""
    times = {}
    if not os.path.exists(SQLITE_DB_PATH):
        logger.warning(f"SQLite DB not found at {SQLITE_DB_PATH}")
        return times
        
    try:
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        
        venues = conn.execute("SELECT venue_id, name FROM venues").fetchall()
        for v in venues:
            bm = conn.execute(
                "SELECT base_seconds, base_meters FROM base_matrix WHERE cell_id = ? AND venue_id = ?",
                (HOME_CELL_ID, v["venue_id"])
            ).fetchone()
            if bm:
                times[normalize_venue_name(v["name"])] = {
                    "minutes": round(bm["base_seconds"] / 60),
                    "miles": round(bm["base_meters"] / 1609.34, 1)
                }
        conn.close()
    except Exception as e:
        logger.error(f"Error querying SQLite: {e}")
        
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
    
    seen: set[int] = set()
    shows: list[dict[str, Any]] = []
    
    # Pre-fetch tags for all artists
    artist_ids = [row[3].id for row in rows if row[3] is not None]
    tags_rows = []
    if artist_ids:
        tags_rows = session.execute(
            select(ArtistTag)
            .where(ArtistTag.artist_id.in_(artist_ids))
        ).scalars().all()
    
    tags_by_artist = {}
    for t in tags_rows:
        tags_by_artist.setdefault(t.artist_id, []).append((t.tag, t.weight))
        
    for artist_id in tags_by_artist:
        tags_by_artist[artist_id] = [t[0] for t in sorted(tags_by_artist[artist_id], key=lambda x: x[1], reverse=True)[:3]]

    for event, score, _match, artist in rows:
        if event.id in seen:
            continue
        seen.add(event.id)
        
        # Match travel time
        norm_v = normalize_venue_name(event.venue)
        travel_info = None
        for k, v in travel_times.items():
            if norm_v == k or norm_v in k or k in norm_v:
                travel_info = v
                break
                
        genres = tags_by_artist.get(artist.id, []) if artist else []
        
        def format_t(t: dt.time) -> str:
            h = t.hour
            m = t.minute
            ampm = "AM" if h < 12 else "PM"
            h12 = h if h <= 12 else h - 12
            if h12 == 0:
                h12 = 12
            return f"{h12}:{m:02d} {ampm}"

        doors_display = format_t(event.doors_time) if event.doors_time else None
        show_display = format_t(event.show_time) if event.show_time else None
        
        # Determine exact timestamp for chronological sorting
        sort_time = event.show_time or event.doors_time or dt.time()
        timestamp = int(dt.datetime.combine(event.date, sort_time).timestamp())
        
        today = dt.date.today()
        if event.date == today:
            date_display = "TONIGHT"
        elif event.date == today + dt.timedelta(days=1):
            date_display = "TOMORROW"
        else:
            date_display = f"{event.date.strftime('%a %b')} {event.date.day}"
        
        ticket_provider = event.ticket_provider or classify_provider(event.ticket_url)
        shows.append(
            {
                "id": event.id,
                "headliner": event.headliner,
                "venue": event.venue,
                "date": event.date.isoformat(),
                "date_display": date_display,
                "doors_display": doors_display,
                "show_display": show_display,
                "ticket_url": event.ticket_url,
                "ticket_provider": ticket_provider,
                "ticket_provider_label": provider_label(ticket_provider),
                "score_total": round(score.score_total, 3) if score else None,
                "matched_artist": artist.raw_name if artist else None,
                "travel_minutes": travel_info["minutes"] if travel_info else None,
                "genres": genres,
                "source": event.source,
                "timestamp": timestamp
            }
        )

    # Collapse the same show across sources (TM + venue-direct), preferring the
    # non-Ticketmaster ticket link, then cap to the limit.
    merged = merge_shows_by_identity(shows)
    return merged[:limit]


def render_html(shows: list[dict[str, Any]], generated_at: dt.datetime) -> str:
    shows_json = json.dumps(shows)
    ts = generated_at.strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0">
  <title>Showcat — Portland Music Discovery</title>
  <meta name="description" content="Every upcoming Portland show, ranked by your taste.">
  <meta http-equiv="Content-Security-Policy" content="upgrade-insecure-requests">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">
  <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
  <style>
    :root {{
      --bg: #121212; --surface: #1E1E24; --surface-hover: #26262d;
      --text: #EBEBEB; --muted: #8A8D91; --border: #35353d;
      --accent: #00F0FF; --accent-dim: rgba(0,240,255,0.12);
      --amber: #FF0055; --amber-dim: rgba(255,0,85,0.12);
      --font-body: 'Inter', system-ui, sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }}
    body {{ background: var(--bg); color: var(--text); font-family: var(--font-body); line-height: 1.4; -webkit-font-smoothing: antialiased; }}
    a {{ color: var(--accent); text-decoration: none; }}
    
    header {{ padding: 1.5rem 1rem 1rem; border-bottom: 1px solid var(--border); background: var(--bg); }}
    .header-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }}
    header h1 {{ font-size: 1.25rem; font-weight: 700; letter-spacing: -0.02em; }}
    header h1 span {{ color: var(--accent); }}
    .header-actions button {{ background: none; border: 1px solid var(--border); color: var(--text); padding: 0.4rem 0.75rem; border-radius: 6px; font-size: 0.8rem; cursor: pointer; margin-left: 0.5rem; }}
    
    .filters-bar {{ display: flex; gap: 0.5rem; }}
    .filter-select {{ flex: 1; padding: 0.5rem; font-size: 0.85rem; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 6px; outline: none; }}
    .filter-btn {{ padding: 0.5rem 0.75rem; font-size: 0.85rem; font-weight: 500; background: var(--surface); color: var(--muted); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; white-space: nowrap; }}
    .filter-btn.active {{ background: var(--accent); color: var(--bg); border-color: var(--accent); font-weight: 700; }}
    
    .layout {{ max-width: 800px; margin: 0 auto; padding-bottom: 3rem; }}

    .sticky-date {{
      position: sticky; top: 0; z-index: 9;
      background: rgba(18, 18, 18, 0.95); backdrop-filter: blur(8px);
      padding: 0.5rem 1rem; border-bottom: 1px solid var(--border);
      font-family: var(--font-mono); font-size: 0.75rem; font-weight: 600; color: var(--muted);
      text-transform: uppercase; letter-spacing: 0.05em;
    }}

    .row-item {{
      border-bottom: 1px solid var(--border); padding: 0.75rem 1rem;
      cursor: pointer; transition: background 0.15s;
      user-select: none; -webkit-user-select: none; touch-action: manipulation;
    }}
    .row-item:hover {{ background: var(--surface); }}
    .row-item.past {{ opacity: 0.4; }}

    .row-core {{ display: grid; grid-template-columns: 4rem 1fr auto; gap: 0.75rem; align-items: flex-start; }}
    .col-expand {{ font-size: 0.6rem; color: var(--muted); padding-top: 0.35rem; line-height: 1; opacity: 0.6; }}
    
    .col-time {{ font-family: var(--font-mono); font-size: 0.85rem; color: var(--accent); font-weight: 600; padding-top: 0.1rem; display: flex; flex-direction: column; gap: 0.2rem; }}
    .time-label {{ font-size: 0.65rem; color: var(--muted); opacity: 0.8; margin-left: 0.2rem; }}
    .col-time.soon {{ color: var(--amber); }}

    .col-main {{ display: flex; flex-direction: column; gap: 0.15rem; }}
    .headliner {{ font-size: 1.05rem; font-weight: 700; color: var(--text); line-height: 1.2; }}
    .venue-info {{ font-size: 0.8rem; color: var(--muted); font-weight: 500; display: flex; align-items: center; gap: 0.4rem; }}

    .row-expanded {{
      margin-top: 0.75rem; margin-left: 4.75rem; padding-top: 0.75rem;
      border-top: 1px dashed var(--border);
      display: flex; flex-direction: column; gap: 0.5rem;
      animation: slideDown 0.2s ease-out forwards;
    }}
    @keyframes slideDown {{ from {{ opacity: 0; transform: translateY(-5px); }} to {{ opacity: 1; transform: translateY(0); }} }}
    
    .drawer-tags {{ display: flex; flex-wrap: wrap; gap: 0.3rem; }}
    .drawer-tag {{ font-size: 0.7rem; padding: 0.2rem 0.4rem; border-radius: 4px; background: var(--surface-hover); color: var(--muted); }}
    
    .drawer-actions {{ display: flex; justify-content: space-between; align-items: center; margin-top: 0.25rem; }}
    .ticket-btn {{ font-size: 0.8rem; font-weight: 600; color: var(--bg); background: var(--accent); padding: 0.35rem 0.75rem; border-radius: 4px; display: inline-flex; align-items: center; gap: 0.3rem; }}
    .ticket-btn--tm {{ background: var(--muted); }}
    .ticket-via {{ font-size: 0.65rem; font-weight: 500; opacity: 0.85; }}
    .travel-chip {{ font-family: var(--font-mono); font-size: 0.75rem; color: var(--muted); }}
    .score-chip {{ font-family: var(--font-mono); font-size: 0.75rem; color: var(--accent); background: var(--accent-dim); padding: 0.15rem 0.4rem; border-radius: 4px; }}

    .empty {{ text-align: center; padding: 4rem 1rem; color: var(--muted); font-size: 0.9rem; }}
    
    /* Modals */
    .modal-overlay {{ position: fixed; inset: 0; background: rgba(0,0,0,0.8); z-index: 40; display: flex; align-items: center; justify-content: center; opacity: 0; pointer-events: none; transition: opacity 0.2s; }}
    .modal-overlay.open {{ opacity: 1; pointer-events: all; }}
    .modal {{ background: var(--bg); border: 1px solid var(--border); width: 90%; max-width: 400px; max-height: 90vh; overflow-y: auto; border-radius: 12px; padding: 1.5rem; }}
    .modal-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; position: sticky; top: -1.5rem; background: var(--bg); padding-bottom: 1rem; border-bottom: 1px solid var(--border); }}
    .modal-close {{ background: none; border: none; color: var(--text); font-size: 1.5rem; cursor: pointer; }}
    
    .venue-search {{ width: 100%; padding: 0.5rem 0.6rem; font-size: 0.85rem; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 6px; outline: none; margin-bottom: 0.75rem; }}
    .venue-search:focus {{ border-color: var(--accent); }}
    .venue-section-label {{ font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); padding: 0.5rem 0 0.25rem; }}
    .venue-list {{ display: flex; flex-direction: column; gap: 0.25rem; }}
    .venue-row {{ display: flex; align-items: center; gap: 0.75rem; font-size: 0.9rem; padding: 0.4rem 0; cursor: pointer; }}
    .venue-row input {{ accent-color: var(--accent); width: 16px; height: 16px; flex-shrink: 0; }}
    .modal-fav-actions {{ display: flex; gap: 0.5rem; margin-bottom: 0.75rem; }}
    .modal-fav-actions button {{ flex: 1; padding: 0.35rem 0; font-size: 0.75rem; background: var(--surface); color: var(--muted); border: 1px solid var(--border); border-radius: 4px; cursor: pointer; }}
  </style>
</head>
<body>
  <div id="app">
    <header>
      <div class="header-top">
        <h1>Show<span>cat</span></h1>
        <div class="header-actions">
          <button @click="favsOpen = true">Venue Favs</button>
          <button @click="playlistOpen = true">🎵 Playlist</button>
        </div>
      </div>
      <div class="filters-bar">
        <select class="filter-select" v-model="filters.connection">
          <option value="all">All Shows Chronological</option>
          <option value="recommended">Top Picks (Connected to Taste)</option>
        </select>
        <button class="filter-btn" :class="{{active: filters.favoritesOnly}}" @click="filters.favoritesOnly = !filters.favoritesOnly">
          {{{{ filters.favoritesOnly ? '★ Favs Only' : '☆ Venues' }}}}
        </button>
      </div>
    </header>

    <div class="layout">
      <div v-if="filteredShows.length === 0" class="empty">No shows match your filters.</div>
      
      <div v-for="group in groupedShows" :key="group.date">
        <div class="sticky-date">{{{{ group.date }}}}</div>
        
        <div v-for="show in group.shows" :key="show.id" :data-row-id="show.id" class="row-item" :class="{{ past: isPast(show.timestamp) }}" @click="toggleExpand(show.id)">
          <div class="row-core">
            <div class="col-time" :class="{{ soon: isSoon(show.timestamp) }}">
              <div v-if="show.doors_display">
                {{{{ formatTime(show.doors_display) }}}}<span class="time-label">d</span>
              </div>
              <div v-if="show.show_display">
                {{{{ formatTime(show.show_display) }}}}<span class="time-label">s</span>
              </div>
              <div v-if="!show.doors_display && !show.show_display">TBA</div>
            </div>
            <div class="col-main">
              <div class="headliner">{{{{ show.headliner }}}}</div>
              <div class="venue-info">
                {{{{ show.venue }}}}
                <span v-if="show.score_total !== null" class="score-chip">{{{{ show.score_total.toFixed(2) }}}}</span>
              </div>
            </div>
            <div class="col-expand">{{{{ expandedRow === show.id ? '▲' : '▾' }}}}</div>
          </div>
          
          <div class="row-expanded" v-if="expandedRow === show.id">
            <div class="drawer-tags" v-if="show.genres && show.genres.length">
              <span class="drawer-tag" v-for="g in show.genres.slice(0,4)">{{{{ g }}}}</span>
            </div>
            <div style="font-size: 0.75rem; color: var(--muted); margin-top: 0.4rem;" v-if="show.matched_artist">
              Matched via {{{{ show.matched_artist }}}}
            </div>
            <div class="drawer-actions">
              <span class="travel-chip" v-if="show.travel_minutes">{{{{ show.travel_minutes }}}}m drive</span>
              <span v-else></span>
              <a v-if="show.ticket_url" :href="show.ticket_url" target="_blank" class="ticket-btn" :class="{{ 'ticket-btn--tm': show.ticket_provider === 'ticketmaster' }}" @click.stop>Tickets<span v-if="show.ticket_provider_label && show.ticket_provider_label !== 'Tickets'" class="ticket-via">via {{{{ show.ticket_provider_label }}}}</span> &rarr;</a>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Favorites Modal -->
    <div class="modal-overlay" :class="{{open: favsOpen}}" @click="favsOpen = false">
      <div class="modal" @click.stop>
        <div class="modal-header">
          <h3 style="font-size:1rem;">Favorite Venues</h3>
          <button class="modal-close" @click="favsOpen = false">&times;</button>
        </div>
        <p style="font-size: 0.8rem; color: var(--muted); margin-bottom: 0.75rem;">Select venues you frequent. Use <strong>★ Favs Only</strong> to filter the list.</p>
        <input class="venue-search" type="text" v-model="venueSearch" placeholder="Search venues…" autocomplete="off">
        <div class="modal-fav-actions">
          <button @click="favoriteVenues = [...allVenues]">Select all</button>
          <button @click="favoriteVenues = []">Clear all</button>
        </div>
        <div class="venue-list">
          <template v-for="group in groupedVenueOptions" :key="group.letter">
            <div class="venue-section-label" v-if="group.venues.length">{{{{ group.letter }}}}</div>
            <label class="venue-row" v-for="venue in group.venues" :key="venue">
              <input type="checkbox" :value="venue" v-model="favoriteVenues">
              {{{{ venue }}}}
            </label>
          </template>
          <div v-if="filteredVenuesForModal.length === 0" style="font-size:0.85rem; color:var(--muted); padding:0.5rem 0;">No venues match.</div>
        </div>
      </div>
    </div>

    <!-- Playlist Modal -->
    <div class="modal-overlay" :class="{{open: playlistOpen}}" @click="playlistOpen = false">
      <div class="modal" @click.stop>
        <div class="modal-header">
          <h3 style="font-size:1rem;">Discovery Playlist</h3>
          <button class="modal-close" @click="playlistOpen = false">&times;</button>
        </div>
        <iframe style="border-radius:12px;" src="https://open.spotify.com/embed/playlist/{os.environ.get('SPOTIFY_PLAYLIST_ID', '')}?utm_source=generator&theme=0" width="100%" height="352" frameBorder="0" allowfullscreen allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture" loading="lazy" v-if="playlistOpen"></iframe>
      </div>
    </div>
  </div>

  <script>
    const rawShows = {shows_json};
    const {{ createApp, ref, computed, watch, onMounted, onUnmounted, nextTick }} = Vue;
    createApp({{
      setup() {{
        const shows = ref(rawShows);
        const expandedRow = ref(null);
        const playlistOpen = ref(false);
        const favsOpen = ref(false);
        const filters = ref({{ connection: 'all', favoritesOnly: false }});
        const favoriteVenues = ref([]);
        const venueSearch = ref('');
        const now = ref(Date.now() / 1000);
        
        // Extract all unique venues
        const allVenues = computed(() => {{
          const v = new Set(shows.value.map(s => s.venue));
          return Array.from(v).sort();
        }});

        // Modal venue list filtered by search
        const filteredVenuesForModal = computed(() => {{
          const q = venueSearch.value.toLowerCase().trim();
          if (!q) return allVenues.value;
          return allVenues.value.filter(v => v.toLowerCase().includes(q));
        }});

        // Alphabetical groups for modal
        const groupedVenueOptions = computed(() => {{
          const letters = {{}};
          filteredVenuesForModal.value.forEach(v => {{
            const l = v[0].toUpperCase();
            if (!letters[l]) letters[l] = [];
            letters[l].push(v);
          }});
          return Object.keys(letters).sort().map(l => ({{ letter: l, venues: letters[l] }}));
        }});
        
        let timer;
        onMounted(() => {{ 
          const s = localStorage.getItem('showcat-favorites'); 
          if (s) favoriteVenues.value = JSON.parse(s); 
          timer = setInterval(() => {{ now.value = Date.now() / 1000; }}, 60000);
        }});
        onUnmounted(() => clearInterval(timer));

        watch(favoriteVenues, (v) => {{ localStorage.setItem('showcat-favorites', JSON.stringify(v)); }}, {{ deep: true }});
        
        const toggleExpand = async (id) => {{
          if (expandedRow.value === id) {{ expandedRow.value = null; return; }}
          expandedRow.value = id;
          await nextTick();
          // If the expanded drawer is below the visible viewport, scroll it into view.
          const drawer = document.querySelector(`[data-row-id="${{id}}"] .row-expanded`);
          if (drawer) {{
            const rect = drawer.getBoundingClientRect();
            if (rect.bottom > window.innerHeight - 12) {{
              drawer.scrollIntoView({{ block: 'nearest', behavior: 'smooth' }});
            }}
          }}
        }};

        const formatTime = (t) => {{
          if (!t) return '';
          return t.replace(/^0/, '').replace(' PM', 'p').replace(' AM', 'a');
        }};

        const isPast = (ts) => ts < now.value - 7200; // 2 hours after start time
        const isSoon = (ts) => ts > now.value && ts < now.value + 7200;

        const filteredShows = computed(() => {{
          let r = shows.value.filter(s => {{
            if (filters.value.connection === 'recommended' && s.score_total === null) return false;
            if (filters.value.favoritesOnly && !favoriteVenues.value.includes(s.venue)) return false;
            return true;
          }});
          // ALWAYS sort chronologically now.
          r.sort((a, b) => a.timestamp - b.timestamp);
          return r;
        }});

        const groupedShows = computed(() => {{
          const groups = {{}};
          filteredShows.value.forEach(s => {{
            const d = s.date_display;
            if (!groups[d]) groups[d] = [];
            groups[d].push(s);
          }});
          return Object.keys(groups).map(k => ({{ date: k, shows: groups[k] }}));
        }});

        return {{
          shows, filters, filteredShows, groupedShows, allVenues, expandedRow,
          playlistOpen, favsOpen, favoriteVenues, venueSearch, filteredVenuesForModal,
          groupedVenueOptions, toggleExpand, formatTime, isPast, isSoon
        }};
      }}
    }}).mount('#app');
  </script>
</body>
</html>"""



class WebOutputAdapter(BaseOutputAdapter):
    def __init__(
        self,
        output_dir: str | None = None,
        scoring_version: str | None = None,
    ) -> None:
        self._output_dir = Path(output_dir or os.environ.get("WEB_OUTPUT_DIR", "public"))
        self._scoring_version = scoring_version or os.environ.get("SCORING_VERSION", "discovery-v1")

    @property
    def output_name(self) -> str:
        return "web"

    def build(self, session: Session) -> str:
        shows = _query_shows(session, self._scoring_version)
        now = dt.datetime.now(dt.UTC)
        return render_html(shows, now)

    def write(self, session: Session) -> Path:
        html_content = self.build(session)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._output_dir / "index.html"
        out_path.write_text(html_content, encoding="utf-8")
        logger.info("Web output written", extra={"path": str(out_path)})
        return out_path

