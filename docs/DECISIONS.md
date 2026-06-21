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

### OQ1 — Is the Spotify account Premium? *(blocks Phase 5 live write)*
Dev-mode apps now require the owner to hold Premium. If not Premium, pivot the bridge to the export-file path. **Resolve before Phase 5.**

### OQ2 — Venue source backends *(Phase 2.1)*
Which Portland venues publish via their own site JSON-LD vs. a shared ticketer (Etix, See Tickets, Eventbrite, Dice, AXS) vs. an aggregator (Bandsintown, Songkick)? Inventory first; one aggregator may replace several brittle scrapers. **Record findings here when known.**

### OQ3 — Decay half-life default *(Phase 6 tuning)*
Starting placeholder is a tunable parameter (lean: ~8 weeks), calibrated against real output. Not fixed.

### OQ4 — Ticket digest delivery channel
Email / ntfy / Discord / feed — undecided. Lean: daily digest. **Pick during Phase 3.**

### OQ5 — Ship Phase 3 digest standalone, or hold all output until the playlist?
Whether the exact-match digest goes live on its own for a while, or Phase 3 is treated purely as a pipeline proving-ground with no user-facing output until Phase 5. **Decide before exiting Phase 3.**
