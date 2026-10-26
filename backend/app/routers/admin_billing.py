"""Admin: membership plans (synced to Stripe products/prices), promotions and the Stripe connection."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit, promotions, security, settings_store
from ..config import get_config
from ..db import get_db
from ..models import LLMModel, Plan, Promotion, User
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
    default_model_id: str | None = None
    allow_model_choice: bool | None = None


async def _check_models(db: AsyncSession, body: PlanIn) -> None:
    if body.default_model_id:
        if await db.get(LLMModel, body.default_model_id) is None:
            raise HTTPException(400, "That default model doesn't exist any more.")
        if body.allowed_model_ids is not None and body.default_model_id not in body.allowed_model_ids:
            raise HTTPException(400, "The plan's default model must be one of the models it allows.")


async def _admin_view(db: AsyncSession, p: Plan, settings: dict) -> dict:
    members = (await db.execute(select(func.count(User.id)).where(User.plan_id == p.id))).scalar_one()
    return {**plan_view(p, settings), "active": p.active, "sort_order": p.sort_order, "members": members,
            "stripe_price_id": p.stripe_price_id, "stripe_product_id": p.stripe_product_id,
            "raw": {k: getattr(p, k) for k in ("daily_generation_limit", "daily_token_limit", "monthly_token_limit",
                                                "max_playlist_size", "allowed_model_ids", "default_model_id",
                                                "allow_model_choice")}}


async def _sync(p: Plan, settings: dict, price_changed: bool) -> str | None:
    """Create/update the Stripe product and price for a paid plan. Returns a warning instead of failing the save."""
    if p.price_cents <= 0:
        return None
    if not settings["stripe_secret_key"]:
        return "Saved, but not on sale yet: add your Stripe secret key under Billing to sell this plan."
    stripe = Stripe(settings["stripe_secret_key"])
    try:
        if p.stripe_product_id:
            try:
                await stripe.update_product(p.stripe_product_id, p.name, p.description)
            except StripeError as e:
                if not e.missing:
                    raise
                # saved under other Stripe keys (test vs live, or another account): start fresh in this one
                p.stripe_product_id = p.stripe_price_id = None
        if not p.stripe_product_id:
            p.stripe_product_id = (await stripe.create_product(p.name, p.description, p.id))["id"]
        if price_changed or not p.stripe_price_id:
            old = p.stripe_price_id
            p.stripe_price_id = (await stripe.create_price(p.stripe_product_id, p.price_cents, p.currency, p.interval, p.id))["id"]
            if old:   # Stripe prices can't change; existing subscribers stay on the old price until they switch
                try:
                    await stripe.archive_price(old)
                except StripeError as e:
                    if not e.missing:
                        raise
    except StripeError as e:
        return f"Saved, but Stripe said: {e}"
    return None


PLAN_FIELDS = ["name", "price_cents", "currency", "interval", "is_default", "active", "daily_generation_limit", "daily_token_limit", "monthly_token_limit", "max_playlist_size", "allow_edit_playlists", "allow_playlist_seeds", "allowed_model_ids", "default_model_id", "allow_model_choice"]


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
    await _check_models(db, body)
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
    await _check_models(db, body)
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
    for promo in (await db.execute(select(Promotion).where(Promotion.code.is_not(None)))).scalars().all():
        if (w := await _push_code(db, promo)):
            warnings.append(f"Promotion {promo.name}: {w}")
    await db.commit()
    return {"ok": not warnings, "warnings": warnings}


# ── promotions ───────────────────────────────────────────────────────────────
class PromotionIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    code: str | None = Field(None, max_length=40, pattern=r"^\s*[A-Za-z0-9_-]*\s*$")
    plan_ids: list[str] | None = None
    trial_days: int | None = Field(None, ge=1, le=730)
    percent_off: int | None = Field(None, ge=1, le=100)
    duration: str = Field("once", pattern="^(once|repeating|forever)$")
    duration_months: int | None = Field(None, ge=1, le=36)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_redemptions: int | None = Field(None, ge=1)
    first_subscription_only: bool = True
    active: bool = True


PROMO_FIELDS = ["name", "code", "plan_ids", "trial_days", "percent_off", "duration", "duration_months", "starts_at", "ends_at",
                "max_redemptions", "first_subscription_only", "active"]
COUPON_TERMS = ("percent_off", "duration", "duration_months", "name")   # a Stripe coupon can't change these
# nor can a Stripe promotion code: changing any of these makes a new code (and the old one is switched off)
CODE_TERMS = (*COUPON_TERMS, "code", "plan_ids", "max_redemptions", "ends_at", "first_subscription_only")


def _promo_admin_view(p: Promotion, warning: str | None = None) -> dict:
    return {**promotions.view(p), "code": p.code, "starts_at": p.starts_at, "max_redemptions": p.max_redemptions,
            "redemptions": p.redemptions, "reserved": p.reserved, "active": p.active, "status": promotions.status(p),
            "on_stripe": bool(p.stripe_promotion_code_id), "warning": warning}


async def _push_code(db: AsyncSession, p: Promotion) -> str | None:
    """Put a code promotion on Stripe (or take a former one off). Returns a warning instead of failing the save."""
    settings = await settings_store.load(db)
    if not settings["stripe_secret_key"]:
        return "Saved, but the code won't work until your Stripe secret key is added under Billing." if p.code else None
    try:
        stripe = Stripe(settings["stripe_secret_key"])
        if p.code:
            await promotions.push_code(db, stripe, p)
        else:
            await promotions.retire_code(stripe, p)
    except StripeError as e:
        return f"Saved, but Stripe said: {e}"
    return None


async def _promo_data(db: AsyncSession, body: PromotionIn, current: Promotion | None) -> dict:
    data = body.model_dump()
    data["code"] = promotions.normalise_code(data["code"])
    if not data["trial_days"] and not data["percent_off"]:
        raise HTTPException(400, "Give the promotion free days, a discount, or both.")
    if data["code"] and data["trial_days"]:
        raise HTTPException(400, "Codes are typed on Stripe's checkout page, and Stripe codes can't give free days. "
                                 "Use a discount for the code, or leave the code blank for an automatic free trial.")
    if data["duration"] == "repeating" and not data["duration_months"]:
        raise HTTPException(400, "Say how many months the discount lasts.")
    if data["duration"] != "repeating":
        data["duration_months"] = None
    if data["starts_at"] and data["ends_at"] and data["ends_at"] <= data["starts_at"]:
        raise HTTPException(400, "The end date must be after the start date.")
    if data["code"]:
        clash = await promotions.by_code(db, data["code"])
        if clash and (current is None or clash.id != current.id):
            raise HTTPException(400, f"Another promotion already uses the code {data['code']}.")
    return data


@router.get("/promotions")
async def list_promotions(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Promotion).order_by(Promotion.created_at.desc()))).scalars().all()
    return [_promo_admin_view(p) for p in rows]


@router.post("/promotions")
async def create_promotion(body: PromotionIn, request: Request, me: User = Depends(security.admin_user),
                           db: AsyncSession = Depends(get_db)):
    p = Promotion(**await _promo_data(db, body, None))
    db.add(p)
    await db.flush()
    warning = await _push_code(db, p) if p.code else None
    audit.record(db, "admin.promotion.create", request=request, actor=me, target_type="promotion", target_id=p.id,
                 target_label=p.name, summary=promotions.describe(p), code=p.code)
    await db.commit()
    return _promo_admin_view(p, warning)


@router.patch("/promotions/{promo_id}")
async def update_promotion(promo_id: str, body: PromotionIn, request: Request, me: User = Depends(security.admin_user),
                           db: AsyncSession = Depends(get_db)):
    p = await db.get(Promotion, promo_id)
    if not p:
        raise HTTPException(404, "Promotion not found.")
    data = await _promo_data(db, body, p)
    before = audit.snapshot(p, PROMO_FIELDS)
    changed = lambda k: promotions.normalised(data[k]) != promotions.normalised(getattr(p, k))  # noqa: E731
    new_code = (data["code"] or p.code) and any(changed(k) for k in CODE_TERMS)
    if any(changed(k) for k in COUPON_TERMS) or (data["code"] and changed("plan_ids")):
        p.stripe_coupon_id = None   # new terms need a new coupon; people already subscribed keep the old one
    for k, v in data.items():
        setattr(p, k, v)
    warning = await _push_code(db, p) if new_code else None
    if changes := audit.diff(p, PROMO_FIELDS, before):
        audit.record(db, "admin.promotion.update", request=request, actor=me, target_type="promotion", target_id=p.id,
                     target_label=p.name, changes=jsonable_encoder(changes))
    await db.commit()
    if not new_code:   # paused/resumed or new dates: just switch the Stripe code on or off
        await promotions.reconcile_codes(db, await settings_store.load(db))
    return _promo_admin_view(p, warning)


@router.delete("/promotions/{promo_id}")
async def delete_promotion(promo_id: str, request: Request, me: User = Depends(security.admin_user),
                           db: AsyncSession = Depends(get_db)):
    p = await db.get(Promotion, promo_id)
    if p:
        settings = await settings_store.load(db)
        if p.stripe_promotion_code_id and settings["stripe_secret_key"]:
            try:
                await promotions.retire_code(Stripe(settings["stripe_secret_key"]), p)
            except StripeError as e:
                raise HTTPException(424, f"Couldn't switch the code off in Stripe, so the promotion wasn't deleted: {e}") from e
        audit.record(db, "admin.promotion.delete", request=request, actor=me, target_type="promotion", target_id=p.id,
                     target_label=p.name)
        await db.delete(p)
        await db.commit()
    return {"ok": True}
