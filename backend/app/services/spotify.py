"""Spotify Web API: PKCE sign-in, token refresh, and the endpoints the app uses.

Written for the February 2026 Web API rules for Development Mode apps: playlists are created with
POST /me/playlists, items added with POST /playlists/{id}/items, and search returns at most 10 results.
"""
import asyncio
import base64
import hashlib
import secrets
import time
from datetime import timedelta, timezone
from urllib.parse import urlencode

import httpx

from .. import crypto
from ..db import utcnow
from ..models import SpotifyConnection

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
SCOPES = " ".join([
    "user-read-private",
    "playlist-read-private",
    "playlist-modify-private",
    "playlist-modify-public",
    "user-top-read",
    "user-read-recently-played",
    "user-library-read",
])


class SpotifyError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class SpotifyUserNotRegistered(SpotifyError):
    """Development Mode app and this Spotify user isn't on its user list (5-user limit)."""


# ── PKCE sign-in ─────────────────────────────────────────────────────────────
def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": redirect_uri, "state": state,
        "scope": SCOPES, "code_challenge_method": "S256", "code_challenge": challenge,
    })


async def exchange_code(client_id: str, code: str, redirect_uri: str, verifier: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.post(TOKEN_URL, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": client_id, "code_verifier": verifier,
        })
    if r.status_code != 200:
        raise SpotifyError(_error_text(r), r.status_code)
    return r.json()


async def get_me(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.get(f"{API}/me", headers={"Authorization": f"Bearer {access_token}"})
    if r.status_code == 403:
        raise SpotifyUserNotRegistered(_error_text(r), 403)
    if r.status_code != 200:
        raise SpotifyError(_error_text(r), r.status_code)
    return r.json()


def store_tokens(conn: SpotifyConnection, tokens: dict) -> None:
    conn.access_token_enc = crypto.encrypt(tokens["access_token"])
    if tokens.get("refresh_token"):
        conn.refresh_token_enc = crypto.encrypt(tokens["refresh_token"])
    conn.expires_at = utcnow() + timedelta(seconds=int(tokens.get("expires_in", 3600)) - 60)
    if tokens.get("scope"):
        conn.scopes = tokens["scope"]


def _error_text(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return f"Spotify returned HTTP {r.status_code}"
    err = body.get("error")
    if isinstance(err, dict):
        return err.get("message") or f"HTTP {r.status_code}"
    return body.get("error_description") or str(err or f"HTTP {r.status_code}")


# ── API client for a connected user ──────────────────────────────────────────
class SpotifyClient:
    """Calls the Web API as the user, refreshing the token when needed. Caller commits the DB session."""

    def __init__(self, conn: SpotifyConnection, http: httpx.AsyncClient | None = None):
        self.conn = conn
        self.http = http or httpx.AsyncClient(timeout=20)
        self._own_http = http is None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        if self._own_http:
            await self.http.aclose()

    async def _token(self) -> str:
        expires = self.conn.expires_at
        if expires.tzinfo is None:   # SQLite returns naive datetimes
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= utcnow():
            await self._refresh()
        return crypto.decrypt(self.conn.access_token_enc) or ""

    async def _refresh(self) -> None:
        refresh = crypto.decrypt(self.conn.refresh_token_enc)
        if not refresh:
            raise SpotifyError("Spotify connection expired; please reconnect Spotify.", 401)
        r = await self.http.post(TOKEN_URL, data={
            "grant_type": "refresh_token", "refresh_token": refresh, "client_id": self.conn.client_id,
        })
        if r.status_code != 200:
            raise SpotifyError("Spotify connection expired; please reconnect Spotify.", 401)
        store_tokens(self.conn, r.json())

    async def request(self, method: str, path: str, **kwargs) -> dict:
        for attempt in range(4):
            r = await self.http.request(method, f"{API}{path}",
                                        headers={"Authorization": f"Bearer {await self._token()}"}, **kwargs)
            if r.status_code == 401 and attempt == 0:
                await self._refresh()
                continue
            if r.status_code == 429 and attempt < 3:
                await asyncio.sleep(min(float(r.headers.get("retry-after", "1")), 10))
                continue
            if r.status_code == 403 and path == "/me":
                raise SpotifyUserNotRegistered(_error_text(r), 403)
            if r.status_code >= 400:
                raise SpotifyError(_error_text(r), r.status_code)
            return r.json() if r.content else {}
        raise SpotifyError("Spotify is rate-limiting requests; try again shortly.", 429)

    # -- endpoints ------------------------------------------------------------
    async def me(self) -> dict:
        return await self.request("GET", "/me")

    async def search_tracks(self, query: str, limit: int = 10) -> list[dict]:
        data = await self.request("GET", "/search", params={"q": query, "type": "track", "limit": min(limit, 10)})
        return (data.get("tracks") or {}).get("items") or []

    async def top(self, kind: str, time_range: str = "medium_term", limit: int = 20) -> list[dict]:
        data = await self.request("GET", f"/me/top/{kind}", params={"time_range": time_range, "limit": limit})
        return data.get("items") or []

    async def recently_played(self, limit: int = 30) -> list[dict]:
        data = await self.request("GET", "/me/player/recently-played", params={"limit": limit})
        return [i["track"] for i in data.get("items") or [] if i.get("track")]

    async def create_playlist(self, name: str, description: str, public: bool) -> dict:
        return await self.request("POST", "/me/playlists",
                                  json={"name": name[:100], "description": description[:300], "public": public})

    async def my_playlists(self, limit: int = 300) -> list[dict]:
        """Playlists in the user's library (owned and followed); callers filter on owner."""
        out: list[dict] = []
        while len(out) < limit:
            data = await self.request("GET", "/me/playlists", params={"limit": 50, "offset": len(out)})
            items = [p for p in data.get("items") or [] if p]
            out += items
            if not data.get("next") or not items:
                break
        return out

    async def playlist(self, playlist_id: str) -> dict:
        return await self.request("GET", f"/playlists/{playlist_id}",
                                  params={"fields": "id,name,description,owner(id),images,external_urls"})

    async def playlist_tracks(self, playlist_id: str, limit: int = 500) -> list[dict]:
        """Track objects in a playlist, in order; podcasts episodes and local files are skipped."""
        out: list[dict] = []
        offset = 0
        while offset < limit:
            data = await self.request("GET", f"/playlists/{playlist_id}/items", params={"limit": 50, "offset": offset})
            items = data.get("items") or []
            for i in items:
                t = i.get("item") or i.get("track")   # "item" since the 2026 API changes
                if t and t.get("type", "track") == "track" and t.get("id") and not i.get("is_local"):
                    out.append(t)
            offset += len(items)
            if not data.get("next") or not items:
                break
        return out

    async def add_items(self, playlist_id: str, uris: list[str]) -> None:
        for i in range(0, len(uris), 100):
            await self.request("POST", f"/playlists/{playlist_id}/items", json={"uris": uris[i:i + 100]})


# ── API client for the app itself (no user) ─────────────────────────────────
_app_tokens: dict[str, tuple[float, str]] = {}


class AppClient:
    """Calls the Web API as the site's Spotify app (client credentials). Only public catalogue data, e.g. new releases."""

    def __init__(self, client_id: str, client_secret: str, http: httpx.AsyncClient | None = None):
        self.client_id, self.client_secret = client_id, client_secret
        self.http = http or httpx.AsyncClient(timeout=20)
        self._own_http = http is None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        if self._own_http:
            await self.http.aclose()

    async def _token(self, fresh: bool = False) -> str:
        hit = _app_tokens.get(self.client_id)
        if hit and hit[0] > time.monotonic() and not fresh:
            return hit[1]
        r = await self.http.post(TOKEN_URL, data={"grant_type": "client_credentials"}, auth=(self.client_id, self.client_secret))
        if r.status_code != 200:
            raise SpotifyError("Spotify rejected the site app's Client ID or secret.", r.status_code)
        body = r.json()
        _app_tokens[self.client_id] = (time.monotonic() + int(body.get("expires_in", 3600)) - 60, body["access_token"])
        return body["access_token"]

    async def request(self, method: str, path: str, **kwargs) -> dict:
        for attempt in range(4):
            r = await self.http.request(method, f"{API}{path}",
                                        headers={"Authorization": f"Bearer {await self._token(fresh=attempt == 1)}"}, **kwargs)
            if r.status_code == 401 and attempt == 0:
                continue
            if r.status_code == 429 and attempt < 3:
                await asyncio.sleep(min(float(r.headers.get("retry-after", "1")), 10))
                continue
            if r.status_code >= 400:
                raise SpotifyError(_error_text(r), r.status_code)
            return r.json() if r.content else {}
        raise SpotifyError("Spotify is rate-limiting requests; try again shortly.", 429)


def track_summary(t: dict) -> dict:
    """The fields of a Spotify track object the UI needs."""
    images = (t.get("album") or {}).get("images") or []
    return {
        "id": t.get("id"),
        "uri": t.get("uri"),
        "name": t.get("name"),
        "artists": [a.get("name") for a in t.get("artists") or []],
        "album": (t.get("album") or {}).get("name"),
        "image": images[-2]["url"] if len(images) >= 2 else (images[0]["url"] if images else None),
        "url": (t.get("external_urls") or {}).get("spotify"),
        "duration_ms": t.get("duration_ms"),
        "explicit": t.get("explicit", False),
    }
