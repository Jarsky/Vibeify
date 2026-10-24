"""Sign-in: Spotify (site app or the user's own app, PKCE), Google (OpenID Connect) and email + password."""
import base64
import json
import re
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit, crypto, mailer, ratelimit, security, settings_store
from ..config import get_config
from ..db import get_db, utcnow
from ..models import EmailToken, Identity, SpotifyConnection, User
from ..services import spotify

router = APIRouter(prefix="/api/auth", tags=["auth"])

CLIENT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"


def spotify_redirect_uri() -> str:
    return f"{get_config().public_url}/api/auth/spotify/callback"


def google_redirect_uri() -> str:
    return f"{get_config().public_url}/api/auth/google/callback"


def _safe_return(path: str | None, default: str = "/") -> str:
    return path if path and path.startswith("/") and not path.startswith("//") else default


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


async def _user_for_identity(db: AsyncSession, provider: str, subject: str) -> User | None:
    ident = (await db.execute(select(Identity).where(Identity.provider == provider, Identity.subject == subject))).scalar_one_or_none()
    return await db.get(User, ident.user_id) if ident else None


async def _new_user(db: AsyncSession, settings: dict, request: Request, method: str, **fields) -> User:
    if not settings["signup_open"]:
        raise HTTPException(403, "Sign-ups are closed on this site.")
    user = User(**fields)
    db.add(user)
    await db.flush()
    audit.record(db, "account.create", request=request, actor=user, target=user, method=method)
    return user


def _maybe_bootstrap_admin(user: User, *keys: str | None) -> None:
    if security.user_is_bootstrap_admin(user.email, *keys):
        user.is_admin = True


# ── Spotify ──────────────────────────────────────────────────────────────────
@router.get("/spotify/start")
async def spotify_start(mode: str = Query("login", pattern="^(login|link)$"), client_id: str | None = None,
                        return_to: str | None = None, db: AsyncSession = Depends(get_db),
                        user: User | None = Depends(security.optional_user)):
    settings = await settings_store.load(db)
    if client_id:   # the user's own Spotify app
        client_id = client_id.strip().lower()
        if not settings["auth_spotify_byo"]:
            raise HTTPException(403, "Connecting your own Spotify app is turned off on this site.")
        if not CLIENT_ID_RE.match(client_id):
            raise HTTPException(400, "That doesn't look like a Spotify Client ID (32 letters and numbers).")
        uses_site_app = False
    else:
        client_id = settings["spotify_client_id"]
        if not (settings["auth_spotify_site_app"] and client_id):
            raise HTTPException(503, "Spotify sign-in isn't set up yet.")
        uses_site_app = True
    if mode == "link" and not user:
        raise HTTPException(401, "Sign in first, then connect Spotify.")
    verifier, challenge = spotify.pkce_pair()
    state = secrets.token_urlsafe(24)
    resp = RedirectResponse(spotify.authorize_url(client_id, spotify_redirect_uri(), state, challenge), status_code=303)
    security.set_oauth_state(resp, {"p": "spotify", "state": state, "verifier": verifier, "client_id": client_id,
                                    "site_app": uses_site_app, "mode": mode, "return_to": _safe_return(return_to)})
    return resp


@router.get("/spotify/callback")
async def spotify_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                           db: AsyncSession = Depends(get_db), user: User | None = Depends(security.optional_user)):
    resp = _redirect("/")
    st = security.pop_oauth_state(request, resp)
    if not st or st.get("p") != "spotify" or st.get("state") != state:
        resp.headers["location"] = "/signin?error=expired"
        return resp
    which = "site" if st["site_app"] else "own"
    if error or not code:
        resp.headers["location"] = f"/signin?error={'cancelled' if error == 'access_denied' else 'spotify'}"
        return resp
    try:
        tokens = await spotify.exchange_code(st["client_id"], code, spotify_redirect_uri(), st["verifier"])
        profile = await spotify.get_me(tokens["access_token"])
    except spotify.SpotifyUserNotRegistered:
        resp.headers["location"] = f"/connect-spotify?error=not_registered&app={which}"
        return resp
    except spotify.SpotifyError as e:
        msg = "redirect" if "redirect" in str(e).lower() else "spotify"
        resp.headers["location"] = f"/connect-spotify?error={msg}&app={which}"
        return resp

    settings = await settings_store.load(db)
    spotify_id = profile["id"]
    owner = await _user_for_identity(db, "spotify", spotify_id)
    if st["mode"] == "link":
        if not user:
            resp.headers["location"] = "/signin?error=expired"
            return resp
        if owner and owner.id != user.id:
            resp.headers["location"] = "/account?error=spotify_in_use"
            return resp
        target = user
    else:
        target = owner
        if target is None:
            try:
                target = await _new_user(db, settings, request, "spotify", display_name=profile.get("display_name") or spotify_id,
                                         avatar_url=((profile.get("images") or [{}])[0] or {}).get("url"))
            except HTTPException:
                resp.headers["location"] = "/signin?error=signups_closed"
                return resp
        if target.is_disabled:
            resp.headers["location"] = "/signin?error=disabled"
            return resp
    if not owner:
        db.add(Identity(user_id=target.id, provider="spotify", subject=spotify_id))
    conn = await db.get(SpotifyConnection, target.id)
    if conn is None:
        conn = SpotifyConnection(user_id=target.id, spotify_user_id=spotify_id, client_id=st["client_id"],
                                 access_token_enc="", refresh_token_enc="", expires_at=utcnow())
        db.add(conn)
    conn.spotify_user_id = spotify_id
    conn.display_name = profile.get("display_name") or ""
    conn.client_id = st["client_id"]
    conn.uses_site_app = st["site_app"]
    spotify.store_tokens(conn, tokens)
    _maybe_bootstrap_admin(target, spotify_id)
    if st["mode"] == "link":
        audit.record(db, "account.spotify_connect", request=request, actor=target, target=target, spotify_user_id=spotify_id,
                     app="site" if st["site_app"] else "own")
    await db.commit()
    if st["mode"] == "login":
        await security.start_session(db, resp, request, target, "spotify")
    resp.headers["location"] = st["return_to"]
    return resp


# ── Google (OpenID Connect) ──────────────────────────────────────────────────
@router.get("/google/start")
async def google_start(return_to: str | None = None, db: AsyncSession = Depends(get_db)):
    settings = await settings_store.load(db)
    if not (settings["auth_google"] and settings["google_client_id"] and settings["google_client_secret"]):
        raise HTTPException(503, "Google sign-in isn't set up on this site.")
    verifier, challenge = spotify.pkce_pair()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    url = GOOGLE_AUTH + "?" + urlencode({
        "client_id": settings["google_client_id"], "redirect_uri": google_redirect_uri(), "response_type": "code",
        "scope": "openid email profile", "state": state, "nonce": nonce, "prompt": "select_account",
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    resp = RedirectResponse(url, status_code=303)
    security.set_oauth_state(resp, {"p": "google", "state": state, "nonce": nonce, "verifier": verifier,
                                    "return_to": _safe_return(return_to)})
    return resp


def _id_token_claims(id_token: str) -> dict:
    # Received directly from Google's token endpoint over TLS with our client secret, so per OpenID Connect
    # Core 3.1.3.7 the signature check may be skipped; the claims below are still validated.
    payload = id_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


@router.get("/google/callback")
async def google_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                          db: AsyncSession = Depends(get_db), current: User | None = Depends(security.optional_user)):
    resp = _redirect("/")
    st = security.pop_oauth_state(request, resp)
    if not st or st.get("p") != "google" or st.get("state") != state:
        resp.headers["location"] = "/signin?error=expired"
        return resp
    if error or not code:
        resp.headers["location"] = "/signin?error=cancelled"
        return resp
    settings = await settings_store.load(db)
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.post(GOOGLE_TOKEN, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": google_redirect_uri(),
            "client_id": settings["google_client_id"], "client_secret": settings["google_client_secret"],
            "code_verifier": st["verifier"],
        })
    if r.status_code != 200:
        resp.headers["location"] = "/signin?error=google"
        return resp
    claims = _id_token_claims(r.json()["id_token"])
    if (claims.get("aud") != settings["google_client_id"] or claims.get("iss") not in ("https://accounts.google.com", "accounts.google.com")
            or claims.get("nonce") != st["nonce"] or int(claims.get("exp", 0)) < utcnow().timestamp()):
        resp.headers["location"] = "/signin?error=google"
        return resp
    sub = claims["sub"]
    email = (claims.get("email") or "").lower() if claims.get("email_verified") else None
    user = await _user_for_identity(db, "google", sub)
    if current is not None:   # signed in already: link Google to this account
        if user and user.id != current.id:
            resp.headers["location"] = "/account?error=google_in_use"
            return resp
        if email and not current.email and (await db.execute(select(User.id).where(User.email == email))).first() is None:
            current.email, current.email_verified = email, True
        user = current
    if user is None and email:   # same verified email as an existing verified account: same person
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing and existing.email_verified:
            user = existing
    if user is None:
        try:
            user = await _new_user(db, settings, request, "google", display_name=claims.get("name") or (email or "").split("@")[0],
                                   email=email, email_verified=bool(email), avatar_url=claims.get("picture"))
        except HTTPException:
            resp.headers["location"] = "/signin?error=signups_closed"
            return resp
    if user.is_disabled:
        resp.headers["location"] = "/signin?error=disabled"
        return resp
    if not await _user_for_identity(db, "google", sub):
        db.add(Identity(user_id=user.id, provider="google", subject=sub))
    _maybe_bootstrap_admin(user)
    await db.commit()
    await security.start_session(db, resp, request, user, "google")
    resp.headers["location"] = st["return_to"]
    return resp


# ── Email + password ─────────────────────────────────────────────────────────
class EmailIn(BaseModel):
    email: str


class CompleteIn(BaseModel):
    token: str
    password: str
    display_name: str = ""


class LoginIn(BaseModel):
    email: str
    password: str


def _clean_email(raw: str) -> str:
    try:
        return validate_email(raw.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as e:
        raise HTTPException(400, "Enter a valid email address.") from e


async def _issue_token(db: AsyncSession, email: str, purpose: str, hours: int) -> str:
    token = secrets.token_urlsafe(32)
    db.add(EmailToken(token_hash=crypto.sha256(token), email=email, purpose=purpose,
                      expires_at=utcnow() + timedelta(hours=hours)))
    await db.commit()
    return token


async def _use_token(db: AsyncSession, token: str, purpose: str) -> EmailToken:
    row = await db.get(EmailToken, crypto.sha256(token))
    expires = row.expires_at.replace(tzinfo=row.expires_at.tzinfo or utcnow().tzinfo) if row else None
    if not row or row.purpose != purpose or row.used_at or expires < utcnow():
        raise HTTPException(400, "This link has expired or was already used. Request a new one.")
    row.used_at = utcnow()
    return row


@router.post("/email/start", dependencies=[Depends(security.csrf_guard)])
async def email_start(body: EmailIn, request: Request, db: AsyncSession = Depends(get_db)):
    """Start sign-up. Same response whether or not the address has an account (no account enumeration)."""
    settings = await settings_store.load(db)
    if not (settings["auth_email"] and settings_store.email_ready(settings)):
        raise HTTPException(503, "Email sign-up isn't available on this site.")
    email = _clean_email(body.email)
    ratelimit.limit(f"email-start:{security.client_ip(request)}", 5, 600)
    ratelimit.limit(f"email-start:{email}", 3, 3600)
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    base = get_config().public_url
    if existing and existing.password_hash:
        token = await _issue_token(db, email, "reset", 2)
        text, html = mailer.link_email(settings, heading="You already have an account",
                                       body="Someone tried to sign up with this email. If it was you, sign in, or use this link to set a new password.",
                                       button="Reset password", url=f"{base}/reset-password?token={token}")
        subject = f"Your {settings['site_name']} account"
    else:
        if not settings["signup_open"] and not existing:
            return {"ok": True}   # silently: sign-ups closed
        token = await _issue_token(db, email, "verify", 24)
        text, html = mailer.link_email(settings, heading=f"Confirm your email for {settings['site_name']}",
                                       body="Click below to confirm your email address and choose a password.",
                                       button="Confirm email", url=f"{base}/verify-email?token={token}")
        subject = f"Confirm your email for {settings['site_name']}"
    await mailer.send(settings, email, subject, text, html)
    return {"ok": True}


@router.post("/email/complete", dependencies=[Depends(security.csrf_guard)])
async def email_complete(body: CompleteIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    if problem := security.password_problem(body.password):
        raise HTTPException(400, problem)
    tok = await _use_token(db, body.token, "verify")
    settings = await settings_store.load(db)
    user = (await db.execute(select(User).where(User.email == tok.email))).scalar_one_or_none()
    if user is None:
        user = await _new_user(db, settings, request, "email", email=tok.email, display_name=body.display_name.strip()[:120] or tok.email.split("@")[0])
    user.email_verified = True
    user.password_hash = security.hash_password(body.password)
    if not await _user_for_identity(db, "email", tok.email):
        db.add(Identity(user_id=user.id, provider="email", subject=tok.email))
    _maybe_bootstrap_admin(user)
    await db.commit()
    await security.start_session(db, response, request, user, "email")
    return {"ok": True}


@router.post("/email/login", dependencies=[Depends(security.csrf_guard)])
async def email_login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    email = body.email.strip().lower()
    ratelimit.limit(f"login:{security.client_ip(request)}", 10, 600)
    ratelimit.limit(f"login:{email}", 8, 900)
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user or not security.verify_password(user.password_hash, body.password):
        audit.record(db, "auth.login_failed", request=request, actor_label=email[:320], target=user, method="password")
        await db.commit()
        raise HTTPException(401, "That email and password don't match.")
    if user.is_disabled:
        audit.record(db, "auth.login_blocked", request=request, actor=user, target=user, reason="disabled")
        await db.commit()
        raise HTTPException(403, "This account has been disabled.")
    await security.start_session(db, response, request, user, "password")
    return {"ok": True}


@router.post("/password/forgot", dependencies=[Depends(security.csrf_guard)])
async def password_forgot(body: EmailIn, request: Request, db: AsyncSession = Depends(get_db)):
    settings = await settings_store.load(db)
    if not settings_store.email_ready(settings):
        raise HTTPException(503, "Password reset emails aren't available on this site.")
    email = _clean_email(body.email)
    ratelimit.limit(f"forgot:{security.client_ip(request)}", 5, 600)
    ratelimit.limit(f"forgot:{email}", 3, 3600)
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user and not user.is_disabled:
        token = await _issue_token(db, email, "reset", 2)
        text, html = mailer.link_email(settings, heading="Reset your password",
                                       body="Click below to choose a new password. The link works for 2 hours.",
                                       button="Choose a new password", url=f"{get_config().public_url}/reset-password?token={token}")
        await mailer.send(settings, email, f"Reset your {settings['site_name']} password", text, html)
    return {"ok": True}


@router.post("/password/reset", dependencies=[Depends(security.csrf_guard)])
async def password_reset(body: CompleteIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    if problem := security.password_problem(body.password):
        raise HTTPException(400, problem)
    tok = await _use_token(db, body.token, "reset")
    user = (await db.execute(select(User).where(User.email == tok.email))).scalar_one_or_none()
    if not user or user.is_disabled:
        raise HTTPException(400, "This link has expired or was already used. Request a new one.")
    user.password_hash = security.hash_password(body.password)
    user.email_verified = True
    if not await _user_for_identity(db, "email", tok.email):
        db.add(Identity(user_id=user.id, provider="email", subject=tok.email))
    audit.record(db, "auth.password_reset", request=request, actor=user, target=user)
    await db.commit()
    await security.start_session(db, response, request, user, "password reset")
    return {"ok": True}


@router.post("/logout", dependencies=[Depends(security.csrf_guard)])
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    await security.end_session(db, response, request)
    return {"ok": True}
