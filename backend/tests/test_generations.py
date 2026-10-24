from datetime import timedelta

import httpx
import pytest
import respx

from app import crypto, settings_store
from app import db as app_db
from app.db import utcnow
from app.models import LLMModel, LLMProvider, SpotifyConnection
from app.services.llm import registry
from app.services.llm.base import LLMResult

from .conftest import sign_up

SONGS = [("Midnight City", "M83"), ("Intro", "The xx"), ("Breathe", "Telepopmusik"), ("Teardrop", "Massive Attack"),
         ("Nightcall", "Kavinsky"), ("Genesis", "Grimes"), ("Unfindable Song", "Nobody")]


def spotify_track(title, artist, n):
    return {"id": f"t{n}", "uri": f"spotify:track:t{n}", "name": title, "explicit": False, "duration_ms": 200000,
            "artists": [{"name": artist}], "album": {"name": "Album", "images": [{"url": f"https://img/{n}"}]},
            "external_urls": {"spotify": f"https://open.spotify.com/track/t{n}"}, "preview_url": None}


def search_handler(request: httpx.Request):
    q = request.url.params["q"].lower()
    for n, (title, artist) in enumerate(SONGS[:-1]):
        if title.lower() in q:
            return httpx.Response(200, json={"tracks": {"items": [spotify_track(title, artist, n)]}})
    return httpx.Response(200, json={"tracks": {"items": []}})


@pytest.fixture
async def ready_user(client, outbox, monkeypatch):
    await sign_up(client, outbox, "listener@example.com")
    me = (await client.get("/api/me")).json()
    async with app_db.sessionmaker()() as db:
        p = LLMProvider(name="Claude", kind="anthropic", api_key_enc=crypto.encrypt("sk-ant-x"), enabled=True)
        db.add(p)
        db.add(LLMModel(provider=p, model_id="claude-opus-5-5", display_name="Claude Opus 5.5", is_default=True))
        db.add(SpotifyConnection(user_id=me["id"], spotify_user_id="listener", display_name="Listener", client_id="a" * 32,
                                 uses_site_app=False, access_token_enc=crypto.encrypt("tok"), refresh_token_enc=crypto.encrypt("ref"),
                                 expires_at=utcnow() + timedelta(hours=1), scopes=""))
        await db.commit()

    calls = []

    async def fake_complete(resolved, system, messages, schema):
        calls.append(messages)
        tracks = [{"title": t, "artist": a, "reason": "fits"} for t, a in SONGS]
        if "swap" in messages[-1]["content"].lower():
            tracks = tracks[1:]
        return LLMResult(data={"message": "Here you go", "title": "Night Drive", "description": "Neon", "tracks": tracks},
                         input_tokens=100, output_tokens=50)

    monkeypatch.setattr(registry, "complete_json", fake_complete)
    return calls


@respx.mock
async def test_generate_refine_save(client, ready_user):
    respx.get("https://api.spotify.com/v1/search").mock(side_effect=search_handler)
    r = await client.post("/api/generations", json={"mode": "prompt", "prompt": "late night drive", "count": 5})
    assert r.status_code == 200, r.text
    gen = r.json()
    assert gen["title"] == "Night Drive"
    assert gen["matched"] == 5
    assert all(t["spotify"] for t in gen["tracks"])   # first 5 matched, unmatched song beyond the count dropped
    assert gen["cover"] == "https://img/0"

    r = await client.post(f"/api/generations/{gen['id']}/refine", json={"message": "swap the first song"})
    assert r.status_code == 200, r.text
    refined = r.json()
    assert refined["tracks"][0]["title"] == "Intro"
    assert len(refined["messages"]) == 4

    r = await client.patch(f"/api/generations/{gen['id']}", json={"order": [4, 3, 2, 1, 0], "title": "Renamed"})
    assert r.json()["tracks"][0]["title"] == SONGS[5][0]

    created = respx.post("https://api.spotify.com/v1/me/playlists").mock(return_value=httpx.Response(
        201, json={"id": "pl1", "external_urls": {"spotify": "https://open.spotify.com/playlist/pl1"}}))
    added = respx.post("https://api.spotify.com/v1/playlists/pl1/items").mock(return_value=httpx.Response(201, json={}))
    r = await client.post(f"/api/generations/{gen['id']}/save", json={"public": False})
    assert r.status_code == 200, r.text
    assert r.json()["spotify_playlist_url"].endswith("pl1")
    assert created.called and added.called
    assert "Renamed" in created.calls[0].request.content.decode()

    replaced = respx.put("https://api.spotify.com/v1/playlists/pl1/items").mock(return_value=httpx.Response(200, json={}))
    renamed = respx.put("https://api.spotify.com/v1/playlists/pl1").mock(return_value=httpx.Response(200))
    r = await client.post(f"/api/generations/{gen['id']}/save", json={})
    assert r.status_code == 200 and replaced.called and renamed.called

    hist = (await client.get("/api/generations")).json()
    assert len(hist) == 1 and "tracks" not in hist[0]
    me = (await client.get("/api/me")).json()
    assert me["usage"]["requests_today"] == 2 and me["usage"]["tokens_this_month"] == 300


@respx.mock
async def test_daily_quota(client, ready_user):
    respx.get("https://api.spotify.com/v1/search").mock(side_effect=search_handler)
    async with app_db.sessionmaker()() as db:
        from sqlalchemy import select

        from app.models import User
        u = (await db.execute(select(User))).scalar_one()
        u.daily_generation_limit = 1
        await db.commit()
    assert (await client.post("/api/generations", json={"mode": "prompt", "prompt": "rainy day", "count": 5})).status_code == 200
    r = await client.post("/api/generations", json={"mode": "prompt", "prompt": "rainy day", "count": 5})
    assert r.status_code == 429


async def test_generate_needs_spotify(client, outbox):
    await sign_up(client, outbox, "nospotify@example.com")
    r = await client.post("/api/generations", json={"mode": "prompt", "prompt": "anything", "count": 5})
    assert r.status_code == 409


async def test_other_users_generation_is_hidden(client, ready_user, outbox):
    async with app_db.sessionmaker()() as db:
        from sqlalchemy import select

        from app.models import Generation, User
        u = (await db.execute(select(User))).scalar_one()
        g = Generation(user_id=u.id, title="mine", description="", request={}, model_label="m", messages=[], tracks=[])
        db.add(g)
        await db.commit()
        gid = g.id
    await client.post("/api/auth/logout")
    await sign_up(client, outbox, "other@example.com")
    assert (await client.get(f"/api/generations/{gid}")).status_code == 404
    assert (await client.delete(f"/api/generations/{gid}")).status_code == 404


def mock_library():
    respx.get("https://api.spotify.com/v1/me/playlists").mock(return_value=httpx.Response(200, json={"items": [
        {"id": "pl9", "name": "Gym", "description": "Loud &amp; fast", "owner": {"id": "listener"}, "images": [{"url": "https://img/pl9"}],
         "items": {"total": 3}, "external_urls": {"spotify": "https://open.spotify.com/playlist/pl9"}, "public": False},
        {"id": "other", "name": "Today's Top Hits", "owner": {"id": "spotify"}, "images": [], "items": {"total": 50}},
    ], "next": None}))
    respx.get("https://api.spotify.com/v1/playlists/pl9").mock(return_value=httpx.Response(200, json={
        "id": "pl9", "name": "Gym", "description": "Loud &amp; fast", "owner": {"id": "listener"},
        "external_urls": {"spotify": "https://open.spotify.com/playlist/pl9"}}))
    respx.get("https://api.spotify.com/v1/playlists/other").mock(return_value=httpx.Response(200, json={
        "id": "other", "name": "Today's Top Hits", "owner": {"id": "spotify"}}))
    items = [{"item": spotify_track(t, a, n), "is_local": False} for n, (t, a) in enumerate(SONGS[:3])]
    items.append({"item": {"type": "episode", "id": "ep1", "uri": "spotify:episode:ep1"}, "is_local": False})
    respx.get("https://api.spotify.com/v1/playlists/pl9/items").mock(return_value=httpx.Response(200, json={"items": items, "next": None}))


@respx.mock
async def test_list_and_import_own_playlist(client, ready_user):
    mock_library()
    pls = (await client.get("/api/spotify/playlists")).json()
    assert [p["id"] for p in pls] == ["pl9"] and pls[0]["total"] == 3
    r = await client.post("/api/generations/import", json={"playlist_id": "pl9"})
    assert r.status_code == 200, r.text
    gen = r.json()
    assert gen["title"] == "Gym" and gen["description"] == "Loud & fast"
    assert [t["title"] for t in gen["tracks"]] == [s[0] for s in SONGS[:3]]   # episode skipped
    assert gen["spotify_playlist_url"].endswith("pl9") and gen["count"] == 3
    assert (await client.post("/api/generations/import", json={"playlist_id": "other"})).status_code == 403
    assert ready_user == []   # importing doesn't call the AI


@respx.mock
async def test_refine_can_change_length(client, ready_user, monkeypatch):
    mock_library()
    respx.get("https://api.spotify.com/v1/search").mock(side_effect=search_handler)
    gen = (await client.post("/api/generations/import", json={"playlist_id": "pl9"})).json()

    async def bigger(resolved, system, messages, schema):
        assert "Current playlist (3 songs)" in messages[-1]["content"]
        return LLMResult(data={"message": "Added two", "title": "Gym", "description": "d", "size": 5,
                               "tracks": [{"title": t, "artist": a, "reason": ""} for t, a in SONGS]}, input_tokens=1, output_tokens=1)

    monkeypatch.setattr(registry, "complete_json", bigger)
    r = await client.post(f"/api/generations/{gen['id']}/refine", json={"message": "add two more songs"})
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 5 and r.json()["matched"] == 5


@respx.mock
async def test_generate_with_playlist_seed(client, ready_user):
    mock_library()
    respx.get("https://api.spotify.com/v1/search").mock(side_effect=search_handler)
    r = await client.post("/api/generations", json={"mode": "prompt", "prompt": "", "count": 5, "seed_playlist_ids": ["pl9"]})
    assert r.status_code == 200, r.text
    sent = ready_user[-1][-1]["content"]
    assert 'my playlist "Gym" (3 songs)' in sent and "Midnight City — M83" in sent
    assert r.json()["request"]["seed_playlists"] == [{"id": "pl9", "name": "Gym"}]
    r = await client.post("/api/generations", json={"mode": "prompt", "prompt": "x y z", "count": 5, "seed_playlist_ids": ["other"]})
    assert r.status_code == 403


async def test_model_choice_toggle(client, ready_user):
    async with app_db.sessionmaker()() as db:
        p = LLMProvider(name="OpenAI", kind="openai", api_key_enc=crypto.encrypt("sk-x"), enabled=True)
        db.add(p)
        db.add(LLMModel(provider=p, model_id="gpt-x", display_name="GPT X", sort_order=-1))
        await db.commit()
    models = (await client.get("/api/me")).json()["models"]
    assert [m["label"] for m in models] == ["Claude Opus 5.5"]   # off by default: only the default model
    async with app_db.sessionmaker()() as db:
        await settings_store.save(db, {"allow_model_choice": True})
    models = (await client.get("/api/me")).json()["models"]
    assert {m["label"] for m in models} == {"Claude Opus 5.5", "GPT X"}


@respx.mock
async def test_discover_rows_cached_and_tolerant(client, ready_user):
    from app.routers import discover
    discover._cache.clear()
    me = respx.get("https://api.spotify.com/v1/me").mock(return_value=httpx.Response(200, json={"id": "listener", "country": "NZ"}))
    releases = respx.get("https://api.spotify.com/v1/browse/new-releases").mock(return_value=httpx.Response(200, json={"albums": {"items": [
        {"id": "al1", "name": "New Album", "artists": [{"name": "Band"}], "images": [{"url": "big"}, {"url": "mid"}],
         "release_date": "2026-10-16", "album_type": "album", "total_tracks": 10, "external_urls": {"spotify": "https://al1"}}]}}))

    def search(request: httpx.Request):
        if request.url.params["type"] == "track":
            n = int(request.url.params["offset"])
            items = [{**spotify_track(f"Hit {n + i}", "Star", n + i), "popularity": 50 + n + i} for i in range(3)]
            return httpx.Response(200, json={"tracks": {"items": items}})
        q = request.url.params["q"]
        return httpx.Response(200, json={"playlists": {"items": [
            None, {"id": "small", "name": "Tiny", "images": [{"url": "x"}], "items": {"total": 3}, "owner": {"display_name": "a"}},
            {"id": "mine", "name": "My own mix", "images": [{"url": "x"}], "items": {"total": 50}, "owner": {"id": "listener"}},
            {"id": f"pl-{q}", "name": q.title(), "description": "Best &amp; newest", "images": [{"url": "cover"}], "items": {"total": 40},
             "owner": {"id": "curator", "display_name": "Curator"}, "external_urls": {"spotify": "https://pl"}}]}})

    def stats(request: httpx.Request):
        pid = request.url.path.rsplit("/", 1)[1]
        stale = "viral" in pid   # one playlist nobody has updated for months
        added = "2026-01-01T00:00:00Z" if stale else utcnow().strftime("%Y-%m-%dT00:00:00Z")
        return httpx.Response(200, json={"followers": {"total": 5000 + len(pid)}, "items": {"items": [{"added_at": added}]}})

    respx.get("https://api.spotify.com/v1/search").mock(side_effect=search)
    detail = respx.get(url__regex=r"https://api\.spotify\.com/v1/playlists/[^/]+$").mock(side_effect=stats)
    data = (await client.get("/api/discover/spotify")).json()
    assert data["country"] == "NZ" and releases.calls[0].request.url.params["country"] == "NZ"
    assert data["rows"]["new_releases"][0]["image"] == "mid"
    trending = data["rows"]["trending"]
    assert len(trending) == 9 and trending[0]["popularity"] == 72   # sorted most popular first
    inspiration = data["rows"]["inspiration"]
    ids = [p["id"] for p in inspiration]
    assert len(inspiration) == 3 + discover.THEMES_PER_DAY and inspiration[0]["description"] == "Best & newest"
    assert "small" not in ids and "mine" not in ids   # too short, and a site user's own playlist
    assert not any("viral" in i for i in ids)          # not updated recently
    assert [p["followers"] for p in inspiration] == sorted((p["followers"] for p in inspiration), reverse=True)
    assert "mine" not in {c.request.url.path.rsplit("/", 1)[1] for c in detail.calls}
    calls = respx.calls.call_count
    await client.get("/api/discover/spotify")
    assert respx.calls.call_count == calls and me.call_count == 1   # served from the cache

    discover._cache.clear()
    releases.mock(return_value=httpx.Response(404, json={"error": {"status": 404, "message": "Not found"}}))
    data = (await client.get("/api/discover/spotify")).json()
    assert data["rows"]["new_releases"] == [] and "new_releases" in data["errors"] and data["rows"]["trending"]


@respx.mock
async def test_untouched_imports_stay_out_of_history(client, ready_user):
    mock_library()
    first = (await client.post("/api/generations/import", json={"playlist_id": "pl9"})).json()
    again = (await client.post("/api/generations/import", json={"playlist_id": "pl9"})).json()
    assert again["id"] != first["id"]   # untouched copy replaced with a fresh load, not duplicated
    assert (await client.get(f"/api/generations/{first['id']}")).status_code == 404
    assert (await client.get("/api/generations")).json() == []   # opening alone doesn't add it to history
    await client.patch(f"/api/generations/{again['id']}", json={"order": [1, 0, 2]})
    assert [g["id"] for g in (await client.get("/api/generations")).json()] == [again["id"]]
    reopened = (await client.post("/api/generations/import", json={"playlist_id": "pl9"})).json()
    assert reopened["id"] == again["id"] and reopened["tracks"][0]["title"] == SONGS[1][0]   # edits kept


def mock_catalogue_rows():
    respx.get("https://api.spotify.com/v1/browse/new-releases").mock(return_value=httpx.Response(200, json={"albums": {"items": [
        {"id": "al1", "name": "New Album", "artists": [{"name": "Band"}], "images": [{"url": "big"}], "release_date": "2026-10-16"}]}}))
    respx.get("https://api.spotify.com/v1/search").mock(side_effect=lambda r: httpx.Response(200, json=(
        {"tracks": {"items": []}} if r.url.params["type"] == "track" else
        {"playlists": {"items": [{"id": f"pl-{r.url.params['q']}", "name": "Mix", "images": [{"url": "c"}], "items": {"total": 30}}]}})))
    respx.get(url__regex=r"https://api\.spotify\.com/v1/playlists/[^/]+$").mock(return_value=httpx.Response(200, json={
        "followers": {"total": 9000}, "items": {"items": [{"added_at": utcnow().strftime("%Y-%m-%dT00:00:00Z")}]}}))


@respx.mock
async def test_public_rows_use_app_credentials(client):
    from app import settings_store
    from app.routers import discover
    from app.services import spotify
    discover._cache.clear()
    spotify._app_tokens.clear()
    assert (await client.get("/api/discover/public")).json()["rows"]["new_releases"] == []   # nothing to call Spotify with
    discover._cache.clear()
    async with app_db.sessionmaker()() as db:
        await settings_store.save(db, {"spotify_client_id": "c" * 32, "spotify_client_secret": "shh"})
    token = respx.post("https://accounts.spotify.com/api/token").mock(return_value=httpx.Response(200, json={"access_token": "app", "expires_in": 3600}))
    mock_catalogue_rows()
    r = (await client.get("/api/discover/public", headers={"cf-ipcountry": "nz"})).json()
    assert r["country"] == "NZ" and r["rows"]["new_releases"][0]["name"] == "New Album" and len(r["rows"]["inspiration"]) == 4 + discover.THEMES_PER_DAY
    assert "trending" not in r["rows"]
    assert token.calls[0].request.content == b"grant_type=client_credentials"
    assert respx.calls[-1].request.headers["authorization"] == "Bearer app"
    assert (await client.get("/api/discover/public", headers={"cf-ipcountry": "XX"})).json()["country"] == "US"


@respx.mock
async def test_public_rows_fall_back_to_admin_connection(client, outbox, ready_user):
    from app.routers import discover
    discover._cache.clear()
    async with app_db.sessionmaker()() as db:
        from sqlalchemy import select

        from app.models import User
        (await db.execute(select(User))).scalars().first().is_admin = True
        await db.commit()
    mock_catalogue_rows()
    r = (await client.get("/api/discover/public", headers={"cf-ipcountry": "NZ"})).json()
    assert r["rows"]["new_releases"] and respx.calls[0].request.headers["authorization"] == "Bearer tok"
