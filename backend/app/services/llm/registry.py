"""Which models a user may use, dispatch to the right provider, quotas and usage logging."""
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ... import crypto, entitlements
from ...models import LLMModel, LLMProvider, UsageLog, User, UserLLMKey
from . import anthropic_provider, gemini_provider, openai_provider
from .base import LLMError, LLMRequest, LLMResult

KIND_LABELS = {"anthropic": "Claude (Anthropic)", "openai": "OpenAI", "gemini": "Google Gemini",
               "openai_compatible": "OpenAI-compatible"}


@dataclass
class ModelOption:
    id: str            # LLMModel.id, or "own:<kind>" for the user's own key
    label: str
    kind: str
    model_id: str
    own_key: bool
    is_default: bool = False


@dataclass
class ResolvedModel:
    option: ModelOption
    api_key: str | None
    base_url: str | None
    max_output_tokens: int


async def _site_models(db: AsyncSession) -> list[LLMModel]:
    rows = await db.execute(
        select(LLMModel).join(LLMProvider).options(selectinload(LLMModel.provider))
        .where(LLMModel.enabled, LLMProvider.enabled).order_by(LLMModel.sort_order, LLMModel.display_name))
    models = []
    for m in rows.scalars():
        has_key = bool(m.provider.api_key_enc) or m.provider.kind == "openai_compatible"
        if has_key:
            models.append(m)
    return models


async def available_models(db: AsyncSession, user: User, settings: dict) -> list[ModelOption]:
    options = []
    allowed = (await entitlements.for_user(db, user, settings)).allowed_model_ids
    for m in await _site_models(db):
        if allowed is not None and m.id not in allowed:
            continue
        options.append(ModelOption(m.id, m.display_name, m.provider.kind, m.model_id, False, m.is_default))
    if options and not settings.get("allow_model_choice"):   # only the site's preferred model
        options = [next((o for o in options if o.is_default), options[0])]
        options[0].is_default = True
    if settings.get("allow_user_llm_keys"):
        for k in (await db.execute(select(UserLLMKey).where(UserLLMKey.user_id == user.id))).scalars():
            options.append(ModelOption(f"own:{k.kind}", f"{k.model_id} (your {KIND_LABELS.get(k.kind, k.kind)} key)",
                                       k.kind, k.model_id, True))
    return options


async def resolve(db: AsyncSession, user: User, settings: dict, option_id: str | None) -> ResolvedModel:
    options = await available_models(db, user, settings)
    if not options:
        raise HTTPException(503, "No AI models are set up yet. An admin needs to add one in the admin panel.")
    chosen = next((o for o in options if o.id == option_id), None) if option_id else None
    if chosen is None:
        chosen = next((o for o in options if o.is_default), options[0])
    if chosen.own_key:
        key = (await db.execute(select(UserLLMKey).where(UserLLMKey.user_id == user.id,
                                                         UserLLMKey.kind == chosen.kind))).scalar_one()
        return ResolvedModel(chosen, crypto.decrypt(key.api_key_enc), key.base_url, 16000)
    m = (await db.execute(select(LLMModel).options(selectinload(LLMModel.provider)).where(LLMModel.id == chosen.id))).scalar_one()
    return ResolvedModel(chosen, crypto.decrypt(m.provider.api_key_enc), m.provider.base_url, m.max_output_tokens)


async def complete_json(resolved: ResolvedModel, system: str, messages: list[dict], schema: dict) -> LLMResult:
    req = LLMRequest(model_id=resolved.option.model_id, api_key=resolved.api_key, base_url=resolved.base_url,
                     system=system, messages=messages, schema=schema, max_output_tokens=resolved.max_output_tokens)
    kind = resolved.option.kind
    if kind == "anthropic":
        return await anthropic_provider.complete_json(req)
    if kind == "openai":
        return await openai_provider.complete_json(req)
    if kind == "openai_compatible":
        return await openai_provider.complete_json(req, compatible=True)
    if kind == "gemini":
        return await gemini_provider.complete_json(req)
    raise LLMError(f"Unknown provider type {kind}")


async def log_usage(db: AsyncSession, user: User, resolved: ResolvedModel, result: LLMResult, generation_id: str | None) -> None:
    db.add(UsageLog(user_id=user.id, generation_id=generation_id, provider_kind=resolved.option.kind,
                    model_id=resolved.option.model_id, input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens, own_key=resolved.option.own_key))


async def list_provider_models(kind: str, api_key: str | None, base_url: str | None) -> list[tuple[str, str]]:
    if kind == "anthropic":
        return await anthropic_provider.list_models(api_key or "", base_url)
    if kind in ("openai", "openai_compatible"):
        return await openai_provider.list_models(api_key, base_url)
    if kind == "gemini":
        return await gemini_provider.list_models(api_key or "")
    raise LLMError(f"Unknown provider type {kind}")
