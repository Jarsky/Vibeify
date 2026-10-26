"""Unauthenticated site info the frontend needs before anyone signs in."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import security, settings_store
from ..db import get_db
from ..models import User
from ..services.llm.registry import KIND_LABELS
from .auth import spotify_redirect_uri

router = APIRouter(prefix="/api", tags=["public"])


@router.get("/config")
async def site_config(user: User | None = Depends(security.optional_user), db: AsyncSession = Depends(get_db)):
    s = await settings_store.load(db)
    return {
        "site_name": s["site_name"],
        "site_tagline": s["site_tagline"],
        "signup_open": s["signup_open"],
        "sign_in": {
            "spotify_site_app": bool(s["auth_spotify_site_app"] and s["spotify_client_id"]),
            "spotify_own_app": bool(s["auth_spotify_byo"]),
            "google": bool(s["auth_google"] and s["google_client_id"] and s["google_client_secret"]),
            "apple": bool(s["auth_apple"] and settings_store.apple_ready(s)),
            "email": bool(s["auth_email"] and settings_store.email_ready(s)),
        },
        "spotify_redirect_uri": spotify_redirect_uri(),
        "allow_user_llm_keys": s["allow_user_llm_keys"],
        "allow_model_choice": s["allow_model_choice"],
        "community_feed": s["community_feed"],
        "support_enabled": s["support_enabled"],
        "max_playlist_size": s["max_playlist_size"],
        "billing_enabled": s["billing_enabled"],
        "provider_kinds": KIND_LABELS,
        "signed_in": user is not None,
    }


@router.get("/health")
async def health():
    return {"ok": True}
