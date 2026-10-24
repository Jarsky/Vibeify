"""OpenAI, and OpenAI-compatible services (OpenRouter, Ollama, LM Studio, vLLM…) via the openai SDK."""
import json

import openai

from .base import OUT_OF_CREDIT, LLMError, LLMRequest, LLMResult


def _client(req_key: str | None, base_url: str | None) -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(api_key=req_key or "not-needed", base_url=base_url or None, timeout=180.0, max_retries=2)


async def complete_json(req: LLMRequest, *, compatible: bool = False) -> LLMResult:
    messages = [{"role": "system", "content": req.system}, *req.messages]
    strict_format = {"type": "json_schema", "json_schema": {"name": "playlist", "schema": req.schema, "strict": True}}
    # Newer OpenAI models take max_completion_tokens; many compatible servers only know max_tokens
    limit = {"max_tokens": req.max_output_tokens} if compatible else {"max_completion_tokens": req.max_output_tokens}
    notes: list[str] = []
    try:
        async with _client(req.api_key, req.base_url) as client:
            try:
                response = await client.chat.completions.create(model=req.model_id, messages=messages,
                                                                response_format=strict_format, **limit)
            except openai.BadRequestError:
                if not compatible:
                    raise
                # Server doesn't support JSON schemas: fall back to JSON mode with the schema in the prompt
                notes.append("json_object fallback")
                messages[0]["content"] += "\n\nReply with a single JSON object matching this JSON Schema:\n" + json.dumps(req.schema)
                response = await client.chat.completions.create(model=req.model_id, messages=messages,
                                                                response_format={"type": "json_object"}, **limit)
    except openai.AuthenticationError as e:
        raise LLMError("The API key for this model was rejected.") from e
    except openai.PermissionDeniedError as e:
        raise LLMError("This API key isn't allowed to use that model.") from e
    except openai.NotFoundError as e:
        raise LLMError(f"The model '{req.model_id}' wasn't found.") from e
    except openai.RateLimitError as e:
        if getattr(e, "code", None) == "insufficient_quota":
            raise LLMError(OUT_OF_CREDIT, status=424) from e
        raise LLMError("The model provider is rate-limiting requests. Try again in a minute.", retryable=True, status=503) from e
    except openai.BadRequestError as e:
        raise LLMError(f"The model provider rejected the request: {e.message}") from e
    except openai.APIStatusError as e:
        retry = e.status_code >= 500
        raise LLMError("The model provider had a problem. Try again shortly." if retry else f"Model error: {e.message}",
                       retryable=retry, status=503 if retry else 424) from e
    except openai.APIConnectionError as e:
        raise LLMError("Couldn't reach the model provider. Try again shortly.", retryable=True, status=503) from e

    choice = response.choices[0]
    if getattr(choice.message, "refusal", None):
        raise LLMError("The model declined this request. Try rephrasing it.", status=422)
    if choice.finish_reason == "length":
        raise LLMError("The model's answer was cut off. Ask for fewer songs or raise the model's output limit.")
    try:
        data = json.loads(choice.message.content or "")
    except json.JSONDecodeError as e:
        raise LLMError("The model returned an unreadable answer. Try again.", retryable=True) from e
    usage = response.usage
    return LLMResult(data=data, input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                     output_tokens=getattr(usage, "completion_tokens", 0) or 0, raw_model=response.model or "", notes=notes)


async def list_models(api_key: str | None, base_url: str | None) -> list[tuple[str, str]]:
    async with _client(api_key, base_url) as client:
        return sorted([(m.id, m.id) async for m in client.models.list()])
