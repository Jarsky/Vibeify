"""Site settings edited in the admin panel. Defaults live here; the database stores overrides.

Secret settings are encrypted at rest and never returned to the browser (only whether they are set).
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import crypto
from .models import Setting

DEFAULTS: dict[str, Any] = {
    "site_name": "Vibeify",
    "site_tagline": "Describe the vibe. Get the playlist.",
    "signup_open": True,
    # sign-in methods
    "auth_spotify_site_app": True,      # "Continue with Spotify" through the site's own Spotify app
    "auth_spotify_byo": True,           # users may connect through their own Spotify app (Client ID)
    "auth_google": False,
    "auth_email": False,
    # credentials
    "spotify_client_id": "",
    "spotify_client_secret": "",
    "google_client_id": "",
    "google_client_secret": "",
    # email
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_username": "",
    "smtp_password": "",
    "smtp_from": "",
    "smtp_security": "starttls",        # starttls | ssl | none
    # limits
    "default_daily_generations": 25,    # LLM requests per user per day (generation + each refinement)
    "default_daily_tokens": 0,          # 0 = no daily token cap
    "default_monthly_tokens": 1_000_000,
    "allow_user_llm_keys": True,
    "allow_model_choice": False,        # off: everyone gets the default site model (shown, not selectable)
    "max_playlist_size": 50,
    # discover page & records
    "community_feed": True,             # anonymous feed of playlists users chose to share
    "audit_retention_days": 365,        # 0 = keep forever
    # support
    "support_enabled": True,
    "support_email": "",                # new requests are emailed here (needs SMTP); blank = admin panel only
    # memberships (Stripe)
    "billing_enabled": False,
    "billing_currency": "usd",
    "stripe_secret_key": "",
    "stripe_webhook_secret": "",
}
SECRET_KEYS = {"spotify_client_secret", "google_client_secret", "smtp_password", "stripe_secret_key", "stripe_webhook_secret"}


async def load(db: AsyncSession) -> dict[str, Any]:
    values = dict(DEFAULTS)
    for row in (await db.execute(select(Setting))).scalars():
        if row.key not in DEFAULTS:
            continue
        if row.key in SECRET_KEYS:
            values[row.key] = crypto.decrypt((row.value or {}).get("enc")) or ""
        else:
            values[row.key] = row.value
    return values


async def save(db: AsyncSession, updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if key not in DEFAULTS:
            raise ValueError(f"unknown setting {key}")
        stored = {"enc": crypto.encrypt(value)} if key in SECRET_KEYS and value else ({} if key in SECRET_KEYS else value)
        row = await db.get(Setting, key)
        if row:
            row.value = stored
        else:
            db.add(Setting(key=key, value=stored))
    await db.commit()


def public_view(values: dict[str, Any]) -> dict[str, Any]:
    """Settings safe for the admin UI: secrets replaced by whether they're set."""
    return {k: (bool(v) if k in SECRET_KEYS else v) for k, v in values.items()}


def email_ready(values: dict[str, Any]) -> bool:
    return bool(values["smtp_host"] and values["smtp_from"])
