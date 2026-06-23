# Showcat — Operational Runbook

Short, copy-pasteable procedures. All commands run from the repo root
(`C:\Users\Justin\Documents\SHOWCATCHER`) and use the `app` Docker service
(which has the DB at `db:5432`, `.env`, and `WEB_OUTPUT_DIR=/website_showcat`
bind-mounted to `C:\website\showcat`).

## Refresh the discovery playlist (hero output)

The discovery Spotify playlist (`SPOTIFY_PLAYLIST_ID=2WyamY…`) is **not** part
of the main pipeline — it's a separate, manual step. Refresh it after a pipeline
run that re-scored shows (the track selection is driven by `discovery-v1` scores).

```bash
# 1. Preview — resolves tracks via Spotify /search, writes NOTHING:
docker compose run --rm app python -m showcat.cli.playlist dryrun

# 2. Write — create/refresh the real playlist in place:
docker compose run --rm app python -m showcat.cli.playlist write
```

**Spotify rate-limit caution (see DECISIONS D21).** All Spotify calls share one
dev-mode quota. The `playlist` commands need `/search`, which is the *same*
budget the pipeline's `EventSpotifySearchStage` spends. If the pipeline just ran
a big event-search batch, `playlist` will 429 with a **multi-hour** `Retry-After`.
Rule of thumb: **don't refresh the playlist on the same day as a large
event-search run.** Check the cooldown:

```bash
docker compose run --rm app python -c "import os,requests; from showcat.core import config; from showcat.adapters.spotify.auth import SpotifyAuth,SpotifyToken; t=SpotifyAuth.from_env().refresh(SpotifyToken('', os.environ['SPOTIFY_REFRESH_TOKEN'],0)); r=requests.get('https://api.spotify.com/v1/search',headers={'Authorization':f'Bearer {t.access_token}'},params={'q':'x','type':'track','limit':1}); print(r.status_code, 'Retry-After=', r.headers.get('Retry-After'))"
```
`200` = clear to run. `429` = wait `Retry-After` seconds.

## Rebuild + redeploy the web page only (no data change)

Picks up template changes (favicon, layout) and current DB state; no network:

```bash
docker compose run --rm app python -m showcat.cli.web
# writes /website_showcat/index.html → C:\website\showcat (served via Caddy + Cloudflared)
```

## Full pipeline (ingest → resolve → tags → metadata → score → web)

```bash
docker compose run --rm app python -m showcat.cli.pipeline          # last 365d backfill
docker compose run --rm app python -m showcat.cli.pipeline full     # full history
```
The optional Spotify event-URL search runs only if `SPOTIFY_REFRESH_TOKEN` is set,
capped at `SPOTIFY_SEARCH_MAX_PER_RUN` (default 100) per run.

## Tests / lint

```bash
make test                              # full offline suite
docker compose run --rm app ruff check src tests
```
