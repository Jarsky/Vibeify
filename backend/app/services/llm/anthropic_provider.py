"""Claude via the official Anthropic Python SDK (anthropic 2.x).

Structured output uses output_config.format (JSON schema), so the first text block is valid JSON.
Current Claude models think adaptively; effort is set explicitly where the model supports it.
For the models that support it, the server-side refusal fallback (fallbacks="default") is enabled so a
policy decline is retried on a suitable model inside the same request.
"""
import json
import re

import anthropic

from .base import OUT_OF_CREDIT, LLMError, LLMRequest, LLMResult

# Models that accept output_config.effort (older ones like Haiku 4.5 / Sonnet 4.5 reject it)
_EFFORT_MODELS = re.compile(r"^claude-(opus|sonnet|haiku|fable|mythos)-(5|[6-9])|^claude-opus-4-[5-9]|^claude-sonnet-4-6")
# Models that accept the "default" server-side fallback form on the Claude API
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

DEFAULT_MODELS = [   # seeded when an Anthropic provider is created
    ("claude-opus-5-5", "Claude Opus 5.5"),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
    ("claude-haiku-5-5", "Claude Haiku 5.5"),
]


def _client(req: LLMRequest) -> anthropic.AsyncAnthropic:
    kwargs = {"api_key": req.api_key, "timeout": 180.0, "max_retries": 2}
    if req.base_url:
        kwargs["base_url"] = req.base_url
    return anthropic.AsyncAnthropic(**kwargs)


async def complete_json(req: LLMRequest) -> LLMResult:
    params: dict = {
        "model": req.model_id,
        "max_tokens": req.max_output_tokens,
        "system": req.system,   # far below the minimum cacheable prefix, so no cache_control
        "messages": req.messages,
        "output_config": {"format": {"type": "json_schema", "schema": req.schema}},
    }
    if _EFFORT_MODELS.match(req.model_id):
        params["output_config"]["effort"] = "medium"   # picking songs is moderate work; set explicitly

    use_fallback = req.model_id in _FALLBACK_MODELS and not req.base_url
    try:
        async with _client(req) as client:
            if use_fallback:
                response = await client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
            else:
                response = await client.messages.create(**params)
    except anthropic.AuthenticationError as e:
        raise LLMError("The Claude API key was rejected. Check it in the admin panel or your account settings.", status=424) from e
    except anthropic.PermissionDeniedError as e:
        raise LLMError("This Claude API key isn't allowed to use that model.", status=424) from e
    except anthropic.NotFoundError as e:
        raise LLMError(f"Claude doesn't recognise the model '{req.model_id}'.", status=424) from e
    except anthropic.RateLimitError as e:
        raise LLMError("Claude is rate-limiting requests right now. Try again in a minute.", retryable=True, status=503) from e
    except anthropic.BadRequestError as e:
        if "credit balance" in str(e.message).lower():
            raise LLMError(OUT_OF_CREDIT, status=424) from e
        raise LLMError(f"Claude rejected the request: {e.message}", status=424) from e
    except anthropic.APIStatusError as e:
        retry = e.status_code >= 500
        raise LLMError("Claude had a problem answering. Try again shortly." if retry else f"Claude error: {e.message}",
                       retryable=retry, status=503 if retry else 424) from e
    except anthropic.APIConnectionError as e:   # includes timeouts
        raise LLMError("Couldn't reach Claude. Try again shortly.", retryable=True, status=503) from e

    if response.stop_reason == "refusal":
        raise LLMError("The model declined this request. Try rephrasing it.", status=422)
    if response.stop_reason == "max_tokens":
        raise LLMError("The model's answer was cut off. Ask for fewer songs or raise the model's output limit.", status=424)
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError("The model returned an unreadable answer. Try again.", retryable=True) from e
    return LLMResult(data=data, input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens,
                     raw_model=response.model)


async def list_models(api_key: str, base_url: str | None) -> list[tuple[str, str]]:
    kwargs = {"api_key": api_key, "timeout": 30.0}
    if base_url:
        kwargs["base_url"] = base_url
    async with anthropic.AsyncAnthropic(**kwargs) as client:
        return [(m.id, m.display_name) async for m in client.models.list()]
