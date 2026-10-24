"""FastAPI application: API routers, the built frontend, and first-start seeding from the environment."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select

from . import audit, crypto, settings_store
from .config import get_config
from .db import sessionmaker
from .models import LLMModel, LLMProvider
from .routers import admin, admin_billing, auth, billing, discover, generations, library, me, public, support
from .security import cleanup_expired
from .services.llm import anthropic_provider

log = logging.getLogger("vibeify")


async def seed_from_env() -> None:
    """Copy optional env seeds into the database once; after that the admin panel owns them."""
    cfg = get_config()
    async with sessionmaker()() as db:
        settings = await settings_store.load(db)
        updates = {}
        if cfg.seed_spotify_client_id and not settings["spotify_client_id"]:
            updates["spotify_client_id"] = cfg.seed_spotify_client_id
        if cfg.seed_spotify_client_secret and not settings["spotify_client_secret"]:
            updates["spotify_client_secret"] = cfg.seed_spotify_client_secret
        if updates:
            await settings_store.save(db, updates)
            log.info("Seeded settings from environment: %s", ", ".join(updates))

        if (await db.execute(select(LLMProvider.id).limit(1))).first() is None:
            seeds = [("Claude", "anthropic", cfg.seed_anthropic_api_key),
                     ("OpenAI", "openai", cfg.seed_openai_api_key),
                     ("Gemini", "gemini", cfg.seed_gemini_api_key)]
            first_model = True
            for name, kind, key in seeds:
                if not key:
                    continue
                p = LLMProvider(name=name, kind=kind, api_key_enc=crypto.encrypt(key), enabled=True)
                db.add(p)
                if kind == "anthropic":
                    for i, (mid, label) in enumerate(anthropic_provider.DEFAULT_MODELS):
                        db.add(LLMModel(provider=p, model_id=mid, display_name=label, sort_order=i,
                                        is_default=first_model and i == 0))
                    first_model = False
                log.info("Seeded %s provider from environment (add models in the admin panel)", name)
            await db.commit()
        await cleanup_expired(db)
        await audit.prune(db, settings["audit_retention_days"])


@asynccontextmanager
async def lifespan(_: FastAPI):
    await seed_from_env()
    yield


app = FastAPI(title="Vibeify", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")
for r in (public.router, auth.router, me.router, library.router, generations.router, discover.router, billing.router,
          support.router, admin.router, admin_billing.router, support.admin_router):
    app.include_router(r)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# ── built frontend (single-page app) ─────────────────────────────────────────
STATIC = Path(get_config().static_dir).resolve()


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    file = (STATIC / path).resolve()
    if path and file.is_file() and file.is_relative_to(STATIC):
        headers = {"Cache-Control": "public, max-age=31536000, immutable"} if path.startswith("assets/") else {}
        return FileResponse(file, headers=headers)
    if path.startswith("assets/") or "." in path.rsplit("/", 1)[-1]:
        return JSONResponse({"detail": "Not found"}, status_code=404, headers={"Cache-Control": "no-store"})
    index = STATIC / "index.html"
    if index.is_file():
        # no-store, not no-cache: Back/Forward reuse a cached page without revalidating, and an index.html from before a
        # deploy points at asset files that no longer exist (a blank page)
        return FileResponse(index, headers={"Cache-Control": "no-store"})
    return JSONResponse({"detail": "Frontend not built"}, status_code=404)
