"""Ollama-native provider (uses ``/api/tags`` and ``/api/chat``)."""

from __future__ import annotations

import httpx

from jqc.core.errors import ProviderUnavailable
from jqc.models.base import ChatMessage, ChatResult, ModelProvider


class OllamaProvider(ModelProvider):
    def __init__(self, base_url: str, model: str, timeout: float = 300.0) -> None:
        self.provider_id = "ollama"
        self.kind = "ollama"
        self.name = "Ollama (local)"
        self.base_url = self.validate_base_url(base_url)
        self.model = model
        self.timeout = timeout

    async def chat(self, messages: list[ChatMessage], model: str | None = None, **kwargs: object) -> ChatResult:
        url = f"{self.base_url.rstrip('/')}/api/chat"
        payload = {
            "model": model or self.model,
            "messages": [m.model_dump() for m in messages],
            "stream": False,
            "options": {"temperature": kwargs.get("temperature", 0.2)},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(self.name, url, f"{type(exc).__name__}: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderUnavailable(self.name, url, f"HTTP {resp.status_code}")
        data = resp.json()
        return ChatResult(
            content=str(data.get("message", {}).get("content", "")),
            model=str(data.get("model", self.model)),
            provider=self.name,
            usage={
                "prompt_tokens": int(data.get("prompt_eval_count", 0)),
                "completion_tokens": int(data.get("eval_count", 0)),
            },
            raw=data,
        )

    async def health(self) -> tuple[bool, str]:
        url = f"{self.base_url.rstrip('/')}/api/version"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
            if resp.status_code < 400:
                return True, f"Ollama running at {self.base_url}"
            return False, f"Ollama returned HTTP {resp.status_code}"
        except httpx.HTTPError as exc:
            return False, f"Unreachable: {type(exc).__name__}: {exc}"

    async def list_models(self) -> list[str]:
        url = f"{self.base_url.rstrip('/')}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
            if resp.status_code >= 400:
                return []
            return [str(m.get("name", "")) for m in resp.json().get("models", []) if m.get("name")]
        except (httpx.HTTPError, ValueError):
            return []

    async def test_connection(self, api_key: str | None = None) -> tuple[bool, str, list[str]]:
        ok, detail = await self.health()
        models = await self.list_models() if ok else []
        return ok, detail, models
