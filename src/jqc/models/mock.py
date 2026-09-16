"""Deterministic demo-mode provider.

Used when no real AI endpoint is configured (``demo_mode``). It echoes a
neutral confirmation so chat/agent flows can be tested end-to-end without API
keys or network access. It never pretends to have performed real work itself;
execution is done by the skills, and the orchestrator writes results.
"""

from __future__ import annotations

from jqc.models.base import ChatMessage, ChatResult, ModelProvider


class MockProvider(ModelProvider):
    def __init__(self, model: str = "jawa-mock") -> None:
        self.provider_id = "mock"
        self.kind = "mock"
        self.name = "Mock AI (demo)"
        self.base_url = "demo://mock"
        self.model = model

    async def chat(self, messages: list[ChatMessage], model: str | None = None, **kwargs: object) -> ChatResult:
        last = next((m.content for m in reversed(messages) if m.role == "user"), "")
        return ChatResult(
            content=(
                "Understood. The local demo agent processed this request in deterministic mode; "
                "the skills carried out the concrete steps. Connect a real model (OpenAI-compatible, "
                "Ollama, or another provider) for generative reasoning."
            ),
            model=model or self.model,
            provider=self.name,
            usage={"prompt_tokens": len(last) // 4, "completion_tokens": 0},
        )

    async def health(self) -> tuple[bool, str]:
        return True, "Demo provider is always available"

    async def test_connection(self, api_key: str | None = None) -> tuple[bool, str, list[str]]:
        return True, "Demo provider", [self.model]
