from app.services.llm import registry

from .conftest import sign_up

OPENAI_MODELS = {"object": "list", "data": [{"id": "b-model", "object": "model", "created": 0, "owned_by": "x"},
                                            {"id": "a-model", "object": "model", "created": 0, "owned_by": "x"}]}


async def test_openai_list_models(sdk_http):
    sdk_http[("GET", "https://api.openai.com/v1/models")] = (200, OPENAI_MODELS)
    assert await registry.list_provider_models("openai", "sk-test", None) == [("a-model", "a-model"), ("b-model", "b-model")]


async def test_openai_compatible_list_models_uses_base_url(sdk_http):
    sdk_http[("GET", "http://ollama:11434/v1/models")] = (200, {"object": "list", "data": [
        {"id": "llama", "object": "model", "created": 0, "owned_by": "x"}]})
    assert await registry.list_provider_models("openai_compatible", None, "http://ollama:11434/v1") == [("llama", "llama")]


async def test_anthropic_list_models(sdk_http):
    sdk_http[("GET", "https://api.anthropic.com/v1/models")] = (200, {
        "data": [{"id": "claude-opus-5-5", "display_name": "Claude Opus 5.5", "type": "model", "created_at": "2026-01-01T00:00:00Z"}],
        "has_more": False, "first_id": "claude-opus-5-5", "last_id": "claude-opus-5-5"})
    assert await registry.list_provider_models("anthropic", "sk-ant-test", None) == [("claude-opus-5-5", "Claude Opus 5.5")]


async def test_admin_discover_reports_rejected_key(client, outbox, sdk_http):
    sdk_http[("GET", "https://api.openai.com/v1/models")] = (401, {"error": {"message": "bad key", "type": "invalid_request_error"}})
    await sign_up(client, outbox, "admin@example.com")
    p = (await client.post("/api/admin/providers", json={"name": "OpenAI", "kind": "openai", "api_key": "sk-bad-key-123456"})).json()
    r = await client.get(f"/api/admin/providers/{p['id']}/discover")
    assert r.status_code == 400 and "rejected" in r.json()["detail"]


async def test_user_key_checked_before_saving(client, outbox, sdk_http):
    sdk_http[("GET", "https://api.openai.com/v1/models")] = (200, OPENAI_MODELS)
    await sign_up(client, outbox, "keys@example.com")
    r = await client.put("/api/me/llm-keys", json={"kind": "openai", "api_key": "sk-user-key-123456", "model_id": "a-model"})
    assert r.status_code == 200, r.text
    me = (await client.get("/api/me")).json()
    assert me["llm_keys"][0]["kind"] == "openai" and "user-key" not in me["llm_keys"][0]["key_hint"]
    assert any(m["id"] == "own:openai" and m["own_key"] for m in me["models"])


def _claude_message(text: str, stop_reason: str = "end_turn") -> dict:
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "stop_reason": stop_reason,
            "stop_sequence": None, "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 120, "output_tokens": 80}}


async def test_claude_structured_output_with_fallback(sdk_http):
    import json

    from app.services.llm import anthropic_provider
    from app.services.llm.base import LLMRequest
    sdk_http[("POST", "https://api.anthropic.com/v1/messages")] = (200, _claude_message(json.dumps({"title": "T", "tracks": []})))
    req = LLMRequest(model_id="claude-opus-5-5", api_key="sk-ant-test", base_url=None, system="sys",
                     messages=[{"role": "user", "content": "hi"}], schema={"type": "object"})
    result = await anthropic_provider.complete_json(req)
    assert result.data["title"] == "T" and result.input_tokens == 120
    sent = sdk_http["_requests"][-1]
    body = json.loads(sent.content)
    assert anthropic_provider.FALLBACK_BETA in sent.headers["anthropic-beta"]
    assert body["fallbacks"] == "default"
    assert body["output_config"] == {"format": {"type": "json_schema", "schema": {"type": "object"}}, "effort": "medium"}


async def test_claude_refusal_is_reported(sdk_http):
    import pytest

    from app.services.llm import anthropic_provider
    from app.services.llm.base import LLMError, LLMRequest
    sdk_http[("POST", "https://api.anthropic.com/v1/messages")] = (200, _claude_message("", stop_reason="refusal"))
    req = LLMRequest(model_id="claude-haiku-5-5", api_key="sk-ant-test", base_url=None, system="sys",
                     messages=[{"role": "user", "content": "hi"}], schema={"type": "object"})
    with pytest.raises(LLMError) as e:
        await anthropic_provider.complete_json(req)
    assert e.value.status == 422
    assert "anthropic-beta" not in sdk_http["_requests"][-1].headers   # no fallback on models outside the list


async def test_out_of_credit_is_explained(sdk_http):
    import pytest

    from app.services.llm import anthropic_provider
    from app.services.llm.base import OUT_OF_CREDIT, LLMError, LLMRequest
    sdk_http[("POST", "https://api.anthropic.com/v1/messages")] = (400, {"type": "error", "error": {
        "type": "invalid_request_error", "message": "Your credit balance is too low to access the Anthropic API."}})
    req = LLMRequest(model_id="claude-opus-5-5", api_key="k", base_url=None, system="s",
                     messages=[{"role": "user", "content": "hi"}], schema={"type": "object"})
    with pytest.raises(LLMError) as e:
        await anthropic_provider.complete_json(req)
    assert str(e.value) == OUT_OF_CREDIT and e.value.status == 424
