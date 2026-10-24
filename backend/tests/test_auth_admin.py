from app import db as app_db
from app.models import Generation, Session, User

from .conftest import enable_email, sign_up


async def test_config_reports_enabled_sign_in(client):
    r = await client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert body["site_name"] == "Vibeify"
    assert body["sign_in"]["spotify_site_app"] is False   # no client id yet
    assert body["sign_in"]["spotify_own_app"] is True
    assert body["spotify_redirect_uri"] == "http://testserver/api/auth/spotify/callback"


async def test_csrf_header_required(client):
    r = await client.post("/api/auth/logout", headers={"X-Requested-With": ""})
    assert r.status_code == 403


async def test_email_signup_login_and_token_reuse(client, outbox):
    token = await sign_up(client, outbox, "someone@example.com")
    me = (await client.get("/api/me")).json()
    assert me["email"] == "someone@example.com" and me["email_verified"] and me["has_password"]
    assert me["is_admin"] is False
    # verification link can't be used twice
    r = await client.post("/api/auth/email/complete", json={"token": token, "password": "another long password"})
    assert r.status_code == 400
    await client.post("/api/auth/logout")
    assert (await client.get("/api/me")).status_code == 401
    r = await client.post("/api/auth/email/login", json={"email": "someone@example.com", "password": "wrong password!!"})
    assert r.status_code == 401
    r = await client.post("/api/auth/email/login", json={"email": "Someone@Example.com", "password": "correct horse battery"})
    assert r.status_code == 200


async def test_signup_for_existing_account_sends_reset_not_verify(client, outbox):
    await sign_up(client, outbox, "dupe@example.com")
    r = await client.post("/api/auth/email/start", json={"email": "dupe@example.com"})
    assert r.status_code == 200
    assert "reset-password?token=" in outbox[-1]["text"]


async def test_email_signup_unavailable_without_smtp(client):
    r = await client.post("/api/auth/email/start", json={"email": "a@example.com"})
    assert r.status_code == 503


async def test_admin_requires_admin(client, outbox):
    await sign_up(client, outbox, "user@example.com")
    assert (await client.get("/api/admin/settings")).status_code == 403


async def test_bootstrap_admin_and_settings(client, outbox):
    await sign_up(client, outbox, "admin@example.com")
    r = await client.get("/api/admin/settings")
    assert r.status_code == 200
    assert r.json()["smtp_password"] is False
    r = await client.put("/api/admin/settings", json={"site_name": "My Lists", "smtp_password": "hunter2", "max_playlist_size": "40"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["site_name"] == "My Lists" and body["smtp_password"] is True and body["max_playlist_size"] == 40
    # "true" placeholder keeps the stored secret
    r = await client.put("/api/admin/settings", json={"smtp_password": True})
    assert r.json()["smtp_password"] is True
    assert (await client.put("/api/admin/settings", json={"nope": 1})).status_code == 400


async def test_admin_providers_and_models(client, outbox):
    await sign_up(client, outbox, "admin@example.com")
    r = await client.post("/api/admin/providers", json={"name": "Claude", "kind": "anthropic", "api_key": "sk-ant-test-1234567890"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert [m["model_id"] for m in p["models"]] == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
    assert "sk-ant-test" not in p["key_hint"]
    first, second = p["models"][0]["id"], p["models"][1]["id"]
    await client.patch(f"/api/admin/models/{first}", json={"is_default": True})
    await client.patch(f"/api/admin/models/{second}", json={"is_default": True})
    models = (await client.get("/api/admin/providers")).json()[0]["models"]
    assert [m["is_default"] for m in models] == [False, True, False]
    me = (await client.get("/api/me")).json()
    assert [m["id"] for m in me["models"]] == [second]   # users get only the default until choice is on
    await client.put("/api/admin/settings", json={"allow_model_choice": True})
    me = (await client.get("/api/me")).json()
    assert len(me["models"]) == 3
    assert (await client.post("/api/admin/providers", json={"name": "x", "kind": "openai_compatible"})).status_code == 400
    assert (await client.delete(f"/api/admin/providers/{p['id']}")).status_code == 200
    assert (await client.get("/api/admin/providers")).json() == []


async def test_admin_user_management_and_cascade_delete(client, outbox):
    await sign_up(client, outbox, "victim@example.com")
    await client.post("/api/auth/logout")
    await sign_up(client, outbox, "admin@example.com")
    users = (await client.get("/api/admin/users", params={"q": "victim"})).json()
    assert users["total"] == 1
    victim = users["users"][0]
    assert victim["sign_in_methods"] == ["email"]
    r = await client.patch(f"/api/admin/users/{victim['id']}", json={"daily_generation_limit": 3, "is_disabled": True})
    assert r.status_code == 200
    async with app_db.sessionmaker()() as db:
        db.add(Generation(user_id=victim["id"], title="t", description="", request={}, model_label="m", messages=[], tracks=[]))
        await db.commit()
    assert (await client.delete(f"/api/admin/users/{victim['id']}")).status_code == 200
    from sqlalchemy import func, select
    async with app_db.sessionmaker()() as db:
        assert await db.get(User, victim["id"]) is None
        assert (await db.execute(select(func.count()).select_from(Generation))).scalar_one() == 0
        assert (await db.execute(select(func.count()).select_from(Session).where(Session.user_id == victim["id"]))).scalar_one() == 0
    me_id = (await client.get("/api/me")).json()["id"]
    assert (await client.patch(f"/api/admin/users/{me_id}", json={"is_admin": False})).status_code == 400
    stats = (await client.get("/api/admin/stats")).json()
    assert stats["users"] == 1


async def test_disabled_user_cannot_log_in(client, outbox):
    await sign_up(client, outbox, "bad@example.com")
    await enable_email()
    async with app_db.sessionmaker()() as db:
        from sqlalchemy import select
        u = (await db.execute(select(User).where(User.email == "bad@example.com"))).scalar_one()
        u.is_disabled = True
        await db.commit()
    assert (await client.get("/api/me")).status_code == 401
    r = await client.post("/api/auth/email/login", json={"email": "bad@example.com", "password": "correct horse battery"})
    assert r.status_code == 403
