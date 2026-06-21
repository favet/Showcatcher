"""Spotify OAuth — Authorization Code flow with refresh.

Handles the narrow surviving auth surface we rely on: send the user through
consent once, exchange the returned code for an access + refresh token, then
refresh the short-lived access token as needed. Secrets come from env only.

The HTTP calls are isolated here so unit tests mock `requests` and never hit
the network; the live consent step is a documented manual action.
"""
import base64
import logging
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
# The minimal scopes for creating/refreshing a private playlist.
DEFAULT_SCOPES = ("playlist-modify-private", "playlist-modify-public")


class SpotifyAuthError(Exception):
    """Raised when a token request fails."""


@dataclass
class SpotifyToken:
    """An access token with its refresh token and absolute expiry (epoch seconds)."""

    access_token: str
    refresh_token: str
    expires_at: float

    def is_expired(self, now: float | None = None, skew_seconds: float = 60.0) -> bool:
        """True if the access token is at/near expiry (refresh before using)."""
        return (now or time.time()) >= (self.expires_at - skew_seconds)


class SpotifyAuth:
    """Authorization Code flow client. Network is confined to `_post_token`."""

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._session = requests.Session()

    @classmethod
    def from_env(cls) -> "SpotifyAuth":
        client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
        client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
        redirect_uri = os.environ.get(
            "SPOTIFY_REDIRECT_URI", "http://localhost:8080/callback"
        )
        if not client_id or not client_secret:
            raise SpotifyAuthError("SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set")
        return cls(client_id, client_secret, redirect_uri)

    def build_authorize_url(
        self, scopes: tuple[str, ...] = DEFAULT_SCOPES, state: str = "opener"
    ) -> str:
        """The URL to open in a browser for the one-time user consent."""
        query = urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": self.redirect_uri,
                "scope": " ".join(scopes),
                "state": state,
            }
        )
        return f"{SPOTIFY_AUTH_URL}?{query}"

    def _basic_auth_header(self) -> dict[str, str]:
        raw = f"{self.client_id}:{self.client_secret}".encode()
        return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}

    def _post_token(self, data: dict[str, str]) -> dict[str, Any]:
        response = self._session.post(
            SPOTIFY_TOKEN_URL,
            data=data,
            headers=self._basic_auth_header(),
            timeout=30,
        )
        if response.status_code != 200:
            raise SpotifyAuthError(
                f"Token request failed ({response.status_code}): {response.text}"
            )
        payload: dict[str, Any] = response.json()
        return payload

    def exchange_code(self, code: str, now: float | None = None) -> SpotifyToken:
        """Exchange an authorization code for the initial token pair."""
        payload = self._post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
            }
        )
        issued = now if now is not None else time.time()
        token = SpotifyToken(
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            expires_at=issued + float(payload.get("expires_in", 3600)),
        )
        logger.info("Spotify authorization code exchanged for tokens")
        return token

    def refresh(self, token: SpotifyToken, now: float | None = None) -> SpotifyToken:
        """Refresh the access token. Spotify may omit a new refresh_token; reuse the old."""
        payload = self._post_token(
            {"grant_type": "refresh_token", "refresh_token": token.refresh_token}
        )
        issued = now if now is not None else time.time()
        refreshed = SpotifyToken(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token", token.refresh_token),
            expires_at=issued + float(payload.get("expires_in", 3600)),
        )
        logger.info("Spotify access token refreshed")
        return refreshed
