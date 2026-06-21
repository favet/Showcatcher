"""playlist CLI — authorize, dry-run, write, or export the discovery playlist.

Subcommands:
  authorize            print the one-time Spotify consent URL
  token <code>         exchange an auth code for tokens (save the refresh token)
  dryrun               build + print the plan, write nothing (resolves URIs)
  write                build the plan and create/refresh the real playlist
  export <path>        build the plan and write it to a local JSON file

Track selection is Last.fm; Spotify is the URI resolver + write target. dryrun
and write need a Spotify access token (refreshed from SPOTIFY_REFRESH_TOKEN);
obtain the refresh token once via `authorize` + `token`.
"""
import os
import sys

from showcat.adapters.lastfm.client import LastFmClient
from showcat.adapters.spotify.auth import SpotifyAuth, SpotifyToken
from showcat.adapters.spotify.client import SpotifyClient
from showcat.core import config as _config  # noqa: F401  (loads .env on import)
from showcat.core import database
from showcat.outputs.playlist.adapter import PlaylistOutputAdapter, PlaylistPlan
from showcat.outputs.playlist.writers import (
    ExportFilePlaylistWriter,
    SpotifyPlaylistWriter,
)


def _lastfm() -> LastFmClient:
    api_key = os.environ.get("LASTFM_API_KEY", "")
    if not api_key:
        raise SystemExit("LASTFM_API_KEY must be set")
    return LastFmClient(api_key=api_key, user=os.environ.get("LASTFM_USER", ""))


def _spotify_client() -> SpotifyClient:
    refresh_token = os.environ.get("SPOTIFY_REFRESH_TOKEN", "")
    if not refresh_token:
        raise SystemExit(
            "SPOTIFY_REFRESH_TOKEN must be set — run `authorize` then `token <code>` first"
        )
    auth = SpotifyAuth.from_env()
    token = auth.refresh(SpotifyToken(access_token="", refresh_token=refresh_token, expires_at=0))
    return SpotifyClient(access_token=token.access_token)


def _build_plan(spotify: SpotifyClient) -> PlaylistPlan:
    lastfm = _lastfm()
    adapter = PlaylistOutputAdapter()
    with database.get_db_session() as session:
        plan = adapter.build(session, lastfm, spotify)
    return plan


def _print_plan(plan: PlaylistPlan) -> None:
    print(f"Discovery playlist plan — {plan.name} [{plan.scoring_version}]")
    print(
        f"  {plan.to_dict()['track_count']} tracks, "
        f"{plan.to_dict()['resolved_count']} resolved, "
        f"under-explored {plan.under_explored_pct:.0%}"
    )
    for e in plan.entries:
        flag = "*" if e.under_explored else " "
        print(f"  {flag} {e.artist_name} — {e.track_name}  [{e.uri or 'UNRESOLVED'}]")


def cmd_authorize() -> int:
    print(SpotifyAuth.from_env().build_authorize_url())
    print("\nVisit the URL, approve, then copy the `code` query param from the redirect.")
    return 0


def cmd_token(code: str) -> int:
    token = SpotifyAuth.from_env().exchange_code(code)
    print("Save this in your .env (gitignored):")
    print(f"SPOTIFY_REFRESH_TOKEN={token.refresh_token}")
    return 0


def cmd_dryrun() -> int:
    plan = _build_plan(_spotify_client())
    _print_plan(plan)
    print("\n(dry-run — no playlist written)")
    return 0


def cmd_write() -> int:
    spotify = _spotify_client()
    plan = _build_plan(spotify)
    writer = SpotifyPlaylistWriter(spotify, os.environ.get("SPOTIFY_PLAYLIST_ID") or None)
    locator = writer.write(plan.name, plan.public, plan.resolved_uris)
    _print_plan(plan)
    print(f"\nWritten: {locator}")
    return 0


def cmd_export(path: str) -> int:
    plan = _build_plan(_spotify_client())
    locator = ExportFilePlaylistWriter(path).write(plan.name, plan.public, plan.resolved_uris)
    _print_plan(plan)
    print(f"\nExported: {locator}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "authorize":
        return cmd_authorize()
    if cmd == "token" and rest:
        return cmd_token(rest[0])
    if cmd == "dryrun":
        return cmd_dryrun()
    if cmd == "write":
        return cmd_write()
    if cmd == "export" and rest:
        return cmd_export(rest[0])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
