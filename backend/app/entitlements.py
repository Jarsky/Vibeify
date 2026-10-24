"""What a user may do: limits and features from their per-user overrides, then their plan, then the site defaults."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Plan, UsageLog, User


@dataclass
class Entitlements:
    plan: Plan | None
    daily_requests: int        # 0 = unlimited
    daily_tokens: int
    monthly_tokens: int
    max_playlist_size: int
    edit_playlists: bool
    playlist_seeds: bool
    allowed_model_ids: list[str] | None   # None = every enabled model


async def user_plan(db: AsyncSession, user: User) -> Plan | None:
    if user.plan_id:
        plan = await db.get(Plan, user.plan_id)
        if plan:
            return plan
    return (await db.execute(select(Plan).where(Plan.is_default).limit(1))).scalar_one_or_none()


async def for_user(db: AsyncSession, user: User, settings: dict) -> Entitlements:
    plan = await user_plan(db, user)

    def pick(field: str, default_key: str) -> int:
        own = getattr(user, field, None)
        if own is not None:
            return own
        if plan is not None and getattr(plan, field) is not None:
            return getattr(plan, field)
        return int(settings[default_key] or 0)

    return Entitlements(
        plan=plan,
        daily_requests=pick("daily_generation_limit", "default_daily_generations"),
        daily_tokens=pick("daily_token_limit", "default_daily_tokens"),
        monthly_tokens=pick("monthly_token_limit", "default_monthly_tokens"),
        max_playlist_size=min(100, plan.max_playlist_size if plan and plan.max_playlist_size else int(settings["max_playlist_size"])),
        edit_playlists=plan.allow_edit_playlists if plan else True,
        playlist_seeds=plan.allow_playlist_seeds if plan else True,
        allowed_model_ids=user.allowed_model_ids if user.allowed_model_ids is not None else (plan.allowed_model_ids if plan else None),
    )


def month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def usage(db: AsyncSession, user: User) -> dict:
    """Use of the site's AI keys (requests on a user's own key aren't counted)."""
    now = datetime.now(timezone.utc)
    base = (UsageLog.user_id == user.id, UsageLog.own_key.is_(False))
    tokens = func.coalesce(func.sum(UsageLog.input_tokens + UsageLog.output_tokens), 0)
    day = (await db.execute(select(func.count(UsageLog.id), tokens).where(*base, UsageLog.created_at >= now - timedelta(days=1)))).one()
    month = (await db.execute(select(tokens).where(*base, UsageLog.created_at >= month_start(now)))).scalar_one()
    return {"requests_today": int(day[0]), "tokens_today": int(day[1]), "tokens_this_month": int(month)}


def upgrade_hint(settings: dict) -> str:
    return " Upgrade your plan for more." if settings.get("billing_enabled") else ""


async def check_quota(db: AsyncSession, user: User, settings: dict) -> None:
    ent = await for_user(db, user, settings)
    used = await usage(db, user)
    more = upgrade_hint(settings) + (" Or add your own API key in Account settings." if settings.get("allow_user_llm_keys") else "")
    if ent.daily_requests and used["requests_today"] >= ent.daily_requests:
        raise HTTPException(429, f"You've reached your limit of {ent.daily_requests} AI requests in 24 hours.{more}")
    if ent.daily_tokens and used["tokens_today"] >= ent.daily_tokens:
        raise HTTPException(429, f"You've used your daily AI allowance. It frees up over the next 24 hours.{more}")
    if ent.monthly_tokens and used["tokens_this_month"] >= ent.monthly_tokens:
        raise HTTPException(429, f"You've used this month's AI allowance.{more}")
