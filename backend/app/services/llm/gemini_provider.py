"""Google Gemini via the google-genai SDK."""
import json

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from .base import LLMError, LLMRequest, LLMResult


async def complete_json(req: LLMRequest) -> LLMResult:
    client = genai.Client(api_key=req.api_key)
    contents = [types.Content(role="model" if m["role"] == "assistant" else "user", parts=[types.Part(text=m["content"])])
                for m in req.messages]
    config = types.GenerateContentConfig(
        system_instruction=req.system,
        response_mime_type="application/json",
        response_json_schema=req.schema,
        max_output_tokens=req.max_output_tokens,
    )
    try:
        response = await client.aio.models.generate_content(model=req.model_id, contents=contents, config=config)
    except genai_errors.ClientError as e:
        if e.code in (401, 403):
            raise LLMError("The Gemini API key was rejected or can't use that model.") from e
        if e.code == 404:
            raise LLMError(f"Gemini doesn't recognise the model '{req.model_id}'.") from e
        if e.code == 429:
            raise LLMError("Gemini is rate-limiting requests. Try again in a minute.", retryable=True, status=503) from e
        raise LLMError(f"Gemini rejected the request: {e.message}") from e
    except genai_errors.ServerError as e:
        raise LLMError("Gemini had a problem answering. Try again shortly.", retryable=True, status=503) from e

    candidate = (response.candidates or [None])[0]
    finish = getattr(getattr(candidate, "finish_reason", None), "name", "") if candidate else ""
    if finish in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "RECITATION"):
        raise LLMError("The model declined this request. Try rephrasing it.", status=422)
    if finish == "MAX_TOKENS":
        raise LLMError("The model's answer was cut off. Ask for fewer songs or raise the model's output limit.")
    try:
        data = json.loads(response.text or "")
    except json.JSONDecodeError as e:
        raise LLMError("The model returned an unreadable answer. Try again.", retryable=True) from e
    usage = response.usage_metadata
    return LLMResult(data=data, input_tokens=(usage.prompt_token_count or 0) if usage else 0,
                     output_tokens=(usage.candidates_token_count or 0) if usage else 0, raw_model=req.model_id)


async def list_models(api_key: str, base_url: str | None = None) -> list[tuple[str, str]]:
    client = genai.Client(api_key=api_key)
    out = []
    async for m in await client.aio.models.list():
        if "generateContent" in (m.supported_actions or []):
            out.append((m.name.removeprefix("models/"), m.display_name or m.name))
    return sorted(out)
