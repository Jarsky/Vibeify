"""Design playlists: generate from a guided form or a prompt, refine in chat, edit, save to Spotify, history."""
import html

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import entitlements, security, settings_store
from ..db import get_db
from ..models import Generation, SpotifyConnection, User
from ..services import matching, recommend
from ..services.llm import registry
from ..services.llm.base import LLMError
from ..services.spotify import SpotifyClient, SpotifyError, track_summary
from .library import owned_playlist

MAX_TRACKS = 100   # most songs a playlist here can hold (refinement asks the model for the whole list)

router = APIRouter(prefix="/api/generations", tags=["generations"], dependencies=[Depends(security.csrf_guard)])


class GuidedIn(BaseModel):
    genres: str = Field("", max_length=300)
    artists: str = Field("", max_length=500)
    mood: str = Field("", max_length=300)
    year_from: int | None = Field(None, ge=1900, le=2100)
    year_to: int | None = Field(None, ge=1900, le=2100)
    discovery: str = Field("mixed", pattern="^(familiar|mixed|new)$")
    allow_explicit: bool = True
    notes: str = Field("", max_length=1000)


class GenerateIn(BaseModel):
    mode: str = Field(pattern="^(guided|prompt)$")
    guided: GuidedIn | None = None
    prompt: str = Field("", max_length=2000)
    count: int = Field(20, ge=5, le=100)
    personalize: bool = False
    model: str | None = None
    seed_playlist_ids: list[str] = Field(default_factory=list, max_length=3)   # the user's playlists, for inspiration


class ImportIn(BaseModel):
    playlist_id: str = Field(min_length=1, max_length=64)


class RefineIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    model: str | None = None


class EditIn(BaseModel):
    title: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=300)
    order: list[int] | None = None   # indexes into the current track list; omitted indexes are removed
    shared: bool | None = None


class SaveIn(BaseModel):
    public: bool = False
    share: bool = False      # list it, anonymously, on the community feed


async def _connection(db: AsyncSession, user: User) -> SpotifyConnection:
    conn = await db.get(SpotifyConnection, user.id)
    if not conn:
        raise HTTPException(409, "Connect your Spotify account first.")
    return conn


async def _own_generation(db: AsyncSession, user: User, gen_id: str) -> Generation:
    gen = await db.get(Generation, gen_id)
    if not gen or gen.user_id != user.id:
        raise HTTPException(404, "Playlist not found.")
    return gen


def _view(gen: Generation, *, full: bool = True) -> dict:
    count = (gen.request or {}).get("count", 20)
    matched = [t for t in gen.tracks if t.get("spotify")]
    out = {
        "id": gen.id, "title": gen.title, "description": gen.description, "model_label": gen.model_label,
        "created_at": gen.created_at, "updated_at": gen.updated_at, "count": count,
        "matched": len(matched), "spotify_playlist_url": gen.spotify_playlist_url,
        "shared": gen.shared, "spotify_public": gen.spotify_public, "imported": (gen.request or {}).get("mode") == "import",
        "cover": next((t["spotify"]["image"] for t in matched if t["spotify"].get("image")), None),
    }
    if full:
        out.update(request=gen.request, messages=gen.messages, tracks=gen.tracks)
    return out


def _untouched_import(gen: Generation) -> bool:
    """A Spotify playlist that was opened here but never refined, edited or saved: not worth listing in history."""
    return (gen.request or {}).get("mode") == "import" and not (gen.request or {}).get("edited")


def _mark_edited(gen: Generation) -> None:
    if _untouched_import(gen):
        gen.request = {**gen.request, "edited": True}   # reassign: JSON columns don't track in-place changes


def _fit(tracks: list[dict], count: int) -> list[dict]:
    """Keep suggestions up to the `count`th matched song; unmatched ones before it stay visible (not saved)."""
    kept, matched = [], 0
    for t in tracks:
        if matched >= count:
            break
        matched += bool(t.get("spotify"))
        kept.append(t)
    return kept


def _clean_suggestions(data: dict, limit: int) -> list[dict]:
    out = []
    for t in data.get("tracks") or []:
        title, artist = str(t.get("title", "")).strip(), str(t.get("artist", "")).strip()
        if title and artist:
            out.append({"title": title[:200], "artist": artist[:200], "reason": str(t.get("reason", "")).strip()[:200]})
    return out[:limit]


async def _ask_llm(db, user, settings, model_choice, messages, gen_id=None):
    resolved = await registry.resolve(db, user, settings, model_choice)
    if not resolved.option.own_key:   # limits cover the site's keys only
        await entitlements.check_quota(db, user, settings)
    try:
        result = await registry.complete_json(resolved, recommend.SYSTEM_PROMPT, messages, recommend.PLAYLIST_SCHEMA)
    except LLMError as e:
        raise HTTPException(e.status, str(e)) from e
    await registry.log_usage(db, user, resolved, result, gen_id)
    return resolved, result


@router.get("")
async def history(user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(select(Generation).where(Generation.user_id == user.id).order_by(Generation.updated_at.desc()).limit(200))
    return [_view(g, full=False) for g in rows.scalars() if not _untouched_import(g)]


@router.post("")
async def create(body: GenerateIn, user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    settings = await settings_store.load(db)
    conn = await _connection(db, user)
    ent = await entitlements.for_user(db, user, settings)
    count = min(body.count, ent.max_playlist_size)
    seeds = list(dict.fromkeys(body.seed_playlist_ids))
    if seeds and not ent.playlist_seeds:
        raise HTTPException(403, "Using your playlists as inspiration isn't included in your plan." + entitlements.upgrade_hint(settings))
    if body.mode == "guided":
        guided = (body.guided or GuidedIn()).model_dump()
        if not seeds and not any(guided.get(k) for k in ("genres", "artists", "mood", "notes", "year_from", "year_to")):
            raise HTTPException(400, "Tell us at least a genre, an artist, a mood or a note.")
        prompt = recommend.guided_prompt(guided, recommend.with_extra(count))
        allow_explicit = guided["allow_explicit"]
    else:
        if len(body.prompt.strip()) < 3 and not seeds:
            raise HTTPException(400, "Describe the playlist you want.")
        text = body.prompt.strip() or "Make me a new playlist in the spirit of my playlists below."
        prompt = recommend.free_prompt(text, recommend.with_extra(count))
        allow_explicit = True
        guided = None

    async with SpotifyClient(conn) as sp:
        try:
            seed_info = []
            for pid in seeds:
                meta = await owned_playlist(sp, conn, pid)
                songs = await sp.playlist_tracks(pid, limit=300)
                if songs:
                    prompt = f"{prompt}\n\n{recommend.seed_prompt(meta.get('name') or 'Untitled', songs)}"
                seed_info.append({"id": pid, "name": meta.get("name") or "Untitled"})
            if body.personalize:
                profile = recommend.taste_profile(await sp.top("artists"), await sp.top("tracks"), await sp.recently_played())
                if profile:
                    prompt = f"{prompt}\n\n{profile}"
            resolved, result = await _ask_llm(db, user, settings, body.model, [{"role": "user", "content": prompt}])
            suggestions = _clean_suggestions(result.data, recommend.with_extra(count) + 10)
            if not suggestions:
                raise HTTPException(424, "The model didn't suggest any songs. Try again or rephrase.")
            tracks = _fit(await matching.match_tracks(sp, suggestions, allow_explicit=allow_explicit), count)
        except SpotifyError as e:
            await db.commit()   # keep refreshed tokens / usage
            raise HTTPException(424 if e.status != 401 else 409, f"Spotify: {e}") from e

    gen = Generation(
        user_id=user.id, title=str(result.data.get("title", ""))[:100] or "New playlist",
        description=str(result.data.get("description", ""))[:300],
        request={"mode": body.mode, "guided": guided, "prompt": body.prompt, "count": count,
                 "personalize": body.personalize, "allow_explicit": allow_explicit, "seed_playlists": seed_info},
        model_label=resolved.option.label,
        messages=[{"role": "user", "content": (body.prompt.strip() if body.mode == "prompt" else "Guided request")
                   + (f" (inspired by {', '.join(x['name'] for x in seed_info)})" if seed_info else "") or "New playlist"},
                  {"role": "assistant", "content": str(result.data.get("message", ""))[:1000]}],
        tracks=tracks,
    )
    db.add(gen)
    await db.commit()
    return _view(gen)


@router.post("/import")
async def import_playlist(body: ImportIn, user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    """Load one of the user's own Spotify playlists to refine here; saving replaces its songs on Spotify."""
    settings = await settings_store.load(db)
    if not (await entitlements.for_user(db, user, settings)).edit_playlists:
        raise HTTPException(403, "Editing your Spotify playlists isn't included in your plan." + entitlements.upgrade_hint(settings))
    conn = await _connection(db, user)
    existing = (await db.execute(select(Generation).where(Generation.user_id == user.id,
                                                          Generation.spotify_playlist_id == body.playlist_id)
                                 .order_by(Generation.updated_at.desc()))).scalars().all()
    for gen in existing:
        if not _untouched_import(gen):
            return _view(gen)   # carry on with the edits already made here
    async with SpotifyClient(conn) as sp:
        try:
            meta = await owned_playlist(sp, conn, body.playlist_id)
            songs = await sp.playlist_tracks(body.playlist_id, limit=MAX_TRACKS + 1)
        except SpotifyError as e:
            await db.commit()
            raise HTTPException(424 if e.status != 401 else 409, f"Spotify: {e}") from e
    if not songs:
        raise HTTPException(400, "This playlist has no songs to work with.")
    if len(songs) > MAX_TRACKS:
        raise HTTPException(400, f"Playlists over {MAX_TRACKS} songs can't be edited here yet (saving would drop the rest). "
                                 "Use it as inspiration for a new playlist instead.")
    tracks, seen = [], set()
    for t in songs:
        if t["uri"] in seen:
            continue
        seen.add(t["uri"])
        tracks.append({"title": t.get("name") or "", "artist": ((t.get("artists") or [{}])[0] or {}).get("name") or "",
                       "reason": "", "spotify": track_summary(t)})
    name = meta.get("name") or "Untitled"
    for old in existing:   # untouched copies from earlier visits: replace with the playlist as it is now
        await db.delete(old)
    gen = Generation(
        user_id=user.id, title=name[:100], description=html.unescape(meta.get("description") or "")[:300],
        request={"mode": "import", "count": len(tracks), "allow_explicit": True, "source_playlist": {"id": meta["id"], "name": name}},
        model_label="", tracks=tracks,
        messages=[{"role": "assistant", "content": f"Loaded \u201c{name}\u201d from Spotify ({len(tracks)} songs). Tell me what to change. "
                                                   "When you're happy, Update on Spotify replaces the playlist's songs."}],
        spotify_playlist_id=meta["id"], spotify_playlist_url=(meta.get("external_urls") or {}).get("spotify"),
    )
    db.add(gen)
    await db.commit()
    return _view(gen)


@router.get("/{gen_id}")
async def get_one(gen_id: str, user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    return _view(await _own_generation(db, user, gen_id))


@router.post("/{gen_id}/refine")
async def refine(gen_id: str, body: RefineIn, user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    settings = await settings_store.load(db)
    gen = await _own_generation(db, user, gen_id)
    conn = await _connection(db, user)
    count = (gen.request or {}).get("count", 20)
    allow_explicit = (gen.request or {}).get("allow_explicit", True)
    known = {matching.match_key(t): t.get("spotify") for t in gen.tracks}
    messages = [{"role": "user", "content": recommend.revision_prompt(body.message, gen.tracks, count)}]
    async with SpotifyClient(conn) as sp:
        try:
            resolved, result = await _ask_llm(db, user, settings, body.model, messages, gen.id)
            try:   # the model reports the length the user asked for ("add 5 more", "cut it to 15")
                size = int(result.data.get("size") or count)
            except (TypeError, ValueError):
                size = count
            limit = (await entitlements.for_user(db, user, settings)).max_playlist_size
            count = max(1, min(size, MAX_TRACKS, max(limit, count)))
            suggestions = _clean_suggestions(result.data, recommend.with_extra(count) + 10)
            if not suggestions:
                raise HTTPException(424, "The model didn't return any songs. Try rephrasing your request.")
            gen.tracks = _fit(await matching.match_tracks(sp, suggestions, allow_explicit=allow_explicit, known=known), count)
        except SpotifyError as e:
            await db.commit()
            raise HTTPException(424 if e.status != 401 else 409, f"Spotify: {e}") from e
    gen.title = str(result.data.get("title") or gen.title)[:100]
    gen.description = str(result.data.get("description") or gen.description)[:300]
    gen.model_label = resolved.option.label
    gen.request = {**(gen.request or {}), "count": count}
    _mark_edited(gen)
    gen.messages = [*gen.messages, {"role": "user", "content": body.message},
                    {"role": "assistant", "content": str(result.data.get("message", ""))[:1000]}]
    await db.commit()
    return _view(gen)


@router.patch("/{gen_id}")
async def edit(gen_id: str, body: EditIn, user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    gen = await _own_generation(db, user, gen_id)
    if body.title is not None:
        gen.title = body.title.strip() or gen.title
    if body.description is not None:
        gen.description = body.description.strip()
    if body.shared is not None:
        if body.shared and (gen.request or {}).get("mode") == "import":
            raise HTTPException(400, "Playlists loaded from your Spotify can't be shared on the community feed.")
        gen.shared = body.shared
    if body.order is not None:
        if any(i < 0 or i >= len(gen.tracks) for i in body.order) or len(set(body.order)) != len(body.order):
            raise HTTPException(400, "Invalid track order.")
        gen.tracks = [gen.tracks[i] for i in body.order]
    if body.title is not None or body.description is not None or body.order is not None:
        _mark_edited(gen)
    await db.commit()
    return _view(gen)


@router.post("/{gen_id}/save")
async def save(gen_id: str, body: SaveIn, user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    gen = await _own_generation(db, user, gen_id)
    conn = await _connection(db, user)
    uris = [t["spotify"]["uri"] for t in gen.tracks if t.get("spotify")]
    if not uris:
        raise HTTPException(400, "None of these songs were found on Spotify, so there's nothing to save.")
    settings = await settings_store.load(db)
    async with SpotifyClient(conn) as sp:
        try:
            if gen.spotify_playlist_id:   # saved before: replace the contents
                await sp.request("PUT", f"/playlists/{gen.spotify_playlist_id}/items", json={"uris": uris[:100]})
                if len(uris) > 100:
                    await sp.add_items(gen.spotify_playlist_id, uris[100:])
                await sp.request("PUT", f"/playlists/{gen.spotify_playlist_id}",
                                 json={"name": gen.title[:100], "description": gen.description[:300]})
            else:
                desc = f"{gen.description} · Made with {settings['site_name']}".strip(" ·")
                playlist = await sp.create_playlist(gen.title or "New playlist", desc, body.public)
                gen.spotify_playlist_id = playlist["id"]
                gen.spotify_playlist_url = (playlist.get("external_urls") or {}).get("spotify")
                gen.spotify_public = body.public
                gen.shared = body.share
                await sp.add_items(playlist["id"], uris)
        except SpotifyError as e:
            await db.commit()
            raise HTTPException(424 if e.status != 401 else 409, f"Spotify: {e}") from e
    _mark_edited(gen)
    await db.commit()
    return _view(gen)


@router.delete("/{gen_id}")
async def remove(gen_id: str, user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _own_generation(db, user, gen_id))
    await db.commit()
    return {"ok": True}
