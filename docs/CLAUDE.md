# CLAUDE.md — Showcat

**Canonical guidance for this repo lives in [`AGENTS.md`](./AGENTS.md). Read it first — it is the source of truth.** This file only adds Claude Code-specific notes. Do not duplicate rules here; if a rule changes, change it in `AGENTS.md` so the two never drift.

## Orientation (read in this order)
1. `AGENTS.md` — working rules, architecture invariants, definition of done.
2. `ARCHITECTURE.md` — how the system is designed.
3. `PROJECT_PLAN.md` — phased build with provable exit gates. **A gate is a hard stop.**
4. `DECISIONS.md` — decisions made and open questions. Record assumptions here.

## The five things to never get wrong
1. Stages couple **only** through the database — no stage calls another.
2. Every stage is **idempotent** (re-run = no duplicates), proven by a test.
3. Every external dependency (Last.fm, each venue source, Spotify) sits **behind an adapter** with committed fixtures.
4. Scoring is **explainable and versioned** — every score decomposes into named, persisted terms.
5. **Never a black box** — every non-trivial decision is logged or decomposable.

## Claude Code working notes
- Before implementing, state which **phase and sub-phase** of `PROJECT_PLAN.md` you're working in, and which gate items the change advances.
- Keep changes small and reviewable; prefer one sub-phase at a time.
- Unit tests must run **offline** against fixtures. If you reach for the network in a unit test, stop — record a real response as a fixture instead.
- When you satisfy a gate item, check its box in `PROJECT_PLAN.md` and note *how* it was proven (test name or command).
- Secrets come from env only. Never write a key into a file. Confirm `.env` is gitignored before touching credentials.
- If a task seems to require editing core/pipeline code to add a *source*, the adapter abstraction is wrong — fix the abstraction.

## Commands
> Filled in during Phase 0; keep this list current as the source of truth for how to run things.
- `make up` — bring up app + Postgres.
- `make test` — run the offline unit suite (lint + types + pytest).
- `make health` — print each stage's last run + status.
- `make migrate` — apply migrations.
