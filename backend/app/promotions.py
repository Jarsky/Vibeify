"""Promotions: which one applies to a checkout, how to describe it, and its Stripe coupon and promotion code.

Automatic promotions (no code) are applied by us at checkout. Code promotions live in Stripe as promotion codes,
typed on Stripe's checkout page; Stripe enforces their use limit, expiry and first-time-customer rule.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Plan, Promotion, User
from .services.stripe import Stripe, StripeError

log = logging.getLogger("vibeify.promotions")


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=dt.tzinfo or timezone.utc) if dt else None


def normalised(value):
    """For comparing a submitted value with a stored one (the database may hand back dates without a timezone)."""
    return _aware(value) if isinstance(value, datetime) else value


def normalise_code(code: str | None) -> str | None:
    code = (code or "").strip().upper()
    return code or None


def problem(promo: Promotion, plan: Plan | None, user: User | None, now: datetime | None = None) -> str | None:
    """Why `promo` can't be used for `plan` by `user` (None = it can). `plan`/`user` None skips those checks."""
    now = now or datetime.now(timezone.utc)
    if not promo.active or (promo.starts_at and _aware(promo.starts_at) > now):
        return "That code isn't valid."
    if promo.ends_at and _aware(promo.ends_at) <= now:
        return "That promotion has ended."
    if promo.max_redemptions is not None and promo.redemptions + promo.reserved >= promo.max_redemptions:
        return "That promotion has been fully claimed."
    if plan is not None and (plan.price_cents <= 0 or (promo.plan_ids is not None and plan.id not in promo.plan_ids)):
        return f"That code doesn't apply to the {plan.name} plan."
    if user is not None and promo.first_subscription_only and user.stripe_subscription_id:
        return "That promotion is for first-time subscribers."
    return None


def status(p: Promotion, now: datetime | None = None) -> str:
    """For the admin list: Running, Paused, Scheduled, Ended or Used up."""
    now = now or datetime.now(timezone.utc)
    if not p.active:
        return "Paused"
    if p.starts_at and _aware(p.starts_at) > now:
        return "Scheduled"
    if p.ends_at and _aware(p.ends_at) <= now:
        return "Ended"
    if p.max_redemptions is not None and p.redemptions + p.reserved >= p.max_redemptions:
        return "Used up"
    return "Running"


async def reserve(db: AsyncSession, p: Promotion) -> bool:
    """Hold one use for a checkout that's starting. One UPDATE, so two people can't both take the last use."""
    q = update(Promotion).where(Promotion.id == p.id)
    if p.max_redemptions is not None:
        q = q.where(Promotion.redemptions + Promotion.reserved < Promotion.max_redemptions)
    held = (await db.execute(q.values(reserved=Promotion.reserved + 1))).rowcount == 1
    await db.commit()
    await db.refresh(p)
    return held


async def release(db: AsyncSession, promo_id: str, used: bool) -> None:
    """A held checkout finished: count it as used (paid) or give the use back (abandoned, expired or failed)."""
    values = {"reserved": Promotion.reserved - 1}
    if used:
        values["redemptions"] = Promotion.redemptions + 1
    res = await db.execute(update(Promotion).where(Promotion.id == promo_id, Promotion.reserved > 0).values(**values))
    if used and res.rowcount == 0:   # nothing held (e.g. started before reservations existed): still count the use
        await db.execute(update(Promotion).where(Promotion.id == promo_id).values(redemptions=Promotion.redemptions + 1))


# Checkouts with a promotion close after an hour (Stripe allows 30 min to 24 h), or when the promotion ends,
# so an ended promotion can't be finished later and abandoned checkouts give their use back quickly.
CHECKOUT_WINDOW = timedelta(hours=1)
STRIPE_MIN_WINDOW = timedelta(minutes=31)


def checkout_expiry(p: Promotion, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    end = min(now + CHECKOUT_WINDOW, _aware(p.ends_at) or now + CHECKOUT_WINDOW)
    return int(max(end, now + STRIPE_MIN_WINDOW).timestamp())


def _value(p: Promotion) -> tuple:
    """Rough generosity, to pick between overlapping automatic promotions."""
    months = {"once": 1, "forever": 120}.get(p.duration, p.duration_months or 1)
    return ((p.percent_off or 0) * months + (p.trial_days or 0) * 100 / 30, p.created_at)


async def automatic(db: AsyncSession, plan: Plan, user: User | None) -> Promotion | None:
    rows = (await db.execute(select(Promotion).where(Promotion.code.is_(None), Promotion.active))).scalars().all()
    usable = [p for p in rows if problem(p, plan, user) is None]
    return max(usable, key=_value) if usable else None


async def by_code(db: AsyncSession, code: str) -> Promotion | None:
    code = normalise_code(code)
    if not code:
        return None
    return (await db.execute(select(Promotion).where(func.upper(Promotion.code) == code))).scalar_one_or_none()


def describe(p: Promotion) -> str:
    parts = []
    if p.trial_days:
        parts.append(f"{p.trial_days} days free")
    if p.percent_off:
        off = "Half price" if p.percent_off == 50 else f"{p.percent_off}% off"
        if p.duration == "forever":
            when = "for as long as you stay subscribed"
        elif p.duration == "repeating" and (p.duration_months or 1) > 1:
            when = f"for {p.duration_months} months"
        else:
            when = "for the first payment" if p.trial_days else "for your first payment"
        parts.append(f"{off if not parts else off.lower()} {when}")
    return ", then ".join(parts)


def view(p: Promotion) -> dict:
    return {"id": p.id, "name": p.name, "summary": describe(p), "trial_days": p.trial_days, "percent_off": p.percent_off,
            "duration": p.duration, "duration_months": p.duration_months, "ends_at": p.ends_at,
            "first_subscription_only": p.first_subscription_only, "plan_ids": p.plan_ids, "has_code": p.code is not None}


async def coupon(stripe: Stripe, p: Promotion, products: list[str] | None = None) -> str | None:
    """The Stripe coupon for the discount part (made on first use), or None for a trial-only promotion.
    `products` limits it to those Stripe products (needed for codes, which customers can type on any plan's checkout)."""
    if not p.percent_off:
        return None
    if not p.stripe_coupon_id:
        data = {"percent_off": p.percent_off, "duration": p.duration, "name": p.name[:40], "metadata": {"promotion_id": p.id}}
        if p.duration == "repeating":
            data["duration_in_months"] = p.duration_months or 1
        if products:
            data["applies_to"] = {"products": products}
        p.stripe_coupon_id = (await stripe.create_coupon(data))["id"]
    return p.stripe_coupon_id


# ── code promotions in Stripe ────────────────────────────────────────────────
def code_should_be_live(p: Promotion, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return bool(p.code and p.active and not (p.starts_at and _aware(p.starts_at) > now)
                and not (p.ends_at and _aware(p.ends_at) <= now)
                and (p.max_redemptions is None or p.redemptions < p.max_redemptions))


async def retire_code(stripe: Stripe, p: Promotion) -> None:
    """Switch off the promotion's Stripe code (codes can't be edited, so changes make a new one)."""
    if p.stripe_promotion_code_id:
        try:
            await stripe.update_promotion_code(p.stripe_promotion_code_id, {"active": False})
        except StripeError as e:
            if not e.missing:
                raise
    p.stripe_promotion_code_id, p.stripe_code_active = None, False


async def push_code(db: AsyncSession, stripe: Stripe, p: Promotion) -> None:
    """Create the Stripe promotion code (and its coupon) for a code promotion, replacing any earlier one."""
    await retire_code(stripe, p)
    if not p.code:
        return
    if p.trial_days or not p.percent_off:
        raise StripeError("Stripe codes can only give a discount, not free days. Edit the promotion to fix it.")
    products = None
    if p.plan_ids is not None:
        plans = (await db.execute(select(Plan).where(Plan.id.in_(p.plan_ids)))).scalars().all()
        products = [pl.stripe_product_id for pl in plans if pl.stripe_product_id]
        if not products:
            raise StripeError("None of this promotion's plans are on Stripe yet. Sync your plans to Stripe first.")
    for attempt in range(2):
        try:
            coupon_id = await coupon(stripe, p, products)
            break
        except StripeError as e:
            if attempt or not e.missing:
                raise
            p.stripe_coupon_id = None   # made under other Stripe keys
    live = code_should_be_live(p)
    now = datetime.now(timezone.utc)
    left = p.max_redemptions - p.redemptions if p.max_redemptions is not None else None
    created = await stripe.create_promotion_code({
        "coupon": coupon_id, "code": p.code, "active": live, "metadata": {"promotion_id": p.id},
        "max_redemptions": left if left and left > 0 else None,
        "expires_at": int(_aware(p.ends_at).timestamp()) if p.ends_at and _aware(p.ends_at) > now else None,
        "restrictions": {"first_time_transaction": p.first_subscription_only},
    })
    p.stripe_promotion_code_id, p.stripe_code_active = created["id"], live


async def reconcile_codes(db: AsyncSession, settings: dict) -> None:
    """Switch Stripe codes on when their start date arrives (and off when paused). There's no scheduler, so this
    runs when someone loads the pricing page or starts a checkout. Never fails the request."""
    if not (settings.get("billing_enabled") and settings.get("stripe_secret_key")):
        return
    rows = (await db.execute(select(Promotion).where(Promotion.code.is_not(None)))).scalars().all()
    stale = [p for p in rows if code_should_be_live(p) != p.stripe_code_active or (code_should_be_live(p) and not p.stripe_promotion_code_id)]
    if not stale:
        return
    stripe = Stripe(settings["stripe_secret_key"])
    for p in stale:
        live = code_should_be_live(p)
        try:
            if p.stripe_promotion_code_id:
                await stripe.update_promotion_code(p.stripe_promotion_code_id, {"active": live})
                p.stripe_code_active = live
            elif live:
                await push_code(db, stripe, p)
        except StripeError as e:
            if e.missing:
                p.stripe_promotion_code_id, p.stripe_code_active = None, False   # recreated next time
            log.warning("promotion %s: couldn't update its Stripe code: %s", p.id, e)
    await db.commit()


async def count_code_redemption(db: AsyncSession, session: dict) -> Promotion | None:
    """A completed checkout that used one of our Stripe codes: count it."""
    for d in session.get("discounts") or []:
        code = d.get("promotion_code")
        code_id = code.get("id") if isinstance(code, dict) else code
        if code_id and (p := (await db.execute(select(Promotion).where(Promotion.stripe_promotion_code_id == code_id))).scalar_one_or_none()):
            p.redemptions += 1
            return p
    return None

