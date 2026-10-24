"""Find each suggested song on Spotify (search is limited to 10 results per call for Development Mode apps)."""
import asyncio
import re
import unicodedata

from rapidfuzz import fuzz

from .spotify import SpotifyClient, SpotifyError, track_summary

_NOISE = re.compile(r"\s*[\(\[][^)\]]*(remaster|remix|version|edit|live|mono|stereo|feat\.?|ft\.?|with )[^)\]]*[\)\]]", re.I)
_DASH_SUFFIX = re.compile(r"\s+-\s+.*(remaster|version|edit|live|mono|stereo|mix).*$", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = _DASH_SUFFIX.sub("", _NOISE.sub("", s))
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).replace(" and ", " ").strip()


def score(title: str, artist: str, candidate: dict) -> float:
    t = fuzz.ratio(norm(title), norm(candidate.get("name", "")))
    artists = [a.get("name", "") for a in candidate.get("artists") or []]
    a = max((fuzz.token_set_ratio(norm(artist), norm(x)) for x in artists), default=0)
    return 0.0 if t < 80 or a < 75 else (t * 0.6 + a * 0.4)


async def match_one(client: SpotifyClient, title: str, artist: str, allow_explicit: bool) -> dict | None:
    q_title, q_artist = title.replace('"', ""), artist.replace('"', "")
    for query in (f'track:"{q_title}" artist:"{q_artist}"', f"{q_title} {q_artist}"):
        try:
            candidates = await client.search_tracks(query, limit=10)
        except SpotifyError as e:
            if e.status in (401, 429):
                raise
            continue
        ranked = sorted(((score(title, artist, c), c) for c in candidates), key=lambda x: -x[0])
        for s, c in ranked:
            if s <= 0:
                break
            if not allow_explicit and c.get("explicit"):
                continue
            return track_summary(c)
    return None


async def match_tracks(client: SpotifyClient, suggestions: list[dict], *, allow_explicit: bool = True,
                       known: dict[str, dict | None] | None = None, concurrency: int = 4) -> list[dict]:
    """Return suggestions with a "spotify" field (summary or None). `known` reuses earlier matches by key."""
    known = known or {}
    sem = asyncio.Semaphore(concurrency)

    async def one(s: dict) -> dict:
        key = f"{norm(s['title'])}|{norm(s['artist'])}"
        if key in known:
            return {**s, "spotify": known[key]}
        async with sem:
            found = await match_one(client, s["title"], s["artist"], allow_explicit)
        return {**s, "spotify": found}

    results = await asyncio.gather(*(one(s) for s in suggestions))
    seen: set[str] = set()
    out = []
    for r in results:   # drop duplicate Spotify tracks (e.g. two titles resolving to one recording)
        uri = (r.get("spotify") or {}).get("uri")
        if uri and uri in seen:
            continue
        if uri:
            seen.add(uri)
        out.append(r)
    return out


def match_key(t: dict) -> str:
    return f"{norm(t['title'])}|{norm(t['artist'])}"
