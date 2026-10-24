"""Provider-neutral interface for the LLM adapters (one module per provider kind)."""
from dataclasses import dataclass, field
from typing import Any

PROVIDER_KINDS = ("anthropic", "openai", "gemini", "openai_compatible")


@dataclass
class LLMRequest:
    model_id: str
    api_key: str | None
    base_url: str | None
    system: str
    messages: list[dict]          # [{"role": "user"|"assistant", "content": str}], first is "user"
    schema: dict                  # JSON Schema the reply must match (an object)
    max_output_tokens: int = 16000


@dataclass
class LLMResult:
    data: dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0
    raw_model: str = ""
    notes: list[str] = field(default_factory=list)


OUT_OF_CREDIT = "The AI account behind this model has run out of credit. The site admin needs to top it up or pick another model."


class LLMError(Exception):
    """An error safe to show the user (no keys or internals in the message)."""

    def __init__(self, message: str, *, retryable: bool = False, status: int = 424):
        super().__init__(message)
        self.retryable = retryable
        self.status = status
