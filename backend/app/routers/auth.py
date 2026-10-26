"""Sign-in: Spotify (site app or the user's own app, PKCE), Google and Apple (OpenID Connect) and email + password.

Every way in is an Identity on a User. A new identity joins an existing account when:
- the person is signed in and links it from Account settings, or
- its provider vouches for the email (Google, Apple) and the account's email is verified too, or
- the email matches but one side isn't verified (Spotify never verifies): the identity is parked in a short-lived
  cookie and linked as soon as the person proves they own the account by signing in to it. Merging on an
  unverified email would let anyone pre-create an account under someone else's address and share it with them.
"""
import base64
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import parse_qs, urlencode

import httpx
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit, crypto, mailer, ratelimit, security, settings_store
from ..config import get_config
from ..db import get_db, utcnow
from ..models import EmailToken, Generation, Identity, SpotifyConnection, User, UserLLMKey
from ..services import apple, spotify

router = APIRouter(prefix="/api/auth", tags=["auth"])

CLIENT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
PROVIDER_NAMES = {"spotify": "Spotify", "google": "Google", "apple": "Apple", "email": "Email"}
LINK_COOKIE = "sl_link"


def spotify_redirect_uri() -> str:
    return f"{get_config().public_url}/api/auth/spotify/callback"


def google_redirect_uri() -> str:
    return f"{get_config().public_url}/api/auth/google/callback"


def apple_redirect_uri() -> str:
    return f"{get_config().public_url}/api/auth/apple/callback"


def _safe_return(path: str | None, default: str = "/") -> str:
    return path if path and path.startswith("/") and not path.startswith("//") else default


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


async def _user_for_identity(db: AsyncSession, provider: str, subject: str) -> User | None:
    ident = (await db.execute(select(Identity).where(Identity.provider == provider, Identity.subject == subject))).scalar_one_or_none()
    return await db.get(User, ident.user_id) if ident else None


async def _user_for_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()


async def _new_user(db: AsyncSession, settings: dict, request: Request, method: str, **fields) -> User:
    if not settings["signup_open"]:
        raise HTTPException(403, "Sign-ups are closed on this site.")
    user = User(**fields)
    db.add(user)
    await db.flush()
    audit.record(db, "account.create", request=request, actor=user, target=user, method=method)
    return user


def _maybe_bootstrap_admin(user: User, *keys: str | None) -> None:
    if security.user_is_bootstrap_admin(user.email if user.email_verified else None, *keys):
        user.is_admin = True


# ── linking ──────────────────────────────────────────────────────────────────
@dataclass
class External:
    """An identity a provider has just vouched for."""
    provider: str
    subject: str
    email: str | None = None
    email_verified: bool = False      # the provider confirmed the person owns the address
    display_name: str = ""
    avatar_url: str | None = None
    spotify: dict | None = field(default=None)   # tokens + app details, to store the Spotify connection


async def _is_throwaway(db: AsyncSession, user: User) -> bool:
    """An account with nothing in it but one sign-in method: safe to fold into the account claiming that method."""
    if user.password_hash or user.stripe_customer_id:
        return False
    count = lambda model: db.execute(select(func.count()).select_from(model).where(model.user_id == user.id))  # noqa: E731
    return ((await count(Identity)).scalar_one() <= 1 and (await count(Generation)).scalar_one() == 0
            and (await count(UserLLMKey)).scalar_one() == 0)


async def _attach(db: AsyncSession, request: Request, user: User, ext: External, how: str) -> None:
    """Make `ext` a sign-in method of `user`, and store the Spotify connection if it is one."""
    ident = (await db.execute(select(Identity).where(Identity.provider == ext.provider, Identity.subject == ext.subject))).scalar_one_or_none()
    if ident is None:
        db.add(Identity(user_id=user.id, provider=ext.provider, subject=ext.subject, email=ext.email))
        audit.record(db, "account.link", request=request, actor=user, target=user, provider=ext.provider, how=how)
    elif ext.email:
        ident.email = ext.email
    if ext.email:
        if not user.email and await _user_for_email(db, ext.email) is None:
            user.email, user.email_verified = ext.email, ext.email_verified
        elif user.email == ext.email and ext.email_verified:
            user.email_verified = True
    if not user.avatar_url and ext.avatar_url:
        user.avatar_url = ext.avatar_url
    if ext.spotify:
        await _save_spotify(db, request, user, ext)
    _maybe_bootstrap_admin(user, ext.subject if ext.provider == "spotify" else None)


async def _save_spotify(db: AsyncSession, request: Request, user: User, ext: External) -> None:
    sp = ext.spotify
    conn = await db.get(SpotifyConnection, user.id)
    changed = conn is None or conn.spotify_user_id != ext.subject or conn.client_id != sp["client_id"]
    if conn is None:
        conn = SpotifyConnection(user_id=user.id, spotify_user_id=ext.subject, client_id=sp["client_id"],
                                 access_token_enc="", refresh_token_enc="", expires_at=utcnow())
        db.add(conn)
    elif conn.spotify_user_id != ext.subject:   # switched to a different Spotify account: drop the old one's sign-in
        old = (await db.execute(select(Identity).where(Identity.user_id == user.id, Identity.provider == "spotify",
                                                       Identity.subject == conn.spotify_user_id))).scalar_one_or_none()
        if old:
            await db.delete(old)
    conn.spotify_user_id = ext.subject
    conn.display_name = ext.display_name
    conn.client_id = sp["client_id"]
    conn.uses_site_app = sp["site_app"]
    spotify.store_tokens(conn, sp["tokens"])
    if changed:
        audit.record(db, "account.spotify_connect", request=request, actor=user, target=user, spotify_user_id=ext.subject,
                     app="site" if sp["site_app"] else "own")


def _link_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_config().secret_key, salt="vibeify-pending-link")


def _park(resp: Response, ext: External, user_id: str) -> None:
    payload = crypto.encrypt(json.dumps({"user_id": user_id, **ext.__dict__}))
    resp.set_cookie(LINK_COOKIE, _link_serializer().dumps(payload), max_age=900, httponly=True,
                    secure=get_config().secure_cookies, samesite="lax", path="/api/auth")


def _parked(request: Request) -> dict | None:
    raw = request.cookies.get(LINK_COOKIE)
    if not raw:
        return None
    try:
        plain = crypto.decrypt(_link_serializer().loads(raw, max_age=900))
    except BadSignature:
        return None
    return json.loads(plain) if plain else None


async def _sign_in(db: AsyncSession, request: Request, resp: Response, user: User, method: str) -> str | None:
    """Start a session; if this browser parked an identity for this account, link it now. Returns the linked provider."""
    linked = None
    if (parked := _parked(request)) is not None:
        resp.delete_cookie(LINK_COOKIE, path="/api/auth")
        if parked.pop("user_id") == user.id:
            ext = External(**parked)
            owner = await _user_for_identity(db, ext.provider, ext.subject)
            if owner is None or owner.id == user.id:
                await _attach(db, request, user, ext, how="confirmed by signing in")
                linked = ext.provider
    await security.start_session(db, resp, request, user, method)
    return linked


async def _finish(db: AsyncSession, request: Request, ext: External, mode: str, current: User | None, return_to: str) -> RedirectResponse:
    """Shared tail of the Spotify, Google and Apple callbacks."""
    resp = _redirect(return_to)
    owner = await _user_for_identity(db, ext.provider, ext.subject)

    if mode == "link":
        if current is None:
            resp.headers["location"] = "/signin?error=expired"
            return resp
        if owner and owner.id != current.id:
            if not await _is_throwaway(db, owner):
                resp.headers["location"] = f"/account?error={ext.provider}_in_use"
                return resp
            # e.g. a duplicate account made by signing in with Google before linking it: fold it in
            audit.record(db, "account.merge", request=request, actor=current, target=current, provider=ext.provider,
                         merged_user_id=owner.id)
            current.is_admin = current.is_admin or owner.is_admin
            await db.delete(owner)
            await db.flush()   # frees its email address for this account
        await _attach(db, request, current, ext, how="linked in account settings")
        await db.commit()
        resp.headers["location"] = f"/account?linked={ext.provider}"
        return resp

    settings = await settings_store.load(db)
    user = owner
    if user is None and ext.email and (existing := await _user_for_email(db, ext.email)):
        if ext.email_verified and existing.email_verified:
            user = existing   # both sides proved they own the address: same person
        else:
            _park(resp, ext, existing.id)
            resp.headers["location"] = f"/signin?link={ext.provider}"
            return resp
    if user is None:
        try:
            user = await _new_user(db, settings, request, ext.provider, display_name=ext.display_name or (ext.email or "").split("@")[0],
                                   email=ext.email, email_verified=bool(ext.email and ext.email_verified), avatar_url=ext.avatar_url)
        except HTTPException:
            resp.headers["location"] = "/signin?error=signups_closed"
            return resp
    if user.is_disabled:
        resp.headers["location"] = "/signin?error=disabled"
        return resp
    await _attach(db, request, user, ext, how="same verified email" if user is not owner else "sign-in")
    await db.commit()
    if linked := await _sign_in(db, request, resp, user, ext.provider):
        resp.headers["location"] = f"/account?linked={linked}"
    return resp


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
    email = (profile.get("email") or "").strip().lower() or None
    ext = External("spotify", profile["id"], email=email, email_verified=False,   # Spotify doesn't verify addresses
                   display_name=profile.get("display_name") or profile["id"],
                   avatar_url=((profile.get("images") or [{}])[0] or {}).get("url"),
                   spotify={"tokens": tokens, "client_id": st["client_id"], "site_app": st["site_app"]})
    final = await _finish(db, request, ext, st["mode"], user, st["return_to"])
    final.delete_cookie(security.OAUTH_COOKIE, path="/api/auth")
    return final


# ── Google (OpenID Connect) ──────────────────────────────────────────────────
@router.get("/google/start")
async def google_start(mode: str = Query("login", pattern="^(login|link)$"), return_to: str | None = None,
                       db: AsyncSession = Depends(get_db), user: User | None = Depends(security.optional_user)):
    settings = await settings_store.load(db)
    if not (settings["auth_google"] and settings["google_client_id"] and settings["google_client_secret"]):
        raise HTTPException(503, "Google sign-in isn't set up on this site.")
    if mode == "link" and not user:
        raise HTTPException(401, "Sign in first, then link Google.")
    verifier, challenge = spotify.pkce_pair()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    url = GOOGLE_AUTH + "?" + urlencode({
        "client_id": settings["google_client_id"], "redirect_uri": google_redirect_uri(), "response_type": "code",
        "scope": "openid email profile", "state": state, "nonce": nonce, "prompt": "select_account",
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    resp = RedirectResponse(url, status_code=303)
    security.set_oauth_state(resp, {"p": "google", "state": state, "nonce": nonce, "verifier": verifier, "mode": mode,
                                    "return_to": _safe_return(return_to)})
    return resp


def _id_token_claims(id_token: str) -> dict:
    # Received directly from the provider's token endpoint over TLS with our client secret, so per OpenID Connect
    # Core 3.1.3.7 the signature check may be skipped; the claims are still validated by the caller.
    payload = id_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def _claims_ok(claims: dict, client_id: str, issuers: tuple[str, ...], nonce: str) -> bool:
    return (claims.get("aud") == client_id and claims.get("iss") in issuers and claims.get("nonce") == nonce
            and int(claims.get("exp", 0)) >= utcnow().timestamp() and bool(claims.get("sub")))


def _verified(claims: dict) -> bool:
    return claims.get("email_verified") in (True, "true")   # Apple sends the string


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
    if not _claims_ok(claims, settings["google_client_id"], ("https://accounts.google.com", "accounts.google.com"), st["nonce"]):
        resp.headers["location"] = "/signin?error=google"
        return resp
    email = (claims.get("email") or "").lower() or None
    ext = External("google", claims["sub"], email=email, email_verified=bool(email) and _verified(claims),
                   display_name=claims.get("name") or "", avatar_url=claims.get("picture"))
    final = await _finish(db, request, ext, st.get("mode", "login"), current, st["return_to"])
    final.delete_cookie(security.OAUTH_COOKIE, path="/api/auth")
    return final


# ── Apple ────────────────────────────────────────────────────────────────────
@router.get("/apple/start")
async def apple_start(mode: str = Query("login", pattern="^(login|link)$"), return_to: str | None = None,
                      db: AsyncSession = Depends(get_db), user: User | None = Depends(security.optional_user)):
    settings = await settings_store.load(db)
    if not (settings["auth_apple"] and settings_store.apple_ready(settings)):
        raise HTTPException(503, "Sign in with Apple isn't set up on this site.")
    if mode == "link" and not user:
        raise HTTPException(401, "Sign in first, then link Apple.")
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    url = apple.AUTH_URL + "?" + urlencode({
        "client_id": settings["apple_client_id"], "redirect_uri": apple_redirect_uri(), "response_type": "code",
        "scope": "name email", "response_mode": "form_post", "state": state, "nonce": nonce,
    })
    resp = RedirectResponse(url, status_code=303)
    security.set_oauth_state(resp, {"p": "apple", "state": state, "nonce": nonce, "mode": mode, "return_to": _safe_return(return_to)})
    return resp


@router.post("/apple/callback")
async def apple_callback_post(request: Request):
    """Apple POSTs from its own site, so our SameSite=Lax cookies aren't sent. Bounce to a GET, which carries them."""
    form = parse_qs((await request.body())[:20_000].decode(errors="replace"))
    params = {k: form[k][0] for k in ("code", "state", "error", "user") if form.get(k)}
    return _redirect(f"/api/auth/apple/callback?{urlencode(params)}")


@router.get("/apple/callback")
async def apple_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                         user: str | None = None, db: AsyncSession = Depends(get_db),
                         current: User | None = Depends(security.optional_user)):
    resp = _redirect("/")
    st = security.pop_oauth_state(request, resp)
    if not st or st.get("p") != "apple" or st.get("state") != state:
        resp.headers["location"] = "/signin?error=expired"
        return resp
    if error or not code:
        resp.headers["location"] = "/signin?error=cancelled"
        return resp
    settings = await settings_store.load(db)
    try:
        secret = apple.client_secret(settings)
    except ValueError:
        resp.headers["location"] = "/signin?error=apple"
        return resp
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.post(apple.TOKEN_URL, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": apple_redirect_uri(),
            "client_id": settings["apple_client_id"], "client_secret": secret,
        })
    if r.status_code != 200:
        resp.headers["location"] = "/signin?error=apple"
        return resp
    claims = _id_token_claims(r.json()["id_token"])
    if not _claims_ok(claims, settings["apple_client_id"], (apple.ISSUER,), st["nonce"]):
        resp.headers["location"] = "/signin?error=apple"
        return resp
    name = ""
    try:   # Apple sends the name only the first time someone signs in to the app
        n = json.loads(user or "{}").get("name") or {}
        name = " ".join(p for p in (n.get("firstName"), n.get("lastName")) if p)
    except (ValueError, AttributeError):
        pass
    email = (claims.get("email") or "").lower() or None
    ext = External("apple", claims["sub"], email=email, email_verified=bool(email) and _verified(claims), display_name=name)
    final = await _finish(db, request, ext, st.get("mode", "login"), current, st["return_to"])
    final.delete_cookie(security.OAUTH_COOKIE, path="/api/auth")
    return final


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


async def _issue_token(db: AsyncSession, email: str, purpose: str, hours: int, user_id: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    db.add(EmailToken(token_hash=crypto.sha256(token), email=email, purpose=purpose, user_id=user_id,
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
    user = await _user_for_email(db, tok.email)
    if user and not user.email_verified and tok.user_id != user.id:
        # Another account holds this address unverified (e.g. reported by Spotify). Proven ownership wins:
        # the address moves to a fresh account instead of handing over whatever that account is.
        audit.record(db, "account.email_released", request=request, target=user, reason="verified by someone else")
        user.email = None
        await db.flush()
        user = None
    if user is None:
        user = await _new_user(db, settings, request, "email", email=tok.email, display_name=body.display_name.strip()[:120] or tok.email.split("@")[0])
    user.email_verified = True
    user.password_hash = security.hash_password(body.password)
    if not await _user_for_identity(db, "email", tok.email):
        db.add(Identity(user_id=user.id, provider="email", subject=tok.email, email=tok.email))
    _maybe_bootstrap_admin(user)
    await db.commit()
    return {"ok": True, "linked": await _sign_in(db, request, response, user, "email")}


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
    return {"ok": True, "linked": await _sign_in(db, request, response, user, "password")}


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
        db.add(Identity(user_id=user.id, provider="email", subject=tok.email, email=tok.email))
    audit.record(db, "auth.password_reset", request=request, actor=user, target=user)
    await db.commit()
    return {"ok": True, "linked": await _sign_in(db, request, response, user, "password reset")}


@router.post("/logout", dependencies=[Depends(security.csrf_guard)])
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    await security.end_session(db, response, request)
    return {"ok": True}
