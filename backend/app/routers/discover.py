"""Home page for signed-in users: new music and playlists from Spotify, and an anonymous feed of playlists made here.

Spotify results are the same for everyone in a country, so they are cached in memory and fetched with whichever
connected user asks first. Spotify's own editorial playlists aren't available to Development Mode apps, so the
inspiration row searches public playlists made by other Spotify users.
"""
import asyncio
import html
import re
import time
from collections import Counter
from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import ratelimit, security, settings_store
from ..db import get_db
from ..models import Generation, SpotifyConnection, User
from ..services.spotify import AppClient, SpotifyClient, SpotifyError, track_summary

router = APIRouter(prefix="/api/discover", tags=["discover"])

SPOTIFY_TTL = 6 * 3600
COUNTRY_TTL = 24 * 3600
THEMES = ["today's top hits", "chill vibes", "workout motivation", "indie discoveries", "throwback hits", "deep focus",
          "feel good", "road trip", "late night", "acoustic covers", "dance party", "rainy day", "summer hits",
          "lofi beats", "rock classics", "hip hop bangers", "jazz cafe", "sad songs", "country roads", "electronic"]
THEMES_PER_DAY = 6
MAX_CANDIDATES = 40     # playlists looked up for followers / freshness per refresh
MIN_FOLLOWERS = 1000
FRESH_DAYS = 30         # songs added within this many days

_cache: dict[str, tuple[float, object]] = {}
_lock = asyncio.Lock()


def _cached(key: str):
    hit = _cache.get(key)
    return hit[1] if hit and hit[0] > time.monotonic() else None


def _store(key: str, value, ttl: int) -> None:
    _cache[key] = (time.monotonic() + ttl, value)


def _image(images: list | None) -> str | None:
    images = images or []
    return images[1]["url"] if len(images) >= 2 else (images[0]["url"] if images else None)


def _album(a: dict) -> dict:
    return {"id": a.get("id"), "name": a.get("name"), "artists": [x.get("name") for x in a.get("artists") or []],
            "image": _image(a.get("images")), "release_date": a.get("release_date"), "type": a.get("album_type"),
            "tracks": a.get("total_tracks"), "url": (a.get("external_urls") or {}).get("spotify")}


def _playlist(p: dict, theme: str) -> dict:
    return {"id": p.get("id"), "name": p.get("name"), "description": html.unescape(p.get("description") or ""),
            "image": (p.get("images") or [{}])[0].get("url"), "owner": (p.get("owner") or {}).get("display_name") or "",
            "tracks": ((p.get("items") or p.get("tracks") or {}).get("total")), "theme": theme,
            "url": (p.get("external_urls") or {}).get("spotify")}


def todays_themes(day: date | None = None) -> list[str]:
    """A different handful of themes each day, the same for everyone that day."""
    start = (day or date.today()).toordinal() * THEMES_PER_DAY % len(THEMES)
    return [THEMES[(start + i) % len(THEMES)] for i in range(THEMES_PER_DAY)]


async def _new_releases(sp: SpotifyClient, country: str) -> list[dict]:
    data = await sp.request("GET", "/browse/new-releases", params={"country": country, "limit": 20})
    return [_album(a) for a in (data.get("albums") or {}).get("items") or [] if a]


async def _trending(sp: SpotifyClient, country: str) -> list[dict]:
    """The most popular songs released this year (search caps results at 10 per page)."""
    year = date.today().year
    seen, out = set(), []
    for offset in (0, 10, 20):
        data = await sp.request("GET", "/search", params={"q": f"year:{year}", "type": "track", "market": country,
                                                          "limit": 10, "offset": offset})
        for t in (data.get("tracks") or {}).get("items") or []:
            key = (t.get("name", "").lower(), ((t.get("artists") or [{}])[0] or {}).get("name", "").lower())
            if t and t.get("id") and key not in seen:
                seen.add(key)
                out.append({**track_summary(t), "popularity": t.get("popularity")})
    return sorted(out, key=lambda t: -(t["popularity"] or 0))[:20]


async def _playlist_stats(sp, playlist_id: str, country: str) -> tuple[int, str]:
    """(followers, newest added_at) for a playlist; added dates come from its first page of songs."""
    full = await sp.request("GET", f"/playlists/{playlist_id}", params={
        "market": country, "fields": "followers(total),items(items(added_at)),tracks(items(added_at))"})
    page = full.get("items") or full.get("tracks") or {}
    newest = max((i.get("added_at") or "" for i in page.get("items") or []), default="")
    return int((full.get("followers") or {}).get("total") or 0), newest


async def _inspiration(sp, country: str, exclude_owners: frozenset[str] = frozenset()) -> list[dict]:
    """Popular playlists that are being kept up to date: searched by trend and theme, ranked by followers.

    Playlists owned by people with an account here are left out, so nobody's own playlist turns up on the site.
    """
    today = date.today()
    month = today.strftime("%B").lower()
    queries = [(q, "trending") for q in (f"viral hits {today.year}", f"top hits {today.year}", f"best new songs {month} {today.year}",
                                         f"new music {month} {today.year}")]
    queries += [(f"{theme} {today.year}", theme) for theme in todays_themes()]
    candidates, seen = [], set()
    for q, theme in queries:
        data = await sp.request("GET", "/search", params={"q": q, "type": "playlist", "market": country, "limit": 10})
        for p in (data.get("playlists") or {}).get("items") or []:
            if not p or p.get("id") in seen or not p.get("images") or (p.get("owner") or {}).get("id") in exclude_owners:
                continue
            item = _playlist(p, theme)
            if (item["tracks"] or 0) >= 15:
                seen.add(item["id"])
                candidates.append(item)
    candidates = candidates[:MAX_CANDIDATES]
    sem = asyncio.Semaphore(5)

    async def stats(item):
        async with sem:
            try:
                item["followers"], item["updated"] = await _playlist_stats(sp, item["id"], country)
            except SpotifyError:
                item["followers"], item["updated"] = 0, ""

    await asyncio.gather(*(stats(c) for c in candidates))
    cutoff = (today - timedelta(days=FRESH_DAYS)).isoformat()
    fresh = sorted((c for c in candidates if c["followers"] >= MIN_FOLLOWERS and c["updated"] >= cutoff),
                   key=lambda c: -c["followers"])
    out, per_theme = [], Counter()
    for c in fresh:   # mostly trending picks, with a couple from each of today's themes
        if per_theme[c["theme"]] < (6 if c["theme"] == "trending" else 2):
            per_theme[c["theme"]] += 1
            out.append(c)
    return out[:12]


ROWS = (("new_releases", _new_releases), ("trending", _trending), ("inspiration", _inspiration))
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _row_key(name: str, country: str) -> str:
    return f"{name}:{country}:{date.today().isoformat()}"


async def _rows(db: AsyncSession, country: str, open_client) -> tuple[dict, dict]:
    """Rows for a country from the cache, fetching the missing ones with the client `open_client()` gives (or None)."""
    rows = {name: _cached(_row_key(name, country)) for name, _ in ROWS}
    errors: dict[str, str] = {}
    missing = [(name, fetch) for name, fetch in ROWS if rows[name] is None]
    if not missing:
        return rows, errors
    async with open_client() as sp:
        for name, fetch in missing:
            if sp is None:
                rows[name], errors[name] = [], "Spotify isn't available right now."
                continue
            async with _lock:   # one request fills the cache while others wait
                if (value := _cached(_row_key(name, country))) is None:
                    try:
                        value = await (fetch(sp, country, await _site_owners(db)) if fetch is _inspiration else fetch(sp, country))
                        _store(_row_key(name, country), value, SPOTIFY_TTL)
                    except SpotifyError as e:
                        errors[name] = str(e)
                        value = []
            rows[name] = value
    return rows, errors


async def _site_owners(db: AsyncSession) -> frozenset[str]:
    return frozenset((await db.execute(select(SpotifyConnection.spotify_user_id))).scalars())


@asynccontextmanager
async def _app_client(settings: dict):
    """The site's own Spotify app (not personalised to anyone), or None without a client secret."""
    if settings["spotify_client_id"] and settings["spotify_client_secret"]:
        async with AppClient(settings["spotify_client_id"], settings["spotify_client_secret"]) as app:
            yield app
    else:
        yield None


@router.get("/spotify")
async def spotify_rows(user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    """New releases, popular songs this year, and playlist ideas. A row that fails comes back empty with an error."""
    conn = await db.get(SpotifyConnection, user.id)
    if not conn:
        return {"connected": False, "country": None, "rows": {}, "errors": {}}
    async with SpotifyClient(conn) as sp:
        country = _cached(f"country:{user.id}")
        if country is None:
            try:
                country = (await sp.me()).get("country") or "US"
            except SpotifyError:
                country = "US"
            _store(f"country:{user.id}", country, COUNTRY_TTL)

        settings = await settings_store.load(db)

        @asynccontextmanager
        async def client():   # the app when possible: searches as a user are biased towards their own library
            async with _app_client(settings) as app:
                yield app or sp

        rows, errors = await _rows(db, country, client)
    await db.commit()   # keep a refreshed Spotify token
    return {"connected": True, "country": country, "rows": rows, "errors": errors}


@router.get("/public")
async def public_rows(request: Request, db: AsyncSession = Depends(get_db)):
    """New releases and playlist ideas for the signed-out landing page, for the visitor's country (Cloudflare's header).

    Fetched as the site's Spotify app when its client secret is set; otherwise through an admin's Spotify connection.
    """
    ratelimit.limit(f"discover:{security.client_ip(request)}", 60, 600)
    country = (request.headers.get("cf-ipcountry") or "").upper()
    if not COUNTRY_RE.match(country) or country in ("XX", "T1"):
        country = "US"
    settings = await settings_store.load(db)

    @asynccontextmanager
    async def client():
        async with _app_client(settings) as app:
            if app:
                yield app
                return
        conn = (await db.execute(select(SpotifyConnection).join(User, User.id == SpotifyConnection.user_id)
                                 .where(User.is_admin, User.is_disabled.is_(False))
                                 .order_by(SpotifyConnection.updated_at.desc()).limit(1))).scalar_one_or_none()
        if conn is None:
            yield None
            return
        async with SpotifyClient(conn) as sp:
            yield sp

    rows, errors = await _rows(db, country, client)
    await db.commit()
    return {"country": country, "rows": {"new_releases": rows["new_releases"], "inspiration": rows["inspiration"]}, "errors": errors}


def _shared_query():
    return (select(Generation).join(User, User.id == Generation.user_id)
            .where(Generation.shared, Generation.spotify_playlist_id.is_not(None), Generation.community_hidden.is_(False),
                   User.is_disabled.is_(False))
            .order_by(Generation.created_at.desc()).limit(24))


def _anonymous(rows: list[Generation], viewer: User) -> list[dict]:
    out = []
    for g in rows:
        tracks = [t["spotify"] for t in g.tracks if t.get("spotify")]
        if len(tracks) < 5:
            continue
        covers = list(dict.fromkeys(t["image"] for t in tracks if t.get("image")))[:4]
        artists = [a for a, _ in Counter(a for t in tracks for a in (t.get("artists") or [])[:1]).most_common(4)]
        out.append({"id": g.id, "title": g.title, "description": g.description, "tracks": len(tracks), "covers": covers,
                    "artists": artists, "created_at": g.created_at, "mine": g.user_id == viewer.id,
                    "url": g.spotify_playlist_url if g.spotify_public else None})
    return out[:12]


@router.get("/community")
async def community(user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    """Recent playlists people here chose to share. Nothing identifies who made them."""
    settings = await settings_store.load(db)
    if not settings["community_feed"]:
        return {"enabled": False, "playlists": []}
    return {"enabled": True, "playlists": _anonymous((await db.execute(_shared_query())).scalars().all(), user)}
