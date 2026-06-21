# Showcat

> Find live shows in Portland by artists you'd love — including bands you've barely heard — and turn them into a Spotify discovery playlist. Live at [showcat.favet.net](https://showcat.favet.net).

## What it does

Showcat learns your taste from your listening history (with time-decay, so this week matters more than last year), watches a set of Portland venues for newly announced lineups, matches shows against your taste, and produces:

1. **A Spotify discovery playlist (the hero output)** — tracks from artists playing upcoming Portland shows, deliberately weighted *toward* bands you've under-explored. The point is discovery.
2. **A ticket digest (the companion)** — upcoming shows by artists you already know, with on-sale dates and ticket links, so you actually catch them before they sell out.

It runs as a pipeline of small, independent stages that communicate only through a Postgres database — built so you can add a venue, swap the scorer, or change an output without disturbing anything else.

## Status

**Phases 0–5 complete.** The full pipeline runs: Last.fm history → Ticketmaster events → entity resolution → discovery scoring → Spotify playlist write. See `PROJECT_PLAN.md` for the phased build and its provable exit gates.

## Architecture at a glance

```
[Last.fm] ─► ingest history ─┐
                             ├─► Postgres ─► resolve ─► score ─► outputs ┬─► Spotify playlist
[venue sources] ─► ingest events ─┘                                     └─► ticket digest
```

Stages never call each other; the database is the bus. Every external dependency (Last.fm, each venue, Spotify) sits behind an adapter with offline test fixtures. Every score is explainable and versioned. Nothing is a black box. Details in `ARCHITECTURE.md`.

## Documentation

| Doc | What's in it |
|---|---|
| **AGENTS.md** | Canonical working rules for agents (Claude Code + Antigravity). Start here if you're coding. |
| **CLAUDE.md** | Thin Claude Code pointer to AGENTS.md + tool-specific notes. |
| **ARCHITECTURE.md** | How the system is designed and why. |
| **PROJECT_PLAN.md** | Phased build with sub-phases and provable gate checklists. |
| **DECISIONS.md** | Decisions made + open questions (so assumptions stay visible). |

## Tech stack

Python · PostgreSQL · Docker Compose · Alembic · pytest · ruff/black/mypy.

## Quickstart

> Populated during Phase 0. Target shape:
```
cp .env.example .env      # add your API keys (never commit .env)
make up                   # app + Postgres
make migrate              # apply schema
make test                 # offline unit suite
make health               # per-stage last-run summary
```

## Scope & data

Single-user, self-hosted, personal use. Listening history is owned locally (sourced from Last.fm). The playlist output uses the surviving Spotify API surface via an adapter designed to be swapped if that changes again. See `DECISIONS.md` for resolved and open architectural decisions.
