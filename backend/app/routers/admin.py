"""Admin panel API: site settings, users, LLM providers/models, usage."""
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import audit, crypto, mailer, security, settings_store
from ..config import get_config
from ..db import get_db
from ..models import (AuditLog, BillingEvent, Generation, Identity, LLMModel, LLMProvider, Plan, Session, SpotifyConnection,
                      SupportTicket, UsageLog, User)
from ..services import recommend
from . import billing
from ..services.llm import anthropic_provider, registry
from ..services.llm.base import PROVIDER_KINDS, LLMError

router = APIRouter(prefix="/api/admin", tags=["admin"],
                   dependencies=[Depends(security.csrf_guard), Depends(security.admin_user)])


# ── settings ─────────────────────────────────────────────────────────────────
@router.get("/settings")
async def get_settings(db: AsyncSession = Depends(get_db)):
    return settings_store.public_view(await settings_store.load(db))


@router.put("/settings")
async def put_settings(body: dict[str, Any], request: Request, me: User = Depends(security.admin_user),
                       db: AsyncSession = Depends(get_db)):
    before = await settings_store.load(db)
    updates = {}
    for key, value in body.items():
        if key not in settings_store.DEFAULTS:
            raise HTTPException(400, f"Unknown setting {key}")
        default = settings_store.DEFAULTS[key]
        if key in settings_store.SECRET_KEYS:
            if value is True or value is None:   # "unchanged" placeholder from the UI
                continue
            value = str(value)
        elif isinstance(default, bool):
            value = bool(value)
        elif isinstance(default, int):
            try:
                value = int(value)
            except (TypeError, ValueError) as e:
                raise HTTPException(400, f"{key} must be a number") from e
        else:
            value = str(value).strip()
        updates[key] = value
    changed = {k: ("(secret changed)" if k in settings_store.SECRET_KEYS else [before[k], v])
               for k, v in updates.items() if before[k] != v}
    if changed:
        audit.record(db, "admin.settings.update", request=request, actor=me, target_type="settings", changes=changed)
    await settings_store.save(db, updates)   # commits the audit entry too
    return settings_store.public_view(await settings_store.load(db))


class TestEmailIn(BaseModel):
    to: str


@router.post("/settings/test-email")
async def test_email(body: TestEmailIn, db: AsyncSession = Depends(get_db)):
    settings = await settings_store.load(db)
    if not settings_store.email_ready(settings):
        raise HTTPException(400, "Set the SMTP host and From address first.")
    text, html = mailer.link_email(settings, heading="Email works", body="This is a test message from the admin panel.",
                                   button="Open the site", url=get_config().public_url)
    try:
        await mailer.send(settings, body.to, f"{settings['site_name']} test email", text, html)
    except Exception as e:   # surface the SMTP error to the admin
        raise HTTPException(400, f"Sending failed: {e}") from e
    return {"ok": True}


# ── users ────────────────────────────────────────────────────────────────────
@router.get("/users")
async def list_users(q: str = "", page: int = 1, db: AsyncSession = Depends(get_db)):
    stmt = select(User).order_by(User.created_at.desc())
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.display_name).like(like), func.lower(User.email).like(like),
                              User.id.in_(select(SpotifyConnection.user_id).where(func.lower(SpotifyConnection.spotify_user_id).like(like)))))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    users = (await db.execute(stmt.offset((page - 1) * 50).limit(50))).scalars().all()
    ids = [u.id for u in users]
    conns = {c.user_id: c for c in (await db.execute(select(SpotifyConnection).where(SpotifyConnection.user_id.in_(ids)))).scalars()}
    idents: dict[str, list[str]] = {}
    for i in (await db.execute(select(Identity).where(Identity.user_id.in_(ids)))).scalars():
        idents.setdefault(i.user_id, []).append(i.provider)
    gens = dict((await db.execute(select(Generation.user_id, func.count(Generation.id))
                                  .where(Generation.user_id.in_(ids)).group_by(Generation.user_id))).all())
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    tokens = dict((await db.execute(select(UsageLog.user_id, func.sum(UsageLog.input_tokens + UsageLog.output_tokens))
                                    .where(UsageLog.user_id.in_(ids), UsageLog.own_key.is_(False), UsageLog.created_at >= month_start)
                                    .group_by(UsageLog.user_id))).all())
    return {"total": total, "page": page, "users": [{
        "id": u.id, "display_name": u.display_name, "email": u.email, "is_admin": u.is_admin, "is_disabled": u.is_disabled,
        "created_at": u.created_at, "last_login_at": u.last_login_at, "sign_in_methods": sorted(idents.get(u.id, [])),
        "spotify_user_id": conns[u.id].spotify_user_id if u.id in conns else None,
        "spotify_app": ("site" if conns[u.id].uses_site_app else "own") if u.id in conns else None,
        "daily_generation_limit": u.daily_generation_limit, "monthly_token_limit": u.monthly_token_limit,
        "daily_token_limit": u.daily_token_limit, "plan_id": u.plan_id, "plan_source": u.plan_source,
        "subscription_status": u.subscription_status,
        "allowed_model_ids": u.allowed_model_ids, "playlists": gens.get(u.id, 0),
        "tokens_this_month": int(tokens.get(u.id) or 0),
    } for u in users]}


class UserPatch(BaseModel):
    is_admin: bool | None = None
    is_disabled: bool | None = None
    daily_generation_limit: int | None = Field(None, ge=0)
    daily_token_limit: int | None = Field(None, ge=0)
    monthly_token_limit: int | None = Field(None, ge=0)
    plan_id: str | None = None           # "" = back to the default plan
    allowed_model_ids: list[str] | None = None
    clear_limits: bool = False           # back to site defaults
    clear_allowed_models: bool = False   # back to "all enabled models"


USER_FIELDS = ["is_admin", "is_disabled", "plan_id", "plan_source", "daily_generation_limit", "daily_token_limit",
               "monthly_token_limit", "allowed_model_ids"]


@router.patch("/users/{user_id}")
async def patch_user(user_id: str, body: UserPatch, request: Request, me: User = Depends(security.admin_user),
                     db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found.")
    before = audit.snapshot(user, USER_FIELDS)
    if user.id == me.id and (body.is_admin is False or body.is_disabled):
        raise HTTPException(400, "You can't remove your own admin access or disable yourself.")
    if body.plan_id is not None:
        if body.plan_id and not await db.get(Plan, body.plan_id):
            raise HTTPException(400, "Unknown plan.")
        user.plan_id, user.plan_source = (body.plan_id, "admin") if body.plan_id else (None, None)
    if body.clear_limits:   # clear first, then apply any limits sent alongside
        user.daily_generation_limit = user.daily_token_limit = user.monthly_token_limit = None
    if body.clear_allowed_models:
        user.allowed_model_ids = None
    for field in ("is_admin", "is_disabled", "daily_generation_limit", "daily_token_limit", "monthly_token_limit", "allowed_model_ids"):
        value = getattr(body, field)
        if value is not None:
            setattr(user, field, value)
    if body.is_disabled:   # end their sessions now rather than on the next request
        await db.execute(sa_delete(Session).where(Session.user_id == user.id))
    if changes := audit.diff(user, USER_FIELDS, before):
        audit.record(db, "admin.user.update", request=request, actor=me, target=user, changes=changes)
    await db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request, me: User = Depends(security.admin_user), db: AsyncSession = Depends(get_db)):
    if user_id == me.id:
        raise HTTPException(400, "You can't delete your own account here.")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found.")
    cancelled = await billing.cancel_for_deletion(db, user)
    audit.record(db, "admin.user.delete", request=request, actor=me, target=user,
                 subscription_cancelled=cancelled or None, stripe_customer=user.stripe_customer_id)
    await db.delete(user)
    await db.commit()
    return {"ok": True}


@router.get("/users/{user_id}")
async def user_detail(user_id: str, db: AsyncSession = Depends(get_db)):
    """Everything about one account for the admin user page."""
    u = await db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found.")
    settings = await settings_store.load(db)
    conn = await db.get(SpotifyConnection, u.id)
    idents = (await db.execute(select(Identity).where(Identity.user_id == u.id).order_by(Identity.created_at))).scalars().all()
    sessions = (await db.execute(select(Session).where(Session.user_id == u.id, Session.expires_at > datetime.now(timezone.utc))
                                 .order_by(Session.last_seen_at.desc()))).scalars().all()
    gens = (await db.execute(select(Generation).where(Generation.user_id == u.id)
                             .order_by(Generation.created_at.desc()).limit(20))).scalars().all()
    gen_total = (await db.execute(select(func.count(Generation.id)).where(Generation.user_id == u.id))).scalar_one()
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage_rows = (await db.execute(
        select(UsageLog.own_key, func.count(UsageLog.id), func.sum(UsageLog.input_tokens + UsageLog.output_tokens))
        .where(UsageLog.user_id == u.id, UsageLog.created_at >= month_start).group_by(UsageLog.own_key))).all()
    usage_all = (await db.execute(select(func.count(UsageLog.id), func.sum(UsageLog.input_tokens + UsageLog.output_tokens))
                                  .where(UsageLog.user_id == u.id))).one()
    activity = (await db.execute(select(AuditLog).where(or_(AuditLog.target_id == u.id, AuditLog.actor_id == u.id))
                                 .order_by(AuditLog.created_at.desc()).limit(100))).scalars().all()
    payments = (await db.execute(select(BillingEvent).where(BillingEvent.user_id == u.id)
                                 .order_by(BillingEvent.received_at.desc()).limit(50))).scalars().all()
    tickets = (await db.execute(select(SupportTicket).where(SupportTicket.user_id == u.id)
                                .order_by(SupportTicket.updated_at.desc()).limit(20))).scalars().all()
    plan = await db.get(Plan, u.plan_id) if u.plan_id else None
    test_mode = settings["stripe_secret_key"].startswith(("sk_test", "rk_test"))
    return {
        "id": u.id, "display_name": u.display_name, "email": u.email, "email_verified": u.email_verified,
        "avatar_url": u.avatar_url, "is_admin": u.is_admin, "is_disabled": u.is_disabled, "has_password": bool(u.password_hash),
        "created_at": u.created_at, "last_login_at": u.last_login_at,
        "identities": [{"provider": i.provider, "subject": i.subject, "created_at": i.created_at} for i in idents],
        "spotify": None if not conn else {"spotify_user_id": conn.spotify_user_id, "display_name": conn.display_name,
                                          "app": "site" if conn.uses_site_app else "own", "client_id": conn.client_id,
                                          "connected_at": conn.created_at},
        "membership": {
            "plan": plan.name if plan else None, "plan_id": u.plan_id, "plan_source": u.plan_source, "status": u.subscription_status,
            "period_end": u.subscription_period_end, "cancel_at_period_end": u.subscription_cancel_at_period_end,
            "stripe_customer_id": u.stripe_customer_id, "stripe_subscription_id": u.stripe_subscription_id,
            "stripe_url": f"https://dashboard.stripe.com/{'test/' if test_mode else ''}customers/{u.stripe_customer_id}"
                          if u.stripe_customer_id else None,
        },
        "limits": {"daily_generation_limit": u.daily_generation_limit, "daily_token_limit": u.daily_token_limit,
                   "monthly_token_limit": u.monthly_token_limit, "allowed_model_ids": u.allowed_model_ids},
        "usage": {
            "month_requests": sum(r[1] for r in usage_rows if not r[0]), "month_tokens": int(sum(r[2] or 0 for r in usage_rows if not r[0])),
            "month_own_key_requests": sum(r[1] for r in usage_rows if r[0]),
            "all_requests": usage_all[0], "all_tokens": int(usage_all[1] or 0), "playlists": gen_total,
        },
        "sessions": [{"created_at": s.created_at, "last_seen_at": s.last_seen_at, "expires_at": s.expires_at,
                      "ip": s.ip, "user_agent": s.user_agent} for s in sessions],
        "playlists": [{"id": g.id, "title": g.title, "created_at": g.created_at, "tracks": len(g.tracks),
                       "spotify_url": g.spotify_playlist_url, "shared": g.shared, "community_hidden": g.community_hidden}
                      for g in gens],
        "activity": [_audit_view(a) for a in activity],
        "payments": [_billing_view(e) for e in payments],
        "support": [{"id": t.id, "number": t.number, "subject": t.subject, "status": t.status, "updated_at": t.updated_at} for t in tickets],
    }


@router.post("/users/{user_id}/sign-out")
async def sign_out_user(user_id: str, request: Request, me: User = Depends(security.admin_user), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found.")
    n = (await db.execute(sa_delete(Session).where(Session.user_id == user.id))).rowcount
    audit.record(db, "admin.user.sign_out", request=request, actor=me, target=user, sessions=n)
    await db.commit()
    return {"ok": True, "sessions": n}


# ── audit log & billing events ─────────────────────────────────────────────
def _audit_view(a: AuditLog) -> dict:
    return {"id": a.id, "created_at": a.created_at, "actor_id": a.actor_id, "actor_label": a.actor_label, "action": a.action,
            "target_type": a.target_type, "target_id": a.target_id, "target_label": a.target_label,
            "details": a.details, "ip": a.ip}


def _billing_view(e: BillingEvent) -> dict:
    return {"id": e.id, "type": e.type, "user_id": e.user_id, "customer_id": e.customer_id, "summary": e.summary,
            "amount_cents": e.amount_cents, "currency": e.currency, "stripe_created_at": e.stripe_created_at,
            "received_at": e.received_at}


@router.get("/audit")
async def audit_log(q: str = "", category: str = "", page: int = 1, db: AsyncSession = Depends(get_db)):
    """category: the action's first part (admin, auth, account, billing)."""
    settings = await settings_store.load(db)
    if page == 1:
        await audit.prune(db, settings["audit_retention_days"])
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    if category:
        stmt = stmt.where(AuditLog.action.like(f"{category}.%"))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(AuditLog.actor_label).like(like), func.lower(AuditLog.target_label).like(like),
                              func.lower(AuditLog.action).like(like), AuditLog.ip.like(like),
                              AuditLog.target_id == q, AuditLog.actor_id == q))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((max(page, 1) - 1) * 50).limit(50))).scalars().all()
    return {"total": total, "page": page, "entries": [_audit_view(a) for a in rows]}


@router.get("/billing/events")
async def billing_events(page: int = 1, db: AsyncSession = Depends(get_db)):
    stmt = select(BillingEvent).order_by(BillingEvent.received_at.desc())
    total = (await db.execute(select(func.count(BillingEvent.id)))).scalar_one()
    rows = (await db.execute(stmt.offset((max(page, 1) - 1) * 50).limit(50))).scalars().all()
    labels = {u.id: audit.label(u) for u in (await db.execute(
        select(User).where(User.id.in_([e.user_id for e in rows if e.user_id])))).scalars()}
    return {"total": total, "page": page,
            "events": [{**_billing_view(e), "user_label": labels.get(e.user_id or "", "")} for e in rows]}


# ── community feed moderation ───────────────────────────────────────────────
@router.get("/community")
async def community(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Generation, User).join(User, User.id == Generation.user_id)
                             .where(Generation.shared, Generation.spotify_playlist_id.is_not(None))
                             .order_by(Generation.created_at.desc()).limit(100))).all()
    return [{"id": g.id, "title": g.title, "description": g.description, "created_at": g.created_at,
             "tracks": len(g.tracks), "spotify_url": g.spotify_playlist_url, "hidden": g.community_hidden,
             "user_id": u.id, "user_label": audit.label(u)} for g, u in rows]


class CommunityPatch(BaseModel):
    hidden: bool


@router.patch("/community/{gen_id}")
async def moderate(gen_id: str, body: CommunityPatch, request: Request, me: User = Depends(security.admin_user),
                   db: AsyncSession = Depends(get_db)):
    gen = await db.get(Generation, gen_id)
    if not gen:
        raise HTTPException(404, "Playlist not found.")
    if gen.community_hidden != body.hidden:
        gen.community_hidden = body.hidden
        audit.record(db, "admin.community.hide" if body.hidden else "admin.community.show", request=request, actor=me,
                     target_type="playlist", target_id=gen.id, target_label=gen.title, owner=gen.user_id)
    await db.commit()
    return {"ok": True}


# ── LLM providers and models ────────────────────────────────────────────────
def _provider_view(p: LLMProvider) -> dict:
    return {"id": p.id, "name": p.name, "kind": p.kind, "base_url": p.base_url, "enabled": p.enabled,
            "key_hint": crypto.mask(crypto.decrypt(p.api_key_enc)), "has_key": bool(p.api_key_enc),
            "models": [{"id": m.id, "model_id": m.model_id, "display_name": m.display_name, "enabled": m.enabled,
                        "is_default": m.is_default, "max_output_tokens": m.max_output_tokens, "sort_order": m.sort_order}
                       for m in sorted(p.models, key=lambda m: (m.sort_order, m.display_name))]}


async def _load_provider(db: AsyncSession, provider_id: str) -> LLMProvider:
    p = (await db.execute(select(LLMProvider).options(selectinload(LLMProvider.models))
                          .where(LLMProvider.id == provider_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Provider not found.")
    return p


@router.get("/providers")
async def list_providers(db: AsyncSession = Depends(get_db)):
    rows = await db.execute(select(LLMProvider).options(selectinload(LLMProvider.models)).order_by(LLMProvider.created_at))
    return [_provider_view(p) for p in rows.scalars()]


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool = True


@router.post("/providers")
async def create_provider(body: ProviderIn, request: Request, me: User = Depends(security.admin_user), db: AsyncSession = Depends(get_db)):
    if body.kind not in PROVIDER_KINDS:
        raise HTTPException(400, "Unknown provider type.")
    if body.kind == "openai_compatible" and not body.base_url:
        raise HTTPException(400, "An OpenAI-compatible provider needs a base URL.")
    p = LLMProvider(name=body.name.strip(), kind=body.kind, base_url=(body.base_url or "").strip() or None,
                    api_key_enc=crypto.encrypt(body.api_key.strip()) if body.api_key else None, enabled=body.enabled)
    db.add(p)
    if body.kind == "anthropic":   # sensible starting models; admins can add/remove
        for i, (mid, label) in enumerate(anthropic_provider.DEFAULT_MODELS):
            db.add(LLMModel(provider=p, model_id=mid, display_name=label, sort_order=i))
    await db.flush()
    audit.record(db, "admin.provider.create", request=request, actor=me, target_type="provider", target_id=p.id,
                 target_label=p.name, kind=p.kind, base_url=p.base_url, key_set=bool(p.api_key_enc))
    await db.commit()
    return _provider_view(await _load_provider(db, p.id))


class ProviderPatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None   # "" clears the key
    enabled: bool | None = None


@router.patch("/providers/{provider_id}")
async def patch_provider(provider_id: str, body: ProviderPatch, request: Request, me: User = Depends(security.admin_user), db: AsyncSession = Depends(get_db)):
    p = await _load_provider(db, provider_id)
    if body.name is not None:
        p.name = body.name.strip() or p.name
    if body.base_url is not None:
        p.base_url = body.base_url.strip() or None
    if body.api_key is not None:
        p.api_key_enc = crypto.encrypt(body.api_key.strip()) if body.api_key.strip() else None
    if body.enabled is not None:
        p.enabled = body.enabled
    audit.record(db, "admin.provider.update", request=request, actor=me, target_type="provider", target_id=p.id, target_label=p.name,
                 **body.model_dump(exclude_none=True, exclude={"api_key"}),
                 api_key=None if body.api_key is None else ("changed" if body.api_key.strip() else "cleared"))
    await db.commit()
    return _provider_view(await _load_provider(db, provider_id))


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: str, request: Request, me: User = Depends(security.admin_user), db: AsyncSession = Depends(get_db)):
    p = await _load_provider(db, provider_id)
    audit.record(db, "admin.provider.delete", request=request, actor=me, target_type="provider", target_id=p.id, target_label=p.name)
    await db.delete(p)
    await db.commit()
    return {"ok": True}


@router.get("/providers/{provider_id}/discover")
async def discover_models(provider_id: str, db: AsyncSession = Depends(get_db)):
    """Model ids the provider's API offers, so admins pick real names instead of typing them."""
    p = await _load_provider(db, provider_id)
    try:
        models = await registry.list_provider_models(p.kind, crypto.decrypt(p.api_key_enc), p.base_url)
    except LLMError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        rejected = any(w in type(e).__name__ for w in ("Authentication", "PermissionDenied")) or getattr(e, "code", None) in (401, 403)
        raise HTTPException(400, "The provider rejected the API key." if rejected else f"Couldn't list models: {type(e).__name__}") from e
    existing = {m.model_id for m in p.models}
    return [{"model_id": mid, "display_name": label, "added": mid in existing} for mid, label in models]


class ModelIn(BaseModel):
    model_id: str = Field(min_length=1, max_length=200)
    display_name: str = Field("", max_length=120)
    max_output_tokens: int = Field(16000, ge=256, le=128000)


@router.post("/providers/{provider_id}/models")
async def add_model(provider_id: str, body: ModelIn, request: Request, me: User = Depends(security.admin_user), db: AsyncSession = Depends(get_db)):
    p = await _load_provider(db, provider_id)
    db.add(LLMModel(provider_id=p.id, model_id=body.model_id.strip(), display_name=body.display_name.strip() or body.model_id.strip(),
                    max_output_tokens=body.max_output_tokens, sort_order=len(p.models)))
    audit.record(db, "admin.model.create", request=request, actor=me, target_type="model", target_label=body.model_id.strip(),
                 provider=p.name)
    await db.commit()
    return _provider_view(await _load_provider(db, provider_id))


class ModelPatch(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None
    max_output_tokens: int | None = Field(None, ge=256, le=128000)
    sort_order: int | None = None


@router.patch("/models/{model_pk}")
async def patch_model(model_pk: str, body: ModelPatch, request: Request, me: User = Depends(security.admin_user), db: AsyncSession = Depends(get_db)):
    m = await db.get(LLMModel, model_pk)
    if not m:
        raise HTTPException(404, "Model not found.")
    if body.is_default:   # only one default across the site
        for other in (await db.execute(select(LLMModel).where(LLMModel.is_default))).scalars():
            other.is_default = False
    for field in ("display_name", "enabled", "is_default", "max_output_tokens", "sort_order"):
        value = getattr(body, field)
        if value is not None:
            setattr(m, field, value)
    audit.record(db, "admin.model.update", request=request, actor=me, target_type="model", target_id=m.id,
                 target_label=m.display_name, **body.model_dump(exclude_none=True))
    await db.commit()
    return {"ok": True}


@router.delete("/models/{model_pk}")
async def delete_model(model_pk: str, request: Request, me: User = Depends(security.admin_user), db: AsyncSession = Depends(get_db)):
    m = await db.get(LLMModel, model_pk)
    if m:
        audit.record(db, "admin.model.delete", request=request, actor=me, target_type="model", target_id=m.id, target_label=m.display_name)
        await db.delete(m)
        await db.commit()
    return {"ok": True}


@router.post("/models/{model_pk}/test")
async def test_model(model_pk: str, db: AsyncSession = Depends(get_db)):
    """A tiny real request (3 songs) to confirm the key, model id and structured output all work."""
    m = (await db.execute(select(LLMModel).options(selectinload(LLMModel.provider)).where(LLMModel.id == model_pk))).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Model not found.")
    resolved = registry.ResolvedModel(registry.ModelOption(m.id, m.display_name, m.provider.kind, m.model_id, False),
                                      crypto.decrypt(m.provider.api_key_enc), m.provider.base_url, m.max_output_tokens)
    started = datetime.now(timezone.utc)
    try:
        result = await registry.complete_json(resolved, recommend.SYSTEM_PROMPT,
                                              [{"role": "user", "content": "Build a playlist of 3 songs for a sunny morning walk."}],
                                              recommend.PLAYLIST_SCHEMA)
    except LLMError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
            "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
            "tracks": [f"{t['title']} — {t['artist']}" for t in result.data.get("tracks", [])][:5]}


# ── usage & stats ────────────────────────────────────────────────────────────
@router.get("/stats")
async def stats(days: int = 30, db: AsyncSession = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))
    count = lambda stmt: db.execute(stmt)   # noqa: E731
    users = (await count(select(func.count(User.id)))).scalar_one()
    new_users = (await count(select(func.count(User.id)).where(User.created_at >= since))).scalar_one()
    playlists = (await count(select(func.count(Generation.id)).where(Generation.created_at >= since))).scalar_one()
    saved = (await count(select(func.count(Generation.id)).where(Generation.created_at >= since,
                                                                 Generation.spotify_playlist_id.is_not(None)))).scalar_one()
    by_model = (await count(select(UsageLog.provider_kind, UsageLog.model_id, func.count(UsageLog.id),
                                   func.sum(UsageLog.input_tokens), func.sum(UsageLog.output_tokens),
                                   func.sum(case((UsageLog.own_key, 1), else_=0)))
                            .where(UsageLog.created_at >= since).group_by(UsageLog.provider_kind, UsageLog.model_id))).all()
    top_users = (await count(select(User.display_name, User.email, func.count(UsageLog.id))
                             .join(UsageLog, UsageLog.user_id == User.id).where(UsageLog.created_at >= since)
                             .group_by(User.id).order_by(func.count(UsageLog.id).desc()).limit(10))).all()
    per_day = (await count(select(func.date(UsageLog.created_at), func.count(UsageLog.id))
                           .where(UsageLog.created_at >= since).group_by(func.date(UsageLog.created_at))
                           .order_by(func.date(UsageLog.created_at)))).all()
    return {
        "days": days, "users": users, "new_users": new_users, "playlists": playlists, "saved_to_spotify": saved,
        "by_model": [{"kind": k, "model_id": mid, "requests": n, "input_tokens": int(i or 0), "output_tokens": int(o or 0),
                      "own_key_requests": int(own or 0)} for k, mid, n, i, o, own in by_model],
        "top_users": [{"display_name": d, "email": e, "requests": n} for d, e, n in top_users],
        "per_day": [{"date": str(d), "requests": n} for d, n in per_day],
    }
