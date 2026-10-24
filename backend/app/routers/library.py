"""The user's own Spotify playlists, for editing them here or using them as inspiration."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .. import security
from ..db import get_db
from ..models import SpotifyConnection, User
from ..services.spotify import SpotifyClient, SpotifyError

router = APIRouter(prefix="/api/spotify", tags=["spotify"], dependencies=[Depends(security.csrf_guard)])


def _total(p: dict) -> int:
    return int(((p.get("items") or p.get("tracks")) or {}).get("total") or 0)


async def owned_playlist(sp: SpotifyClient, conn: SpotifyConnection, playlist_id: str) -> dict:
    try:
        meta = await sp.playlist(playlist_id)
    except SpotifyError as e:
        raise HTTPException(404, "Playlist not found on Spotify.") from e
    if (meta.get("owner") or {}).get("id") != conn.spotify_user_id:
        raise HTTPException(403, "You can only use playlists you own.")
    return meta


@router.get("/playlists")
async def my_playlists(user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    conn = await db.get(SpotifyConnection, user.id)
    if not conn:
        raise HTTPException(409, "Connect your Spotify account first.")
    async with SpotifyClient(conn) as sp:
        try:
            items = await sp.my_playlists()
        except SpotifyError as e:
            await db.commit()
            raise HTTPException(424 if e.status != 401 else 409, f"Spotify: {e}") from e
    await db.commit()   # keep a refreshed token
    return [{
        "id": p["id"], "name": p.get("name") or "Untitled", "description": p.get("description") or "",
        "image": ((p.get("images") or [{}])[0] or {}).get("url"), "total": _total(p),
        "url": (p.get("external_urls") or {}).get("spotify"), "public": p.get("public"),
    } for p in items if (p.get("owner") or {}).get("id") == conn.spotify_user_id]
