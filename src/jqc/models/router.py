"""Model Router: builds provider adapters from stored config + the secret
vault, resolves the default, and falls back gracefully when a provider is
unavailable."""

from __future__ import annotations

import logging

from jqc.core.errors import ProviderUnavailable
from jqc.models.base import ChatMessage, ChatResult, ModelProvider
from jqc.models.mock import MockProvider
from jqc.models.ollama import OllamaProvider
from jqc.models.openai_compat import OpenAICompatProvider
from jqc.security.secrets import SecretStore
from jqc.storage.db import Database
from jqc.storage.repos import Providers

log = logging.getLogger(__name__)


def build_provider(record: dict, secrets: SecretStore) -> ModelProvider:
    """Instantiate an adapter from a stored provider row."""
    kind = record["kind"]
    provider_id = record["id"]
    model = record["model"] or ""
    base_url = record.get("base_url")
    api_key = secrets.get(f"provider.{provider_id}.api_key")
    if kind == "mock":
        return MockProvider(model or "jawa-mock")
    if kind == "ollama":
        if not base_url:
            raise ProviderUnavailable(provider_id, "no endpoint configured", "base_url missing")
        return OllamaProvider(base_url, model or "")
    if kind == "openai-compatible":
        if not base_url:
            raise ProviderUnavailable(provider_id, "no endpoint configured", "base_url missing")
        config = record.get("config") or {}
        return OpenAICompatProvider(
            provider_id=provider_id,
            name=record["name"],
            base_url=base_url,
            model=model or "",
            api_key=api_key,
            timeout=float(config.get("timeout", 60)),
        )
    raise ProviderUnavailable(provider_id, "unknown", f"unsupported kind {kind!r}")


class ModelRouter:
    def __init__(self, db: Database, secrets: SecretStore) -> None:
        self.db = db
        self.secrets = secrets
        self.repo = Providers(db)

    def list_providers(self) -> list[dict]:
        return self.repo.list()

    def default(self) -> tuple[ModelProvider, str]:
        """Return the configured default provider and its default model."""
        default = self.repo.default()
        if default:
            provider_id, model = default
            record = self.repo.get(provider_id)
            if record:
                return build_provider(record, self.secrets), model
        return MockProvider(), "jawa-mock"

    async def chat(
        self,
        messages: list[ChatMessage],
        provider: str | None = None,
        model: str | None = None,
        prefer_local: bool = False,
        **kwargs: object,
    ) -> ChatResult:
        """Run a chat completion with graceful fallback.

        ``prefer_local`` reorders candidates so local kinds come first
        (used in hybrid/private privacy modes).
        """
        records = self.repo.list()
        enabled = [r for r in records if r["enabled"]]
        if prefer_local:
            enabled.sort(key=lambda r: 0 if r["kind"] in {"ollama", "mock"} else 1)
        if provider:
            want = [r for r in enabled if r["id"] == provider]
            if not want:
                want = [r for r in enabled if r["name"].lower() == provider.lower()]
            enabled = want or enabled
        elif not enabled:
            enabled = [{"id": "mock", "kind": "mock", "name": "Mock", "base_url": None, "model": "jawa-mock"}]

        errors: list[str] = []
        for record in enabled:
            adapter = build_provider(record, self.secrets)
            try:
                return await adapter.chat(messages, model=model, **kwargs)
            except ProviderUnavailable as exc:
                errors.append(f"{adapter.name}: {exc.detail or 'unavailable'}")
                log.warning("provider %s failed, trying next: %s", adapter.name, exc.detail)
        raise ProviderUnavailable("all providers failed", ", ".join(errors) or "none configured")

    async def test(self, provider_id: str) -> tuple[bool, str, list[str]]:
        record = self.repo.get(provider_id)
        if not record:
            return False, f"Provider {provider_id} not found", []
        adapter = build_provider(record, self.secrets)
        return await adapter.test_connection(self.secrets.get(f"provider.{provider_id}.api_key"))
