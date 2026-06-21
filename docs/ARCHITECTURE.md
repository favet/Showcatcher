# Architecture — Showcat

## Purpose

Turn your listening history into live-music discovery near Portland. Two outputs:

- **Spotify discovery playlist (hero):** tracks from artists playing upcoming Portland shows, weighted *toward* bands you've under-explored. The value is discovery, not reminders.
- **Ticket digest (companion):** upcoming shows by artists you already know, with on-sale dates and ticket links — because a playlist alone never tells you *when, where,* or *go buy now*.

## The model: a pipeline of independent stages, with the database as the bus

```
[Last.fm] ─► (ingest history) ─┐
                               ├─► Postgres ─► (resolve) ─► (score) ─► outputs ┬─► Spotify playlist
[venue sources] ─► (ingest events) ─┘                                         └─► ticket digest
```

Each box in the middle is a **stage**: an independent worker that reads its inputs from Postgres and writes its outputs to Postgres. **No stage calls another stage.** They communicate only through tables. This is the single most important structural decision — it's what makes the system additive (you can add a source, swap the scorer, or add an output without touching anything else) and debuggable (every hand-off is inspectable as data at rest).

### Stages
- **ingest/history** — pulls scrobbles from Last.fm (full backfill, then incremental), resolves artist identity to MBIDs.
- **ingest/events** — per-source adapters pull upcoming shows, normalize them, and diff snapshots to detect new shows and added openers.
- **resolve** — matches event artists to your taste artists (MBID first, fuzzy fallback with confidence).
- **score** — computes a decomposable, versioned score per upcoming show.
- **outputs/digest** and **outputs/playlist** — render the two deliverables behind output adapters.

## Why Postgres (not SQLite)

Multiple worker services write concurrently; SQLite's single-writer lock fights that. We also want real indexing on the event/snapshot history, JSON columns for raw captures, and reliable migrations. For a multi-worker pipeline, Postgres is the better fit even at single-user scale.

## Adapters: every external edge is isolated

All external IO lives behind an adapter with a narrow interface and committed fixtures:

- **Last.fm adapter** — history + artist top-tracks.
- **Source adapters** (`adapters/sources/<venue>/`) — one per venue or aggregator. Source-specific parsing never leaks past the adapter. Adding one is additive (see the recipe in `AGENTS.md`).
- **Spotify adapter** — search (URI resolution) + playlist write.

Adapters exist so the volatile outside world can change without breaking the engine, and so tests run offline against recorded responses. A **contract test** per adapter is the canary that fires the moment a venue redesigns its site or a vendor changes its API.

## Data model (overview)

- `scrobbles` — your listening history; unique on (timestamp, artist, track) for idempotent ingest.
- `artists` — canonical artist identities keyed by MBID; an unresolved queue holds anything that didn't map.
- `events` — normalized upcoming shows: `headliner`, `openers[]`, `date`, `venue`, `on_sale_date`, `ticket_url`, `source`, `source_id`, `first_seen`, `last_seen`.
- `event_snapshots` / change log — raw captures + detected changes (new event, added opener).
- `matches` — event-artist ↔ taste-artist links with confidence; low-confidence rows go to a review queue.
- `scores` — per-show score **with its full term breakdown persisted** (taste, adjacency, discovery, recency, distance) and the scoring-config version used.
- `run_ledger` — every stage run: what it touched, outcome, timing.
- `dead_letter` — every failed/unparseable record with enough context to replay.

## Entity resolution

The unglamorous hard part. Event listings give dirty strings ("Mt. Joy", free-text openers, DJ aliases); your taste profile has clean MBIDs. Resolution is MBID-first with a fuzzy fallback that emits a confidence score. **Low-confidence matches are never silently accepted or dropped** — they land in a review queue. This is a deliberate "no black box" choice.

## Scoring

Scoring is a **swappable, versioned module**. A show's score is the sum of named terms:

- **taste** — decayed affinity for the matched artist.
- **adjacency** — similarity to your taste vector (powers discovery of unknown bands).
- **discovery** — a boost for artists that are taste-adjacent **and** low in your personal play-count. This is the tilt the hero playlist depends on.
- **recency** — freshness of the underlying listening signal.
- **distance** — the venue's `close`/`near`/`far` band from the Valhalla ETA map.

Every term is persisted per show, so any ranking is fully explainable after the fact (`explain <show>`). Config is versioned so two scoring variants can be run on identical input and diffed — the project expects to A/B this repeatedly.

The decay model itself is simple (exponential, tunable half-life). The design effort goes into *what* is decayed (MBID-keyed artists, with tags as a secondary signal) and how the terms combine — neither is hardcoded; both are tuned in Phase 6.

## The Spotify bridge (and why it's behind an adapter)

Spotify's API has contracted repeatedly (audio-features/recommendations/related-artists deprecated Nov 2024; top-tracks, popularity, and per-user-id playlist-create removed Feb 2026; dev-mode now requires the owner to hold Premium). The surviving surface we rely on is narrow: `POST /me/playlists`, add/replace items, and `/search`.

So the bridge is a **hybrid**: pick representative tracks via **Last.fm** `artist.getTopTracks` (off the eroding API), resolve them to Spotify URIs via `/search`, then write via `/me/playlists`. The whole thing lives behind the output adapter, with an export-file fallback stub — if Spotify removes more, we swap the adapter, not the engine. Track selection is deliberately kept off Spotify so the discovery logic is never hostage to vendor churn.

## Diagnostics architecture

Observability is built in Phase 0, before any feature, so everything inherits it:

- **Structured logging** — JSON, one event per meaningful decision.
- **Run ledger** — the durable record of every stage run.
- **Dead-letter** — capture-and-continue for bad records; a single malformed event never sinks a run.
- **Anomaly detection** — a source returning zero (or far below trailing average) raises an alert; silent "no results" is the most common failure mode in scraping systems and we refuse to let it pass quietly.
- **Explain affordances** — score breakdowns and track-resolution decisions are both queryable.

## External dependencies & their failure modes

| Dependency | Used for | Main failure mode | Mitigation |
|---|---|---|---|
| Last.fm API | history, artist top-tracks | rate limits; slow backfill | resumable backfill, fixtures, local store of record |
| Venue sources | upcoming shows | silent layout change; zero results | contract tests, anomaly alerts, dead-letter |
| Spotify API | URI resolution, playlist write | further endpoint removal; Premium/dev-mode gate | adapter + export-file fallback; selection kept on Last.fm |
| Valhalla ETA map | distance bands | static, low risk | computed once per venue at registration |

## Deployment & Live Hosting (Local Web Server)

The `showcat.favet.net` website is hosted **locally** on this Windows machine and tunneled to the internet. 

**Infrastructure:**
- **Document Root**: `C:\website`
- **Web Server**: `Caddy` running as a Windows Service, bound to port 80 and serving `C:\website` as a `file_server`.
- **Tunneling**: `Cloudflared` running as a Windows Service, exposing the local Caddy web server to the public `showcat.favet.net` domain securely.

**Deployment Process ("Pushing Live"):**
The GitHub repository (`favet/showcat`) is the source of truth for the *codebase*, but **pushing code to GitHub does not deploy the website**.

To push website updates live:
1. Generate the static HTML using the backend tool:
   ```bash
   docker compose run --rm app python -m showcat.cli.web
   ```
   *This writes the generated HTML to `public/index.html` inside the project directory.*
2. Copy the generated file to the active Caddy document root:
   ```powershell
   Copy-Item C:\Users\Justin\Documents\SHOWCATCHER\public\index.html C:\website\showcat\index.html -Force
   ```
   *(Any changes copied to `C:\website\showcat\` are instantly live on the internet.)*

> **For Future Sessions:** When making frontend changes or updating the generated timeline, always execute both steps. Do not assume the live site updates from `public/index.html` automatically or from GitHub commits.
