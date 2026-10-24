"""The signed-in user's account: profile, sign-in methods, Spotify connection, own AI keys, password."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit, crypto, entitlements, security, settings_store
from ..db import get_db, utcnow
from ..models import AuditLog, Generation, Identity, Session, SpotifyConnection, SupportTicket, UsageLog, User, UserLLMKey
from . import billing
from ..services.llm import registry
from ..services.llm.base import PROVIDER_KINDS, LLMError

router = APIRouter(prefix="/api/me", tags=["me"], dependencies=[Depends(security.csrf_guard)])


async def _usage(db: AsyncSession, user: User, settings: dict) -> dict:
    ent = await entitlements.for_user(db, user, settings)
    return {**await entitlements.usage(db, user), "daily_limit": ent.daily_requests, "daily_token_limit": ent.daily_tokens,
            "monthly_token_limit": ent.monthly_tokens}


async def _membership(db: AsyncSession, user: User, settings: dict) -> dict:
    ent = await entitlements.for_user(db, user, settings)
    return {
        "plan": None if not ent.plan else {"id": ent.plan.id, "name": ent.plan.name, "price_cents": ent.plan.price_cents,
                                            "currency": ent.plan.currency, "interval": ent.plan.interval},
        "status": user.subscription_status, "period_end": user.subscription_period_end,
        "cancel_at_period_end": user.subscription_cancel_at_period_end, "source": user.plan_source,
        "has_billing_account": bool(user.stripe_customer_id),
        "features": {"edit_playlists": ent.edit_playlists, "playlist_seeds": ent.playlist_seeds},
        "max_playlist_size": ent.max_playlist_size,
    }


@router.get("")
async def me(user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    settings = await settings_store.load(db)
    idents = (await db.execute(select(Identity).where(Identity.user_id == user.id))).scalars().all()
    conn = await db.get(SpotifyConnection, user.id)
    keys = (await db.execute(select(UserLLMKey).where(UserLLMKey.user_id == user.id))).scalars().all()
    models = await registry.available_models(db, user, settings)
    return {
        "id": user.id, "display_name": user.display_name, "email": user.email, "email_verified": user.email_verified,
        "avatar_url": user.avatar_url, "is_admin": user.is_admin, "has_password": bool(user.password_hash),
        "created_at": user.created_at,
        "sign_in_methods": sorted({i.provider for i in idents}),
        "spotify": None if not conn else {
            "spotify_user_id": conn.spotify_user_id, "display_name": conn.display_name,
            "uses_site_app": conn.uses_site_app, "client_id": conn.client_id, "connected_at": conn.created_at,
        },
        "llm_keys": [{"kind": k.kind, "model_id": k.model_id, "base_url": k.base_url,
                      "key_hint": crypto.mask(crypto.decrypt(k.api_key_enc))} for k in keys],
        "models": [{"id": m.id, "label": m.label, "kind": m.kind, "own_key": m.own_key, "is_default": m.is_default} for m in models],
        "usage": await _usage(db, user, settings),
        "membership": await _membership(db, user, settings),
    }


class ProfileIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


@router.patch("")
async def update_profile(body: ProfileIn, user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    user.display_name = body.display_name.strip()
    await db.commit()
    return {"ok": True}


@router.delete("/spotify")
async def disconnect_spotify(request: Request, user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    idents = (await db.execute(select(Identity).where(Identity.user_id == user.id))).scalars().all()
    if all(i.provider == "spotify" for i in idents) and not user.password_hash:
        raise HTTPException(400, "Spotify is your only way to sign in. Add a password or Google first.")
    await db.execute(delete(SpotifyConnection).where(SpotifyConnection.user_id == user.id))
    await db.execute(delete(Identity).where(Identity.user_id == user.id, Identity.provider == "spotify"))
    audit.record(db, "account.spotify_disconnect", request=request, actor=user, target=user)
    await db.commit()
    return {"ok": True}


class KeyIn(BaseModel):
    kind: str
    api_key: str = Field(min_length=8, max_length=500)
    model_id: str = Field(min_length=1, max_length=200)
    base_url: str | None = None


@router.put("/llm-keys")
async def put_llm_key(body: KeyIn, request: Request, user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    settings = await settings_store.load(db)
    if not settings["allow_user_llm_keys"]:
        raise HTTPException(403, "Using your own AI keys is turned off on this site.")
    if body.kind not in PROVIDER_KINDS:
        raise HTTPException(400, "Unknown provider.")
    if body.kind == "openai_compatible" and not body.base_url:
        raise HTTPException(400, "An OpenAI-compatible provider needs a base URL.")
    try:   # check the key works before saving it
        await registry.list_provider_models(body.kind, body.api_key.strip(), body.base_url)
    except LLMError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(400, "That key didn't work with the provider. Check it and try again.") from e
    row = (await db.execute(select(UserLLMKey).where(UserLLMKey.user_id == user.id, UserLLMKey.kind == body.kind))).scalar_one_or_none()
    if row is None:
        row = UserLLMKey(user_id=user.id, kind=body.kind, api_key_enc="", model_id="")
        db.add(row)
    row.api_key_enc = crypto.encrypt(body.api_key.strip())
    row.model_id = body.model_id.strip()
    row.base_url = body.base_url
    audit.record(db, "account.ai_key_set", request=request, actor=user, target=user, kind=body.kind, model=row.model_id)
    await db.commit()
    return {"ok": True}


@router.delete("/llm-keys/{kind}")
async def delete_llm_key(kind: str, request: Request, user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(delete(UserLLMKey).where(UserLLMKey.user_id == user.id, UserLLMKey.kind == kind))
    audit.record(db, "account.ai_key_removed", request=request, actor=user, target=user, kind=kind)
    await db.commit()
    return {"ok": True}


class PasswordIn(BaseModel):
    current_password: str = ""
    new_password: str


@router.post("/password")
async def change_password(body: PasswordIn, request: Request, user: User = Depends(security.current_user),
                          db: AsyncSession = Depends(get_db)):
    if user.password_hash and not security.verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "Your current password is wrong.")
    if not user.email:
        raise HTTPException(400, "Add an email address to your account before setting a password.")
    if problem := security.password_problem(body.new_password):
        raise HTTPException(400, problem)
    had_password = bool(user.password_hash)
    user.password_hash = security.hash_password(body.new_password)
    audit.record(db, "account.password_changed" if had_password else "account.password_set", request=request, actor=user, target=user)
    await db.commit()
    return {"ok": True}


@router.delete("")
async def delete_account(request: Request, response: Response, user: User = Depends(security.current_user),
                         db: AsyncSession = Depends(get_db)):
    cancelled = await billing.cancel_for_deletion(db, user)   # before anything else: no charges for a deleted account
    audit.record(db, "account.delete", request=request, actor=user, target=user, subscription_cancelled=cancelled or None,
                 stripe_customer=user.stripe_customer_id)
    await security.end_session(db, response, request)
    await db.delete(await db.get(User, user.id))
    await db.commit()
    return {"ok": True}


# ── sessions (devices) ───────────────────────────────────────────────────────
@router.get("/sessions")
async def sessions(request: Request, user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    current = crypto.sha256(request.cookies.get(security.SESSION_COOKIE) or "")
    rows = (await db.execute(select(Session).where(Session.user_id == user.id, Session.expires_at > utcnow())
                             .order_by(Session.last_seen_at.desc()))).scalars().all()
    return [{"id": s.token_hash[:12], "current": s.token_hash == current, "created_at": s.created_at,
             "last_seen_at": s.last_seen_at, "ip": s.ip, "user_agent": s.user_agent} for s in rows]


@router.post("/sessions/sign-out-others")
async def sign_out_others(request: Request, user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    current = crypto.sha256(request.cookies.get(security.SESSION_COOKIE) or "")
    n = (await db.execute(delete(Session).where(Session.user_id == user.id, Session.token_hash != current))).rowcount
    audit.record(db, "account.sign_out_others", request=request, actor=user, target=user, sessions=n)
    await db.commit()
    return {"ok": True, "sessions": n}


# ── data export (privacy) ────────────────────────────────────────────────────
@router.get("/export")
async def export(request: Request, user: User = Depends(security.current_user), db: AsyncSession = Depends(get_db)):
    """Everything stored about the account, as JSON. Secrets (tokens, keys, password hash) are left out."""
    conn = await db.get(SpotifyConnection, user.id)
    q = lambda model, *where: db.execute(select(model).where(*where))  # noqa: E731
    idents = (await q(Identity, Identity.user_id == user.id)).scalars().all()
    keys = (await q(UserLLMKey, UserLLMKey.user_id == user.id)).scalars().all()
    gens = (await db.execute(select(Generation).where(Generation.user_id == user.id).order_by(Generation.created_at))).scalars().all()
    usage = (await db.execute(select(UsageLog).where(UsageLog.user_id == user.id).order_by(UsageLog.created_at))).scalars().all()
    sess = (await q(Session, Session.user_id == user.id)).scalars().all()
    events = (await db.execute(select(AuditLog).where(AuditLog.target_id == user.id).order_by(AuditLog.created_at))).scalars().all()
    tickets = (await db.execute(select(SupportTicket).where(SupportTicket.user_id == user.id).order_by(SupportTicket.created_at))).scalars().all()
    audit.record(db, "account.export", request=request, actor=user, target=user)
    await db.commit()
    data = {
        "exported_at": utcnow().isoformat(),
        "account": {"id": user.id, "display_name": user.display_name, "email": user.email, "email_verified": user.email_verified,
                    "avatar_url": user.avatar_url, "created_at": user.created_at, "last_login_at": user.last_login_at,
                    "has_password": bool(user.password_hash), "plan_id": user.plan_id, "subscription_status": user.subscription_status,
                    "subscription_period_end": user.subscription_period_end, "stripe_customer_id": user.stripe_customer_id},
        "sign_in_methods": [{"provider": i.provider, "subject": i.subject, "created_at": i.created_at} for i in idents],
        "spotify": None if not conn else {"spotify_user_id": conn.spotify_user_id, "display_name": conn.display_name,
                                          "client_id": conn.client_id, "scopes": conn.scopes, "connected_at": conn.created_at},
        "ai_keys": [{"kind": k.kind, "model_id": k.model_id, "base_url": k.base_url, "created_at": k.created_at} for k in keys],
        "playlists": [{"id": g.id, "title": g.title, "description": g.description, "request": g.request, "messages": g.messages,
                       "tracks": g.tracks, "model": g.model_label, "spotify_playlist_url": g.spotify_playlist_url,
                       "shared_on_community_feed": g.shared, "created_at": g.created_at, "updated_at": g.updated_at} for g in gens],
        "ai_usage": [{"at": u.created_at, "provider": u.provider_kind, "model": u.model_id, "input_tokens": u.input_tokens,
                      "output_tokens": u.output_tokens, "own_key": u.own_key} for u in usage],
        "sessions": [{"created_at": s.created_at, "last_seen_at": s.last_seen_at, "ip": s.ip, "user_agent": s.user_agent} for s in sess],
        "support_requests": [{"number": t.number, "category": t.category, "subject": t.subject, "status": t.status,
                              "created_at": t.created_at,
                              "messages": [{**m, "author": "Support" if m["from"] == "admin" else m["author"]} for m in t.messages]}
                             for t in tickets],
        "account_activity": [{"at": a.created_at, "action": a.action, "by": "you" if a.actor_id == user.id else ("a site admin" if a.action.startswith("admin.") else a.actor_label or "system"),
                              "ip": a.ip if a.actor_id == user.id else "", "details": a.details} for a in events],
    }
    return JSONResponse(jsonable_encoder(data), headers={
        "Content-Disposition": f'attachment; filename="account-export-{utcnow():%Y%m%d}.json"'})
