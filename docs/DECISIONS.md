# Decisions — Opener

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
