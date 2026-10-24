"""Passwords, sessions, signed OAuth state, CSRF guard and the current-user dependencies."""
import json
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import crypto
from .config import get_config
from .db import get_db, utcnow
from .models import Session, User

SESSION_COOKIE = "sl_session"
OAUTH_COOKIE = "sl_oauth"
SESSION_DAYS = 30
CSRF_HEADER = "x-requested-with"

_hasher = PasswordHasher()


# ── passwords ────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_problem(password: str) -> str | None:
    if len(password) < 10:
        return "Use at least 10 characters."
    if len(password) > 256:
        return "That password is too long."
    if password.lower() == password and password.isalpha():
        return "Mix in some numbers, symbols or capitals."
    return None


# ── sessions ─────────────────────────────────────────────────────────────────
def client_ip(request: Request) -> str:
    if get_config().trust_proxy_headers:
        if cf := request.headers.get("cf-connecting-ip"):   # Cloudflare's view of the visitor; X-Forwarded-For can be prefilled
            return cf.strip()
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


async def start_session(db: AsyncSession, response: Response, request: Request, user: User, method: str) -> None:
    from . import audit   # audit imports this module
    audit.record(db, "auth.login", request=request, actor=user, target=user, method=method,
                 user_agent=(request.headers.get("user-agent") or "")[:200])
    token = secrets.token_urlsafe(32)
    db.add(Session(
        token_hash=crypto.sha256(token), user_id=user.id,
        expires_at=utcnow() + timedelta(days=SESSION_DAYS),
        user_agent=(request.headers.get("user-agent") or "")[:500], ip=client_ip(request),
    ))
    user.last_login_at = utcnow()
    await db.commit()
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
                        secure=get_config().secure_cookies, samesite="lax", path="/")


async def end_session(db: AsyncSession, response: Response, request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await db.execute(delete(Session).where(Session.token_hash == crypto.sha256(token)))
        await db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


async def _session_user(request: Request, db: AsyncSession) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    sess = await db.get(Session, crypto.sha256(token))
    if not sess or sess.expires_at.replace(tzinfo=sess.expires_at.tzinfo or timezone.utc) < utcnow():
        return None
    user = await db.get(User, sess.user_id)
    if not user or user.is_disabled:
        return None
    if utcnow() - sess.last_seen_at.replace(tzinfo=sess.last_seen_at.tzinfo or timezone.utc) > timedelta(minutes=10):
        sess.last_seen_at = utcnow()
        await db.commit()
    return user


async def optional_user(request: Request, db: AsyncSession = Depends(get_db)) -> User | None:
    return await _session_user(request, db)


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user = await _session_user(request, db)
    if not user:
        raise HTTPException(401, "Sign in to continue.")
    return user


async def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admins only.")
    return user


# ── OAuth state (PKCE verifier etc.), kept in a short-lived encrypted cookie ─
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_config().secret_key, salt="vibeify-oauth")


def set_oauth_state(response: Response, data: dict) -> None:
    payload = crypto.encrypt(json.dumps(data))
    response.set_cookie(OAUTH_COOKIE, _serializer().dumps(payload), max_age=600, httponly=True,
                        secure=get_config().secure_cookies, samesite="lax", path="/api/auth")


def pop_oauth_state(request: Request, response: Response) -> dict | None:
    raw = request.cookies.get(OAUTH_COOKIE)
    response.delete_cookie(OAUTH_COOKIE, path="/api/auth")
    if not raw:
        return None
    try:
        payload = _serializer().loads(raw, max_age=600)
    except BadSignature:
        return None
    plain = crypto.decrypt(payload)
    return json.loads(plain) if plain else None


# ── CSRF: state-changing API calls must carry a header browsers won't send cross-site ──
async def csrf_guard(request: Request) -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.headers.get(CSRF_HEADER, "").lower() != "vibeify":
        raise HTTPException(403, "Missing request header.")


async def cleanup_expired(db: AsyncSession) -> None:
    now = utcnow()
    await db.execute(delete(Session).where(Session.expires_at < now))
    await db.commit()


def user_is_bootstrap_admin(*keys: str | None) -> bool:
    wanted = get_config().admin_bootstrap_set
    return any(k and k.lower() in wanted for k in keys)


async def users_count(db: AsyncSession) -> int:
    return len((await db.execute(select(User.id).limit(2))).all())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
