"""Provider adapter tests against a local mock OpenAI/Ollama server so CI needs
no network or API keys."""

from __future__ import annotations

import threading

import pytest
from fastapi import FastAPI

from jqc.core.errors import ProviderUnavailable
from jqc.models.ollama import OllamaProvider
from jqc.models.openai_compat import OpenAICompatProvider


def _serve(app: FastAPI, port: int) -> threading.Thread:
    import uvicorn

    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(cfg)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return thread


def _wait_until(pred, timeout=10):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.1)
    raise RuntimeError("timeout waiting for server")


def _server_pair(app: FastAPI):
    """Bind a mock server on an ephemeral port (hermetic: no port collisions)."""
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    _serve(app, port)
    _wait_until(lambda: _http_ok(port), 15)
    return port


@pytest.fixture(scope="module")
def openai_server():
    app = FastAPI()

    @app.get("/v1/models")
    async def models():
        return {"data": [{"id": "mock-model-1"}, {"id": "mock-model-2"}]}

    @app.post("/v1/chat/completions")
    async def chat(body: dict):
        user = next((m["content"] for m in body.get("messages", []) if m.get("role") == "user"), "")
        return {
            "id": "cmpl-mock",
            "model": body.get("model", ""),
            "choices": [{"message": {"role": "assistant", "content": f"echo:{user}"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }

    port = _server_pair(app)
    return port


@pytest.fixture(scope="module")
def ollama_server():
    app = FastAPI()

    @app.get("/api/version")
    async def version():
        return {"version": "0.4.0"}

    @app.get("/api/tags")
    async def tags():
        return {"models": [{"name": "llama3.1:8b"}, {"name": "tiny:latest"}]}

    @app.post("/api/chat")
    async def chat(body: dict):
        return {
            "model": body.get("model"),
            "message": {"role": "assistant", "content": "ollama-ok"},
            "prompt_eval_count": 4,
            "eval_count": 2,
        }

    port = _server_pair(app)
    return port


def _http_ok(port: int) -> bool:
    import socket

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.mark.asyncio
async def test_openai_chat(openai_server):
    p = OpenAICompatProvider("p1", "Test", f"http://127.0.0.1:{openai_server}",
                             "mock-model-1", api_key="sk-test")
    from jqc.models.base import ChatMessage

    result = await p.chat([ChatMessage(role="user", content="hi there")])
    assert result.content == "echo:hi there"
    assert result.model == "mock-model-1"
    assert result.usage["completion_tokens"] == 2


@pytest.mark.asyncio
async def test_openai_health_and_models(openai_server):
    p = OpenAICompatProvider("p1", "Test", f"http://127.0.0.1:{openai_server}",
                             "mock-model-1", api_key="sk-test")
    ok, _ = await p.health()
    assert ok
    ok, _detail, models = await p.test_connection()
    assert ok and set(models) == {"mock-model-1", "mock-model-2"}


@pytest.mark.asyncio
async def test_openai_unreachable_is_provider_unavailable():
    p = OpenAICompatProvider("p1", "Dead", "http://127.0.0.1:1", "m")
    from jqc.models.base import ChatMessage

    with pytest.raises(ProviderUnavailable):
        await p.chat([ChatMessage(role="user", content="x")])


@pytest.mark.asyncio
async def test_ollama_chat(ollama_server):
    p = OllamaProvider(f"http://127.0.0.1:{ollama_server}", "llama3.1:8b")
    from jqc.models.base import ChatMessage

    result = await p.chat([ChatMessage(role="user", content="hi")])
    assert result.content == "ollama-ok"


@pytest.mark.asyncio
async def test_ollama_tags(ollama_server):
    p = OllamaProvider(f"http://127.0.0.1:{ollama_server}", "llama3.1:8b")
    ok, _detail, models = await p.test_connection()
    assert ok and "llama3.1:8b" in models


@pytest.mark.asyncio
async def test_mock_provider():
    from jqc.models.mock import MockProvider

    p = MockProvider()
    ok, _ = await p.health()
    assert ok


@pytest.mark.asyncio
async def test_bad_base_url_validation():
    from jqc.models.base import ModelProvider

    with pytest.raises(ValueError):
        ModelProvider.validate_base_url("not a url")
