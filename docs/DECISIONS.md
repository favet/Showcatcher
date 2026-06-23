# Decisions — Showcat

A lightweight log so assumptions are **visible and revisable**, never silently baked in. Add a new entry whenever a real choice is made; move open questions to "Decided" once resolved.

Format: `Dn — Title — Decision — Why — Status`.

## Decided

### D1 — Taste source is Last.fm, not Spotify
**Decision:** Listening history comes from Last.fm; it's stored in our own Postgres as the system of record.
**Why:** Last.fm's API paginates the *full* history (Spotify caps recently-played at 50 and has deprecated audio-features, recommendations, and related-artists for new apps). Owning a local copy removes a fragile live dependency. A one-time Spotify "extended streaming history" GDPR export can seed gaps if needed.
**Status:** Firm.

### D2 — PostgreSQL over SQLite
**Decision:** Postgres.
**Why:** Multiple worker stages write concurrently; SQLite's single-writer lock fights that. We also want indexing on snapshot history and JSON columns for raw captures.
**Status:** Firm.

### D3 — Pipeline of independent stages; database is the bus
**Decision:** Stages read/write only via Postgres and never call each other.
**Why:** Additivity and debuggability — add a source, swap the scorer, or add an output without touching the rest; every hand-off is inspectable as data.
**Status:** Firm (a core invariant — see AGENTS.md).

### D4 — Every external edge sits behind an adapter with fixtures
**Decision:** Last.fm, each venue source, and Spotify are all adapters; tests run offline against committed responses.
**Why:** The outside world changes; the engine shouldn't. Contract tests act as canaries.
**Status:** Firm (core invariant).

### D5 — Scoring is explainable and versioned
**Decision:** Every score decomposes into named, persisted terms; scoring config is versioned for A/B.
**Why:** "Never a black box," and the expectation that we'll A/B the ranking repeatedly.
**Status:** Firm. The *contents* of the formula (terms, weights) are deliberately **not** fixed yet — tuned in Phase 6.

### D6 — Spotify bridge is a hybrid behind an output adapter
**Decision:** Select tracks via Last.fm `artist.getTopTracks`, resolve URIs via Spotify `/search`, write via `POST /me/playlists`; keep an export-file fallback stub.
**Why:** Spotify's API has contracted three times in ~18 months; keeping track selection off it, and the write behind an adapter, prevents vendor churn from stranding the hero output.
**Status:** Firm. Live write is contingent on OQ1.

### D7 — Outputs are a discovery playlist (hero) + ticket digest (companion)
**Decision:** Hero output is a Spotify-importable playlist weighted toward under-explored future-Portland artists. Companion is a ticket digest (on-sale dates + links). Pre-show "warm-up audio for shows I'm already attending" is dropped.
**Why:** The valuable job is *discovery and getting tickets*, not warming up for shows already on the calendar.
**Status:** Firm.

### D8 — Distance bands from the existing Valhalla ETA map
**Decision:** Venues get a `close` (≤10 min) / `near` (10–30 min) / `far` (>30 min) band, computed once at registration, feeding the score.
**Why:** The offline ETA map already exists; venue coordinates are static, so this is cheap "icing."
**Status:** Firm. Band thresholds are tunable.

### D17 — De-Ticketmaster: prefer venue-direct ticket links *(resolved Phase 8, 2026-06-21)*
**Decision:** Visitors should not be sent to Ticketmaster when a venue-direct option exists. Ticketmaster stays a **discovery safety-net** (so genuinely TM-only shows still appear), but the **link shown** is the most-preferred non-TM, event-specific URL. Preference order (higher wins): named non-TM ticketers (Etix, Dice, Eventbrite, TicketWeb, …) > the venue's own site > Ticketmaster (last resort) > unknown. Each ticket button shows its provider ("Tickets via Etix →"); the rare TM-only case is styled muted.
**Key finding:** Portland's dedicated music venues almost universally ticket through **Etix** (verified live 2026-06-21: Crystal, Aladdin, Roseland, Hawthorne, Mississippi Studios, Polaris, Holocene, Alberta Rose). Ticketmaster's Discovery API merely aggregates/resells them. So the planned per-platform Dice/Eventbrite adapters are largely unnecessary — venue-direct scrapers yield Etix links natively.
**How:** `showcat.adapters.tickets.providers` classifies a URL → provider and ranks providers; `Event.ticket_provider` is persisted at ingest; per-venue scrapers (e.g. `AladdinAdapter`) discover shows with their real Etix links; the web output collapses the TM + venue-direct duplicates by canonical key (normalised venue+date+headliner) and picks the best link.
**Status:** Framework complete (8.0–8.5). Venue-direct scraper coverage is additive and ongoing — Aladdin first; True West cluster (Mississippi/Polaris/Rev Hall), Hawthorne, and JS-rendered Wonder/Doug Fir are follow-on (see VENUES.md).

### D15 — Auth model: single-owner pipeline, zero-auth consumers *(resolved Phase 6, 2026-06-21)*
**Decision:** Showcat is a **single-owner pipeline** to minimize authentication friction. The pipeline owner (Justin) runs the backend pipeline using their credentials. Consumers (visitors) need **zero authentication** to use the application or consume its outputs.

**Why and How Auth Works:**
1. **Last.fm History:** **No user OAuth is required.** Since Last.fm listening profiles are public, the pipeline reads history using a standard developer API key and a username (e.g. `LASTFM_USER=j-m-f` in `.env`). No credentials are needed from the listener.
2. **Spotify Integration:** **OAuth is only required to write/update a playlist.** A user token (`SPOTIFY_REFRESH_TOKEN`) is needed because playlist creation and item modification are write operations.

**Evaluating Alternatives & Best Approach:**
*   **The "Pre-made Playlist" Copy/Follow Model (Best Approach):** Instead of requiring every visitor to authenticate with Spotify (which would force us to set up user login, session management, and Spotify developer scopes), we write to a **public, pre-made Spotify playlist** (`2WyamYcCikdYEQBRivJhk2`) owned by Justin.
    *   Visitors simply **follow** this public playlist or **copy** its contents to their own library with zero setup/login friction.
*   **Personalized/Custom Music Taste (Zero-Auth Path):** If a visitor wants to see upcoming shows matching their *own* music taste (rather than Justin's):
    *   They can provide their Last.fm username in a simple web form.
    *   The web application performs taste matching and resolver queries on the fly using their public Last.fm history (using the app's Last.fm developer key).
    *   It displays their personalized concert digest directly on the web page.
    *   **No Spotify login/authorization is required** for this personalized web view, avoiding the need for complex Spotify OAuth.

**Status:** Resolved. The current system relies on single-owner Spotify token credentials to refresh the public playlist, keeping consumer access 100% auth-free.

### D16 — Web Output & Deployment (Local Caddy + Cloudflared) *(resolved Phase 7, 2026-06-21)*
**Decision:** The static web output (`index.html`) and the live pipeline progress dashboard (`progress.json`) are written directly to `C:\website` on the owner's machine. They are served to the public internet via a local Caddy server coupled with a Cloudflare Tunnel (`cloudflared`).
**Why:** This is the simplest possible continuous deployment pipeline. Because Showcat is a single-owner pipeline running on a local machine (D15), writing the build artifacts to a local directory synced to the internet eliminates the need for VPS provisioning, GitHub Actions, or remote server syncing. Changes are instantaneous and secure.
**Status:** Firm. Implemented in Phase 7.

### D18 — Etix Price Scraping Abandoned *(resolved 2026-06-22)*
**Decision:** Scraping advance ticket prices from Etix.com for Portland venues is written off and abandoned. No further effort will be spent attempting to automate price extraction from Etix portals.
**Why:** Investigation with both plain HTTP requests and headless Chromium via Playwright confirmed that Etix employs robust DataDome bot-protection gateways. DataDome successfully blocks automated browser requests and requires CAPTCHA resolution. Given the project's constraint against manual intervention/CAPTCHAs and the high maintenance cost of bypassing sophisticated anti-bot protections, the feature cannot be reliably automated.
**Status:** Resolved (Written off). The `EventEtixPricePatchStage` and related code were deleted.

### D19 — Resolver Guard 3: multi-word fuzzy matches must share a distinctive token *(resolved 2026-06-22)*
**Decision:** In the fuzzy fallback, when a candidate pair shares **no** exact distinctive token (after stripping articles) and **at least one** side is multi-word, raise the auto-accept bar out of reach so the pair routes to the **review** queue instead of `matched`.
**Why:** `difflib` char-ratio produced coincidental matches above the 0.75 threshold purely on letter overlap — e.g. `"Like Mang"`→`"louke man"` (0.78), `"Heather Christie"`→`"The Charities"` (0.76). Real multi-word fuzzy matches always share an exact token (`"Mount Joy"`/`"Mt. Joy"` share *joy*; `"Bright Eyes"`/`"Bright Eyez"` share *bright*), so requiring one shared token kills the false positives without dropping legitimate matches. The both-single-token case is left to the existing Guard 1 (0.90 bar), which still permits a high-confidence single-word typo match.
**Impact:** Applied to live data 2026-06-22 — 113 coincidental matches downgraded (matched 505→392), 99 events lost a falsely-inflated score (re-scored 438→339). Proven by `tests/test_resolve.py` (`test_no_shared_token_guard_*`, `test_shared_token_multiword_still_matches`).
**Status:** Firm. Residual: a pair sharing only a common given-name token (`"Christian Groth"`→`"Christian Rich"`) still clears — acceptable; tightening further trades too much recall.

### D20 — Catcat mascot is the favicon + default show image *(resolved 2026-06-22)*
**Decision:** `Media/catcat.png` is shipped as a package asset (`src/showcat/outputs/web/catcat_b64.txt`, base64) and used both as the page favicon and as the default show image when an event has no Spotify/event artwork — replacing the prior `🐱` emoji fallback.
**Why:** A single embedded asset keeps the static page self-contained (no external image host) and gives a consistent brand mascot. Shipping it inside the package (not just `Media/`) means it deploys with the web output regardless of CWD.
**Status:** Firm.

### D21 — Spotify quota: throttle event-search so it can't lock out the playlist refresh *(resolved 2026-06-22)*
**Decision:** `EventSpotifySearchStage` caps each run (`SPOTIFY_SEARCH_MAX_PER_RUN`, default 100), paces to ~2.5 req/s (`SPOTIFY_SEARCH_DELAY_S`, default 0.4), and **stops immediately on a 429** (reading `SpotifyError.retry_after`) instead of retrying. Results persist per-event, so a large backlog drains over several runs.
**Why:** All Spotify operations share one dev-mode app quota, and exceeding the rolling ~30-second window triggers a **fixed multi-hour cooldown** (observed `Retry-After` ≈ 9.9h). On 2026-06-22 the stage fired ~251 `/search` calls at ~8 req/s and locked out the discovery-playlist refresh (`cli/playlist write`, which also needs `/search`) for the rest of the day. Proven by `tests/test_spotify_search.py` (cap + stop-on-429 + transient-error handling).
**Operational rule:** don't run a large event-search batch on a day you intend to refresh the playlist.
**Status:** Firm. See [[reference-spotify-rate-limit]] in memory for the empirical detail.

## Open questions (do not hardcode silently — resolve in the noted phase)

### D13 — Spotify account is Premium; live-write bridge path chosen *(resolved Phase 5, OQ1)*
**Decision:** The owner's Spotify account holds Premium (confirmed 2026-06-21), so the **live-write** bridge path is taken: select tracks on Last.fm, resolve URIs via Spotify `/search`, write via `POST /me/playlists` + replace items. The export-file path remains implemented as a fallback stub (`ExportFilePlaylistWriter`) proving swappability, not as the primary.
**Why:** Dev-mode apps now require the owner to hold Premium; Premium is present, so the hero output can write a real playlist.
**Status:** Resolved. Live write verified against the real account — see D14.

### D14 — Live write works on Feb-2026 endpoints (/me/playlists, /playlists/{id}/items) *(Phase 5 live run, 2026-06-21)*
**Finding:** A full live run succeeded end to end — 16,643 scrobbles ingested, 100 Portland shows, 17 scored, 15 tracks resolved to real Spotify URIs via `/search`, and **15 tracks written to a real Spotify playlist** (`2WyamYcCikdYEQBRivJhk2`, read back as 15 items).
**Root cause of the initial 403:** The first `SpotifyClient` used endpoints **removed in February 2026** — `POST /users/{id}/playlists` (create) and `PUT /playlists/{id}/tracks` (write items). Spotify returns **403 Forbidden** (not 404) for these removed endpoints, which masqueraded as a permissions/quota problem and sent diagnosis down the wrong path (Premium, allowlist, scopes were all already correct). Switching to the current endpoints — **`POST /me/playlists`** to create and **`PUT /playlists/{id}/items`** to write items — fixed it immediately. ARCHITECTURE.md had specified `/me/playlists` all along; the client had diverged.
**Lesson:** A Spotify 403 with valid auth can mean a **deprecated endpoint**, not a permission failure. Check the endpoint against the current API before chasing account/scope causes.
**Status:** Resolved. Live write is verified; Gate 5 fully met. Premium remains the dev-mode prerequisite (D13); no Extended Quota Mode was needed for personal-account playlist writes.

### D9 — Event source: Ticketmaster Discovery API *(resolved Phase 2.1)*
**Decision:** Use the Ticketmaster Discovery API (`https://app.ticketmaster.com/discovery/v2/`) as the first (and primary) event source adapter.
**Why:** Bandsintown's public API is artist-centric only (no venue query). Songkick API access is heavily restricted. The major Portland venues that matter (Crystal Ballroom, Hawthorne Theatre, Wonder Ballroom, Roseland, Arlene Schnitzer, McMenamins) all sell tickets through Ticketmaster/Live Nation, making a single `venueId`-filtered query cleanly cover all of them. The API is free for developers, returns structured JSON, and provides `headliner`, openers (embedded in event name/attractions), `date`, `on_sale_date`, and `ticket_url` directly. A `venue` config file maps Ticketmaster venue IDs to friendly names.
**Fallback:** If Ticketmaster restricts their API further, the adapter interface allows swapping to direct venue-site scraping per the recipe in AGENTS.md.
**Status:** Decided. Add `TICKETMASTER_API_KEY` to `.env.example`.

### OQ3 — Decay half-life default *(Phase 6 tuning)*
Starting placeholder is a tunable parameter (lean: ~8 weeks), calibrated against real output. Not fixed.

### D12 — Phase 4 scoring engine: tag-cosine adjacency + play-count discovery tilt *(Phase 4)*
**Decision:** Adjacency is the cosine similarity of an artist's Last.fm tag vector to the affinity-weighted **taste vector**. Discovery is `adjacency / (1 + play_count)` — high only when an artist is taste-adjacent **and** barely played. The unified scorer combines named term *signals* (taste/adjacency/discovery/recency/distance) as a weighted sum selected by `scoring_version`; the persisted breakdown stores each term's contribution so totals are explainable, and `ab_diff` runs two versions on identical signals. Two versions ship: `exact-match-v1` (taste-only, raw — the Phase 3 precision digest) and `discovery-v1` (the hero tilt; taste is saturated `taste/(taste+k)` so an unbounded affinity can't swamp the discovery term).
**Why:** Tag-cosine keeps similarity offline/deterministic and behind the existing Last.fm adapter (no new vendor); the play-count penalty is the simplest explainable formula that produces the required tilt. Saturation keeps version weights meaningful rather than gamed to fixture magnitudes.
**Status:** Structure firm. **Weights, the saturation constant `k`, and the half-life are provisional placeholders tuned in Phase 6** (see OQ3). `discovery-v1` is not yet the production pointer — `SCORING_VERSION` stays `exact-match-v1` until the playlist wires discovery in (Phase 5).
**Alternative considered:** ListenBrainz similar-artists for adjacency — deferred; tag overlap is sufficient and dependency-free for now (the plan allows "tag overlap and/or ListenBrainz").

### D11 — Ticket digest delivery channel: email (daily) *(resolved Phase 3, OQ4)*
**Decision:** When the ticket digest ships, it is delivered as a **daily digest email**.
**Why:** Simplest channel with no extra service to run; matches the plan's lean. The digest is already built behind an output adapter (`DigestOutputAdapter`), so the email sender is an additive renderer/transport, not a pipeline change. Other channels (ntfy/Discord/feed) remain swappable behind the same adapter if wanted later.
**Status:** Decided. Not yet implemented — gated on D10 (no user-facing delivery is wired until Phase 5).

### D10 — Hold all user-facing output until Phase 5 *(resolved Phase 3, OQ5)*
**Decision:** Phase 3 is treated purely as a pipeline **proving ground**. The exact-match digest is built and proven (artifact + golden test) but **not** delivered to the user standalone; all user-facing output waits for the Spotify discovery playlist (the hero) in Phase 5.
**Why:** The valuable job is discovery + getting tickets together (D7). Shipping a standalone digest now would add a delivery/transport surface to maintain before the hero output exists, for marginal benefit. Building the digest as a proving ground still de-risks resolution + scoring end-to-end.
**Status:** Decided. Proceed to Phase 4 (discovery scoring); revisit delivery (D11) at Phase 5.
