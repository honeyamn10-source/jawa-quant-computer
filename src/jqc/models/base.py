"""Model provider interface shared by all adapters.

Every provider speaks a common ``chat`` operation so the router and the
orchestrator never depend on vendor specifics. ``plan_draft`` reuses the same
endpoint with a prompt requesting strict JSON.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"] = "user"
    content: str


class ChatResult(BaseModel):
    content: str
    model: str
    provider: str
    usage: dict[str, int] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class ModelProvider(ABC):
    """Minimum contract every AI provider adapter must satisfy."""

    provider_id: str
    kind: str
    name: str
    base_url: str | None
    model: str

    @abstractmethod
    async def chat(self, messages: list[ChatMessage], model: str | None = None, **kwargs: Any) -> ChatResult:
        """Run a chat completion."""

    @abstractmethod
    async def health(self) -> tuple[bool, str]:
        """Return (reachable, human-readable detail)."""

    async def test_connection(self, api_key: str | None = None) -> tuple[bool, str, list[str]]:
        ok, detail = await self.health()
        return ok, detail, []

    @staticmethod
    def validate_base_url(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                f"Invalid endpoint URL '{url}'. Expected http(s)://host[:port].",
            )
        return url.rstrip("/")


class LocalProviderMixin:
    """Marker for providers that run on this machine (privacy-friendly)."""
