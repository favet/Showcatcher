"""Phase 5.1 — Spotify OAuth tests (offline; HTTP mocked)."""
from typing import Any

import pytest

from opener.adapters.spotify.auth import SpotifyAuth, SpotifyToken


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


def _auth() -> SpotifyAuth:
    return SpotifyAuth(
        client_id="cid", client_secret="secret", redirect_uri="http://localhost:8080/callback"
    )


class TestAuthorizeUrl:
    def test_authorize_url_includes_scopes_and_redirect(self) -> None:
        url = _auth().build_authorize_url()
        assert url.startswith("https://accounts.spotify.com/authorize?")
        assert "client_id=cid" in url
        assert "playlist-modify-private" in url
        assert "redirect_uri=http" in url


class TestTokenExchange:
    def test_exchange_code_returns_tokens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        auth = _auth()
        payload = {"access_token": "acc", "refresh_token": "ref", "expires_in": 3600}
        monkeypatch.setattr(auth._session, "post", lambda *_a, **_k: FakeResponse(200, payload))

        token = auth.exchange_code("the-code", now=1000.0)
        assert token.access_token == "acc"
        assert token.refresh_token == "ref"
        assert token.expires_at == 1000.0 + 3600

    def test_failed_exchange_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from opener.adapters.spotify.auth import SpotifyAuthError

        auth = _auth()
        monkeypatch.setattr(auth._session, "post", lambda *_a, **_k: FakeResponse(400, {}))
        with pytest.raises(SpotifyAuthError):
            auth.exchange_code("bad")

    def test_refresh_reuses_refresh_token_when_omitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        auth = _auth()
        # Spotify often omits a new refresh_token on refresh.
        payload = {"access_token": "newacc", "expires_in": 3600}
        monkeypatch.setattr(auth._session, "post", lambda *_a, **_k: FakeResponse(200, payload))

        old = SpotifyToken(access_token="old", refresh_token="keepme", expires_at=0.0)
        refreshed = auth.refresh(old, now=2000.0)
        assert refreshed.access_token == "newacc"
        assert refreshed.refresh_token == "keepme"
        assert refreshed.expires_at == 2000.0 + 3600


class TestTokenExpiry:
    def test_is_expired_with_skew(self) -> None:
        token = SpotifyToken(access_token="a", refresh_token="r", expires_at=1000.0)
        assert token.is_expired(now=999.0) is True  # within 60s skew
        assert token.is_expired(now=900.0) is False
