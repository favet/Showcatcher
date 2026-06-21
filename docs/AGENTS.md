# AGENTS.md — Working Rules for Opener

> This is the **single source of truth** for how agents (Claude Code, Antigravity) work in this repo. `CLAUDE.md` and any `.agents/rules/*` point here. If you change a rule, change it here.

## What this project is

Opener finds live shows in Portland by artists you'd like — including bands you've *barely heard* — and produces two outputs: a **Spotify discovery playlist** (the hero) weighted toward under-explored artists, and a **ticket digest** for artists you already know, with on-sale dates and links. It learns taste from your listening history with time-decay.

Read `ARCHITECTURE.md` for the design and `PROJECT_PLAN.md` for the phased build with provable gates.

## Non-negotiable architecture invariants

These are the spine. Do not violate them without recording a decision in `DECISIONS.md`.

1. **Stages couple only through the database.** No stage imports or calls another stage. The DB is the bus. This is what keeps the pipeline additive.
2. **Every stage is idempotent.** Re-running any stage produces no duplicates and no corruption. Enforced with unique constraints + tests, not vibes.
3. **Every external dependency sits behind an adapter** (Last.fm, each venue/source, Spotify). Source-specific parsing never leaks into core. Adapters have committed fixtures.
4. **Scoring is explainable and versioned.** Every score decomposes into named terms (taste, adjacency, discovery, recency, distance) that are persisted. Scoring config is versioned so variants can be A/B-compared.
5. **Nothing is a black box.** Every non-trivial decision is logged and/or decomposable. "Never a black box" is the project's defining diagnostic principle — honor it everywhere.
6. **Secrets live in env, never in the repo.** `.env` is gitignored; `.env.example` documents required keys.

## Tech stack

- **Python** (typed), **PostgreSQL**, **Docker Compose**, **Alembic** migrations, **pytest**.
- Lint/format: **ruff** + **black**. Types: **mypy**. Pre-commit runs all three.
- No framework lock-in inside stages; keep modules small and single-purpose.

## Repo layout (target)

```
opener/
├── AGENTS.md            # this file — canonical agent rules
├── CLAUDE.md            # thin pointer to AGENTS.md + Claude Code notes
├── README.md
├── ARCHITECTURE.md
├── PROJECT_PLAN.md      # phases + provable gates
├── DECISIONS.md         # decision log + open questions
├── .env.example
├── docker-compose.yml
├── pyproject.toml
├── alembic/             # migrations
├── src/opener/
│   ├── core/            # BaseStage, run-ledger, dead-letter, logging, config
│   ├── ingest/          # listening-history + event-source stages
│   ├── adapters/        # lastfm/, sources/<venue>/, spotify/  (external IO only)
│   ├── resolve/         # entity resolution
│   ├── score/           # taste vector, similarity, scoring (versioned)
│   └── outputs/         # digest/, playlist/  (output adapters)
└── tests/
    ├── fixtures/        # committed recorded responses + golden files
    └── ...
```

## Definition of Done (every change)

- [ ] Typed, ruff-clean, black-formatted, mypy-clean.
- [ ] Tests run **offline** against committed fixtures — no live network in unit tests.
- [ ] If it's a stage: idempotency test passes.
- [ ] Failures route to `dead_letter` / `run_ledger`; nothing is silently swallowed.
- [ ] Any decision it makes is logged or decomposable.
- [ ] Docs updated (`PROJECT_PLAN.md` checkboxes, `ARCHITECTURE.md`, or `DECISIONS.md`).

## How to add a new event source (the recipe)

Adding a venue/source must be **additive** — no core edits.

1. Create `src/opener/adapters/sources/<name>/`.
2. Implement the source adapter interface (fetch → list of raw records).
3. Map raw records to the normalized `Event` schema (`headliner`, `openers[]`, `date`, `venue`, `on_sale_date`, `ticket_url`, `source`, `source_id`).
4. Commit a real captured response as a fixture in `tests/fixtures/`.
5. Write a **contract test** that parses the fixture and fails if the layout changes.
6. Wire the source via **config**, not code.
7. Confirm the source-health (zero-result) check covers it.

If step 1–7 requires editing core or pipeline code, the abstraction is wrong — fix the abstraction, don't special-case the source.

## Testing rules

- **Fixture-based and offline.** Unit tests never hit the network. Record real responses once, commit them, test against them.
- **Contract tests for every adapter** — they are the canary for "the venue changed its site / Spotify changed its API."
- **Golden tests** for deterministic pipeline output (digest, playlist plan, scoring breakdowns).
- **Idempotency tests** for every stage.
- A test that needs the network belongs in a separate, clearly-marked integration suite that is **not** required for the unit gate.

## Diagnostics rules

- **Structured logs** (JSON), one event per meaningful decision.
- **`run_ledger`**: every stage run records what it touched and its outcome.
- **`dead_letter`**: every unparseable/failed record is captured with enough context to replay it.
- **Anomaly checks**: a source that returns zero (or far below its trailing average) raises an anomaly — it is almost always broken, not empty.
- **`explain` affordances**: it must be possible to ask "why did show X score Y?" and "why was track T chosen for artist A?" and get a real answer.

## Don't bake in assumptions

This project deliberately threw out an unexamined scoring algorithm and an unexamined event schema. Keep that discipline:

- Open design questions live in `DECISIONS.md`. If you must assume something to proceed, **record the assumption there** so it's visible and revisable.
- Two specifics that are **not** yet settled and must not be hardcoded silently: the venue-source backends (Phase 2.1 inventory) and the decay half-life / scoring weights (Phase 6 tuning).

## Working style

- Plan before coding; respect the phase gates in `PROJECT_PLAN.md` — a gate is a hard stop.
- Prefer small, reviewable changes over large ones.
- When a gate item is satisfied, note *how* it was proven (test name / command) next to the checkbox.
