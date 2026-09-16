"""Generic OpenAI-compatible provider (works with OpenAI, OpenRouter, local
servers exposing ``/v1/chat/completions``, and Ollama's OpenAI shim)."""

from __future__ import annotations

import httpx

from jqc.core.errors import ProviderUnavailable
from jqc.models.base import ChatMessage, ChatResult, ModelProvider
from jqc.security.secrets import LIVE_SECRETS, redact_text


class OpenAICompatProvider(ModelProvider):
    def __init__(
        self,
        provider_id: str,
        name: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.provider_id = provider_id
        self.kind = "openai-compatible"
        self.name = name
        self.base_url = self.validate_base_url(base_url)
        self.model = model
        self.api_key = api_key or ""
        self.timeout = timeout
        if self.api_key:
            LIVE_SECRETS.add(self.api_key)

    def _chat_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    async def chat(self, messages: list[ChatMessage], model: str | None = None, **kwargs: object) -> ChatResult:
        payload = {
            "model": model or self.model,
            "messages": [m.model_dump() for m in messages],
            "temperature": kwargs.get("temperature", 0.2),
            "max_tokens": kwargs.get("max_tokens", 2048),
        }
        if kwargs.get("json_mode"):
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self._chat_url(), json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(self.name, self._chat_url(), f"{type(exc).__name__}: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderUnavailable(
                self.name,
                self._chat_url(),
                f"HTTP {resp.status_code}: {redact_text(resp.text[:300])}",
            )
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return ChatResult(
            content=content,
            model=data.get("model", self.model),
            provider=self.name,
            usage=data.get("usage", {}),
            raw=data,
        )

    async def health(self) -> tuple[bool, str]:
        base = self.base_url.rstrip("/")
        models_url = f"{base}/v1/models" if not base.endswith("/v1") else f"{base}/models"
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(models_url, headers=headers)
            if resp.status_code < 400:
                return True, f"Reachable at {models_url} (HTTP {resp.status_code})"
            return False, f"Endpoint responded HTTP {resp.status_code}"
        except httpx.HTTPError as exc:
            return False, f"Unreachable: {type(exc).__name__}: {exc}"

    async def test_connection(self, api_key: str | None = None) -> tuple[bool, str, list[str]]:
        ok, detail = await self.health()
        models: list[str] = []
        if ok:
            models = await self._list_models()
        return ok, detail, models

    async def _list_models(self) -> list[str]:
        base = self.base_url.rstrip("/")
        models_url = f"{base}/v1/models" if not base.endswith("/v1") else f"{base}/models"
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(models_url, headers=headers)
            if resp.status_code >= 400:
                return []
            data = resp.json()
            items = data.get("data", [])
            return [str(m.get("id", "")).strip() for m in items if m.get("id")]
        except (httpx.HTTPError, ValueError):
            return []
