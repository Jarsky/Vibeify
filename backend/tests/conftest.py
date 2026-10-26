import os
import re

import pytest

os.environ.update(SECRET_KEY="test-secret-key-" + "x" * 32, PUBLIC_URL="http://testserver",
                  BOOTSTRAP_ADMINS="admin@example.com", STATIC_DIR="/nonexistent")

import httpx  # noqa: E402
import httpx2  # noqa: E402  (the HTTP stack inside the anthropic/openai SDKs; respx doesn't see it)

from app import db as app_db  # noqa: E402
from app import mailer, ratelimit  # noqa: E402
from app.config import get_config  # noqa: E402
from app.db import Base  # noqa: E402


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
    get_config.cache_clear()
    app_db.reset_engine_for_tests()
    ratelimit.reset_for_tests()
    async with app_db.engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver",
                                 headers={"X-Requested-With": "vibeify"}) as c:
        yield c
    await app_db.engine().dispose()


@pytest.fixture
def outbox(monkeypatch):
    sent: list[dict] = []

    async def fake_send(settings, to, subject, text, html):
        sent.append({"to": to, "subject": subject, "text": text})

    monkeypatch.setattr(mailer, "send", fake_send)
    return sent


async def enable_email(db_client=None):
    from app import settings_store
    async with app_db.sessionmaker()() as db:
        await settings_store.save(db, {"auth_email": True, "smtp_host": "smtp.test", "smtp_from": "noreply@test"})


async def sign_up(client, outbox, email, password="correct horse battery"):
    await enable_email()
    r = await client.post("/api/auth/email/start", json={"email": email})
    assert r.status_code == 200, r.text
    token = re.search(r"token=([\w-]+)", outbox[-1]["text"]).group(1)
    r = await client.post("/api/auth/email/complete", json={"token": token, "password": password, "display_name": email.split("@")[0]})
    assert r.status_code == 200, r.text
    return token


@pytest.fixture(autouse=True)
def sdk_http(monkeypatch):
    """Canned responses for the AI SDKs, keyed by (method, url without query). Any other SDK request fails the test."""
    routes: dict = {}   # also collects sent requests under "_requests"

    async def handle(self, request):
        key = (request.method, str(request.url).split("?")[0])
        if key not in routes:
            raise RuntimeError(f"unexpected network call from an AI SDK: {key}")
        status, body = routes[key]
        routes.setdefault("_requests", []).append(request)
        return httpx2.Response(status, json=body, request=request)

    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", handle)
    return routes


async def connect_spotify(email: str) -> None:
    """Give an account a Spotify connection (needed e.g. before buying a plan)."""
    from sqlalchemy import select

    from app.db import utcnow
    from app.models import SpotifyConnection, User
    async with app_db.sessionmaker()() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        db.add(SpotifyConnection(user_id=user.id, spotify_user_id=f"sp-{user.id[:8]}", client_id="a" * 32,
                                 access_token_enc="", refresh_token_enc="", expires_at=utcnow()))
        await db.commit()
