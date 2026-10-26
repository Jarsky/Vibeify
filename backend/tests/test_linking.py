"""Sign-in methods joining the same account: verified-email matches, parked links, linking/unlinking in settings."""
import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app import db as app_db
from app import settings_store
from app.models import Identity, SpotifyConnection, User
from app.services import apple

from .conftest import sign_up

GOOGLE_CLIENT = "google-client"
APPLE_CLIENT = "nz.vibeify.test"


async def enable_oauth():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    async with app_db.sessionmaker()() as db:
        await settings_store.save(db, {"auth_spotify_site_app": True, "spotify_client_id": "a" * 32, "auth_google": True,
                                       "google_client_id": GOOGLE_CLIENT, "google_client_secret": "shh", "auth_apple": True,
                                       "apple_client_id": APPLE_CLIENT, "apple_team_id": "TEAM", "apple_key_id": "KEY",
                                       "apple_private_key": pem})


def id_token(claims: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


async def _start(client, path: str) -> dict:
    r = await client.get(path)
    assert r.status_code == 303, r.text
    return {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).query).items()}


async def spotify(client, spotify_id: str, email: str | None, mode: str = "login") -> str:
    q = await _start(client, f"/api/auth/spotify/start?mode={mode}&return_to=/home")
    with respx.mock:
        respx.post("https://accounts.spotify.com/api/token").mock(return_value=httpx.Response(200, json={
            "access_token": "at", "refresh_token": "rt", "expires_in": 3600, "scope": "user-read-email"}))
        respx.get("https://api.spotify.com/v1/me").mock(return_value=httpx.Response(200, json={
            "id": spotify_id, "display_name": spotify_id.title(), "email": email, "images": []}))
        r = await client.get(f"/api/auth/spotify/callback?code=c&state={q['state']}")
    assert r.status_code == 303
    return r.headers["location"]


async def google(client, sub: str, email: str, verified: bool = True, mode: str = "login") -> str:
    q = await _start(client, f"/api/auth/google/start?mode={mode}")
    claims = {"iss": "https://accounts.google.com", "aud": GOOGLE_CLIENT, "sub": sub, "email": email,
              "email_verified": verified, "nonce": q["nonce"], "exp": 9_999_999_999, "name": "G User"}
    with respx.mock:
        respx.post("https://oauth2.googleapis.com/token").mock(return_value=httpx.Response(200, json={"id_token": id_token(claims)}))
        r = await client.get(f"/api/auth/google/callback?code=c&state={q['state']}")
    assert r.status_code == 303
    return r.headers["location"]


async def users() -> list[User]:
    async with app_db.sessionmaker()() as db:
        from sqlalchemy import select
        return list((await db.execute(select(User))).scalars())


async def methods(client) -> list[str]:
    return (await client.get("/api/me")).json()["sign_in_methods"]


async def test_spotify_now_asks_for_email(client):
    await enable_oauth()
    q = await _start(client, "/api/auth/spotify/start")
    assert "user-read-email" in q["scope"].split()


async def test_google_joins_verified_email_account(client, outbox):
    await enable_oauth()
    await sign_up(client, outbox, "same@example.com")
    await client.post("/api/auth/logout")
    assert await google(client, "g1", "same@example.com") == "/"
    assert len(await users()) == 1
    assert await methods(client) == ["email", "google"]


async def test_unverified_google_email_does_not_join(client, outbox):
    await enable_oauth()
    await sign_up(client, outbox, "same@example.com")
    await client.post("/api/auth/logout")
    assert await google(client, "g1", "same@example.com", verified=False) == "/signin?link=google"
    assert len(await users()) == 1
    assert (await client.get("/api/me")).status_code == 401   # not signed in to anything


async def test_spotify_email_links_after_signing_in_to_existing_account(client, outbox):
    """Spotify doesn't verify emails: the match is parked until the person signs in to the account with that email."""
    await enable_oauth()
    await google(client, "g1", "me@example.com")
    await client.post("/api/auth/logout")
    assert await spotify(client, "listener", "me@example.com") == "/signin?link=spotify"
    assert len(await users()) == 1
    assert await google(client, "g1", "me@example.com") == "/account?linked=spotify"
    me = (await client.get("/api/me")).json()
    assert me["sign_in_methods"] == ["google", "spotify"] and me["spotify"]["spotify_user_id"] == "listener"
    await client.post("/api/auth/logout")
    assert await spotify(client, "listener", "me@example.com") == "/home"   # now signs straight in
    assert (await client.get("/api/me")).json()["id"] == me["id"]


async def test_parked_link_ignored_for_a_different_account(client, outbox):
    await enable_oauth()
    await google(client, "g1", "me@example.com")
    await client.post("/api/auth/logout")
    await sign_up(client, outbox, "other@example.com")
    await client.post("/api/auth/logout")
    assert await spotify(client, "listener", "me@example.com") == "/signin?link=spotify"
    r = await client.post("/api/auth/email/login", json={"email": "other@example.com", "password": "correct horse battery"})
    assert r.json()["linked"] is None
    assert await methods(client) == ["email"]


async def test_spotify_email_never_grants_bootstrap_admin(client):
    await enable_oauth()
    await spotify(client, "sneaky", "admin@example.com")
    me = (await client.get("/api/me")).json()
    assert me["email"] == "admin@example.com" and not me["email_verified"] and not me["is_admin"]


async def test_link_folds_in_empty_duplicate_account(client):
    """The production case: signed in with Google before linking it, which made a second, empty account."""
    await enable_oauth()
    await spotify(client, "listener", None)
    await client.post("/api/auth/logout")
    await google(client, "g1", "me@example.com")   # duplicate account
    await client.post("/api/auth/logout")
    await spotify(client, "listener", None)
    assert len(await users()) == 2
    assert await google(client, "g1", "me@example.com", mode="link") == "/account?linked=google"
    me = (await client.get("/api/me")).json()
    assert me["sign_in_methods"] == ["google", "spotify"]
    assert me["email"] == "me@example.com" and me["email_verified"]
    assert [i["email"] for i in me["identities"] if i["provider"] == "google"] == ["me@example.com"]
    assert len(await users()) == 1


async def test_link_refuses_account_with_content(client, outbox):
    await enable_oauth()
    await sign_up(client, outbox, "me@example.com")
    await google(client, "g1", "me@example.com", mode="link")
    await client.post("/api/auth/logout")
    await spotify(client, "listener", None)
    assert await google(client, "g1", "me@example.com", mode="link") == "/account?error=google_in_use"
    assert len(await users()) == 2


async def test_unlink(client):
    await enable_oauth()
    await spotify(client, "listener", None)
    r = await client.delete("/api/me/sign-in/spotify")
    assert r.status_code == 400 and "only way" in r.json()["detail"]
    await google(client, "g1", "me@example.com", mode="link")
    assert (await client.delete("/api/me/sign-in/spotify")).status_code == 200
    me = (await client.get("/api/me")).json()
    assert me["sign_in_methods"] == ["google"] and me["spotify"] is None
    async with app_db.sessionmaker()() as db:
        assert await db.get(SpotifyConnection, me["id"]) is None
    assert (await client.delete("/api/me/sign-in/apple")).status_code == 404


async def test_password_needs_verified_email_and_adds_email_method(client):
    await enable_oauth()
    await spotify(client, "listener", "me@example.com")
    r = await client.post("/api/me/password", json={"new_password": "correct horse battery"})
    assert r.status_code == 400 and "Confirm" in r.json()["detail"]
    await google(client, "g1", "me@example.com", mode="link")   # Google confirms the address
    assert (await client.post("/api/me/password", json={"new_password": "correct horse battery"})).status_code == 200
    assert await methods(client) == ["email", "google", "spotify"]
    assert (await client.delete("/api/me/sign-in/email")).status_code == 200
    me = (await client.get("/api/me")).json()
    assert not me["has_password"] and me["sign_in_methods"] == ["google", "spotify"]


async def test_confirmed_address_moves_off_unverified_account(client, outbox):
    """Someone signs in with a Spotify account carrying another person's address; that person signs up by email."""
    from .conftest import enable_email
    await enable_oauth()
    await enable_email()
    await spotify(client, "squatter", "victim@example.com")
    squatter_id = (await client.get("/api/me")).json()["id"]
    await client.post("/api/auth/logout")
    await sign_up(client, outbox, "victim@example.com")
    me = (await client.get("/api/me")).json()
    assert me["id"] != squatter_id and me["email_verified"]
    async with app_db.sessionmaker()() as db:
        assert (await db.get(User, squatter_id)).email is None


async def test_confirm_email_from_settings_keeps_own_account(client, outbox):
    from .conftest import enable_email
    import re
    await enable_oauth()
    await enable_email()
    await spotify(client, "listener", "me@example.com")
    my_id = (await client.get("/api/me")).json()["id"]
    assert (await client.post("/api/me/email/confirm")).status_code == 200
    token = re.search(r"token=([\w-]+)", outbox[-1]["text"]).group(1)
    await client.post("/api/auth/logout")   # e.g. opened on another device
    r = await client.post("/api/auth/email/complete", json={"token": token, "password": "correct horse battery"})
    assert r.status_code == 200
    me = (await client.get("/api/me")).json()
    assert me["id"] == my_id and me["email_verified"] and me["sign_in_methods"] == ["email", "spotify"]


async def test_apple_form_post_bounce_and_sign_in(client):
    await enable_oauth()
    q = await _start(client, "/api/auth/apple/start")
    assert q["response_mode"] == "form_post"
    r = await client.post("/api/auth/apple/callback", content=f"code=c&state={q['state']}&user=%7B%22name%22%3A%7B%22firstName%22%3A%22Ann%22%7D%7D",
                          headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 303 and r.headers["location"].startswith("/api/auth/apple/callback?")
    claims = {"iss": apple.ISSUER, "aud": APPLE_CLIENT, "sub": "a1", "email": "ann@privaterelay.appleid.com",
              "email_verified": "true", "nonce": q["nonce"], "exp": 9_999_999_999}
    with respx.mock:
        token = respx.post(apple.TOKEN_URL).mock(return_value=httpx.Response(200, json={"id_token": id_token(claims)}))
        r = await client.get(r.headers["location"])
    assert r.headers["location"] == "/"
    secret = parse_qs(token.calls[0].request.content.decode())["client_secret"][0]
    assert len(secret.split(".")) == 3 and json.loads(base64.urlsafe_b64decode(secret.split(".")[0] + "==")) == {"alg": "ES256", "kid": "KEY"}
    me = (await client.get("/api/me")).json()
    assert me["display_name"] == "Ann" and me["sign_in_methods"] == ["apple"] and me["email_verified"]
    async with app_db.sessionmaker()() as db:
        from sqlalchemy import select
        assert (await db.execute(select(Identity.email).where(Identity.provider == "apple"))).scalar_one() == "ann@privaterelay.appleid.com"
