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

from showcat.ingest.events.models import Event
from showcat.ingest.history.models import Artist, ArtistTag
from showcat.outputs.base import BaseOutputAdapter
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

def _query_shows(session: Session, scoring_version: str, limit: int = 100) -> list[dict[str, Any]]:
    today = dt.date.today()
    rows = (
        session.execute(
            select(Event, EventScore, EventMatch, Artist)
            .join(EventScore, EventScore.event_id == Event.id)
            .join(EventMatch, EventMatch.event_id == Event.id)
            .join(Artist, Artist.id == EventMatch.artist_id)
            .where(EventScore.scoring_version == scoring_version)
            .where(EventMatch.status == "matched")
            .where(Event.date >= today)
            .order_by(EventScore.score_total.desc(), Event.date.asc())
        )
        .unique()
        .all()
    )

    travel_times = get_travel_times()
    
    seen: set[int] = set()
    shows: list[dict[str, Any]] = []
    
    # Pre-fetch tags for all artists
    artist_ids = [row[3].id for row in rows]
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
                
        genres = tags_by_artist.get(artist.id, [])
        
        shows.append(
            {
                "id": event.id,
                "headliner": event.headliner,
                "venue": event.venue,
                "capacity": get_venue_capacity(event.venue),
                "date": event.date.isoformat(),
                "date_display": f"{event.date.strftime('%a %b')} {event.date.day}, {event.date.year}",
                "ticket_url": event.ticket_url,
                "score_total": round(score.score_total, 3),
                "matched_artist": artist.raw_name,
                "travel_minutes": travel_info["minutes"] if travel_info else None,
                "travel_miles": travel_info["miles"] if travel_info else None,
                "genres": genres,
                "timestamp": int(dt.datetime.combine(event.date, dt.time()).timestamp())
            }
        )
        if len(shows) >= limit:
            break
    return shows


def render_html(shows: list[dict[str, Any]], generated_at: dt.datetime) -> str:
    shows_json = json.dumps(shows)
    ts = generated_at.strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Showcat — Portland Music Discovery</title>
  <meta name="description" content="Upcoming Portland shows weighted toward artists you haven't fully explored yet.">
  
  <!-- Force HTTPS -->
  <meta http-equiv="Content-Security-Policy" content="upgrade-insecure-requests">
  
  <!-- Prevent browser caching of the HTML file so users always get the latest updates -->
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Outfit:wght@500;600;700;800&display=swap" rel="stylesheet">
  <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
  <style>
    :root {{
      --bg: #09090b;
      --bg-gradient: radial-gradient(circle at top, #1e1330 0%, #09090b 60%);
      --surface: rgba(20, 20, 25, 0.7);
      --surface-hover: rgba(28, 28, 35, 0.9);
      --accent: #10b981;
      --accent-hover: #34d399;
      --accent-glow: rgba(16, 185, 129, 0.15);
      --text: #f4f4f5;
      --muted: #a1a1aa;
      --border: rgba(63, 63, 70, 0.5);
      --border-hover: rgba(16, 185, 129, 0.4);
      --font-display: 'Outfit', system-ui, -apple-system, sans-serif;
      --font-body: 'Inter', system-ui, -apple-system, sans-serif;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background-color: var(--bg);
      background-image: var(--bg-gradient);
      background-attachment: fixed;
      color: var(--text);
      font-family: var(--font-body);
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
      padding-bottom: 4rem;
    }}
    a {{ color: var(--accent); text-decoration: none; transition: color 0.2s ease; }}
    a:hover {{ color: var(--accent-hover); }}
    
    header {{ max-width: 1000px; margin: 0 auto; padding: 3rem 1.5rem 2rem; text-align: center; }}
    header h1 {{
      font-family: var(--font-display); font-size: 2.5rem; font-weight: 800; letter-spacing: -0.03em;
      margin-bottom: 0.5rem; background: linear-gradient(135deg, #fff 30%, var(--accent) 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }}
    header p {{ color: var(--muted); font-size: 1rem; max-width: 600px; margin: 0 auto; }}
    
    .layout-grid {{
      max-width: 1000px; margin: 0 auto; padding: 0 1.5rem;
      display: grid; grid-template-columns: 1fr; gap: 2rem;
    }}
    @media (min-width: 768px) {{
      .layout-grid {{ grid-template-columns: 280px 1fr; align-items: start; }}
    }}
    
    .panel {{
      background: var(--surface); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
      border: 1px solid var(--border); border-radius: 14px; padding: 1.5rem;
    }}
    
    .filters h3 {{ font-family: var(--font-display); margin-bottom: 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }}
    .filter-group {{ margin-bottom: 1.5rem; }}
    .filter-group label {{ display: block; margin-bottom: 0.5rem; font-weight: 500; font-size: 0.9rem; color: var(--muted); }}
    
    .checkbox-item {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.4rem; font-size: 0.9rem; cursor: pointer; }}
    .checkbox-item input {{ accent-color: var(--accent); width: 16px; height: 16px; cursor: pointer; }}
    
    .timeline-container {{ display: flex; flex-direction: column; gap: 1rem; position: relative; }}
    
    .show-card {{
      background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
      padding: 1.25rem 1.5rem; transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
      display: flex; flex-direction: column; gap: 0.75rem; position: relative;
    }}
    .show-card:hover {{
      background: var(--surface-hover); border-color: var(--border-hover);
      transform: translateY(-2px); box-shadow: 0 12px 30px rgba(0, 0, 0, 0.4), 0 0 15px var(--accent-glow);
    }}
    
    .show-header {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }}
    .show-headliner {{ font-family: var(--font-display); font-size: 1.25rem; font-weight: 700; color: #fff; }}
    .show-details {{ color: var(--muted); font-size: 0.9rem; margin-top: 0.15rem; display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }}
    
    .venue-name {{ display: inline-flex; align-items: center; gap: 0.3rem; }}
    .star-btn {{ background: none; border: none; color: var(--muted); cursor: pointer; font-size: 1.1rem; padding: 0; line-height: 1; transition: color 0.2s; }}
    .star-btn:hover {{ color: #fbbf24; }}
    .star-btn.active {{ color: #fbbf24; }}
    
    .score-badge {{
      background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.25);
      border-radius: 8px; padding: 0.35rem 0.6rem; text-align: center; min-width: 50px;
    }}
    .score-num {{ font-family: var(--font-display); font-size: 1rem; font-weight: 700; color: var(--accent); }}
    
    .tags {{ display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.5rem; }}
    .tag {{ background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.75rem; }}
    
    .travel-pill {{ background: rgba(59, 130, 246, 0.1); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.2); padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.75rem; display: inline-flex; align-items: center; gap: 0.2rem; }}
    
    .ticket-btn {{
      background: var(--accent); color: #09090b; font-weight: 600; font-size: 0.85rem;
      padding: 0.4rem 0.9rem; border-radius: 6px; display: inline-block; margin-top: 0.5rem;
    }}
    .ticket-btn:hover {{ background: var(--accent-hover); }}
    
    .drawer-overlay {{
      position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); backdrop-filter: blur(4px);
      z-index: 40; opacity: 0; pointer-events: none; transition: opacity 0.3s;
    }}
    .drawer-overlay.open {{ opacity: 1; pointer-events: all; }}
    
    .drawer {{
      position: fixed; top: 0; right: -400px; width: 100%; max-width: 400px; height: 100vh;
      background: #09090b; border-left: 1px solid var(--border); z-index: 50;
      transition: right 0.3s cubic-bezier(0.4, 0, 0.2, 1); padding: 1.5rem; display: flex; flex-direction: column;
    }}
    .drawer.open {{ right: 0; }}
    .drawer-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }}
    .drawer-close {{ background: none; border: none; color: var(--text); font-size: 1.5rem; cursor: pointer; }}
    
    .drawer-btn {{ background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 0.5rem 1rem; border-radius: 8px; cursor: pointer; font-weight: 500; margin-bottom: 1rem; }}
    .drawer-btn:hover {{ background: var(--surface-hover); border-color: var(--border-hover); }}
    
    .empty-state {{ text-align: center; padding: 3rem; color: var(--muted); }}
    
  </style>
</head>
<body>
  <div id="app">
    <header>
      <h1>Show<span>cat</span></h1>
      <p>Chronological timeline of top recommended Portland shows.</p>
    </header>
    
    <div class="layout-grid">
      <!-- Filters Sidebar -->
      <aside class="panel filters">
        <h3>Filters</h3>
        
        <div class="filter-group">
          <label>Favorites</label>
          <label class="checkbox-item">
            <input type="checkbox" v-model="filters.favoritesOnly">
            Show only starred venues ({{{{ favoriteVenues.length }}}})
          </label>
        </div>
        
        <div class="filter-group">
          <label>Max Travel Time (from Home)</label>
          <input type="range" v-model="filters.maxTravelMins" min="5" max="60" step="5" style="width:100%">
          <div style="text-align:right; font-size:0.8rem; color:var(--muted)">
            {{{{ filters.maxTravelMins }}}} mins
          </div>
        </div>
        
        <div class="filter-group">
          <label>Venue Size</label>
          <label class="checkbox-item"><input type="checkbox" value="small" v-model="filters.sizes"> Small (&lt;300)</label>
          <label class="checkbox-item"><input type="checkbox" value="mid" v-model="filters.sizes"> Mid (300-1000)</label>
          <label class="checkbox-item"><input type="checkbox" value="large" v-model="filters.sizes"> Large (&gt;1000)</label>
        </div>
        
        <div class="filter-group">
          <label>Sort By</label>
          <select v-model="filters.sortBy" style="width:100%; padding:0.4rem; background:rgba(255,255,255,0.05); color:white; border:1px solid var(--border); border-radius:4px;">
            <option value="date">Chronological (Date)</option>
            <option value="score">Top Score</option>
          </select>
        </div>
        
        <button class="drawer-btn" style="width:100%" @click="drawerOpen = true">
          🎵 Open Spotify Playlist
        </button>
      </aside>

      <!-- Timeline -->
      <main class="timeline-container">
        <div style="font-size:0.9rem; color:var(--muted); margin-bottom:0.5rem">
          Showing {{{{ filteredShows.length }}}} of {{{{ shows.length }}}} upcoming shows
        </div>
        
        <div v-if="filteredShows.length === 0" class="empty-state">
          No shows match your filters. Try adjusting them.
        </div>
        
        <article v-for="show in filteredShows" :key="show.id" class="show-card">
          <div class="show-header">
            <div>
              <h2 class="show-headliner">{{{{ show.headliner }}}}</h2>
              <div class="show-details">
                <span>{{{{ show.date_display }}}}</span>
                <span>&bull;</span>
                <span class="venue-name">
                  {{{{ show.venue }}}}
                  <button class="star-btn" :class="{{active: isFavorite(show.venue)}}" @click="toggleFavorite(show.venue)" title="Toggle Favorite">
                    ★
                  </button>
                </span>
                <span v-if="show.travel_minutes" class="travel-pill">
                  🚗 {{{{ show.travel_minutes }}}} min
                </span>
              </div>
            </div>
            <div class="score-badge" title="Discovery Score">
              <span class="score-num">{{{{ show.score_total.toFixed(1) }}}}</span>
            </div>
          </div>
          
          <div>
            <div style="font-size:0.85rem; color:var(--muted)">Matched via <strong>{{{{ show.matched_artist }}}}</strong></div>
            <div class="tags" v-if="show.genres && show.genres.length">
              <span class="tag" v-for="g in show.genres">{{{{ g }}}}</span>
            </div>
          </div>
          
          <div>
            <a v-if="show.ticket_url" :href="show.ticket_url" target="_blank" class="ticket-btn">Get tickets &rarr;</a>
          </div>
        </article>
      </main>
    </div>
    
    <!-- Spotify Drawer -->
    <div class="drawer-overlay" :class="{{open: drawerOpen}}" @click="drawerOpen = false"></div>
    <div class="drawer" :class="{{open: drawerOpen}}">
      <div class="drawer-header">
        <h3 style="font-family:var(--font-display)">Discovery Playlist</h3>
        <button class="drawer-close" @click="drawerOpen = false">&times;</button>
      </div>
      <iframe style="border-radius:12px; flex-grow:1" src="https://open.spotify.com/embed/playlist/{SPOTIFY_PLAYLIST_ID}?utm_source=generator&theme=0" width="100%" height="100%" frameBorder="0" allowfullscreen="" allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture" loading="lazy" v-if="drawerOpen"></iframe>
    </div>
    
    <footer style="text-align:center; padding: 2rem; color:var(--muted); font-size:0.85rem; margin-top:2rem; border-top:1px solid var(--border)">
      Generated {ts} &middot; Taste from <a href="https://www.last.fm/user/j-m-f" target="_blank">Last.fm</a>
    </footer>
  </div>

  <script>
    const rawShows = {shows_json};
    
    const {{ createApp, ref, computed, watch, onMounted }} = Vue;

    createApp({{
      setup() {{
        const shows = ref(rawShows);
        const drawerOpen = ref(false);
        
        const filters = ref({{
          favoritesOnly: false,
          maxTravelMins: 60,
          sizes: ['small', 'mid', 'large'],
          sortBy: 'date'
        }});
        
        const favoriteVenues = ref([]);
        
        onMounted(() => {{
          const saved = localStorage.getItem('showcat-favorites');
          if (saved) {{
            favoriteVenues.value = JSON.parse(saved);
          }}
        }});
        
        watch(favoriteVenues, (newVals) => {{
          localStorage.setItem('showcat-favorites', JSON.stringify(newVals));
        }}, {{ deep: true }});
        
        const isFavorite = (venue) => favoriteVenues.value.includes(venue);
        
        const toggleFavorite = (venue) => {{
          if (isFavorite(venue)) {{
            favoriteVenues.value = favoriteVenues.value.filter(v => v !== venue);
          }} else {{
            favoriteVenues.value.push(venue);
          }}
        }};
        
        const filteredShows = computed(() => {{
          let result = shows.value.filter(show => {{
            // Travel time filter
            if (show.travel_minutes && show.travel_minutes > filters.value.maxTravelMins) return false;
            
            // Size filter
            if (!filters.value.sizes.includes(show.capacity)) return false;
            
            // Favorites filter
            if (filters.value.favoritesOnly && !isFavorite(show.venue)) return false;
            
            return true;
          }});
          
          if (filters.value.sortBy === 'date') {{
            result.sort((a, b) => a.timestamp - b.timestamp);
          }} else {{
            result.sort((a, b) => b.score_total - a.score_total);
          }}
          
          return result;
        }});
        
        return {{
          shows, filters, filteredShows, drawerOpen,
          favoriteVenues, isFavorite, toggleFavorite
        }}
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

