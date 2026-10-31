"""LLM provider abstraction. Business logic depends only on ``LLMProvider``; models are swappable by config."""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import Settings, get_settings

log = logging.getLogger(__name__)


class AIError(Exception):
    pass


class AIRefused(AIError):
    pass


class AINotAvailable(AIError):
    """No external provider configured, consent missing or budget exhausted: use the local path."""


@dataclass(slots=True)
class LLMResult:
    data: dict[str, Any]
    input_tokens: int
    output_tokens: int
    model: str


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete_json(self, *, system: str, user: str, max_tokens: int = 4000) -> LLMResult: ...


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(text)
        if not match:
            raise AIError("model did not return JSON") from None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise AIError("model returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise AIError("model returned JSON that is not an object")
    return value


class OpenAICompatibleProvider:
    """Any chat-completions compatible endpoint (self-hosted or a Russian cloud provider)."""

    name = "openai_compatible"

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        if not settings.ai_base_url or not settings.ai_model:
            raise AINotAvailable("AI_BASE_URL и AI_MODEL не заданы")
        self.settings = settings
        self.model = settings.ai_model
        self._http = http

    async def complete_json(self, *, system: str, user: str, max_tokens: int = 4000) -> LLMResult:
        http = self._http or httpx.AsyncClient(timeout=self.settings.ai_timeout_seconds)
        headers = {"Content-Type": "application/json"}
        key = self.settings.ai_api_key.get_secret_value()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            response = await http.post(
                f"{self.settings.ai_base_url.rstrip('/')}/chat/completions", json=body, headers=headers
            )
        except httpx.TransportError as exc:
            raise AIError(f"AI provider unreachable: {exc.__class__.__name__}") from exc
        finally:
            if self._http is None:
                await http.aclose()
        if response.status_code >= 400:
            raise AIError(f"AI provider error {response.status_code}")
        payload = response.json()
        content = payload["choices"][0]["message"].get("content") or ""
        usage = payload.get("usage") or {}
        return LLMResult(
            data=parse_json_object(content),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            model=payload.get("model") or self.model,
        )


class AnthropicProvider:
    name = "anthropic"
    DEFAULT_MODEL = "claude-opus-5-5"
    THINKING_HEADROOM = 12000

    def __init__(self, settings: Settings):
        import anthropic

        key = settings.ai_api_key.get_secret_value()
        if not key:
            raise AINotAvailable("AI_API_KEY не задан")
        self.settings = settings
        self.model = settings.ai_model or self.DEFAULT_MODEL
        self._client = anthropic.AsyncAnthropic(api_key=key, timeout=settings.ai_timeout_seconds, max_retries=2)

    async def complete_json(self, *, system: str, user: str, max_tokens: int = 4000) -> LLMResult:
        import anthropic

        request: dict[str, Any] = {
            "model": self.model,
            # Current models think adaptively and thinking counts against max_tokens: leave room for the answer.
            "max_tokens": max_tokens + self.THINKING_HEADROOM,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if "haiku" not in self.model:
            # Server-side fallback when the primary model declines (stop_reason "refusal"). Haiku has none.
            request["betas"] = ["server-side-fallback-2026-07-01"]
            request["fallbacks"] = "default"
        try:
            response = await self._client.beta.messages.create(**request)
        except anthropic.RateLimitError as exc:
            raise AIError("AI rate limited") from exc
        except anthropic.APIStatusError as exc:
            raise AIError(f"AI provider error {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise AIError("AI provider unreachable") from exc
        if response.stop_reason == "refusal":
            raise AIRefused("model declined the request")
        text = "".join(block.text for block in response.content if block.type == "text")
        return LLMResult(
            data=parse_json_object(text),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )


def build_provider(settings: Settings | None = None) -> LLMProvider | None:
    """Returns None for the ``local`` provider: callers then use deterministic local logic."""
    settings = settings or get_settings()
    if settings.ai_provider == "openai_compatible":
        return OpenAICompatibleProvider(settings)
    if settings.ai_provider == "anthropic":
        return AnthropicProvider(settings)
    return None
