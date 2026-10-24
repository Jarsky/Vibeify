"""Admin: membership plans (synced to Stripe products/prices) and the Stripe connection."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit, security, settings_store
from ..config import get_config
from ..db import get_db
from ..models import Plan, User
from ..services.stripe import Stripe, StripeError
from .billing import plan_view

router = APIRouter(prefix="/api/admin", tags=["admin"],
                   dependencies=[Depends(security.csrf_guard), Depends(security.admin_user)])

LIMIT = Field(None, ge=0)


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field("", max_length=500)
    perks: list[str] = Field(default_factory=list, max_length=12)
    price_cents: int = Field(0, ge=0, le=10_000_000)
    currency: str = Field("", max_length=3)
    interval: str = Field("month", pattern="^(month|year)$")
    is_default: bool = False
    active: bool = True
    highlight: bool = False
    sort_order: int = 0
    daily_generation_limit: int | None = LIMIT
    daily_token_limit: int | None = LIMIT
    monthly_token_limit: int | None = LIMIT
    max_playlist_size: int | None = Field(None, ge=5, le=100)
    allow_edit_playlists: bool = True
    allow_playlist_seeds: bool = True
    allowed_model_ids: list[str] | None = None


async def _admin_view(db: AsyncSession, p: Plan, settings: dict) -> dict:
    members = (await db.execute(select(func.count(User.id)).where(User.plan_id == p.id))).scalar_one()
    return {**plan_view(p, settings), "active": p.active, "sort_order": p.sort_order, "members": members,
            "stripe_price_id": p.stripe_price_id, "stripe_product_id": p.stripe_product_id,
            "raw": {k: getattr(p, k) for k in ("daily_generation_limit", "daily_token_limit", "monthly_token_limit",
                                                "max_playlist_size", "allowed_model_ids")}}


async def _sync(p: Plan, settings: dict, price_changed: bool) -> str | None:
    """Create/update the Stripe product and price for a paid plan. Returns a warning instead of failing the save."""
    if p.price_cents <= 0:
        return None
    if not settings["stripe_secret_key"]:
        return "Saved, but not on sale yet: add your Stripe secret key under Billing to sell this plan."
    stripe = Stripe(settings["stripe_secret_key"])
    try:
        if not p.stripe_product_id:
            p.stripe_product_id = (await stripe.create_product(p.name, p.description, p.id))["id"]
        else:
            await stripe.update_product(p.stripe_product_id, p.name, p.description)
        if price_changed or not p.stripe_price_id:
            old = p.stripe_price_id
            p.stripe_price_id = (await stripe.create_price(p.stripe_product_id, p.price_cents, p.currency, p.interval, p.id))["id"]
            if old:   # Stripe prices can't change; existing subscribers stay on the old price until they switch
                await stripe.archive_price(old)
    except StripeError as e:
        return f"Saved, but Stripe said: {e}"
    return None


PLAN_FIELDS = ["name", "price_cents", "currency", "interval", "is_default", "active", "daily_generation_limit", "daily_token_limit", "monthly_token_limit", "max_playlist_size", "allow_edit_playlists", "allow_playlist_seeds", "allowed_model_ids"]


@router.get("/plans")
async def list_plans(db: AsyncSession = Depends(get_db)):
    settings = await settings_store.load(db)
    rows = (await db.execute(select(Plan).order_by(Plan.sort_order, Plan.price_cents))).scalars().all()
    return [await _admin_view(db, p, settings) for p in rows]


async def _only_default(db: AsyncSession, keep: Plan) -> None:
    await db.execute(update(Plan).where(Plan.id != keep.id).values(is_default=False))


@router.post("/plans")
async def create_plan(body: PlanIn, request: Request, me: User = Depends(security.admin_user), db: AsyncSession = Depends(get_db)):
    settings = await settings_store.load(db)
    data = body.model_dump()
    data["currency"] = (data["currency"] or settings["billing_currency"]).lower()
    data["perks"] = [x.strip() for x in data["perks"] if x.strip()]
    p = Plan(**data)
    db.add(p)
    await db.flush()
    if p.is_default:
        await _only_default(db, p)
    warning = await _sync(p, settings, price_changed=True)
    audit.record(db, "admin.plan.create", request=request, actor=me, target_type="plan", target_id=p.id, target_label=p.name,
                 price_cents=p.price_cents, currency=p.currency, interval=p.interval)
    await db.commit()
    return {"plan": await _admin_view(db, p, settings), "warning": warning}


@router.patch("/plans/{plan_id}")
async def update_plan(plan_id: str, body: PlanIn, request: Request, me: User = Depends(security.admin_user), db: AsyncSession = Depends(get_db)):
    settings = await settings_store.load(db)
    p = await db.get(Plan, plan_id)
    if not p:
        raise HTTPException(404, "Plan not found.")
    data = body.model_dump()
    data["currency"] = (data["currency"] or p.currency).lower()
    data["perks"] = [x.strip() for x in data["perks"] if x.strip()]
    price_changed = (data["price_cents"], data["currency"], data["interval"]) != (p.price_cents, p.currency, p.interval)
    before = audit.snapshot(p, PLAN_FIELDS)
    for k, v in data.items():
        setattr(p, k, v)
    if p.is_default:
        await _only_default(db, p)
    warning = await _sync(p, settings, price_changed)
    if changes := audit.diff(p, PLAN_FIELDS, before):
        audit.record(db, "admin.plan.update", request=request, actor=me, target_type="plan", target_id=p.id, target_label=p.name,
                     changes=changes)
    await db.commit()
    return {"plan": await _admin_view(db, p, settings), "warning": warning}


@router.delete("/plans/{plan_id}")
async def delete_plan(plan_id: str, request: Request, me: User = Depends(security.admin_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Plan, plan_id)
    if not p:
        return {"ok": True}
    paying = (await db.execute(select(func.count(User.id)).where(User.plan_id == p.id, User.plan_source == "stripe"))).scalar_one()
    if paying:
        raise HTTPException(400, f"{paying} member(s) pay for this plan. Hide it from the pricing page instead (untick “Offered”).")
    audit.record(db, "admin.plan.delete", request=request, actor=me, target_type="plan", target_id=p.id, target_label=p.name)
    await db.delete(p)
    await db.commit()
    return {"ok": True}


@router.post("/billing/test")
async def test_stripe(db: AsyncSession = Depends(get_db)):
    settings = await settings_store.load(db)
    try:
        acct = await Stripe(settings["stripe_secret_key"]).account()
    except StripeError as e:
        raise HTTPException(400, str(e)) from e
    name = (acct.get("settings") or {}).get("dashboard", {}).get("display_name") or acct.get("business_profile", {}).get("name") or acct.get("id")
    return {"ok": True, "account": name, "live": not settings["stripe_secret_key"].startswith(("sk_test_", "rk_test_")),
            "webhook_url": f"{get_config().public_url}/api/billing/webhook"}


@router.post("/plans/resync")
async def resync(db: AsyncSession = Depends(get_db)):
    """Push every paid plan to Stripe (e.g. after adding the key, or switching from test to live keys)."""
    settings = await settings_store.load(db)
    warnings = []
    for p in (await db.execute(select(Plan).where(Plan.price_cents > 0))).scalars():
        if (w := await _sync(p, settings, price_changed=False)):
            warnings.append(f"{p.name}: {w}")
    await db.commit()
    return {"ok": not warnings, "warnings": warnings}
