from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.services.ai.provider import AIRefused, AnthropicProvider


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _response(text: str = '{"ok": true}', stop_reason: str = "end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        model="claude-sonnet-5-5",
    )


def _provider(model: str, response) -> tuple[AnthropicProvider, FakeMessages]:
    settings = Settings(ai_provider="anthropic", ai_api_key=SecretStr("test-key"), ai_model=model)
    provider = AnthropicProvider(settings)
    fake = FakeMessages(response)
    provider._client = SimpleNamespace(beta=SimpleNamespace(messages=fake))
    return provider, fake


async def test_sends_fallback_and_thinking_headroom():
    provider, fake = _provider("claude-sonnet-5-5", _response())
    result = await provider.complete_json(system="s", user="u", max_tokens=4000)
    call = fake.calls[0]
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["max_tokens"] == 4000 + AnthropicProvider.THINKING_HEADROOM
    assert result.data == {"ok": True}
    assert (result.input_tokens, result.output_tokens) == (10, 5)


async def test_haiku_has_no_server_side_fallback():
    provider, fake = _provider("claude-haiku-5-5", _response())
    await provider.complete_json(system="s", user="u")
    assert "fallbacks" not in fake.calls[0]
    assert "betas" not in fake.calls[0]


async def test_refusal_raises():
    provider, _ = _provider("claude-opus-5-5", _response(text="", stop_reason="refusal"))
    with pytest.raises(AIRefused):
        await provider.complete_json(system="s", user="u")
