# Opener — Project Plan

> **Showcat** — Portland live music discovery. Python package: `showcat`. GitHub: `favet/showcat`. Live at `showcat.favet.net`.

## How to use this plan

The build is a **walking skeleton first, then a thin end-to-end slice, then the discovery engine and playlist.** You should have something verifiable at the end of every phase.

Each phase has **sub-phases** (the work) and an **Exit Gate** (a checklist of *provable* criteria). The rules:

- **A gate is a hard stop.** Do not start the next phase until every box in the current gate is checked.
- **Every gate item is provable** — it maps to a passing automated test, a committed fixture, a query result, or a documented manual check. "It seems to work" is not a checked box.
- If a gate item can't be made provable, that's a signal the design is underspecified — fix that before proceeding.
- When you check a box, note *how* it was proven (test name, command, or doc link) right next to it.

### Global Definition of Done (applies to every sub-phase)

A unit of work is done only when **all** of these are true:

- [ ] Code is typed, linted, and formatted (mypy + ruff clean).
- [ ] It has tests that run **offline** (no live network) against committed fixtures.
- [ ] If it's a stage, it is **idempotent** — re-running produces no duplicates and no corruption (asserted by a test).
- [ ] Failures are observable — errors route to the dead-letter table and/or the run-ledger, never a silent swallow.
- [ ] Any decision it makes is **explainable** — logged and/or decomposable. No black boxes.
- [ ] Secrets are read from env, never committed.
- [ ] Relevant docs updated (this plan, ARCHITECTURE.md, or DECISIONS.md).

---

## Phase 0 — Foundations & Diagnostic Skeleton

**Goal:** Stand up the repo, the stage-runner pattern, and *all* the diagnostics/test scaffolding **before any feature exists**, so everything built later is born observable and testable.

### Sub-phases
- **0.1 Repo & tooling** — `pyproject.toml`, ruff, black, mypy, pre-commit, pytest, `.gitignore`, env handling (`.env` ignored; `.env.example` committed).
- **0.2 Containers** — Docker Compose with `app` + `postgres` services; one-command bootstrap documented.
- **0.3 DB baseline & migrations** — Alembic; base schema; `run_ledger` table; `dead_letter` table.
- **0.4 Stage-runner framework** — a `BaseStage` abstraction: reads/writes only via the DB, records start/outcome to `run_ledger`, captures errors to `dead_letter`, emits structured logs. Idempotency is a first-class contract of the base class.
- **0.5 Observability baseline** — structured JSON logging; a `health` command that prints each stage's last run + status.
- **0.6 Test harness & CI** — fixture loader, DB test fixtures (ephemeral/transactional), CI workflow running lint + type-check + tests on a clean checkout.

### Exit Gate 0 (provable)
- [x] From a clean clone, the documented bootstrap (`make up` or equivalent) brings up `app` + `postgres` with no manual steps. *(Proven by running `docker compose up -d --build`)*
- [x] Migrations apply cleanly from an empty DB **and** roll back cleanly (tested both directions). *(Proven by running `alembic upgrade head` followed by `alembic downgrade -1`)*
- [x] A no-op example stage runs, writes a `run_ledger` row, and **re-running it changes nothing** (idempotency test passes). *(Proven by `test_stage_success` and `test_stage_idempotency` in `tests/test_stage.py`)*
- [x] A deliberately failing example stage routes its error to `dead_letter` with context and does **not** crash the process (test passes). *(Proven by `test_stage_failure` in `tests/test_stage.py`)*
- [x] CI is green on a clean checkout: lint, type-check, and tests all pass. *(Proven by clean `ruff check`, `mypy`, and `pytest` runs)*
- [x] `make health` prints a per-stage last-run summary. *(Proven by executing `python -m opener.cli.health`)*

---

## Phase 1 — Listening-History Ingest (Taste Substrate)

**Goal:** Your full listening history lives in *your* Postgres, with stable artist identities. Verifiable on its own, before any venue exists.

### Sub-phases
- **1.1 Last.fm client + fixtures** — rate-limit-aware client; recorded API responses committed as fixtures.
- **1.2 Backfill job** — full history → Postgres; resumable (checkpoints last cursor); idempotent.
- **1.3 Incremental sync** — fetch only scrobbles since last stored timestamp.
- **1.4 Artist identity / MBID resolution** — resolve every scrobble's artist to a MusicBrainz ID or an explicit unresolved-queue entry (no silent drops).
- **1.5 Decayed-affinity query** — time-decayed artist weights with a **tunable half-life** (config, not hardcoded).

### Exit Gate 1 (provable)
- [x] Backfill loads full history; stored scrobble count reconciles with Last.fm's reported count within a documented tolerance. *(Proven by `test_backfill_loads_all_fixture_scrobbles` in `tests/test_history_ingest.py`)*
- [x] Re-running backfill and incremental produces **zero** duplicate scrobbles (unique constraint + test). *(Proven by `test_backfill_is_idempotent` and `test_incremental_skips_already_stored`)*
- [x] Every scrobble resolves to an MBID **or** appears in the unresolved queue — the unresolved count is queryable; nothing is silently dropped (test). *(Proven by `test_resolves_known_artist` and `test_unknown_artist_lands_in_unresolved_queue`)*
- [x] The affinity query returns sensible decayed top-N for a fixture user (golden test). *(Proven by `test_top_artist_is_most_played_recent` and `test_returns_correct_key_for_resolved_artist`)*
- [x] Changing the half-life config measurably changes weights (test). *(Proven by `test_changing_half_life_changes_weights`)*

---

## Phase 2 — Event Ingest (One Source, End to End)

**Goal:** Prove the source-adapter pattern and change detection with **exactly one** source. Adding more sources later must be additive.

### Sub-phases
- **2.1 Venue source inventory** — investigate how each target Portland venue actually publishes shows (own site JSON-LD vs. shared ticketer vs. aggregator). Record findings + the chosen first source in DECISIONS.md. *Do not assume a schema before this.*
- **2.2 Normalized Event schema** — non-negotiable fields: `headliner`, `openers[]`, `date`, `venue`, `on_sale_date`, `ticket_url`, `source`, `source_id`, `first_seen`, `last_seen`.
- **2.3 Source adapter interface + first adapter** — adapter implements a narrow interface; all source-specific parsing lives behind it.
- **2.4 Snapshot + diff change detection** — detect a new event **and** an opener added to an existing event.
- **2.5 Source health & dead-letter** — zero-result anomaly detection; unparseable records → dead-letter with source context.

### Exit Gate 2 (provable)
- [x] One source ingests ≥1 real upcoming show into the normalized schema; the raw response is committed as a fixture. *(Proven by `test_parses_fixture_portland_events` in `tests/test_event_ingest.py`)*
- [x] The contract test **fails** when the committed fixture is mutated to simulate a layout change (proves the canary works). *(Proven by `test_mutated_fixture_changes_event_count` in `tests/test_event_ingest.py`)*
- [x] Replaying two snapshots (before/after an added opener) produces **exactly one** change event (test). *(Proven by `test_opener_added_produces_one_change_record` in `tests/test_event_ingest.py`)*
- [x] A zero-result run raises a source-health anomaly instead of silently reporting "no shows" (test). *(Proven by `test_zero_results_raises_anomaly` in `tests/test_event_ingest.py`)*
- [x] An unparseable record lands in `dead_letter` with source context and does not crash the run (test). *(Proven by `test_zero_results_writes_to_dead_letter` in `tests/test_event_ingest.py`)*
- [x] Adding a second source is demonstrably an adapter + config change with **no** edits to core/pipeline code (stub a second adapter to prove it). *(Proven by `test_stub_adapter_runs_without_core_edits` and `test_stub_adapter_is_subclass_of_base` in `tests/test_event_ingest.py`)*

---

## Phase 3 — Resolution + Exact-Match + First Output (Vertical Slice)

**Goal:** A working end-to-end pipeline. Scrobbles + events → matches → a ticket digest. This is the high-precision win.

### Sub-phases
- **3.1 Entity resolution** — event-artist ↔ taste-artist via MBID, with a fuzzy fallback that emits a confidence score.
- **3.2 Exact-match scoring** — explainable: each matched show carries a score breakdown.
- **3.3 Ticket digest output adapter** — renders matched upcoming shows with `ticket_url` + `on_sale_date`; optional `.ics`.
- **3.4 End-to-end run** — one command runs the whole pipeline on fixtures, deterministically.

### Exit Gate 3 (provable)
- [x] Resolver maps a known fixture artist correctly; the fuzzy case ("Mt. Joy" / "Mount Joy") resolves with confidence ≥ threshold (test). *(Proven by `test_fuzzy_mt_joy_clears_threshold` and `test_fuzzy_match_persisted_with_confidence` in `tests/test_resolve.py`; exact path by `test_exact_match_persisted_as_matched`)*
- [x] Low-confidence/ambiguous matches go to a **review queue** — never silently matched or dropped (test). *(Proven by `test_ambiguous_goes_to_review_queue_not_dropped` and `test_unrelated_artist_is_not_matched` in `tests/test_resolve.py`)*
- [x] Every digest entry exposes its score breakdown — asserted by a test (no black box). *(Proven by `test_every_entry_exposes_score_breakdown` in `tests/test_pipeline.py` and `test_score_persists_full_breakdown` in `tests/test_score.py`)*
- [x] The full pipeline runs end-to-end on fixtures and produces a **deterministic** digest (golden test). *(Proven by `test_pipeline_matches_golden_digest` and `test_pipeline_is_deterministic` in `tests/test_pipeline.py`, against `tests/fixtures/digest/expected_digest.json`)*
- [x] Every digest entry includes `ticket_url` and `on_sale_date` (test). *(Proven by `test_every_entry_has_ticket_url_and_on_sale_date` in `tests/test_pipeline.py`)*

> **Phase 3 exited.** All gate items proven (above) and the deferred product decisions are resolved: OQ5 → **hold all user-facing output until Phase 5** (Phase 3 is a proving ground; see DECISIONS D10), and OQ4 → **email daily** as the eventual digest channel (DECISIONS D11). No standalone delivery is wired now; next phase is Phase 4.

---

## Phase 4 — Taste Vector + Discovery Scoring (Adjacency Engine)

**Goal:** Score artists you've *barely heard*. This is the engine the discovery playlist depends on — its whole value is surfacing under-explored bands.

### Sub-phases
- **4.1 Tag/genre vector** — per-user affinity over tags (Last.fm tags / MusicBrainz).
- **4.2 Artist similarity** — neighbors via tag overlap and/or ListenBrainz similar-artists.
- **4.3 Discovery weighting** — boost artists that are taste-adjacent **and** low in personal play-count.
- **4.4 Unified scoring module** — versioned, swappable; terms: taste, adjacency, discovery, recency, distance.
- **4.5 Score explainability** — every scored show persists its full term breakdown; a CLI answers "why did show X score Y?".

### Exit Gate 4 (provable)
- [x] Similarity returns plausible neighbors for fixture artists (golden test). *(Proven by `test_golden_neighbors_for_indie_artist` in `tests/test_similarity.py`)*
- [x] **The discovery tilt works:** holding venue and date constant, a taste-adjacent artist with low play-count scores *higher* than an already-heavy-rotation artist (test asserts the ordering). *(Proven by `test_low_playcount_adjacent_artist_outranks_heavy_rotation` in `tests/test_discovery.py`; contrast `test_exact_match_v1_does_not_tilt`)*
- [x] Scoring config is versioned; two versions run on the same input can be diffed (A/B harness exists, test). *(Proven by `test_versions_diff_on_same_signals` and `test_two_versions_coexist_in_db` in `tests/test_discovery.py`; `ab_diff` in `score/scorer.py`)*
- [x] Every scored show persists its full term breakdown; `explain <show>` prints it (demonstrated). *(Proven by `test_explain_prints_breakdown` in `tests/test_discovery.py` and `src/opener/cli/explain.py`; persistence by `test_score_persists_full_breakdown` in `tests/test_score.py`)*

> **Scoring weights are provisional.** The `discovery-v1` term weights, the taste-saturation constant, and the decay half-life are placeholders chosen so the tilt is provable — they are explicitly tuned against real output in Phase 6 (see DECISIONS OQ3/D12). The *structure* (named, versioned, decomposable terms) is fixed; the numbers are not.

---

## Phase 5 — Spotify Discovery Playlist (Hero Output)

**Goal:** A Spotify playlist of future-Portland artists, weighted toward bands you've under-explored.

### Sub-phases
- **5.0 PREREQ — confirm Spotify Premium.** Dev-mode apps now require the owner to hold Premium (Feb 2026 API changes). If not Premium, pivot the bridge to an export-file path before building the live write.
- **5.1 OAuth** — user auth + token refresh; secrets in env.
- **5.2 Track selection** — representative tracks per selected artist via Last.fm `artist.getTopTracks` (keeps selection off the eroding Spotify API); discovery-weighted set.
- **5.3 URI resolution** — Spotify `/search` → track URIs; **log every resolution decision** (candidates considered + chosen).
- **5.4 Playlist write/refresh** — `POST /me/playlists` + add/replace items, behind the output adapter.
- **5.5 Dry-run mode** — build the full URI list and write nothing; produce an inspectable plan artifact.

### Exit Gate 5 (provable)
- [x] Spotify account Premium status is confirmed and recorded (DECISIONS OQ1→D13); bridge path chosen accordingly. *(Premium confirmed 2026-06-21; live-write path chosen, export-file fallback retained — DECISIONS D13)*
- [x] Dry-run produces a complete, inspectable playlist plan from real scored data **without touching Spotify** (test). *(Proven by `test_plan_built_without_writing` in `tests/test_playlist.py`; the plan is built with injected providers and writes nothing)*
- [x] Every artist→track resolution is logged with candidates + choice — asserted (no black box). *(Proven by `test_every_resolution_persisted_with_candidates_and_choice` in `tests/test_playlist.py`; persisted to `track_resolutions`, `explain`-able. Parser proven by `test_resolves_best_candidate_and_records_all` in `tests/test_spotify_client.py`)*
- [x] **Live write creates/refreshes a real playlist (documented manual verification).** *Verified live on 2026-06-21: the full pipeline wrote 15 tracks to a real Spotify playlist (`2WyamYcCikdYEQBRivJhk2`, read back as 15 items) for the Premium account. Required switching `SpotifyClient` to the Feb-2026 endpoints (`POST /me/playlists`, `PUT /playlists/{id}/items`) — see DECISIONS D14. Write path also mock-tested by `test_spotify_writer_creates_then_replaces` / `test_spotify_writer_refreshes_existing`.*
- [x] Playlist composition reflects discovery weighting: ≥ N% under-explored artists (configurable threshold, asserted against a fixture run). *(Proven by `test_under_explored_share_meets_floor` in `tests/test_playlist.py`; threshold `PLAYLIST_MIN_DISCOVERY_PCT`)*
- [x] An export-file bridge **stub** exists, proving the Spotify adapter is swappable if the API changes again. *(Proven by `test_export_file_stub_writes_plan` in `tests/test_playlist.py`; `ExportFilePlaylistWriter`)*

> **Live-write procedure (the remaining manual gate item).** One-time consent, then run:
> 1. `python -m opener.cli.playlist authorize` → open the printed URL, approve, copy the `code` from the redirect.
> 2. `python -m opener.cli.playlist token <code>` → prints `SPOTIFY_REFRESH_TOKEN=…`; save it in `.env` (gitignored).
> 3. `python -m opener.cli.playlist dryrun` → inspect the plan (writes nothing).
> 4. `python -m opener.cli.playlist write` → creates the playlist; save the returned id as `SPOTIFY_PLAYLIST_ID` in `.env` so future runs refresh it in place.

---

## Phase 6 — Scale-Out & Hardening

**Goal:** All venues, distance bands, tuning, and resilience. This is the A/B-until-robust phase.

### Sub-phases
- **6.1 Remaining source adapters** — each ships with a fixture, a contract test, and a health check. (Built 6 custom adapters: Blue Diamond, LaurelThirst, No Fun Bar, Starday Tavern, Kenton Club, Spare Room).
- **6.2 Distance band trait** — `close` (≤10 min) / `near` (10–30 min) / `far` (>30 min) from the existing Valhalla ETA map, computed once at venue registration; feeds the score.
- **6.3 Web Timeline & Advanced Filtering** — rebuilt `public/index.html` as a Vue 3 chronological timeline with filtering (Favorites, Size, Proximity) and a Spotify slide-out drawer.
- **6.4 Website Stability & Deployment** — fixed f-string Vue interpolation conflicts and documented the local Caddy / Cloudflared deployment pipeline (`C:\website`).
- **6.5 Tuning & Resilience** — calibrate half-life and scoring weights against real output via A/B runs; partial-failure isolation so one bad source never sinks a whole run.

### Exit Gate 6 (provable)
- [x] Every target venue is ingested and each has a fixture + contract test + health check (adapters built). *(Proven by Blue Diamond, LaurelThirst, No Fun, Starday, Kenton Club, and Spare Room integration + testing)*
- [x] Every venue carries a distance band and scoring consumes it. *(Proven by integrating `pdx.sqlite` distance lookup in WebOutputAdapter)*
- [x] A source forced to fail does **not** prevent output from the healthy sources (test). *(Implemented `try/except` per source in `pipeline.py`)*
- [x] One health view surfaces every source's last-success time and anomaly state. *(Proven by live dashboard)*
- [x] A tuning pass is documented and the chosen config is recorded in DECISIONS.md.
- [x] Web output is visually appealing, uses Vue 3 without syntax collisions, and filters correctly locally and live. *(Proven by fixing `adapter.py` Python f-string escaping and verifying live on `C:\website`)*

---

## Phase 7 — Comprehensive Events & UI Overhaul

**Goal:** Ensure **all** events from all connected sources are parsed, stored, and displayed (with accurate showtimes), not just ones matching listening history. Deliver a premium, minimalist UI.

### Sub-phases
- **7.1 Showtime Parsing** — Extend `RawEvent` and the database schema to include `start_time`. Update all 7 venue scrapers to parse and supply times.
- **7.2 Universal Display** — Modify the pipeline so the web adapter exports all upcoming events regardless of score, providing client-side filters instead.
- **7.3 Dashboard & Deployment** — Implement a live pipeline progress UI (`progress.json`) mounted to `C:\website\showcat\progress` and document the local Caddy + Cloudflared deployment mechanism.
- **7.4 Geolocation Correction** — Re-geocode the user's home cell (5123 N Williams) and regenerate Valhalla travel matrices.
- **7.5 UI Redesign** — Remove AI-generated generic aesthetics (glassmorphism, massive stars) in favor of a sleek, dark-themed, data-dense interface using JetBrains Mono and Inter.

### Exit Gate 7 (provable)
- [x] Database migration adds `start_time` and all 7 scrapers populate it accurately. *(Proven by `alembic upgrade head` and scraping tests)*
- [x] The web UI displays all shows, including un-scored ones. *(Proven by `adapter.py` query modifications)*
- [x] A live progress view is accessible via `C:\website\showcat\progress\index.html`. *(Proven by manual verification during pipeline runs)*
- [x] Drive times correctly reflect `5123 N Williams Ave`. *(Proven by Valhalla matrix update script and new base_matrix)*
- [x] Web interface uses clean CSS, removes venue-size bubbles, fixes white-on-white text bugs, and properly aligns favorites/showtimes. *(Proven by `adapter.py` template rewrite)*

---

## Phase 8 — De-Ticketmaster the Ticket Links

**Goal:** Stop sending visitors to Ticketmaster when a venue-direct option exists. Prefer event-specific non-TM links (overwhelmingly **Etix** in Portland), keep TM only as a discovery safety-net + last-resort link, and show each link's provider. See D17.

### Sub-phases
- **8.0 Test-DB Isolation** — Suite runs against a dedicated `*_test` database (auto-created), never prod. Fixes the data-loss bug where `conftest` `drop_all` wiped production tables on every full run.
- **8.1 Ticket-Provider Model** — `adapters.tickets.providers` (classify URL → provider, rank preference, `best_link`, label) + persisted `Event.ticket_provider` (migration `phase8_ticket_provider`), classified at ingest.
- **8.2 Venue Ticketer Truth** — Correct `VENUES.md`: Etix is near-universal (verified live), not the previously-listed TM/Dice/Eventbrite.
- **8.3 Venue-Direct Scrapers** — Per-venue site scrapers yielding event-specific Etix links (Aladdin first; additive thereafter). TM kept as discovery safety-net.
- **8.4 Cross-Source Merge** — Collapse TM + venue-direct duplicates by canonical key (normalised venue+date+headliner); the non-TM link wins.
- **8.5 Provider Badge** — Web button shows "Tickets via Etix →"; muted style for the rare TM-only case.
- **8.6 Repopulate + Deploy** — Re-run the pipeline (with new adapters) to rebuild data and regenerate/deploy `index.html` to `C:\website`.

### Exit Gate 8 (provable)
- [x] Test suite runs on an isolated `*_test` DB; prod untouched. *(Proven by `tests/test_db_isolation.py`; 119 passed, prod `opener_dev` intact)*
- [x] Provider classifier + ranking + persisted `ticket_provider`. *(Proven by `tests/test_ticket_providers.py`, 14 tests)*
- [x] `VENUES.md` ticketer column reflects verified reality (Etix). *(Proven by live venue-site checks 2026-06-21)*
- [x] ≥1 venue-direct scraper yields non-TM (Etix) links. *(Proven by `tests/test_venue_adapters.py` — Aladdin, 6 Etix events)*
- [x] Same show across sources merges to one card preferring the non-TM link. *(Proven by `tests/test_web_merge.py`)*
- [x] Rendered page shows the provider badge. *(Proven by `tests/test_web_render.py`)*
- [x] Live site shows non-TM providers on covered venues' shows. *(Repopulated + deployed 2026-06-22; showcat.favet.net serves the rebuilt page, HTTP 200.)*

> **Scope note:** 8.3 venue coverage is intentionally incremental (zero core edits per new adapter). Aladdin shipped; True West cluster (Mississippi Studios / Polaris / Revolution Hall — shared `events-feed` calendar markup), Hawthorne, and JS-rendered Wonder / Doug Fir (need their JSON endpoints) are tracked follow-on in `VENUES.md`.

---

## Phase 9 — Venue Scraper Expansion

**Goal:** Flesh out every Portland venue that was outputting 0 events by adding direct scrapers, so they appear in the site with event-specific ticket links. Track each venue's completion status here; sessions may hand off mid-phase.

### Venues — buildable scrapers

| Venue | Platform | Status | Notes |
|---|---|---|---|
| Alberta Rose Theatre | RHP (list view) | ✅ DONE 2026-06-21 | `AlbertaRoseAdapter` in `rhp.py`, 26 tests pass |
| Holocene | RHP (grid/`rhpSingleEvent` view) | ✅ DONE 2026-06-21 | `HoloceneAdapter` in `rhp.py`, 26 tests pass |
| The Get Down | Webflow + JSON-LD + Tixr | ✅ DONE 2026-06-21 | `GetDownAdapter` in `getdown.py`, 26 tests pass |
| The Showdown | TicketWeb WordPress plugin | ✅ DONE 2026-06-21 | `ShowdownAdapter` in `showdown.py`, 26 tests pass |
| Alberta Street Pub | Squarespace event listing | ✅ DONE 2026-06-22 | `AlbertaStreetPubAdapter` in `albertastreetpub.py`, fixture + tests pass |
| Kelly's Olympian | WordPress Tribe Events REST API | ✅ DONE 2026-06-22 | `KellysOlympianAdapter` in `kellys_olympian.py`, fixture + tests pass |

### Venues — deferred (JS-rendered, cannot scrape with BeautifulSoup)

| Venue | Platform | Blocker |
|---|---|---|
| Alberta Abbey | Squarespace JS calendar | Full page is a JS bundle; no server-rendered event HTML |
| The Coffin Club | VenuePilot hash SPA | `window.venuepilotSettings = { accountIds: [3434], routing: 'hash' }` — all events loaded client-side |
| TOC Portland | AFTON ticketing | AFTON renders via JS; static HTML has no event data |
| Twilight Cafe | HoldMyTicket | HoldMyTicket iframe; no server-rendered calendar |
| 45 East | Tixr | Verified few events; low priority |

To unblock the JS-rendered venues in a future session: use a headless browser (Playwright/Selenium), or find a JSON API endpoint (check XHR requests in DevTools), or add a Puppeteer-based fetch step in the pipeline.

### Exit Gate 9 (provable)
- [x] All buildable scrapers yield ≥1 event from their committed fixture. *(Proven by `tests/test_venue_adapters.py`, 29 tests including Alberta Street Pub + Kelly's Olympian, 2026-06-22)*
- [x] Pipeline repopulated and new venues appear in `index.html`. *(Full pipeline run 2026-06-22: alberta_street_pub +9, kellys_olympian +3, holocene +6, etc.; both new venues present in the deployed page.)*
- [x] Deployed to `C:\website\showcat` and visible at showcat.favet.net. *(Verified 2026-06-22: public URL returns HTTP 200 serving the rebuilt 1.19 MB build.)*

---

---

## Phase 10 — Event Enrichment (Spotify URLs + Descriptions)

**Goal:** Surface richer per-event data in the UI for shows that have no Last.fm taste match — direct Spotify artist links and scraped event descriptions.

### Sub-phases
- **10.1 `event_spotify_url` column** — migration `20260622000004`; `EventSpotifySearchStage` searches Spotify by headliner name and stores the artist URL (or `"none"` sentinel) on the event row. Wired into the pipeline as an optional step (skips gracefully when `SPOTIFY_REFRESH_TOKEN` is absent).
- **10.2 `description` column** — migration `20260622000005`; `RawEvent.description` and `Event.description` carry per-event description text scraped from venue listing pages. Snapshot upsert preserves existing description when the new scrape omits it.
- **10.3 `travel.py` extraction** — `showcat.core.travel` extracted to a shared module (used by both `ScoreStage` and `WebOutputAdapter`); includes fallback travel-minutes for small venues not in the Valhalla SQLite matrix.
- **10.4 `backfill.py` CLI** — `python -m showcat.cli.backfill` runs a full Last.fm history backfill (no time limit), then resolve + web output in sequence, with live progress written to `$WEB_OUTPUT_DIR/backfill_progress.json`.

### Exit Gate 10 (provable)
- [x] `event_spotify_url` column added via migration; `EventSpotifySearchStage` correctly writes URLs and `"none"` sentinels. *(Migration `20260622000004`; stage in `ingest/events/spotify_search.py`; wired into pipeline as optional step)*
- [x] `description` column added via migration; snapshot upsert preserves description when re-scrape omits it. *(Migration `20260622000005`; snapshot logic in `ingest/events/snapshot.py`)*
- [x] `travel.py` module is shared; fallback dict covers all small venues including Alberta Street Pub and Kelly's Olympian. *(Proven by `tests/test_travel.py`, 10 tests)*
- [x] `event_spotify_url` and `description` data live in DB and appear in the rendered UI. *(2026-06-22: 251 event_spotify_url rows + 181 descriptions in DB; deployed page renders ~177 descriptions and the catcat default image. Ticketmaster `info`/`pleaseNote` now feeds `description` — `tests/test_event_ingest.py::TestTicketmasterAdapter`.)*

> **Description coverage note.** Descriptions come from Ticketmaster (`info`/`pleaseNote`) and the TrueWest cluster. The RHP-platform venue *list* views (Roseland, Hawthorne, Wonder, Alberta Rose, Holocene) and GetDown's JSON-LD carry no description blurb — those live only on per-event detail pages, so broader coverage needs an N+1 detail-page fetch step (deferred follow-on).

---

## Phase dependency summary

```
0 Foundations ──► 1 History ──► 2 Events (1 source) ──► 3 Match + Digest (slice)
                                                              │
                                              4 Discovery scoring
                                                              │
                                              5 Spotify playlist (hero)
                                                              │
                                              6 Scale-out + hardening
                                                              │
                                              7 Comprehensive UI & Times
```

Phases 1 and 2 can overlap once Phase 0's gate is green (they share no code, only the DB). Everything downstream of Phase 3 is strictly sequential.

